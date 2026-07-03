"""MCP interface for KausaMemory.

The engine is exposed to any MCP-speaking agent as a small set of tools. The tool
schemas and the dispatch layer here are transport-agnostic: the same MemoryTools
is used by the local stdio transport (Sovereign mode, free) and by the HTTP + x402
transport (Hosted mode, paid). Only the transport and the payment gate differ.
"""

from __future__ import annotations

from ..engine.core import KausaMemory

TOOLS = [
    {
        "name": "memory_store",
        "description": "Store a piece of text in long-term memory (verbatim).",
        "input": {"content": "string", "role": "string?", "ttl_seconds": "number?"},
    },
    {
        "name": "memory_search",
        "description": "Retrieve the most relevant memories for a query.",
        "input": {"query": "string", "limit": "integer?"},
    },
    {
        "name": "memory_context",
        "description": "Return relevant memories as a ready-to-prompt context block.",
        "input": {"query": "string", "limit": "integer?"},
    },
]


class MemoryTools:
    """Thin dispatch over KausaMemory, shared by every MCP transport."""

    def __init__(self, memory: KausaMemory) -> None:
        self.memory = memory

    def list_tools(self) -> list[dict]:
        return TOOLS

    def call(self, name: str, args: dict) -> dict:
        if name == "memory_store":
            r = self.memory.store(
                args["content"], role=args.get("role"), ttl_seconds=args.get("ttl_seconds")
            )
            return {"episode_id": r.episode_id, "action": r.action, "superseded": r.superseded}
        if name == "memory_search":
            results = self.memory.search(args["query"], limit=int(args.get("limit", 8)))
            return {
                "results": [
                    {"id": x.episode_id, "content": x.content, "score": x.score, "channels": x.channels}
                    for x in results
                ]
            }
        if name == "memory_context":
            return {"context": self.memory.context(args["query"], limit=int(args.get("limit", 8)))}
        raise ValueError(f"unknown tool: {name}")


def _json_schema(tool: dict) -> dict:
    """Convert a TOOLS entry's compact "input" spec into a JSON Schema object.
    A trailing "?" on a type marks the field optional; everything else is required.
    """
    type_map = {"string": "string", "integer": "integer", "number": "number"}
    properties: dict = {}
    required: list = []
    for field, spec in tool["input"].items():
        optional = spec.endswith("?")
        base = spec[:-1] if optional else spec
        properties[field] = {"type": type_map.get(base, "string")}
        if not optional:
            required.append(field)
    schema = {"type": "object", "properties": properties}
    if required:
        schema["required"] = required
    return schema


def run_stdio(db_path: str = "kausamemory.db") -> None:
    """Sovereign mode: expose MemoryTools over an MCP stdio server.

    Local, no payment, on-device. Any MCP-speaking agent can connect over stdio and
    use the three memory tools. The dispatch in MemoryTools is the whole behaviour;
    the mcp package only provides the async transport loop.
    """
    import asyncio
    import json

    import mcp.types as types
    from mcp.server import Server
    from mcp.server.stdio import stdio_server

    memory = KausaMemory(path=db_path)
    tools = MemoryTools(memory)
    server = Server("kausamemory")

    @server.list_tools()
    async def _list_tools() -> list[types.Tool]:
        return [
            types.Tool(
                name=t["name"],
                description=t["description"],
                inputSchema=_json_schema(t),
            )
            for t in tools.list_tools()
        ]

    @server.call_tool()
    async def _call_tool(name: str, arguments: dict) -> list[types.TextContent]:
        result = tools.call(name, arguments or {})
        return [types.TextContent(type="text", text=json.dumps(result))]

    async def _main() -> None:
        async with stdio_server() as (read_stream, write_stream):
            await server.run(
                read_stream,
                write_stream,
                server.create_initialization_options(),
            )

    asyncio.run(_main())
