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
RUN groupadd --system app && useradd --system --gid app --no-create-home app
COPY --from=build /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    EKA_ENVIRONMENT=prod \
    EKA_LOG_JSON=true
WORKDIR /app
USER app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/live', timeout=2)"]
# The request middleware writes the access log, so uvicorn's own is off.
CMD ["uvicorn", "eka.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
