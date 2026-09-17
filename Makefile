# Makefile — convenience commands for local development
# Usage: make <target>

.DEFAULT_GOAL := help
PYTHON        := python
VENV          := .venv
PIP           := $(VENV)/bin/pip
PYTEST        := $(VENV)/bin/pytest

.PHONY: help venv install test lint discover archive weekly-queue setup-notion clean

help:  ## Show this help message
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
	  awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'

venv:  ## Create the virtual environment
	$(PYTHON) -m venv $(VENV)
	$(VENV)/bin/pip install --upgrade pip

install: venv  ## Install all dependencies into the venv
	$(VENV)/bin/pip install -r requirements.txt
	@echo "✓ Dependencies installed. Activate with: source $(VENV)/bin/activate"

test:  ## Run the test suite (no credentials required)
	$(PYTEST)

test-v:  ## Run tests with verbose output
	$(PYTEST) -v

discover:  ## Run the daily discovery pipeline (requires .env)
	@[ -f .env ] && export $$(cat .env | grep -v '^#' | xargs) ; $(PYTHON) main.py

archive:  ## Run the archive job (requires .env)
	@[ -f .env ] && export $$(cat .env | grep -v '^#' | xargs) ; $(PYTHON) -m src.archive

weekly-queue:  ## Run the weekly queue generator (requires .env)
	@[ -f .env ] && export $$(cat .env | grep -v '^#' | xargs) ; $(PYTHON) -m src.weekly_queue

setup-notion:  ## Create the Notion database (usage: make setup-notion PAGE_ID=<page_id>)
	@[ -f .env ] && export $$(cat .env | grep -v '^#' | xargs) ; \
	  $(PYTHON) scripts/setup_notion.py $(PAGE_ID)

lint:  ## Run basic syntax check on all Python files
	$(PYTHON) -m py_compile main.py src/*.py src/ingest/*.py scripts/*.py
	@echo "✓ Syntax OK"

clean:  ## Remove compiled Python files and pytest cache
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -delete 2>/dev/null || true
	rm -rf .pytest_cache .coverage htmlcov
