"""Monotonic sequence counter: assigns SeqNo to every processed command."""

from matching_engine.types import SeqNo


class SeqCounter:
    def __init__(self) -> None:
        self._next = SeqNo(0)

    def advance(self) -> SeqNo:
        self._next = SeqNo(self._next + 1)
        return self._next
