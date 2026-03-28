.PHONY: install lint type test check coverage clean paper hooks

## Setup
install:
	pip install -e ".[dev]"
	pre-commit install

hooks:
	pre-commit install

## Quality
lint:
	ruff check core/ execution/ infra/ pipeline/

lint-fix:
	ruff check --fix core/ execution/ infra/ pipeline/

type:
	mypy core/ execution/ infra/ pipeline/ --strict

test:
	pytest tests/ -v --tb=short

check: lint type test

## Coverage
coverage:
	pytest tests/ --cov=core --cov=execution --cov=infra --cov=pipeline --cov-report=html --cov-report=term-missing
	@echo "HTML report: htmlcov/index.html"

## Trading
paper:
	python -m pipeline.orchestrator --paper --once

paper-loop:
	python -m pipeline.orchestrator --paper

## Cleanup
clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache htmlcov .coverage
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
