.DEFAULT_GOAL := help

PY ?= python
PIP ?= $(PY) -m pip
PYTEST ?= $(PY) -m pytest

.PHONY: help
help:
	@echo "Available targets:"
	@echo "  install      pip install -e .[dev]"
	@echo "  test         run the full test suite"
	@echo "  test-fast    run pytest excluding the slow tier"
	@echo "  lint         ruff check + mypy"
	@echo "  format       ruff format"
	@echo "  typecheck    mypy --strict on src/"
	@echo "  clean        remove caches and build artefacts"

.PHONY: install
install:
	$(PIP) install -e ".[dev]"

.PHONY: test
test:
	$(PYTEST)

.PHONY: test-fast
test-fast:
	$(PYTEST) -m "not slow"

.PHONY: lint
lint:
	$(PY) -m ruff check .
	$(PY) -m ruff format --check .
	$(PY) -m mypy src

.PHONY: format
format:
	$(PY) -m ruff format .

.PHONY: typecheck
typecheck:
	$(PY) -m mypy src

.PHONY: clean
clean:
	rm -rf .mypy_cache .pytest_cache .ruff_cache build dist *.egg-info \
	       src/*.egg-info **/__pycache__ .coverage htmlcov
