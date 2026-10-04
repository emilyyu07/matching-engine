"""Unit tests for matching_engine.sequencer.SeqCounter."""

from matching_engine.sequencer import SeqCounter


def test_first_advance_returns_one() -> None:
    counter = SeqCounter()
    assert counter.advance() == 1


def test_advance_is_strictly_increasing() -> None:
    counter = SeqCounter()
    values = [counter.advance() for _ in range(5)]
    assert values == sorted(values)
    assert len(set(values)) == len(values)


def test_two_counters_do_not_share_state() -> None:
    first = SeqCounter()
    second = SeqCounter()
    first.advance()
    first.advance()
    assert second.advance() == 1
