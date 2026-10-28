"""Replay logs: lossless encoding, format guards, and the lockstep check."""

from pathlib import Path

import pytest
from sim.generator import Cancel, Limit, generate
from sim.replay import check, decode, encode, read_log, write_log

from matching_engine.engine import Engine
from matching_engine.types import Side

REGRESSIONS = Path(__file__).resolve().parents[1] / "regressions"


def test_encoding_round_trips_exact_types() -> None:
    # == can't tell 1, 1.0 and True apart; repr can.
    commands = generate(1, 3000)
    assert [repr(decode(encode(c))) for c in commands] == [repr(c) for c in commands]


def test_valid_enum_and_invalid_string_encode_differently() -> None:
    valid = Limit(Side.BUY, 100, 1, None, None)
    invalid = Limit("buy", 100, 1, None, None)
    assert encode(valid) != encode(invalid)


def test_log_file_round_trips(tmp_path: Path) -> None:
    commands = generate(2, 500)
    write_log(tmp_path / "a.jsonl", commands, seed=2)
    loaded = read_log(tmp_path / "a.jsonl")
    assert [repr(c) for c in loaded] == [repr(c) for c in commands]


def test_unknown_format_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "a.jsonl"
    path.write_text('{"format": 99, "seed": null, "n": 0}\n')
    with pytest.raises(ValueError):
        read_log(path)


def test_truncated_log_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "a.jsonl"
    write_log(path, generate(3, 10))
    path.write_text("\n".join(path.read_text().splitlines()[:-1]) + "\n")
    with pytest.raises(ValueError):
        read_log(path)


def test_clean_stream_has_no_divergence() -> None:
    assert check(generate(0, 2000)) is None


def test_check_reports_the_first_divergent_step(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commands = generate(0, 300)
    first_cancel = next(i for i, c in enumerate(commands) if isinstance(c, Cancel))
    monkeypatch.setattr(Engine, "cancel", lambda self, order_id: [])
    result = check(commands)
    assert result is not None
    assert result.step == first_cancel


@pytest.mark.parametrize(
    "log", sorted(REGRESSIONS.glob("*.jsonl")), ids=lambda p: p.name
)
def test_saved_failures_replay_clean(log: Path) -> None:
    assert check(read_log(log)) is None
