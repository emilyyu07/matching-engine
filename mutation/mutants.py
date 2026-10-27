"""Hand-written mutants: each injects one known bug into src/matching_engine."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Mutant:
    name: str
    file: str  # relative to src/matching_engine
    old: str
    new: str
    breaks: str  # the invariant or SPEC rule this bug violates


def apply(mutant: Mutant, source: str) -> str:
    """Swap `old` for `new`; refuse unless `old` occurs exactly once."""
    found = source.count(mutant.old)
    if found != 1:
        raise ValueError(f"mutant {mutant.name!r}: expected 1 match, found {found}")
    return source.replace(mutant.old, mutant.new)
