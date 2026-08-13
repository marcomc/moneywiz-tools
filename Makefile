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
BUNDLE_RUNTIME_ROOTS := moneywiz.sh .moneywizrc.example

.DEFAULT_GOAL := help

.PHONY: help check-deps configure-install-dir build-bundle _build-bundle _validate-bundle sync app-venv install-runtime install install-moneywiz uninstall reinstall run clean

help: ## Show available targets
	@awk 'BEGIN { FS = ":.*##" } /^[a-zA-Z_-]+:.*##/ { printf "  %-24s %s\n", $$1, $$2 }' $(MAKEFILE_LIST)

check-deps: ## Verify bundle build dependencies
	@command -v git >/dev/null 2>&1 \
		|| { echo "x git not found; install Git before building MoneyWiz Tools"; exit 1; }
	@command -v uv >/dev/null 2>&1 \
		|| { echo "x uv not found; install uv before building MoneyWiz Tools"; exit 1; }
	@command -v swiftc >/dev/null 2>&1 \
		|| { echo "x swiftc not found; install Xcode Command Line Tools"; exit 1; }
	@if [ ! -f "$(PROJECT_FILE)" ] || [ ! -f "$(LOCK_FILE)" ]; then \
		echo "x pyproject.toml or uv.lock is missing"; \
		echo "  Run: uv lock"; \
		exit 1; \
	fi
	@git -C "$(CURDIR)" rev-parse --is-inside-work-tree >/dev/null 2>&1 \
		|| { echo "x bundle source is not a Git worktree: $(CURDIR)"; exit 1; }
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

_build-bundle:
	@mkdir -p "$(APP_CONTENTS)/MacOS"
	@mkdir -p "$(APP_RUNTIME)/python" "$(APP_RUNTIME)/bin"
	@mkdir -p "$(APP_RUNTIME)/scripts" "$(APP_RUNTIME)/doc"
	@cp -f "$(HOST_PLIST)" "$(APP_CONTENTS)/Info.plist"
	@swiftc -parse-as-library "$(HOST_SOURCE)" -o "$(APP_HOST)"
	@set -eu; \
		for payload_path in $(BUNDLE_RUNTIME_ROOTS); do \
			cp -f "$(CURDIR)/$$payload_path" "$(APP_RUNTIME)/$$payload_path"; \
		done; \
		manifest="$(APP_RUNTIME)/.tracked-payload"; \
		git -C "$(CURDIR)" ls-files -z -- scripts doc > "$$manifest"; \
		while IFS= read -r -d '' payload_path; do \
			destination="$(APP_RUNTIME)/$$payload_path"; \
			mkdir -p "$$(dirname "$$destination")"; \
			cp -f "$(CURDIR)/$$payload_path" "$$destination"; \
		done < "$$manifest"; \
		rm -f "$$manifest"
	@uv python install --install-dir "$(APP_PYTHON_MANAGED)" --no-bin "$(APP_PYTHON_VERSION)"
	@base_python="$$(find "$(APP_PYTHON_MANAGED)" -type f -path '*/bin/python$(APP_PYTHON_VERSION)' -print -quit)"; \
		if [ -z "$$base_python" ]; then \
			echo "x bundled Python 3 interpreter was not installed"; \
			exit 1; \
		fi; \
		uv venv --clear --relocatable --seed --link-mode copy --python "$$base_python" "$(APP_VENV)"; \
		managed_python="$${base_python#$(APP_RUNTIME)/python/}"; \
		if [ "$$managed_python" = "$$base_python" ]; then \
			echo "x bundled Python path is outside the staged runtime"; \
			exit 1; \
		fi; \
		ln -sfn "../../$$managed_python" "$(APP_VENV)/bin/python"
	@uv export --project "$(CURDIR)" --frozen --no-dev --format requirements-txt --output-file "$(APP_RUNTIME)/requirements.txt"
	@uv pip install --python "$(APP_PY)" --quiet --requirement "$(APP_RUNTIME)/requirements.txt"
	@chmod +x "$(APP_RUNTIME)/moneywiz.sh"

_validate-bundle:
	@test -f "$(APP_CONTENTS)/Info.plist" \
		|| { echo "x bundle is missing Contents/Info.plist"; exit 1; }
	@test -x "$(APP_HOST)" \
		|| { echo "x bundle is missing the executable Core Data host"; exit 1; }
	@test -x "$(APP_RUNTIME)/moneywiz.sh" \
		|| { echo "x bundle is missing the executable moneywiz launcher"; exit 1; }
	@test -x "$(APP_PY)" \
		|| { echo "x bundle is missing the bundled Python interpreter"; exit 1; }

