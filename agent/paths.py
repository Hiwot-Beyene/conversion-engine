"""Repository-root path resolution so data files load regardless of process CWD."""
from __future__ import annotations

from pathlib import Path
from typing import Union

PathLike = Union[str, Path]

# agent/paths.py -> agent/ -> repo root
REPO_ROOT: Path = Path(__file__).resolve().parent.parent


def resolve_repo_path(path_str: PathLike) -> Path:
    """
    If path_str is relative and not found from CWD, try under REPO_ROOT.
    """
    if path_str is None or path_str == "":
        return Path(path_str) if path_str != "" else Path(".")
    p = Path(path_str)
    if p.is_file():
        return p.resolve()
    if p.is_absolute() and p.exists():
        return p
    candidate = (REPO_ROOT / path_str).resolve()
    if candidate.is_file() or candidate.is_dir():
        return candidate
    return p.resolve()
