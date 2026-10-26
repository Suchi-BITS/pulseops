# PulseOps

PulseOps is an incident intelligence platform focused on evidence gathering, investigation workflows, and safe operational decision support.

## Phase 0 foundation

This repository currently provides the project foundation only:

- Python 3.11+ project configuration
- FastAPI application skeleton
- configuration management
- health endpoint
- pytest setup
- Docker-based local run path

## Local setup

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

## Run the app

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Then open:

- http://localhost:8000/health
- http://localhost:8000/docs

## Neo4j local development

Start Neo4j locally with Docker Compose:

```bash
docker compose up -d neo4j
```

The default local connection is:

- bolt://localhost:7687
- username: neo4j
- password: password

## Run tests

```bash
pytest
```

## Docker

```bash
docker build -t pulseops .
docker run --rm -p 8000:8000 pulseops
```
