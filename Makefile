.PHONY: install dev sample eval test e2e contracts check
install:
	uv sync --frozen
	npm --prefix frontend ci
dev:
	uv run python -m scripts.dev
sample:
	uv run python -m scripts.sample
	uv run python -m scripts.generate_segments
eval:
	uv run python -m scripts.evaluate
contracts:
	uv run python -m scripts.contracts
test:
	uv run pytest
	npm --prefix frontend run build
e2e:
	npm --prefix frontend run test:e2e
check: test e2e
	uv run python scripts/check_public.py --tracked

classify:
	uv run python -m scripts.classify
