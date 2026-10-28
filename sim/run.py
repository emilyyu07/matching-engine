"""Command-line runner: feeds a generated stream to the engine.

A divergence writes the full command log to logs/ for `python -m sim.replay`.
"""

import argparse
import sys
from pathlib import Path

from sim.generator import generate
from sim.replay import check, describe, write_log

LOG_DIR = Path("logs")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="sim.run")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--n", type=int, default=100_000)
    parser.add_argument("--seeds", type=int, default=1, help="consecutive seeds")
    args = parser.parse_args(argv)

    failed = 0
    for seed in range(args.seed, args.seed + args.seeds):
        commands = generate(seed, args.n)
        divergence = check(commands)
        if divergence is None:
            print(f"seed {seed}: ok ({args.n} commands)", flush=True)
            continue
        path = LOG_DIR / f"seed-{seed}-n{args.n}.jsonl"
        write_log(path, commands, seed)
        print(f"seed {seed}: DIVERGED\n{describe(divergence)}\n  log: {path}")
        failed += 1
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
