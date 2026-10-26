"""Docker build and runtime validation (P11). Local Docker only: no registry, no cloud.

    python scripts/docker_check.py [--dockerfile FILE] [--build-context NAME=PATH ...] [--tag TAG] [--port N] [--keep-image]

Builds the image, starts a container with throw-away credentials (a random token whose SHA-256 is passed in the environment,
exactly as in a real deployment), and verifies:

  * the image builds and the container starts
  * GET /health/ready succeeds, and the container's Docker health check reaches "healthy"
  * GET /ui/ serves the built React app with the exact Content-Security-Policy and the baseline security headers
  * interactive API docs are off, and the API refuses unauthenticated requests with the error envelope
  * the process runs as the unprivileged user (uid 10001)
  * no env file and no API-key-shaped string is present in the image (regression for the stray app/agent/.env)
  * Node/npm are not part of the runtime image

``--dockerfile`` and ``--build-context`` are passed straight to ``docker build`` so that a developer behind a TLS-intercepting
proxy can supply a local variant; by default the repository Dockerfile is built unchanged. The container and (unless
``--keep-image``) the image are always removed afterwards.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import secrets
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def run(args: list[str], *, timeout: int = 900, check: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=check, cwd=ROOT)


def http(url: str, token: str | None = None) -> tuple[int, dict[str, str], str]:
    request = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"} if token else {})
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, {k.lower(): v for k, v in response.headers.items()}, response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as error:
        return error.code, {k.lower(): v for k, v in error.headers.items()}, error.read().decode("utf-8", "replace")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--dockerfile", type=Path, default=None)
    parser.add_argument("--build-context", action="append", default=[], metavar="NAME=PATH")
    parser.add_argument("--tag", default="pulseops:p11-check")
    parser.add_argument("--port", type=int, default=18766)
    parser.add_argument("--keep-image", action="store_true")
    parser.add_argument("--ready-timeout", type=int, default=120)
    args = parser.parse_args(argv)

    from app.ui import CONTENT_SECURITY_POLICY

    results: list[tuple[str, bool, str]] = []

    def check(name: str, ok: bool, detail: str = "") -> bool:
        results.append((name, ok, detail))
        print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if detail else ""))
        return ok

    if run(["docker", "info", "--format", "{{.ServerVersion}}"], timeout=60).returncode != 0:
        check("docker daemon available", False, "start Docker (Docker Desktop on Windows) and retry")
        print("DOCKER CHECK: FAIL")
        return 1

    name = f"pulseops-p11-{secrets.token_hex(4)}"
    token = secrets.token_urlsafe(32)
    credentials = json.dumps([{"principal_id": "p11-check", "tenant_id": "acme", "token_sha256": hashlib.sha256(token.encode()).hexdigest()}])
    build = ["docker", "build", "-t", args.tag]
    if args.dockerfile:
        build += ["-f", str(args.dockerfile)]
    for context in args.build_context:
        build += ["--build-context", context]
    try:
        built = run(build + ["."], timeout=1800)
        if not check("image builds", built.returncode == 0, "" if built.returncode == 0 else built.stderr.strip().splitlines()[-1][:200]):
            return _finish(results)
        started_run = run(["docker", "run", "-d", "--name", name, "-p", f"127.0.0.1:{args.port}:8000",
                           "-e", "PULSEOPS_ENVIRONMENT=production", "-e", "PULSEOPS_AUTH_MODE=apikey", "-e", "PULSEOPS_SEED_DEMO_DATA=false",
                           "-e", f"PULSEOPS_API_CREDENTIALS={credentials}", args.tag], timeout=120)
        if not check("container starts", started_run.returncode == 0, started_run.stderr.strip()[:200]):
            return _finish(results)
        base = f"http://127.0.0.1:{args.port}"
        ready, deadline = (0, "", ""), time.time() + args.ready_timeout
        while time.time() < deadline:
            try:
                ready = http(base + "/health/ready")
                if ready[0] == 200:
                    break
            except (urllib.error.URLError, ConnectionError, TimeoutError, OSError):
                pass
            time.sleep(1.5)
        if not check("/health/ready succeeds", ready[0] == 200 and json.loads(ready[2]) == {"status": "ready", "checks": {"database": "ok"}} if ready[0] == 200 else False, f"status {ready[0]}"):
            print(run(["docker", "logs", "--tail", "20", name]).stdout[-1500:])
            return _finish(results)

        status, headers, body = http(base + "/ui/")
        check("/ui/ serves the built React app", status == 200 and '<div id="root">' in body, f"status {status}")
        check("UI carries the exact Content-Security-Policy", headers.get("content-security-policy") == CONTENT_SECURITY_POLICY)
        check("UI carries the baseline security headers", headers.get("x-content-type-options") == "nosniff"
              and headers.get("x-frame-options") == "DENY" and headers.get("referrer-policy") == "no-referrer")
        status, _, _ = http(base + "/docs")
        check("interactive API docs are off", status == 404, f"status {status}")
        status, _, body = http(base + "/incidents")
        check("unauthenticated API call is refused with the envelope", status == 401 and {"detail", "code", "request_id"} <= set(json.loads(body)))
        status, _, body = http(base + "/me", token)
        check("a valid token authenticates but has no membership in a fresh database (fail closed)", status == 403, f"status {status}")

        uid = run(["docker", "exec", name, "id", "-u"]).stdout.strip()
        user = run(["docker", "inspect", "--format", "{{.Config.User}}", args.tag]).stdout.strip()
        check("runs as the unprivileged user", uid == "10001" and user == "pulseops", f"uid {uid}, user {user}")
        env_files = run(["docker", "run", "--rm", "--entrypoint", "sh", args.tag, "-c",
                         "find / -xdev \\( -name '.env' -o -name '.env.*' \\) -not -path '/proc/*' 2>/dev/null; true"]).stdout.strip()
        check("no env file inside the image", env_files == "", env_files[:200])
        keys = run(["docker", "run", "--rm", "--entrypoint", "sh", args.tag, "-c",
                    "grep -rIl 'sk-ant-[A-Za-z0-9_-]\\{20,\\}' /app /data 2>/dev/null; true"]).stdout.strip()
        check("no API-key-shaped string inside the image", keys == "", keys[:200])
        node = run(["docker", "exec", name, "sh", "-c", "command -v node || command -v npm || true"]).stdout.strip()
        check("Node/npm are not in the runtime image", node == "", node)

        health, deadline = "", time.time() + 90
        while time.time() < deadline:
            health = run(["docker", "inspect", "--format", "{{.State.Health.Status}}", name]).stdout.strip()
            if health == "healthy":
                break
            time.sleep(3)
        check("Docker health check reaches healthy", health == "healthy", health)
        return _finish(results)
    finally:
        run(["docker", "rm", "-f", name], timeout=120)  # always: even a container that failed to start is removed
        if not args.keep_image:
            run(["docker", "rmi", args.tag], timeout=120)


def _finish(results: list[tuple[str, bool, str]]) -> int:
    failed = [name for name, ok, _ in results if not ok]
    print("DOCKER CHECK:", "PASS" if not failed else "FAIL (" + "; ".join(failed) + ")")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
