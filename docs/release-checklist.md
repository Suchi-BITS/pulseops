# PulseOps release-readiness checklist (P11)

Run from a clean checkout. The single command `python scripts/quality_gate.py` performs every automated item and writes
`quality-report.json`; the flake check is separate. A run with any `--skip-*` flag is **INCOMPLETE** and cannot be used for
release. Tick an item only with evidence from the run you are releasing. The "Recorded" column holds the result of the P11
validation run (see `docs/phase-11.md`, section 16).

| | Item | How it is verified | Recorded |
|---|---|---|---|
| [x] | Python tests pass | gate `python-tests-coverage` | REC_PY_TESTS |
| [x] | Frontend tests pass | gate `frontend-tests-coverage` | REC_FE_TESTS |
| [x] | Python coverage passes | gate `python-coverage-threshold` (`quality/thresholds.json`) | REC_PY_COV |
| [x] | Frontend coverage passes | gate `frontend-tests-coverage` | REC_FE_COV |
| [x] | Replay v2 passes | gate `replay-v2` (`GATE: PASS`) | REC_V2 |
| [x] | Replay v3 passes | gate `replay-v3` (`GATE: PASS`) | REC_V3 |
| [x] | Tenant isolation = 1.00 | gate `tenant-isolation` (both replays) | REC_TENANT |
| [x] | Evaluation datasets, baselines and scorer unchanged | gate `eval-integrity` | REC_INTEGRITY |
| [x] | Security tests pass | gate `security-tests` | REC_SEC |
| [x] | Bandit passes | gate `bandit` (medium and above) | REC_BANDIT |
| [x] | Dependency checks pass | gate `dependency-audit`; accepted findings are in `quality/dependency-audit-allowlist.json` and not expired | REC_DEPS |
| [x] | Python pins match the environment | gate `constraints-check` | REC_CONSTRAINTS |
| [x] | Secret scan passes | gate `secret-scan` | REC_SECRET |
| [x] | API contract passes | gate `api-reliability-tests` (`-m contract`) | REC_CONTRACT |
| [x] | Reliability tests pass | gate `api-reliability-tests` (`-m reliability`) | REC_REL |
| [x] | Browser E2E passes | gate `browser-e2e` (8 scenarios, no retries) | REC_E2E |
| [x] | Performance smoke passes | gate `performance-smoke` | REC_PERF |
| [x] | Docker validation passes | gate `docker-validation` | REC_DOCKER |
| [x] | Flake check passes | `python scripts/quality_gate.py --flake` | REC_FLAKE |
| [x] | Documentation updated | `docs/phase-11.md`, `CHANGELOG.md`, architecture/security/curriculum notes | updated |
| [x] | Known limitations documented | `docs/phase-11.md` section 14 | documented |
| [x] | No secrets in the repository | secret scan, plus the manual step below | REC_SECRET |
| [x] | Live Claude evaluation is explicitly NOT part of release validation | no step runs `python -m evals live`; CI has none | confirmed |

## Manual checks (not automatable)

- [ ] **Local `.env` files.** The secret scan reports git-ignored env files as informational only. Look at the notes it prints:
      remove any stray env file (for example `app/agent/.env`; nothing reads it) and rotate any key that was ever inside an
      image or archive that left this machine.
- [ ] Choose and set the release version (currently `0.1.0` in `app/core/config.py`) and date the `CHANGELOG.md` entry.
- [ ] Review accepted dependency findings and their expiry dates; re-assess any that are close to expiry.
- [ ] Production-like start: `PULSEOPS_ENVIRONMENT=production`, `PULSEOPS_AUTH_MODE=apikey`, real credential hashes, no demo
      data; confirm `/health/ready` and sign in through `/ui/`.
- [ ] Back up the production database before running `python -m app.migrations.gate9_1` / `app.migrations.p9` (both write
      their own `.bak`; do not rely on that alone).

## Rollback

P11 has no schema change. Revert the change set (source changes are listed in `docs/phase-11.md` section 15) and restore
the previous image; databases need no downgrade. If a P9 migration was run, restore the `*.pre-p9.bak` / `*.pre-gate9_1.bak`
file it wrote.
