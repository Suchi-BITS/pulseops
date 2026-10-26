"""PulseOps evaluation harness (Phase 7 Gate 7, extended in Gate 8).

Observational only: ``evals`` imports ``app``; ``app`` must never import ``evals``.
Scores never feed back into policy, approval or any production workflow decision.
"""

from __future__ import annotations

import atexit
import os
import shutil
import tempfile
from pathlib import Path

DATASET_VERSION = "golden-v2"

# Importing ``app`` builds services against the default database at import time. Unless a database is explicitly
# configured, point the evaluation process at a throwaway one so running evals never creates or touches a
# developer's ``pulseops.db``. Evaluation cases and probes use their own temporary databases regardless.
# The harness drives the app in-process through the controlled development identity; it never runs against a
# production configuration.
os.environ["PULSEOPS_ENVIRONMENT"] = "development"
os.environ["PULSEOPS_AUTH_MODE"] = "dev"
os.environ["PULSEOPS_SEED_DEMO_DATA"] = "true"
os.environ.pop("PULSEOPS_API_CREDENTIALS", None)

if not os.environ.get("PULSEOPS_DATABASE_URL"):
    _EVAL_DIR = Path(tempfile.mkdtemp(prefix="pulseops-evals-"))
    atexit.register(shutil.rmtree, _EVAL_DIR, True)
    os.environ["PULSEOPS_DATABASE_URL"] = "sqlite:" + (_EVAL_DIR / "pulseops-evals.db").as_posix()
