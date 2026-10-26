# PulseOps application image (Gate 9, P9). Local platform only: no cloud-specific configuration.
#
# Stage 1 builds the React UI (P9.3). Only its static output is copied into the runtime image: Node, npm and the
# frontend sources are not part of the final image.
FROM node:22.12-slim@sha256:35531c52ce27b6575d69755c73e65d4468dba93a25644eed56dc12879cae9213 AS ui-build
WORKDIR /ui
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# Stage 2: the application. Base image pinned by tag and digest (python 3.11.16-slim); update both together.
FROM python:3.11.16-slim@sha256:9534e5a8e315485d4061ed659af0fd78a284c015f9b73661b41d6bab25604534

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PULSEOPS_ENVIRONMENT=production \
    PULSEOPS_DATABASE_URL=sqlite:////data/pulseops.db

# Unprivileged runtime user; /data is the only writable application location (SQLite persistence).
RUN groupadd --system --gid 10001 pulseops \
    && useradd --system --uid 10001 --gid pulseops --home-dir /app --shell /usr/sbin/nologin pulseops \
    && mkdir -p /app /data \
    && chown pulseops:pulseops /data

WORKDIR /app

COPY pyproject.toml README.md constraints.txt ./
COPY app ./app
COPY --from=ui-build /ui/dist ./frontend/dist

# constraints.txt pins the exact dependency versions the quality gate verified (P11).
RUN pip install -c constraints.txt -e .

# No secrets are baked into the image. PULSEOPS_ENVIRONMENT defaults to production, so the process refuses to start
# unless PULSEOPS_API_CREDENTIALS (credential hashes) is supplied at runtime; set PULSEOPS_ENVIRONMENT=development
# explicitly for local development.
VOLUME ["/data"]
USER pulseops
EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=5 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/ready', timeout=3).read()"]

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
