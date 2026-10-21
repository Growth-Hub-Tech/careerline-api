# Common tasks. Run `make install` once after cloning.
VENV ?= .venv
BIN := $(VENV)/bin

.PHONY: install dev start migrate migration lint format typecheck test check db-up db-down

install: ## Create the virtualenv, install Python and Node tools, set up the git hooks
	python3.13 -m venv $(VENV) || python3 -m venv $(VENV)
	$(BIN)/pip install --upgrade pip
	$(BIN)/pip install -r requirements-dev.txt
	npm install
	git config blame.ignoreRevsFile .git-blame-ignore-revs

dev: ## Run the API with auto-reload (migrates first)
	$(BIN)/alembic upgrade head
	$(BIN)/uvicorn app.main:app --reload --port $${PORT:-8000}

start: ## Run the API the way Render does
	PATH="$(CURDIR)/$(BIN):$$PATH" bash scripts/start.sh

migrate: ## Apply all migrations
	$(BIN)/alembic upgrade head

migration: ## Create a migration from model changes: make migration m="add x to y"
	$(BIN)/alembic revision --autogenerate -m "$(m)"

lint: ## Lint Python
	$(BIN)/ruff check .

format: ## Format Python (ruff) and Markdown/JSON/YAML (Prettier)
	$(BIN)/ruff check --fix .
	$(BIN)/ruff format .
	npx prettier --write .

typecheck: ## Type-check the app
	$(BIN)/mypy

test: ## Run the tests
	$(BIN)/pytest

check: lint typecheck test ## Everything CI checks, except migrations
	$(BIN)/ruff format --check .
	npx prettier --check .

db-up: ## Start a local Postgres in Docker
	docker compose up -d db

db-down: ## Stop the local Postgres
	docker compose down
