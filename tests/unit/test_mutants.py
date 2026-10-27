from pathlib import Path

import pytest
from mutation.catalogue import MUTANTS
from mutation.mutants import Mutant, apply

_SRC = Path(__file__).resolve().parents[2] / "src" / "matching_engine"

_MUTANT = Mutant(name="m", file="f.py", old="<=", new="<", breaks="x")


def test_apply_replaces_the_single_match() -> None:
    assert apply(_MUTANT, "a <= b") == "a < b"


def test_apply_rejects_a_missing_match() -> None:
    with pytest.raises(ValueError):
        apply(_MUTANT, "a == b")


def test_apply_rejects_an_ambiguous_match() -> None:
    with pytest.raises(ValueError):
        apply(_MUTANT, "a <= b and c <= d")


def test_catalogue_names_are_unique() -> None:
    names = [m.name for m in MUTANTS]
    assert len(names) == len(set(names))


@pytest.mark.parametrize("mutant", MUTANTS, ids=lambda m: m.name)
def test_every_mutant_applies_to_the_current_source(mutant: Mutant) -> None:
    # Catches a stale mutant after a refactor, before it reads as "survived".
    source = (_SRC / mutant.file).read_text()
    assert apply(mutant, source) != source
