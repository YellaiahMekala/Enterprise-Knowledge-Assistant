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
| `prom/alertmanager:v0.28.1` | `alertmanager` | `monitoring` | Pull |
| `grafana/loki:3.5.3` | `loki` | `monitoring` | Pull |
| `grafana/alloy:v1.10.2` | `alloy` | `monitoring` | Pull |
| `quay.io/keycloak/keycloak:26.3` | `keycloak` | `idp` | Pull |
| `enterprise-knowledge-assistant-ops-agent` | `ops-agent` | `agent` | Build (`ops-agent/Dockerfile`) |
| `axllent/mailpit:v1.27` | `mailpit` | `agent` | Pull |
| `timberio/vector:0.51.1-alpine` | `log-shipper` | `cloudwatch` | Pull |
| `localstack/localstack:4.9` | `localstack` | `cloudwatch` | Pull |

Base images used by the builds (pulled automatically during `build`):
`python:3.12-slim`, `maven:3.9-eclipse-temurin-21`, `eclipse-temurin:21-jre`.

## 2. Pull the public images

```bash
docker pull pgvector/pgvector:0.8.7-pg17
docker pull prom/prometheus:v3.5.0
docker pull grafana/grafana:12.1.0
docker pull prom/alertmanager:v0.28.1
docker pull grafana/loki:3.5.3
docker pull grafana/alloy:v1.10.2
docker pull quay.io/keycloak/keycloak:26.3
docker pull axllent/mailpit:v1.27

# Optional: pre-pull base images so builds are faster
docker pull python:3.12-slim
docker pull maven:3.9-eclipse-temurin-21
docker pull eclipse-temurin:21-jre
```

Or let Compose pull everything the selected profiles need:

```bash
docker compose --profile edge --profile idp --profile monitoring --profile agent pull --ignore-buildable
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

# Identity provider (Keycloak on :8180) for the edge and the UI's single sign-on
docker compose --profile edge --profile idp up -d --build

# Triage agent and the local mail catcher (needs the monitoring profile)
docker compose --profile monitoring --profile agent up -d --build

# Container logs to CloudWatch Logs (ADR-040), against LocalStack on :4566 by default.
# Search them with the agent: OPS_AGENT_CLOUDWATCH_LOG_GROUP=/eka-local
docker compose --profile cloudwatch up -d localstack log-shipper

# Everything
docker compose --profile edge --profile idp --profile monitoring --profile agent up -d --build
```

Check that it's running:

```bash
docker compose ps
docker compose logs -f api
```

## 5. Stop and clean up

```bash
P="--profile edge --profile idp --profile monitoring --profile agent"
docker compose $P down               # stop; volumes (data) are kept
docker compose $P down --rmi local   # also remove the project-built images
```

**Keycloak realm changes.** Keycloak imports `keycloak/realm-eka.json` only when its container is created. After a realm change (for example the refresh token rotation added on 2026-11-11), recreate it once: `docker compose --profile idp up -d --force-recreate keycloak`. It keeps no other data. The test users `alice` and `boss` have fixed ids in the realm, so a recreated Keycloak gives them the same subject and they still see their documents behind the edge.

**Do not** use `down -v` unless you want to delete the data volumes:

| Volume | What's in it |
|---|---|
| `enterprise-knowledge-assistant_eka-pgdata` | Database: documents, chunks, embeddings |
| `enterprise-knowledge-assistant_eka-files` | Uploaded files |
| `enterprise-knowledge-assistant_eka-models` | Cached models (re-downloaded if deleted; slow first start) |
| `enterprise-knowledge-assistant_eka-loki` | Container logs kept by Loki (3 days) |

## 6. Free disk space later

```bash
docker rmi enterprise-knowledge-assistant-api enterprise-knowledge-assistant-worker \
  enterprise-knowledge-assistant-migrate enterprise-knowledge-assistant-core-behind-edge \
  enterprise-knowledge-assistant-edge enterprise-knowledge-assistant-ops-agent
docker rmi prom/prometheus:v3.5.0 grafana/grafana:12.1.0 prom/alertmanager:v0.28.1 \
  grafana/loki:3.5.3 grafana/alloy:v1.10.2 quay.io/keycloak/keycloak:26.3 axllent/mailpit:v1.27
docker builder prune -f
```

Keep `pgvector/pgvector:0.8.7-pg17` if another project still uses it (`docker ps -a --filter ancestor=pgvector/pgvector:0.8.7-pg17`).
