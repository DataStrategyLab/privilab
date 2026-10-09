FROM ghcr.io/astral-sh/uv:0.12.23@sha256:61d393e44e249f2e4b526b6c7ddcecce245946826e608e11c93ad4f5bba55b21 AS uv

FROM python:3.13.15-slim-bookworm@sha256:2325bb286ec344af3e5898cc224b5844e2707ac6e26b1632516fd3edc84a5e26

COPY --from=uv /uv /uvx /bin/

ENV PATH="/app/.venv/bin:$PATH" \
    UV_LINK_MODE=copy \
    UV_NO_CACHE=1 \
    UV_NO_DEV=1 \
    UV_PYTHON_DOWNLOADS=never \
    PRIVILAB_PREVIEW_CORPUS_ROOT=/app/fixtures/corpus \
    PRIVILAB_PREVIEW_DB=/app/.local/preview/provenance.sqlite3

WORKDIR /app

COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project --no-editable

COPY src ./src
COPY fixtures/corpus ./fixtures/corpus
RUN uv sync --frozen --no-dev --no-editable

EXPOSE 8000

CMD ["uvicorn", "privilab.main:app", "--host", "0.0.0.0", "--port", "8000"]