build-bundle: ## Build a self-contained MoneyWiz Tools.app bundle
	@set -eu; \
		mkdir -p "$(APP_BUNDLE_DIR)"; \
		backup_bundle="$(APP_BUNDLE_DIR)/.$(APP_BUNDLE_NAME).previous"; \
		if [ -e "$$backup_bundle" ] || [ -L "$$backup_bundle" ]; then \
			if [ -e "$(APP_BUNDLE)" ] || [ -L "$(APP_BUNDLE)" ]; then \
				if ! $(MAKE) --no-print-directory _validate-bundle; then \
					echo "x both active and recovery bundles exist; leaving both for manual inspection" >&2; \
					exit 1; \
				fi; \
				rm -rf "$$backup_bundle"; \
			else \
				mv "$$backup_bundle" "$(APP_BUNDLE)"; \
				echo "ok restored interrupted bundle promotion"; \
			fi; \
		fi; \
		$(MAKE) --no-print-directory check-deps; \
		staging_bundle="$$(mktemp -d "$(APP_BUNDLE_DIR)/.$(APP_BUNDLE_NAME).staging.XXXXXX")"; \
		previous_moved=0; \
		cleanup() { \
			status="$$?"; \
			trap - EXIT HUP INT TERM; \
			if [ "$$previous_moved" -eq 1 ] && { [ -e "$$backup_bundle" ] || [ -L "$$backup_bundle" ]; }; then \
				if [ ! -e "$(APP_BUNDLE)" ] && [ ! -L "$(APP_BUNDLE)" ]; then \
					mv "$$backup_bundle" "$(APP_BUNDLE)" \
						|| { echo "x failed to restore the previous bundle from $$backup_bundle" >&2; status=1; }; \
				elif [ ! -e "$$staging_bundle" ] && [ ! -L "$$staging_bundle" ]; then \
					rm -rf "$$backup_bundle"; \
				else \
					echo "x bundle recovery requires manual inspection: $$backup_bundle" >&2; \
					status=1; \
				fi; \
			fi; \
			if [ -e "$$staging_bundle" ] || [ -L "$$staging_bundle" ]; then \
				rm -rf "$$staging_bundle"; \
			fi; \
			exit "$$status"; \
		}; \
		trap cleanup EXIT; \
		trap 'exit 1' HUP INT TERM; \
		$(MAKE) --no-print-directory _build-bundle APP_BUNDLE="$$staging_bundle"; \
		$(MAKE) --no-print-directory _validate-bundle APP_BUNDLE="$$staging_bundle"; \
		if [ -e "$(APP_BUNDLE)" ] || [ -L "$(APP_BUNDLE)" ]; then \
			mv "$(APP_BUNDLE)" "$$backup_bundle"; \
			previous_moved=1; \
		fi; \
		if ! mv "$$staging_bundle" "$(APP_BUNDLE)"; then \
			echo "x failed to publish the staged bundle" >&2; \
			exit 1; \
		fi; \
		if [ "$$previous_moved" -eq 1 ]; then \
			rm -rf "$$backup_bundle"; \
			previous_moved=0; \
		fi; \
		trap - EXIT HUP INT TERM
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
	@$(MAKE) --no-print-directory _validate-bundle
	@set -eu; \
		mkdir -p "$(BINDIR)"; \
		if [ -d "$(MONEYWIZ_PATH)" ] && [ ! -L "$(MONEYWIZ_PATH)" ]; then \
			echo "x cannot replace directory at $(MONEYWIZ_PATH)" >&2; \
			exit 1; \
		fi; \
		temporary_link="$$(mktemp "$(BINDIR)/.moneywiz.link.XXXXXX")"; \
		trap 'rm -f "$$temporary_link"' EXIT HUP INT TERM; \
		rm -f "$$temporary_link"; \
		ln -s "$(APP_RUNTIME)/moneywiz.sh" "$$temporary_link"; \
		mv -f "$$temporary_link" "$(MONEYWIZ_PATH)"; \
		trap - EXIT HUP INT TERM
	@echo "ok linked moneywiz -> $(MONEYWIZ_PATH)"

uninstall: ## Remove the application bundle and command symlinks
	@rm -f "$(MONEYWIZ_PATH)" "$(LEGACY_MONEYWIZ_CLI_PATH)"
	@rm -rf "$(APP_BUNDLE)"
	@echo "ok removed $(APP_BUNDLE) and command symlinks"

reinstall: ## Rebuild and reinstall the application bundle
	@$(MAKE) --no-print-directory install

run: install ## Show moneywiz help from the installed bundle
	@"$(MONEYWIZ_PATH)" --help

clean: uninstall ## Alias for removing the installed bundle
