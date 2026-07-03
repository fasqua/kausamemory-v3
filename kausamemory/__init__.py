"""KausaMemory v3 - a smart, self-sovereign memory layer for AI agents."""

from .engine.core import KausaMemory, StoreResult
from .engine.retriever import RetrievalResult

__version__ = "3.0.0-alpha"
__all__ = ["KausaMemory", "StoreResult", "RetrievalResult"]
