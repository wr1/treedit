ROOT ?= .
PORT ?= 8765
AGENT ?=
AGENT_ARG := $(if $(AGENT),--agent '$(AGENT)',)
VENV := .venv
TREEDIT := $(VENV)/bin/treedit
APP_PC := webkit2gtk-4.1 javascriptcoregtk-4.1 libsoup-3.0 gtk+-3.0 dbus-1
APP_DEPS := libdbus-1-dev libwebkit2gtk-4.1-dev libgtk-3-dev libsoup-3.0-dev libjavascriptcoregtk-4.1-dev librsvg2-dev libssl-dev build-essential pkg-config

.DEFAULT_GOAL := help
.PHONY: help install open web print lint test build skill tool app app-build app-deps app-check clean

help: ## Show this help (override ROOT=path PORT=n AGENT=claude)
	@awk 'BEGIN {FS = ":.*## "} /^[a-zA-Z_-]+:.*## / {printf "  \033[36m%-10s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

$(TREEDIT): pyproject.toml
	uv venv -q $(VENV)
	uv pip install -q -p $(VENV) -e .

install: $(TREEDIT) ## Create .venv and install treedit (editable)

open: $(TREEDIT) ## Open ROOT in the app window, AGENT in the right pane (browser if Tauri libs are missing)
	@if pkg-config --exists $(APP_PC); then cargo build -q --manifest-path app/Cargo.toml; \
	else echo "Tauri libraries missing (make app-deps) - using the browser"; fi
	$(TREEDIT) open $(abspath $(ROOT)) -p $(PORT) $(AGENT_ARG)

web: $(TREEDIT) ## Open ROOT in the web browser instead
	$(TREEDIT) open $(abspath $(ROOT)) -p $(PORT) --browser $(AGENT_ARG)

print: $(TREEDIT) ## Print the annotated, word-count coloured tree of ROOT
	$(TREEDIT) print $(ROOT)

lint: ## Run ruff on src and tests
	uvx ruff check src tests

test: ## Run the tests with coverage
	uv run pytest

build: ## Build the sdist and wheel into dist/
	uv build

skill: $(TREEDIT) ## Regenerate SKILL.md and install it for Claude Code / Hermes
	$(TREEDIT) skill show > SKILL.md
	$(TREEDIT) skill install

tool: ## Install treedit + the treedit-app window globally (uv tool bin dir)
	uv tool install --force --reinstall-package treedit .
	@if pkg-config --exists $(APP_PC); then \
		cargo build --release -q --manifest-path app/Cargo.toml && \
		install -m755 app/target/release/treedit-app "$$(uv tool dir --bin)/treedit-app" && \
		echo "installed $$(uv tool dir --bin)/treedit-app - treedit open uses the app window"; \
	else echo "Tauri libraries missing (make app-deps) - installed the CLI only; treedit open uses the browser"; fi

app-check:
	@pkg-config --exists $(APP_PC) || { echo "missing system libraries:$$(for m in $(APP_PC); do pkg-config --exists $$m || printf ' %s' $$m; done)"; echo "run: make app-deps"; exit 1; }

app: app-check open ## Same as open, but fail if the app can't be built

app-build: app-check ## Build the release binary app/target/release/treedit-app
	cargo build --release --manifest-path app/Cargo.toml

app-deps: ## Install the system libraries Tauri needs (Ubuntu/Debian, uses sudo)
	sudo apt install -y $(APP_DEPS)

clean: ## Remove .venv, caches and app build output
	rm -rf app/target $(VENV) .ruff_cache .pytest_cache .coverage coverage.xml htmlcov src/treedit/__pycache__ build dist *.egg-info
