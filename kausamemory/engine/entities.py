"""Lightweight, zero-LLM entity extraction for the graph channel.

Deliberately simple: it pulls capitalized multi-word sequences and distinctive
identifier-like tokens. This is the weakest of the four retrieval channels and
the most improvable: a local NER model or an optional local-LLM enrichment can
replace `extract_entities` later without touching the rest of the engine. The
point for v1 is that the graph channel exists and costs zero cloud calls.
"""

from __future__ import annotations

import re

_STOP = {
    "the", "a", "an", "and", "or", "but", "if", "then", "i", "you", "he", "she",
    "it", "we", "they", "this", "that", "these", "those", "what", "when", "where",
    "who", "why", "how", "is", "are", "was", "were", "do", "does", "did", "my",
    "your", "our", "their", "of", "to", "in", "on", "for", "with", "at", "by",
}

_CAP_SEQ = re.compile(r"\b([A-Z][a-zA-Z0-9]+(?:\s+[A-Z][a-zA-Z0-9]+)*)\b")
_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_\-]+")


def extract_entities(text: str, max_entities: int = 12) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()

    # 1) capitalized sequences (proper nouns, product names)
    for m in _CAP_SEQ.finditer(text):
        phrase = m.group(1).strip()
        key = phrase.lower()
        if key in _STOP or key in seen:
            continue
        seen.add(key)
        found.append(phrase)

    # 2) distinctive lowercase tokens with digits/underscores/hyphens
    #    (identifiers like "sqlite-vec", "gpt-4o", "vec0")
    for m in _TOKEN.finditer(text):
        tok = m.group(0)
        key = tok.lower()
        if key in seen or key in _STOP:
            continue
        if any(c.isdigit() for c in tok) or "-" in tok or "_" in tok:
            seen.add(key)
            found.append(tok)

    return found[:max_entities]
