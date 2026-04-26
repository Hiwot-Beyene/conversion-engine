"""
Backward-compatible entrypoint for τ² evaluation harness.

Use `python -m eval.tau2_harness` or `python -m eval.tau2.runner`.
"""
from __future__ import annotations

from eval.tau2.runner import main


if __name__ == "__main__":
    raise SystemExit(main())
