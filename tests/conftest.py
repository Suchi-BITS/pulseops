"""Test isolation: every test session uses its own temporary SQLite database.

Set before any ``app`` module is imported (several modules build services at import time), so tests never read or
write a developer's ``pulseops.db``. The variable is forced, not defaulted, on purpose.
"""

from __future__ import annotations

import atexit
import os
import shutil
import tempfile
from pathlib import Path

_SESSION_DIR = Path(tempfile.mkdtemp(prefix="pulseops-tests-"))
atexit.register(shutil.rmtree, _SESSION_DIR, True)
os.environ["PULSEOPS_DATABASE_URL"] = "sqlite:" + (_SESSION_DIR / "pulseops-test.db").as_posix()

# Gate 9: tests run in the development environment with the controlled dev identity (the default dev principal is a
# human admin; individual tests send X-Dev-Principal to act as other principals). Real bearer authentication is
# covered by tests that set the environment explicitly. These are forced so a developer's shell cannot change them.
os.environ["PULSEOPS_ENVIRONMENT"] = "development"
os.environ["PULSEOPS_AUTH_MODE"] = "dev"
os.environ["PULSEOPS_SEED_DEMO_DATA"] = "true"
os.environ.pop("PULSEOPS_API_CREDENTIALS", None)


# P11 flake-detection set: the fast tests that guard security, tenancy, HITL and reliability. Selected by file here so
# that no existing test file has to be edited. `python scripts/quality_gate.py --flake` repeats exactly these tests.
_CRITICAL_FILES = (
    "test_phase7_gate6.py",  # event ingestion, idempotency, concurrent duplicates
    "test_phase7_gate9_1.py",  # tenancy and tenant-scoped roles
    "test_phase9.py",  # P9 API contracts, investigation record, HITL boundary
    "test_phase11_security.py",
    "test_phase11_reliability.py",
    "test_phase11_contract.py",
)


def pytest_collection_modifyitems(config, items):  # noqa: ARG001
    import pytest

    for item in items:
        if item.fspath.basename in _CRITICAL_FILES:
            item.add_marker(pytest.mark.critical)
