"""Console server: a local dashboard for KausaMemory.

Runs on the user's own machine. Reads the local SQLite memory (episodes,
entities, snapshots) and exposes it as JSON, plus serves the console UI.
Nothing leaves the machine; this is a bridge from the browser to local memory.

Built on Starlette directly to keep dependencies minimal.

Run:
    python -m kausamemory.console --db /path/to/kausamemory.db
    then open http://127.0.0.1:8787
"""
from __future__ import annotations

import json
import os
import time

import httpx

from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware

from kausamemory.engine.core import KausaMemory

# UsePod: OpenAI-compatible drop-in proxy. Token is the user's own UsePod
# token (they fund it, they pay per call), read from the environment so it
# never leaves the machine. Format matches KausaAgent's Gateway call.
USEPOD_BASE = "https://api.usepod.ai/proxy"
USEPOD_MODEL = os.environ.get("USEPOD_MODEL", "deepseek/deepseek-v4-flash")
ORACLE_CONTEXT_LIMIT = 6


def _int_param(request, name, default, lo, hi):
    raw = request.query_params.get(name)
    if raw is None:
        return default
    try:
        val = int(raw)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, val))


def _bool_param(request, name, default=False):
    raw = request.query_params.get(name)
    if raw is None:
        return default
    return raw.lower() in ("1", "true", "yes", "on")


