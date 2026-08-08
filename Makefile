SHELL := /bin/bash
APP_HOME ?= $(HOME)/.local/share/moneywiz-tools
APP_VENV := $(APP_HOME)/venv
APP_PY := $(APP_VENV)/bin/python
APP_PIP := $(APP_VENV)/bin/pip
API_DIR := $(CURDIR)/moneywiz-api
RUNTIME_DIR := $(APP_HOME)/runtime
RUNTIME_SH := $(RUNTIME_DIR)/moneywiz.sh

PREFIX ?= $(HOME)/.local
BINDIR ?= $(PREFIX)/bin
INSTALL_NAME ?= moneywiz-cli
INSTALL_PATH ?= $(BINDIR)/$(INSTALL_NAME)
SCRIPT_NAME ?= moneywiz
SCRIPT_PATH ?= $(BINDIR)/$(SCRIPT_NAME)
MARKDOWN_FILES := README.md CHANGELOG.md TODO.md AGENTS.md doc/*.md

.DEFAULT_GOAL := help

.PHONY: help check-deps check-runtime-deps sync app-venv install-runtime install install-moneywiz install-cli cli uninstall reinstall run clean

help: ## Show available targets
	@awk 'BEGIN { FS = ":.*##" } /^[a-zA-Z_-]+:.*##/ { printf "  %-16s %s\n", $$1, $$2 }' $(MAKEFILE_LIST)

check-deps: ## Verify required local tools
	@echo "Checking runtime dependencies..."
	@command -v python3 >/dev/null 2>&1 \
		|| { echo "✗ python3 not found"; exit 1; }
	@python3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" \
		|| { echo "✗ Python 3.10+ required (found $$(python3 --version 2>&1))"; exit 1; }
	@if [ ! -d "$(API_DIR)" ]; then \
		echo "✗ moneywiz-api directory not found at $(API_DIR)"; \
		echo "  Run: git clone https://github.com/marcomc/moneywiz-api.git moneywiz-api"; \
		exit 1; \
	fi
	@mkdir -p "$(BINDIR)"
	@echo "✓ python3 $$(python3 --version 2>&1 | awk '{print $$2}')"
	@if echo "$$PATH" | tr ':' '\n' | grep -Fxq "$(BINDIR)"; then \
		echo "✓ $(BINDIR) is on PATH"; \
	else \
		echo "⚠ $(BINDIR) is not on PATH"; \
		echo "  Add this to your shell profile:"; \
		echo "  export PATH=\"$(BINDIR):\$$PATH\""; \
	fi

check-runtime-deps: check-deps ## Backward-compatible alias

sync: ## Create/refresh the standalone runtime virtualenv
	@$(MAKE) app-venv

app-venv: ## Create/refresh the standalone runtime virtualenv
	@mkdir -p "$(APP_HOME)"
	@if [ ! -x "$(APP_PY)" ]; then \
		echo "Creating standalone virtualenv at $(APP_VENV)..."; \
		python3 -m venv "$(APP_VENV)"; \
	fi
	"$(APP_PIP)" install --upgrade pip --quiet

install: check-deps ## Install moneywiz wrapper into a standalone self-contained runtime
	@$(MAKE) install-runtime
	@$(MAKE) install-moneywiz
	@echo ""
	@echo "✓ moneywiz wrapper installed successfully"
	@echo "  Run: $(SCRIPT_NAME) --help"

install-cli: check-deps sync ## Install moneywiz-cli into a standalone user venv
	"$(APP_PIP)" install --no-build-isolation --quiet "$(API_DIR)"
	@$(MAKE) install-link
	@echo ""
	@echo "✓ moneywiz-cli installed successfully"
	@echo "  Run: $(INSTALL_NAME) --help"

cli: install-cli ## Alias target for installing the moneywiz-cli console entrypoint

install-runtime: ## Copy project runtime payload into a self-contained install directory
	@mkdir -p "$(RUNTIME_DIR)"
	@mkdir -p "$(RUNTIME_DIR)/moneywiz-api/src"
	@mkdir -p "$(RUNTIME_DIR)/scripts"
	@mkdir -p "$(RUNTIME_DIR)/tests"
	@mkdir -p "$(RUNTIME_DIR)/doc"
	@cp -f "$(CURDIR)/moneywiz.sh" "$(RUNTIME_DIR)/moneywiz.sh"
	@cp -f "$(CURDIR)/requirements.txt" "$(RUNTIME_DIR)/requirements.txt"
	@cp -f "$(CURDIR)/.moneywizrc.example" "$(RUNTIME_DIR)/.moneywizrc.example"
	@cp -Rf "$(CURDIR)/moneywiz-api/src/." "$(RUNTIME_DIR)/moneywiz-api/src/"
	@cp -f "$(CURDIR)/moneywiz-api/pyproject.toml" "$(RUNTIME_DIR)/moneywiz-api/pyproject.toml"
	@cp -f "$(CURDIR)/moneywiz-api/README.md" "$(RUNTIME_DIR)/moneywiz-api/README.md"
	@cp -Rf "$(CURDIR)/scripts/." "$(RUNTIME_DIR)/scripts/"
	@cp -Rf "$(CURDIR)/tests/." "$(RUNTIME_DIR)/tests/"
	@cp -Rf "$(CURDIR)/doc/." "$(RUNTIME_DIR)/doc/"
	@echo "✓ Copied self-contained runtime payload to $(RUNTIME_DIR)"

install-link: ## Symlink the CLI entrypoint into ~/.local/bin
	@mkdir -p "$(BINDIR)"
	@if [ -x "$(APP_VENV)/bin/$(INSTALL_NAME)" ]; then \
		ln -sf "$(APP_VENV)/bin/$(INSTALL_NAME)" "$(INSTALL_PATH)"; \
		echo "✓ Linked $(INSTALL_NAME) -> $(INSTALL_PATH)"; \
	else \
		echo "✗ $(APP_VENV)/bin/$(INSTALL_NAME) not found"; \
		exit 1; \
	fi

install-moneywiz: ## Install moneywiz wrapper binary into ~/.local/bin
	@mkdir -p "$(BINDIR)"
	@{ \
		echo '#!/usr/bin/env sh'; \
		echo 'exec "$(RUNTIME_SH)" "$$@"'; \
	} > "$(SCRIPT_PATH)"
	@chmod +x "$(SCRIPT_PATH)"
	@echo "✓ Linked moneywiz wrapper -> $(SCRIPT_PATH)"

uninstall: ## Remove the standalone moneywiz-cli install
	@rm -f "$(INSTALL_PATH)"
	@rm -f "$(SCRIPT_PATH)"
	@rm -rf "$(APP_HOME)"
	@echo "✓ Removed $(INSTALL_PATH)"
	@echo "✓ Removed standalone runtime at $(APP_HOME)"

reinstall: ## Reinstall moneywiz-cli
	@$(MAKE) uninstall
	@$(MAKE) install

run: install ## Show moneywiz-cli help
	"$(INSTALL_PATH)" --help

clean: ## Remove only the generated standalone runtime environment
	rm -rf "$(APP_HOME)"
	@echo "✓ Removed $(APP_HOME)"
