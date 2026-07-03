"""Local write-time reconciliation, no cloud LLM.

Cheap path (implemented, offline): on write, compare the new episode to its
nearest existing neighbor by vector similarity. If they are near-duplicates above
a threshold, treat it as an UPDATE (supersede the old one) instead of piling on a
duplicate. This is the light version of mem0's ADD/UPDATE/DELETE/NOOP.

Contradiction path (pluggable hook): a small local NLI model can be supplied to
flag when a new statement contradicts a near neighbor (not just duplicates it).
When it fires, the old fact is superseded via valid_to/superseded_by rather than
deleted. Default is None (no-op), because NLI needs a model; the interface is
here so it plugs in without touching the engine. Contradiction detection is only
claimed when a real checker is supplied.
"""

from __future__ import annotations

from typing import Callable

# Takes (new_text, existing_text); returns True if the new statement contradicts
# the existing one. Plug a local NLI model here.
ContradictionChecker = Callable[[str, str], bool]


class Reconciler:
    def __init__(
        self,
        dedup_threshold: float = 0.92,
        contradiction_checker: ContradictionChecker | None = None,
    ) -> None:
        self.dedup_threshold = dedup_threshold
        self.contradiction_checker = contradiction_checker

    def classify(
        self, new_text: str, neighbor_text: str | None, similarity: float | None
    ) -> str:
        """Return one of: 'add', 'update', 'contradict'.

        'update'     : near-duplicate of an existing fact -> supersede old
        'contradict' : semantically opposes an existing fact -> supersede old
        'add'        : genuinely new -> insert
        """
        if neighbor_text is None or similarity is None:
            return "add"
        if similarity >= self.dedup_threshold:
            return "update"
        if self.contradiction_checker is not None:
            if similarity >= 0.5 and self.contradiction_checker(new_text, neighbor_text):
                return "contradict"
        return "add"

    @property
    def claims_contradiction_detection(self) -> bool:
        return self.contradiction_checker is not None
