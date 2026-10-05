SHELL := /bin/sh

UV := .tools/bin/uv
PYTHON := .venv/bin/python
PYTEST := .venv/bin/pytest
RUFF := .venv/bin/ruff
MYPY := .venv/bin/mypy
UVICORN := .venv/bin/uvicorn

export UV_CACHE_DIR := $(CURDIR)/.local/uv-cache
export UV_PYTHON_INSTALL_DIR := $(CURDIR)/.local/python

.PHONY: bootstrap ci ci-stages guard contract fixture-validation format-check lint typecheck \
	build-check tests fixture-smoke golden-eval secret-scan clean-state preview \
	container-build container-preview eval-live

bootstrap:
	./scripts/bootstrap.sh

guard:
	@test -x "$(UV)" || { echo "missing pinned uv; run ./scripts/bootstrap.sh" >&2; exit 1; }
	@test -x "$(PYTHON)" || { echo "missing virtual environment; run ./scripts/bootstrap.sh" >&2; exit 1; }

ci: guard
	@set -eu; \
	before="$$(mktemp)"; \
	after="$$(mktemp)"; \
	trap 'rm -f "$$before" "$$after"' EXIT HUP INT TERM; \
	git status --porcelain=v1 --untracked-files=all > "$$before"; \
	$(MAKE) --no-print-directory ci-stages; \
	git status --porcelain=v1 --untracked-files=all > "$$after"; \
	if ! cmp -s "$$before" "$$after"; then \
		echo "make ci changed repository-visible state:" >&2; \
		diff -u "$$before" "$$after" >&2 || true; \
		exit 1; \
	fi

ci-stages: contract fixture-validation format-check lint typecheck build-check tests fixture-smoke golden-eval secret-scan clean-state

contract:
	@echo "==> validate configuration, schemas, and repository contract"
	@UV_OFFLINE=1 "$(UV)" lock --check --offline
	@"$(PYTEST)" -q tests/contract

fixture-validation: guard
	@echo "==> validate DSL-106 fixtures, corpus, and license references"
	@"$(PYTHON)" scripts/validate_fixtures.py

format-check:
	@echo "==> format check"
	@"$(RUFF)" format --check .

lint:
	@echo "==> Ruff lint"
	@"$(RUFF)" check .

typecheck:
	@echo "==> mypy"
	@"$(MYPY)"

build-check:
	@echo "==> build check"
	@set -eu; \
	temp_root="$$(mktemp -d)"; \
	out="$$temp_root/dist"; \
	trap 'rm -rf "$$temp_root"' EXIT HUP INT TERM; \
	UV_CACHE_DIR="$$temp_root/uv-cache" UV_OFFLINE=1 "$(UV)" build \
		--offline --no-sources --out-dir "$$out" >/dev/null; \
	wheel="$$(find "$$out" -type f -name '*.whl' -print -quit)"; \
	sdist="$$(find "$$out" -type f -name '*.tar.gz' -print -quit)"; \
	test -n "$$wheel"; \
	test -n "$$sdist"; \
	"$(PYTHON)" scripts/verify_built_package.py "$$wheel" "$$temp_root/smoke"

tests:
	@echo "==> unit, integration, and security tests"
	@"$(PYTEST)" -q tests/unit tests/integration tests/security

fixture-smoke:
	@echo "==> fixture smoke eval"
	@"$(PYTHON)" -m privilab.evals.smoke

eval-live: guard
	@PRIVILAB_LIVE_EVAL=1 "$(PYTHON)" -m privilab.evals.live_openai

golden-eval: guard
	@"$(PYTHON)" scripts/validate_trade_regulatory.py
	@"$(PYTHON)" -m privilab.evals.trade_regulatory --root "$(CURDIR)"

secret-scan:
	@echo "==> secret scan"
	@./scripts/secret_scan.sh

clean-state:
	@echo "==> clean working-tree / generated-state check"
	@! git ls-files | grep -E '(^|/)(\.venv|\.tools|\.local|__pycache__|\.pytest_cache|\.mypy_cache|\.ruff_cache|dist|build)(/|$$)'
	@! git ls-files | grep -E '\.(sqlite|sqlite3|db|pyc|log)$$'

preview: guard
	@"$(UVICORN)" privilab.main:app \
		--host "$${PRIVILAB_HOST:-127.0.0.1}" \
		--port "$${PRIVILAB_PORT:-8000}"

container-build:
	docker build --tag privilab:local .

container-preview:
	docker run --rm --publish 127.0.0.1:8000:8000 privilab:local