def create_app(db_path: str, namespace: str = "default") -> Starlette:
    mem = KausaMemory(path=db_path, namespace=namespace)

    async def stats(request):
        active = mem.db.execute(
            "SELECT COUNT(*) FROM episodes WHERE namespace = ? AND valid_to IS NULL",
            (namespace,),
        ).fetchone()[0]
        total = mem.db.execute(
            "SELECT COUNT(*) FROM episodes WHERE namespace = ?", (namespace,)
        ).fetchone()[0]
        entities = mem.db.execute(
            "SELECT COUNT(*) FROM entities WHERE namespace = ?", (namespace,)
        ).fetchone()[0]
        snapshots = mem.db.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0]
        return JSONResponse(
            {
                "active": active,
                "total": total,
                "superseded": total - active,
                "entities": entities,
                "snapshots": snapshots,
                "namespace": namespace,
            }
        )

    async def episodes(request):
        limit = _int_param(request, "limit", 50, 1, 500)
        offset = _int_param(request, "offset", 0, 0, 10_000_000)
        include_superseded = _bool_param(request, "include_superseded", False)
        where = "WHERE namespace = ?"
        params = [namespace]
        if not include_superseded:
            where += " AND valid_to IS NULL"
        rows = mem.db.execute(
            "SELECT id, content, role, created_at, valid_to, superseded_by, access_count "
            "FROM episodes " + where + " ORDER BY created_at DESC LIMIT ? OFFSET ?",
            params + [limit, offset],
        ).fetchall()
        items = [
            {
                "id": r["id"],
                "content": r["content"],
                "role": r["role"],
                "created_at": r["created_at"],
                "superseded": r["valid_to"] is not None,
                "superseded_by": r["superseded_by"],
                "access_count": r["access_count"],
            }
            for r in rows
        ]
        return JSONResponse({"items": items, "count": len(items)})

    async def search(request):
        q = request.query_params.get("q", "").strip()
        if not q:
            return JSONResponse({"items": [], "count": 0, "query": ""})
        limit = _int_param(request, "limit", 20, 1, 100)
        results = mem.search(q, limit=limit)
        items = [{"id": r.episode_id, "content": r.content} for r in results]
        return JSONResponse({"items": items, "count": len(items), "query": q})

    async def entities(request):
        limit = _int_param(request, "limit", 100, 1, 500)
        rows = mem.db.execute(
            "SELECT e.id, e.name, e.kind, e.created_at, "
            "  (SELECT COUNT(*) FROM episode_entities ee WHERE ee.entity_id = e.id) AS mentions "
            "FROM entities e WHERE e.namespace = ? ORDER BY mentions DESC, e.name LIMIT ?",
            (namespace, limit),
        ).fetchall()
        items = [
            {"id": r["id"], "name": r["name"], "kind": r["kind"], "mentions": r["mentions"]}
            for r in rows
        ]
        return JSONResponse({"items": items, "count": len(items)})

    async def snapshots(request):
        limit = _int_param(request, "limit", 50, 1, 200)
        rows = mem.db.execute(
            "SELECT seq, cid, created_at, locator FROM snapshots ORDER BY seq DESC LIMIT ?",
            (limit,),
        ).fetchall()
        items = [
            {"seq": r["seq"], "cid": r["cid"], "created_at": r["created_at"], "locator": r["locator"]}
            for r in rows
        ]
        return JSONResponse({"items": items, "count": len(items)})

    async def ask(request):
        try:
            body = await request.json()
        except Exception:
            body = {}
        question = (body.get("question") or "").strip()
        if not question:
            return JSONResponse({"error": "empty question"}, status_code=400)

        token = os.environ.get("USEPOD_TOKEN", "").strip()
        if not token:
            return JSONResponse(
                {
                    "error": "no_token",
                    "message": "Set USEPOD_TOKEN in the environment to enable the Oracle. "
                    "You fund your own UsePod token; calls are paid from it.",
                },
                status_code=428,
            )

        # 1) ground the question in local memory
        results = mem.search(question, limit=ORACLE_CONTEXT_LIMIT)
        sources = [{"id": r.episode_id, "content": r.content} for r in results]

        if sources:
            context_lines = "\n".join(f"[{s['id']}] {s['content']}" for s in sources)
            system_prompt = (
                "You answer strictly from the user's own memory below. "
                "Each item is prefixed with its id in square brackets. "
                "Cite the ids you used in the form [id]. "
                "If the memory does not contain the answer, say so plainly.\n\n"
                "MEMORY:\n" + context_lines
            )
        else:
            system_prompt = (
                "The user's memory returned no relevant items for this question. "
                "Tell the user their memory has nothing on this yet; do not invent facts."
            )

        payload = {
            "model": USEPOD_MODEL,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": question},
            ],
            "max_tokens": 800,
            "temperature": 0.2,
        }
        url = USEPOD_BASE + "/" + token + "/v1/chat/completions"

        try:
            async with httpx.AsyncClient(timeout=120) as client:
                resp = await client.post(url, json=payload, headers={"Content-Type": "application/json"})
        except Exception as exc:
            return JSONResponse({"error": "upstream_unreachable", "message": str(exc)}, status_code=502)

        if resp.status_code != 200:
            return JSONResponse(
                {"error": "upstream_error", "status": resp.status_code, "message": resp.text[:300]},
                status_code=502,
            )

        try:
            data = resp.json()
            answer = data["choices"][0]["message"]["content"]
        except (json.JSONDecodeError, KeyError, IndexError, TypeError):
            return JSONResponse({"error": "bad_upstream_response", "message": resp.text[:300]}, status_code=502)

        return JSONResponse({"answer": answer, "sources": sources, "model": USEPOD_MODEL})

    async def health(request):
        return JSONResponse({"ok": True, "time": time.time(), "namespace": namespace})

    routes = [
        Route("/api/stats", stats),
        Route("/api/episodes", episodes),
        Route("/api/search", search),
        Route("/api/entities", entities),
        Route("/api/snapshots", snapshots),
        Route("/api/health", health),
        Route("/api/ask", ask, methods=["POST"]),
    ]
    allowed_origins = [
        "https://kausalayer.com",
        "https://www.kausalayer.com",
        "http://127.0.0.1:8787",
        "http://localhost:8787",
    ]
    middleware = [
        Middleware(
            CORSMiddleware,
            allow_origins=allowed_origins,
            allow_methods=["GET"],
            allow_headers=["*"],
        )
    ]
    return Starlette(routes=routes, middleware=middleware)


def run(db_path: str, host: str = "127.0.0.1", port: int = 8787, namespace: str = "default") -> None:
    import uvicorn

    app = create_app(db_path, namespace=namespace)
    uvicorn.run(app, host=host, port=port, log_level="info")
