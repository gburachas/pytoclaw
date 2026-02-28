.PHONY: install dev test lint typecheck clean docker

install:
	uv sync

dev:
	uv sync --all-extras

test:
	uv run pytest tests/ -v

test-cov:
	uv run pytest tests/ -v --cov=pyclaw --cov-report=term-missing

lint:
	uv run ruff check src/ tests/

lint-fix:
	uv run ruff check --fix src/ tests/

typecheck:
	uv run mypy src/pyclaw/

clean:
	rm -rf build/ dist/ *.egg-info src/*.egg-info .pytest_cache .mypy_cache .ruff_cache
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true

docker:
	docker build -t pyclaw:latest .

docker-run:
	docker run --rm -v ~/.pyclaw:/root/.pyclaw pyclaw:latest
