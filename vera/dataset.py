"""Loads the bundled public dataset (dataset/bundle.json).

One file instead of 355 small ones keeps the repo easy to upload through
GitHub's web page. Keys: categories, merchants, customers, triggers
(each a dict keyed by id) and test_pairs (the 30 canonical pairs).
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

BUNDLE = Path(__file__).resolve().parents[1] / "dataset" / "bundle.json"


@lru_cache(maxsize=1)
def load_bundle(path: str | None = None) -> dict:
    p = Path(path) if path else BUNDLE
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"categories": {}, "merchants": {}, "customers": {}, "triggers": {}, "test_pairs": []}
