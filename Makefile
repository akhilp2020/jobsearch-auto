UV ?= uv

.PHONY: dev test fmt lint

dev:
	$(UV) sync

test:
	$(UV) run pytest

fmt:
	$(UV) run black .
	$(UV) run ruff check . --fix

lint:
	$(UV) run ruff check .
