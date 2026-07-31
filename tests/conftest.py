"""Shared pytest setup for the suite.

Two jobs:

1. Put the repo root on ``sys.path`` so ``import data`` works without every
   test file repeating the same ``sys.path.insert`` dance.
2. Point **every** data store at a throwaway directory for the whole session,
   so running the tests can never read or overwrite the user's real
   ``inventory.json`` / ``containers.json`` / ``materials.json`` /
   ``batches.json`` / ``price_compare.json``.

Note on (2): several modules freeze a path at import time — ``data.CONTAINERS_FILE``
and ``price_compare.PRICE_FILE`` are both *derived* from ``INVENTORY_JSON`` when
their module is first imported — so redirecting ``INVENTORY_JSON`` alone is not
enough. Each derived path is rebound explicitly below.

The individual test modules remain runnable standalone (``python3
tests/test_x.py``); the ones that need isolation still do their own redirect.
This fixture is what makes the *pytest* path safe and deterministic no matter
which order the modules were collected in.
"""
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture(autouse=True, scope="session")
def _isolated_data_stores(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("inventory-data")

    import config
    import data
    import operations_data
    import price_compare

    targets = [
        (data, "INVENTORY_JSON", tmp / "inventory.json"),
        (data, "CONTAINERS_FILE", tmp / "containers.json"),
        (config, "MATERIALS_JSON", tmp / "materials.json"),
        (config, "BATCHES_JSON", tmp / "batches.json"),
        (operations_data, "MATERIALS_JSON", tmp / "materials.json"),
        (operations_data, "BATCHES_JSON", tmp / "batches.json"),
        (price_compare, "PRICE_FILE", tmp / "price_compare.json"),
    ]
    saved = [(mod, attr, getattr(mod, attr)) for mod, attr, _ in targets]
    for mod, attr, path in targets:
        Path(path).write_text("[]", encoding="utf-8")
        setattr(mod, attr, path)
    try:
        yield tmp
    finally:
        for mod, attr, original in saved:
            setattr(mod, attr, original)
