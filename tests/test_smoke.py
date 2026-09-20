"""Smoke test: the package imports."""

import matching_engine


def test_package_imports() -> None:
    assert matching_engine.__doc__
