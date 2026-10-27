"""Runs each mutant against the full test suite and reports which survive.

Usage: python -m mutation.run [mutant-name ...]
"""

import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from mutation.catalogue import MUTANTS
from mutation.mutants import Mutant, apply

ROOT = Path(__file__).resolve().parent.parent
PACKAGE = ROOT / "src" / "matching_engine"
TIMEOUT_S = 300
_FAILURE = re.compile(r"^(?:FAILED|ERROR) (?:\S*/)?tests/(\w+)/", re.MULTILINE)


class Verdict(Enum):
    KILLED = "killed"
    SURVIVED = "survived"
    BROKEN = "broken"  # pytest itself failed to run, e.g. a collection error


@dataclass(frozen=True)
class Result:
    verdict: Verdict
    layers: tuple[str, ...]  # test directories with a failure
    output: str


def _env(workdir: Path) -> dict[str, str]:
    # The copy comes first so it shadows the editable install of src/.
    return {**os.environ, "PYTHONPATH": os.pathsep.join([str(workdir), str(ROOT)])}


def _check_shadowing(workdir: Path) -> None:
    probe = subprocess.run(
        [
            sys.executable,
            "-c",
            "import matching_engine; print(matching_engine.__file__)",
        ],
        cwd=workdir,
        env=_env(workdir),
        capture_output=True,
        text=True,
        check=True,
    )
    if not Path(probe.stdout.strip()).is_relative_to(workdir):
        raise RuntimeError(f"mutated copy is not the imported engine: {probe.stdout}")


def _run_suite(workdir: Path) -> Result:
    # cwd is the temp dir so Hypothesis's example database never touches the repo.
    command = [
        sys.executable,
        *("-m", "pytest", str(ROOT / "tests")),
        *("-c", str(ROOT / "pyproject.toml"), "--rootdir", str(ROOT)),
        *("-q", "--tb=no", "-rfE", "-p", "no:cacheprovider", "--hypothesis-seed=0"),
    ]
    try:
        proc = subprocess.run(
            command,
            cwd=workdir,
            env=_env(workdir),
            capture_output=True,
            text=True,
            timeout=TIMEOUT_S,
        )
    except subprocess.TimeoutExpired:
        return Result(Verdict.KILLED, ("timeout",), "")
    layers = tuple(sorted(set(_FAILURE.findall(proc.stdout))))
    verdict = {0: Verdict.SURVIVED, 1: Verdict.KILLED}.get(
        proc.returncode, Verdict.BROKEN
    )
    return Result(verdict, layers, proc.stdout)


def run_mutant(mutant: Mutant | None) -> Result:
    """Run the suite on a temp copy of the engine; None leaves it unmutated."""
    with tempfile.TemporaryDirectory() as tmp:
        workdir = Path(tmp).resolve()  # macOS temp dirs are symlinked
        copy = workdir / "matching_engine"
        shutil.copytree(PACKAGE, copy, ignore=shutil.ignore_patterns("__pycache__"))
        if mutant is not None:
            target = copy / mutant.file
            target.write_text(apply(mutant, target.read_text()))
        _check_shadowing(workdir)
        return _run_suite(workdir)


def main(names: list[str]) -> int:
    known = {m.name for m in MUTANTS}
    if unknown := set(names) - known:
        raise SystemExit(f"unknown mutants: {sorted(unknown)}")
    selected = [m for m in MUTANTS if not names or m.name in names]

    baseline = run_mutant(None)
    if baseline.verdict is not Verdict.SURVIVED:  # unmutated code must pass
        print(baseline.output[-2000:])
        print("baseline suite fails on unmutated code; aborting")
        return 2

    survivors: list[Mutant] = []
    broken: list[Mutant] = []
    for mutant in selected:
        result = run_mutant(mutant)
        print(
            f"{mutant.name:<26} {result.verdict.value:<9} {', '.join(result.layers)}",
            flush=True,
        )
        if result.verdict is Verdict.SURVIVED:
            survivors.append(mutant)
        elif result.verdict is Verdict.BROKEN:
            broken.append(mutant)

    killed = len(selected) - len(survivors) - len(broken)
    print(f"\nkilled {killed}/{len(selected)}")
    for mutant in survivors:
        print(f"SURVIVED {mutant.name}: {mutant.breaks}")
    for mutant in broken:
        print(f"BROKEN   {mutant.name}: pytest did not run cleanly")
    return 0 if killed == len(selected) else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
