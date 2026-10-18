.PHONY: install dev sample eval eval-v2 test e2e contracts check
install:
	uv sync --frozen
	npm --prefix frontend ci
dev:
	uv run python -m scripts.dev
sample:
	uv run python -m scripts.sample
	uv run python -m scripts.generate_segments
	uv run python -m scripts.generate_groups
	uv run python -m backend.tools.weekly_signals
eval:
	uv run python -m scripts.evaluate
eval-v2:
	uv run python -m eval.run_v2
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
