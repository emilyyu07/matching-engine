.PHONY: test fast lint typecheck sim

test:
	pytest -q -x

fast:
	pytest -q -m "not slow"

lint:
	ruff check . && ruff format --check .

typecheck:
	mypy --strict src reference

sim:
	python -m sim.run --seed 42 --n 100000
