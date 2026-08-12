SHELL := /bin/bash

USER_CONFIG_DIR := $(HOME)/.config/moneywiz-tools
INSTALL_CONFIG := $(USER_CONFIG_DIR)/install.mk
-include $(INSTALL_CONFIG)

APP_BUNDLE_DIR ?= $(HOME)/Applications
APP_BUNDLE_NAME ?= MoneyWiz Tools.app
APP_BUNDLE := $(APP_BUNDLE_DIR)/$(APP_BUNDLE_NAME)
APP_CONTENTS := $(APP_BUNDLE)/Contents
APP_RUNTIME := $(APP_CONTENTS)/Resources/runtime
APP_HOST := $(APP_CONTENTS)/MacOS/MoneyWizTools
APP_PYTHON_VERSION ?= 3.11
APP_PYTHON_MANAGED := $(APP_RUNTIME)/python/managed
APP_VENV := $(APP_RUNTIME)/python/venv
APP_PY := $(APP_VENV)/bin/python

PREFIX ?= $(HOME)/.local
BINDIR ?= $(PREFIX)/bin
MONEYWIZ_PATH := $(BINDIR)/moneywiz
LEGACY_MONEYWIZ_CLI_PATH := $(BINDIR)/moneywiz-cli

HOST_SOURCE := $(CURDIR)/scripts/moneywiz_tools_host.swift
HOST_PLIST := $(CURDIR)/scripts/MoneyWizTools-Info.plist
PROJECT_FILE := $(CURDIR)/pyproject.toml
LOCK_FILE := $(CURDIR)/uv.lock

.DEFAULT_GOAL := help

.PHONY: help check-deps configure-install-dir build-bundle sync app-venv install-runtime install install-moneywiz uninstall reinstall run clean

help: ## Show available targets
	@awk 'BEGIN { FS = ":.*##" } /^[a-zA-Z_-]+:.*##/ { printf "  %-24s %s\n", $$1, $$2 }' $(MAKEFILE_LIST)

check-deps: ## Verify bundle build dependencies
	@command -v uv >/dev/null 2>&1 \
		|| { echo "x uv not found; install uv before building MoneyWiz Tools"; exit 1; }
	@command -v swiftc >/dev/null 2>&1 \
		|| { echo "x swiftc not found; install Xcode Command Line Tools"; exit 1; }
	@if [ ! -f "$(PROJECT_FILE)" ] || [ ! -f "$(LOCK_FILE)" ]; then \
		echo "x pyproject.toml or uv.lock is missing"; \
		echo "  Run: uv lock"; \
		exit 1; \
	fi
	@mkdir -p "$(BINDIR)"
	@echo "ok uv $$(uv --version | awk '{print $$2}')"
	@echo "ok swiftc $$(swiftc --version | awk 'NR == 1 {print $$4}')"
	@if echo "$$PATH" | tr ':' '\n' | grep -Fxq "$(BINDIR)"; then \
		echo "ok $(BINDIR) is on PATH"; \
	else \
		echo "warning: $(BINDIR) is not on PATH"; \
		echo "  Add: export PATH=\"$(BINDIR):\$$PATH\""; \
	fi

configure-install-dir: ## Persist APP_BUNDLE_DIR in ~/.config/moneywiz-tools/install.mk
	@mkdir -p "$(USER_CONFIG_DIR)"
	@printf 'APP_BUNDLE_DIR := %s\n' "$(APP_BUNDLE_DIR)" > "$(INSTALL_CONFIG)"
	@echo "Saved bundle location in $(INSTALL_CONFIG)"

build-bundle: check-deps ## Build a self-contained MoneyWiz Tools.app bundle
	@rm -rf "$(APP_RUNTIME)"
	@mkdir -p "$(APP_CONTENTS)/MacOS"
	@mkdir -p "$(APP_RUNTIME)/python" "$(APP_RUNTIME)/bin"
	@mkdir -p "$(APP_RUNTIME)/scripts"
	@mkdir -p "$(APP_RUNTIME)/tests" "$(APP_RUNTIME)/doc"
	@cp -f "$(HOST_PLIST)" "$(APP_CONTENTS)/Info.plist"
	@swiftc "$(HOST_SOURCE)" -o "$(APP_HOST)"
	@cp -f "$(CURDIR)/moneywiz.sh" "$(APP_RUNTIME)/moneywiz.sh"
	@cp -f "$(CURDIR)/.moneywizrc.example" "$(APP_RUNTIME)/.moneywizrc.example"
	@cp -Rf "$(CURDIR)/scripts/." "$(APP_RUNTIME)/scripts/"
	@cp -Rf "$(CURDIR)/tests/." "$(APP_RUNTIME)/tests/"
	@cp -Rf "$(CURDIR)/doc/." "$(APP_RUNTIME)/doc/"
	@uv python install --install-dir "$(APP_PYTHON_MANAGED)" --no-bin "$(APP_PYTHON_VERSION)"
	@base_python="$$(find "$(APP_PYTHON_MANAGED)" -type f -path '*/bin/python$(APP_PYTHON_VERSION)' -print -quit)"; \
		if [ -z "$$base_python" ]; then \
			echo "x bundled Python 3 interpreter was not installed"; \
			exit 1; \
		fi; \
		uv venv --clear --relocatable --seed --link-mode copy --python "$$base_python" "$(APP_VENV)"
	@uv export --project "$(CURDIR)" --frozen --no-dev --format requirements-txt --output-file "$(APP_RUNTIME)/requirements.txt"
	@uv pip install --python "$(APP_PY)" --quiet --requirement "$(APP_RUNTIME)/requirements.txt"
	@chmod +x "$(APP_RUNTIME)/moneywiz.sh"
	@echo "Built self-contained bundle at $(APP_BUNDLE)"

sync: build-bundle ## Build or refresh the application bundle

app-venv: build-bundle ## Backward-compatible alias for building the bundled Python runtime

install-runtime: build-bundle ## Backward-compatible alias for building the application bundle

install: build-bundle ## Install moneywiz as a symlink into ~/.local/bin
	@$(MAKE) --no-print-directory install-moneywiz
	@rm -f "$(LEGACY_MONEYWIZ_CLI_PATH)"
	@echo ""
	@echo "ok moneywiz installed successfully"
	@echo "  Run: moneywiz --help"

install-moneywiz: ## Link the moneywiz command to the bundle runtime
	@mkdir -p "$(BINDIR)"
	@ln -sfn "$(APP_RUNTIME)/moneywiz.sh" "$(MONEYWIZ_PATH)"
	@echo "ok linked moneywiz -> $(MONEYWIZ_PATH)"

uninstall: ## Remove the application bundle and command symlinks
	@rm -f "$(MONEYWIZ_PATH)" "$(LEGACY_MONEYWIZ_CLI_PATH)"
	@rm -rf "$(APP_BUNDLE)"
	@echo "ok removed $(APP_BUNDLE) and command symlinks"

reinstall: ## Rebuild and reinstall the application bundle
	@$(MAKE) --no-print-directory uninstall
	@$(MAKE) --no-print-directory install

run: install ## Show moneywiz help from the installed bundle
	@"$(MONEYWIZ_PATH)" --help

clean: uninstall ## Alias for removing the installed bundle
