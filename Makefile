BUNDLE ?= examples/bundle
IMAGE  ?= graphql-typst-api:dev

.PHONY: help install lock upgrade lint fmt typecheck test test-all cov check \
        bundle-check run warm docker-build docker-run clean

help:
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
	  | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

install:  ## Sync the dev environment
	uv sync --all-extras

lock:  ## Refresh uv.lock
	uv lock

upgrade:  ## Upgrade locked dependencies
	uv lock --upgrade

lint:  ## Lint and check formatting
	uv run ruff check .
	uv run ruff format --check .

fmt:  ## Apply formatting and safe fixes
	uv run ruff check --fix .
	uv run ruff format .

typecheck:  ## Run mypy
	uv run mypy

test:  ## Run the offline test suite
	uv run pytest

test-all:  ## Also run tests that download @preview packages
	GRAPHQL_TYPST_API_TEST_NETWORK=1 uv run pytest

bundle-check:  ## Validate the example bundle
	uv run graphql-typst-api check --bundle-dir $(BUNDLE)

check: lint typecheck test bundle-check  ## Everything CI runs

run:  ## Serve the example bundle locally
	GRAPHQL_TYPST_API_BUNDLE_DIR=$(BUNDLE) uv run graphql-typst-api serve --reload

warm:  ## Populate the Typst @preview package cache
	GRAPHQL_TYPST_API_BUNDLE_DIR=$(BUNDLE) uv run graphql-typst-api warm-cache

docker-build:  ## Build the container image
	docker build -t $(IMAGE) .

docker-run:  ## Run the container image
	docker run --rm -p 8000:8000 \
	  -e GRAPHQL_TYPST_API_GRAPHQL_URL=$(GRAPHQL_TYPST_API_GRAPHQL_URL) $(IMAGE)

clean:  ## Remove caches and build output
	rm -rf dist build .pytest_cache .mypy_cache .ruff_cache htmlcov coverage.xml .coverage
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
