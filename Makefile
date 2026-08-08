SHELL := /bin/bash
APP_HOME ?= $(HOME)/.local/share/moneywiz-tools
APP_VENV := $(APP_HOME)/venv
APP_PY := $(APP_VENV)/bin/python
APP_PYTHON_VERSION ?= 3.11
API_DIR := $(CURDIR)/moneywiz-api
RUNTIME_DIR := $(APP_HOME)/runtime
RUNTIME_SH := $(RUNTIME_DIR)/moneywiz.sh
MONEYWIZ_APP ?= /Applications/Setapp/MoneyWiz 2026.app
CORE_DATA_WRITER_SOURCE := $(CURDIR)/scripts/moneywiz_coredata_writer.swift
CORE_DATA_WRITER_PLIST := $(CURDIR)/scripts/MoneyWizWriter-Info.plist
CORE_DATA_WRITER_APP := $(RUNTIME_DIR)/MoneyWizWriter.app
CORE_DATA_WRITER_BIN := $(CORE_DATA_WRITER_APP)/Contents/MacOS/MoneyWiz

PREFIX ?= $(HOME)/.local
BINDIR ?= $(PREFIX)/bin
INSTALL_NAME ?= moneywiz-cli
INSTALL_PATH ?= $(BINDIR)/$(INSTALL_NAME)
SCRIPT_NAME ?= moneywiz
SCRIPT_PATH ?= $(BINDIR)/$(SCRIPT_NAME)
MARKDOWN_FILES := README.md CHANGELOG.md TODO.md AGENTS.md doc/*.md

.DEFAULT_GOAL := help

.PHONY: help check-deps check-runtime-deps check-coredata-writer-deps build-coredata-writer sync app-venv install-runtime install install-moneywiz install-cli cli uninstall reinstall run clean

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

check-coredata-writer-deps: ## Verify the compiler needed for the compatible write runtime
	@command -v swiftc >/dev/null 2>&1 \
		|| { echo "x swiftc not found; install Xcode Command Line Tools"; exit 1; }

build-coredata-writer: check-coredata-writer-deps ## Compile the MoneyWiz-compatible Core Data writer bundle
	@mkdir -p "$(CORE_DATA_WRITER_APP)/Contents/MacOS"
	@cp -f "$(CORE_DATA_WRITER_PLIST)" "$(CORE_DATA_WRITER_APP)/Contents/Info.plist"
	@if [ -f "$(MONEYWIZ_APP)/Contents/Info.plist" ]; then \
		short_version="$$(/usr/libexec/PlistBuddy -c 'Print :CFBundleShortVersionString' "$(MONEYWIZ_APP)/Contents/Info.plist" 2>/dev/null || true)"; \
		bundle_version="$$(/usr/libexec/PlistBuddy -c 'Print :CFBundleVersion' "$(MONEYWIZ_APP)/Contents/Info.plist" 2>/dev/null || true)"; \
		if [ -n "$$short_version" ]; then /usr/libexec/PlistBuddy -c "Set :CFBundleShortVersionString $$short_version" "$(CORE_DATA_WRITER_APP)/Contents/Info.plist"; fi; \
		if [ -n "$$bundle_version" ]; then /usr/libexec/PlistBuddy -c "Set :CFBundleVersion $$bundle_version" "$(CORE_DATA_WRITER_APP)/Contents/Info.plist"; fi; \
	fi
	@swiftc "$(CORE_DATA_WRITER_SOURCE)" -o "$(CORE_DATA_WRITER_BIN)"
	@chmod +x "$(CORE_DATA_WRITER_BIN)"
	@echo "Built compatible Core Data writer at $(CORE_DATA_WRITER_APP)"

sync: ## Create/refresh the standalone runtime virtualenv
	@$(MAKE) app-venv

app-venv: ## Create/refresh the standalone runtime virtualenv
	@mkdir -p "$(APP_HOME)"
	@command -v uv >/dev/null 2>&1 \
		|| { echo "x uv not found; install uv before installing moneywiz-cli"; exit 1; }
	@if [ ! -x "$(APP_PY)" ] || ! "$(APP_PY)" -c "import sys; raise SystemExit(sys.version_info[:2] != (3, 11))"; then \
		echo "Creating standalone Python $(APP_PYTHON_VERSION) virtualenv at $(APP_VENV)..."; \
		uv venv --clear --python "$(APP_PYTHON_VERSION)" "$(APP_VENV)"; \
	fi
	@uv pip install --python "$(APP_PY)" --upgrade pip setuptools wheel --quiet

install: check-deps ## Install moneywiz wrapper into a standalone self-contained runtime
	@$(MAKE) install-runtime
	@$(MAKE) install-moneywiz
	@echo ""
	@echo "✓ moneywiz wrapper installed successfully"
	@echo "  Run: $(SCRIPT_NAME) --help"

install-cli: check-deps sync ## Install moneywiz-cli into a standalone user venv
	@uv pip install --python "$(APP_PY)" --no-build-isolation --quiet "$(API_DIR)"
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
	@$(MAKE) --no-print-directory build-coredata-writer
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
