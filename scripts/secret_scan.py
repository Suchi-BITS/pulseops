"""Repository-wide secret scan (P11). Lightweight, deterministic, offline.

    python scripts/secret_scan.py [--root DIR] [--json FILE]

It looks for credential-shaped content in every text file under the repository, INCLUDING generated artifacts
(frontend/dist, perf-results, eval-reports, ...). Categories: Anthropic/OpenAI-style API keys, bearer tokens, AWS / GitHub /
Slack / Google credentials, private keys, credentials embedded in URLs, hard-coded secret assignments, and real values in
environment files.

It NEVER prints a secret: findings are reported as ``file:line: category`` only, and the JSON report holds the same.

Policy for ``.env`` files: a local, git-ignored ``.env`` may legitimately hold developer secrets, so its presence is reported
as informational. It FAILS the scan if it is not git-ignored. ``.env.example`` must hold placeholders only.

Accepted exceptions live in scripts/secret_scan_allowlist.json (path glob + category + a written reason). Nothing is silently
ignored: allowlisted findings are counted and listed by location in the output.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ALLOWLIST = Path(__file__).with_name("secret_scan_allowlist.json")

SKIP_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
             "pulseops_ai_engineering.egg-info", ".runtime", "playwright-report", "test-results", ".coverage_html"}
SKIP_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".ico", ".woff", ".woff2", ".ttf", ".pyc", ".whl", ".zip", ".gz", ".db",
                 ".sqlite", ".sqlite3", ".bak", ".pdf", ".map"}
MAX_BYTES = 3_000_000
PLACEHOLDER = re.compile(r"^(?:|<[^>]*>|\$\{[^}]*\}|\$[A-Z_]+|changeme|change-me|example|your[-_ ].*|xxx+|\*+|\.\.\.|none|null|todo|dummy.*|test.*|placeholder.*)$", re.I)

PATTERNS: dict[str, re.Pattern[str]] = {
    "anthropic_api_key": re.compile(r"sk-ant-[A-Za-z0-9_\-]{20,}"),
    "openai_style_api_key": re.compile(r"\bsk-[A-Za-z0-9]{32,}\b"),
    "aws_access_key_id": re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    "aws_secret_access_key": re.compile(r"(?i)aws.{0,25}secret.{0,25}['\"][0-9A-Za-z/+]{40}['\"]"),
    "github_token": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b|\bgithub_pat_[A-Za-z0-9_]{50,}\b"),
    "slack_token": re.compile(r"\bxox[abprs]-[A-Za-z0-9\-]{10,}\b"),
    "google_api_key": re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b"),
    "private_key": re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP |ENCRYPTED )?PRIVATE KEY"),
    "bearer_token": re.compile(r"(?i)\bbearer\s+(?!<)[A-Za-z0-9._~+/=\-]{24,}"),
    "credentials_in_url": re.compile(r"://[^/\s:@'\"<>{}$]+:(?![\s'\"<>{}$])[^/\s:@'\"<>{}$]{4,}@(?!localhost\b)"),
    "hardcoded_secret_assignment": re.compile(
        r"(?i)\b[\w.-]*(?:password|passwd|secret|api[_-]?key|access[_-]?token|auth[_-]?token|credential)s?[\"']?\s*[:=]\s*[\"']([^\"'\s${}<>]{16,})[\"']"),
}
SECRET_ENV_NAME = re.compile(r"(?i)(key|token|secret|password|credential)")
HEX_HASH = re.compile(r"^[0-9a-f]{32,128}$")


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    category: str


def scan_text(text: str, path: str = "<memory>") -> list[Finding]:
    """Categories found in ``text``, by line. The matched text is never kept."""
    findings: list[Finding] = []
    for number, line in enumerate(text.splitlines(), start=1):
        if len(line) > 20_000:  # minified bundles: scan in chunks
            chunks = [line[i:i + 20_000] for i in range(0, len(line), 19_000)]
        else:
            chunks = [line]
        for chunk in chunks:
            for category, pattern in PATTERNS.items():
                match = pattern.search(chunk)
                if not match:
                    continue
                if category == "hardcoded_secret_assignment":
                    value = match.group(1)
                    if HEX_HASH.match(value) or PLACEHOLDER.match(value):  # a digest or a placeholder is not a secret
                        continue
                    if "." in value and "/" not in value and not re.search(r"[0-9]", value):  # an identifier like a.b.c
                        continue
                findings.append(Finding(path, number, category))
    return findings


def _env_file_findings(path: Path, rel: str, ignored: bool) -> tuple[list[Finding], list[str]]:
    findings: list[Finding] = []
    info: list[str] = []
    is_example = path.name.endswith((".example", ".template", ".sample"))
    populated = 0
    for number, raw in enumerate(path.read_text("utf-8", errors="ignore").splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        value = value.strip().strip("'\"")
        if re.search(r"<[^<>]+>", value):  # a documented template such as <64-hex-sha256-of-the-token>
            continue
        if SECRET_ENV_NAME.search(name) and value and not PLACEHOLDER.match(value) and not HEX_HASH.match(value):
            populated += 1
            if is_example:
                findings.append(Finding(rel, number, "real_value_in_env_example"))
    if not is_example:
        if not ignored:
            findings.append(Finding(rel, 1, "env_file_not_git_ignored"))
        elif populated:
            if rel.startswith(("app/", "frontend/")):
                info.append(f"{rel}: stray env file inside a directory that the Docker image copies; nothing reads it, so remove it "
                            "(the .dockerignore excludes env files at every depth, but the secret should not sit here)")
            info.append(f"{rel}: {populated} populated secret variable(s) in a git-ignored local env file (values not read out; not a repository leak)")
    return findings, info


def gitignore_covers(root: Path, name: str) -> bool:
    gitignore = root / ".gitignore"
    if not gitignore.exists():
        return False
    for raw in gitignore.read_text("utf-8").splitlines():
        entry = raw.strip()
        if entry and not entry.startswith(("#", "!")) and fnmatch.fnmatch(name, entry.rstrip("/")):
            return True
    return False


def load_allowlist(path: Path = ALLOWLIST) -> list[dict]:
    if not path.exists():
        return []
    entries = json.loads(path.read_text("utf-8"))["allow"]
    for entry in entries:
        if not entry.get("reason", "").strip():
            raise SystemExit(f"allowlist entry {entry.get('path')} has no written reason")
    return entries


def is_allowed(finding: Finding, allowlist: list[dict]) -> bool:
    return any(fnmatch.fnmatch(finding.path, e["path"]) and e["category"] in (finding.category, "*") for e in allowlist)


def iter_files(root: Path):
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel_parts = path.relative_to(root).parts
        if any(part in SKIP_DIRS for part in rel_parts[:-1]) or path.suffix.lower() in SKIP_SUFFIXES:
            continue
        try:
            if path.stat().st_size > MAX_BYTES:
                continue
        except OSError:
            continue
        yield path


def scan_repository(root: Path = ROOT, allowlist: list[dict] | None = None) -> tuple[list[Finding], list[Finding], list[str], int]:
    """Returns (findings, allowlisted findings, informational notes, files scanned)."""
    allowlist = load_allowlist() if allowlist is None else allowlist
    findings: list[Finding] = []
    allowed: list[Finding] = []
    info: list[str] = []
    scanned = 0
    for path in iter_files(root):
        rel = path.relative_to(root).as_posix()
        try:
            data = path.read_bytes()
        except OSError:
            continue
        if b"\x00" in data[:4096]:
            continue  # binary
        scanned += 1
        text = data.decode("utf-8", errors="ignore")
        current = scan_text(text, rel)
        if path.name == ".env" or path.name.startswith(".env."):
            env_findings, env_info = _env_file_findings(path, rel, gitignore_covers(root, path.name))
            current = env_findings  # an env file is judged by the env policy above, not by line patterns
            info.extend(env_info)
        for finding in current:
            (allowed if is_allowed(finding, allowlist) else findings).append(finding)
    return findings, allowed, info, scanned


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--json", type=Path, default=None, help="write a redacted JSON report")
    args = parser.parse_args(argv)
    findings, allowed, info, scanned = scan_repository(args.root.resolve())
    for finding in findings:
        print(f"{finding.path}:{finding.line}: {finding.category}")
    for note in info:
        print("info:", note)
    if allowed:
        print(f"allowlisted ({len(allowed)}):", ", ".join(sorted({f'{f.path}:{f.line}:{f.category}' for f in allowed})))
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps({
            "files_scanned": scanned, "findings": [f.__dict__ for f in findings], "allowlisted": [f.__dict__ for f in allowed],
            "info": info, "passed": not findings}, indent=2), encoding="utf-8")
    print(f"SECRET SCAN: {'FAIL' if findings else 'PASS'} ({scanned} files, {len(findings)} finding(s), {len(allowed)} allowlisted)")
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
