# syntax=docker/dockerfile:1
FROM python:3.12-slim AS build
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
WORKDIR /workspace
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install .

FROM python:3.12-slim
# Uploaded files and the embedding-model cache live on volumes mounted under /data. A named
# volume takes the ownership of the directory it is mounted on, so the non-root user can write.
RUN groupadd --system app && useradd --system --gid app --no-create-home app \
    && mkdir -p /data/files /data/models && chown -R app:app /data
COPY --from=build /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    EKA_ENVIRONMENT=prod \
    EKA_LOG_JSON=true \
    EKA_STORAGE_LOCAL_DIR=/data/files \
    EKA_EMBEDDING_CACHE_DIR=/data/models \
    # The non-root user has no home directory, so the Hugging Face client cache goes to the
    # model volume instead of ~/.cache (which cannot be created).
    HF_HOME=/data/models/huggingface
WORKDIR /app
# Migrations ship in the image so the compose "migrate" service can run them.
COPY alembic.ini ./
COPY alembic ./alembic
USER app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/live', timeout=2)"]
# Default command: the API. The worker uses the same image: python -m eka.worker
# The request middleware writes the access log, so uvicorn's own is off.
CMD ["uvicorn", "eka.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
