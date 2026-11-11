# Docker Guide: Restoring Images and Running the App

Use this guide after a cleanup has removed this project's Docker images.
Run every command from the `enterprise-knowledge-assistant/` folder in Git Bash.

## 1. Images this app needs

| Image | Compose service | Profile | How to get it |
|---|---|---|---|
| `pgvector/pgvector:0.8.7-pg17` | `db` | default | Pull |
| `enterprise-knowledge-assistant-migrate` | `migrate` | default | Build (`Dockerfile`) |
| `enterprise-knowledge-assistant-api` | `api` | default | Build (`Dockerfile`) |
| `enterprise-knowledge-assistant-worker` | `worker` | default | Build (`Dockerfile`) |
| `enterprise-knowledge-assistant-core-behind-edge` | `core-behind-edge` | `edge` | Build (`Dockerfile`) |
| `enterprise-knowledge-assistant-edge` | `edge` | `edge` | Build (`gateway/Dockerfile`) |
| `prom/prometheus:v3.5.0` | `prometheus` | `monitoring` | Pull |
| `grafana/grafana:12.1.0` | `grafana` | `monitoring` | Pull |

Base images used by the builds (pulled automatically during `build`):
`python:3.12-slim`, `maven:3.9-eclipse-temurin-21`, `eclipse-temurin:21-jre`.

## 2. Pull the public images

```bash
docker pull pgvector/pgvector:0.8.7-pg17
docker pull prom/prometheus:v3.5.0
docker pull grafana/grafana:12.1.0

# Optional: pre-pull base images so builds are faster
docker pull python:3.12-slim
docker pull maven:3.9-eclipse-temurin-21
docker pull eclipse-temurin:21-jre
```

Or let Compose pull everything the selected profiles need:

```bash
docker compose --profile edge --profile monitoring pull --ignore-buildable
```

## 3. Build the project images

The project images are not on a registry. Rebuild them from source:

```bash
# Core (migrate, api, worker)
docker compose build

# Core + edge gateway (core-behind-edge, edge)
docker compose --profile edge build
```

## 4. Run the app

```bash
# Core stack: db + migrate + api + worker
docker compose up -d --build

# With the edge gateway
docker compose --profile edge up -d --build

# With Prometheus + Grafana
docker compose --profile monitoring up -d

# Everything
docker compose --profile edge --profile monitoring up -d --build
```

Check that it's running:

```bash
docker compose ps
docker compose logs -f api
```

## 5. Stop and clean up

```bash
docker compose --profile edge --profile monitoring down      # stop; volumes (data) are kept
docker compose --profile edge --profile monitoring down --rmi local   # also remove the project-built images
```

**Do not** use `down -v` unless you want to delete the data volumes:

| Volume | What's in it |
|---|---|
| `enterprise-knowledge-assistant_eka-pgdata` | Database: documents, chunks, embeddings |
| `enterprise-knowledge-assistant_eka-files` | Uploaded files |
| `enterprise-knowledge-assistant_eka-models` | Cached models (re-downloaded if deleted; slow first start) |

## 6. Free disk space later

```bash
docker rmi enterprise-knowledge-assistant-api enterprise-knowledge-assistant-worker \
  enterprise-knowledge-assistant-migrate enterprise-knowledge-assistant-core-behind-edge \
  enterprise-knowledge-assistant-edge
docker rmi prom/prometheus:v3.5.0 grafana/grafana:12.1.0
docker builder prune -f
```

Keep `pgvector/pgvector:0.8.7-pg17` if another project still uses it (`docker ps -a --filter ancestor=pgvector/pgvector:0.8.7-pg17`).
