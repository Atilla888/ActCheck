# One container: FastAPI serves the API and the built frontend on $PORT (default 8000).
#   docker build -t actcheck . && docker run --env-file .env -p 8000:8000 actcheck
# Keys come from the environment at run time; none are baked into the image.

FROM node:22-slim AS web
WORKDIR /web
COPY app/frontend/package.json app/frontend/package-lock.json ./
RUN npm ci
COPY app/frontend ./
RUN npm run build

FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.13.5 /uv /bin/uv
RUN apt-get update \
    && apt-get install -y --no-install-recommends libglib2.0-0 fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev
COPY agent agent
COPY schemas schemas
COPY measure measure
COPY app/__init__.py app/__init__.py
COPY app/server app/server
COPY data/samples/demo data/samples/demo
COPY --from=web /web/dist app/frontend/dist
# os.cpu_count() reports the host, not the container; more SAM decode processes run out of memory.
ENV PATH="/app/.venv/bin:$PATH" ACTCHECK_OUTPUT_DIR=/tmp/actcheck PORT=8000 ACTCHECK_SAM_WORKERS=2
EXPOSE 8000
CMD ["sh", "-c", "uvicorn app.server.main:app --host 0.0.0.0 --port ${PORT}"]
