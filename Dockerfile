# Reproducible environment for the cambium experiments.
#
#   docker build -t cambium .
#   docker run --rm -v "$PWD/results:/app/results" cambium eval --no-mlflow
#
# Candidate code runs in the subprocess sandbox tier inside this container
# (the container itself is the outer boundary). For the docker sandbox tier
# use a host install instead: nesting docker-in-docker is out of scope.
FROM python:3.13-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    MLFLOW_DISABLE_AGENT_HINT=1

COPY --from=ghcr.io/astral-sh/uv:0.8 /uv /usr/local/bin/uv

WORKDIR /app

# Dependencies first, for layer caching.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project

COPY src ./src
RUN uv sync --frozen --no-dev

RUN useradd --create-home --uid 10001 cambium && mkdir -p /app/results && chown cambium /app/results
USER cambium

ENV PATH="/app/.venv/bin:$PATH"
ENTRYPOINT ["cambium"]
CMD ["--help"]
