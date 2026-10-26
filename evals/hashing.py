"""Deterministic content hashing for evaluation datasets (simple on purpose)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


def canonical_sha256(data: Any) -> str:
    """sha256 over canonical JSON (sorted keys, no insignificant whitespace). Whitespace-only edits do not change it;
    any change to content, including values, keys or list order, does."""
    canonical = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def file_sha256(path: Path) -> str:
    return canonical_sha256(json.loads(Path(path).read_text(encoding="utf-8")))
