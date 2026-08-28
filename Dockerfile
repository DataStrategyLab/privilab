FROM ghcr.io/astral-sh/uv:0.12.6@sha256:88bc6eb1ccd4b82efd0e1b530caffabddf50dc2bf612e66c14ea25b8ee8a4d3d AS uv

FROM python:3.14.7-slim-bookworm@sha256:416f0db2a2b561945630cef9877a7ea0581b27449eb9fd9df42f03e1b74b5b63

COPY --from=uv /uv /uvx /bin/

ENV PATH="/app/.venv/bin:$PATH" \
    UV_LINK_MODE=copy \
    UV_NO_CACHE=1 \
    UV_NO_DEV=1 \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project --no-editable

COPY src ./src
RUN uv sync --frozen --no-dev --no-editable

EXPOSE 8000

CMD ["uvicorn", "privilab.main:app", "--host", "0.0.0.0", "--port", "8000"]
