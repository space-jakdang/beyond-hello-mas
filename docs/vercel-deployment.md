# Vercel preview deployment

The repository root is a FastAPI application. Vercel builds the Vite frontend through the `tool.vercel.scripts.build` command in `pyproject.toml`; FastAPI serves the resulting frontend and API from one origin. Keep API credentials in Vercel server-side Environment Variables. Never prefix them with `VITE_`.

In the Vercel project setup, use:

| Setting | Value |
|---|---|
| Root Directory | `./` |
| Framework Preset | `FastAPI` |
| Build Command | Leave blank (the repository build script runs) |
| Output Directory | Leave blank (FastAPI serves `frontend/dist`) |
| Install Command | Leave blank (Vercel detects Python dependencies) |

Set these server-side Environment Variables for Preview (and Production only when ready):

| Name | Value |
|---|---|
| `DATA_MODE` | `sample` |
| `LLM_MODE` | `live` |
| `OPENAI_API_KEY` | Your OpenAI API key |
| `OPENAI_MODEL` | A model enabled for your API project, such as `gpt-5.6-terra` |
| `INPUT_USD_PER_MILLION` | Current model input price; for `gpt-5.6-terra`, `2` |
| `OUTPUT_USD_PER_MILLION` | Current model output price; for `gpt-5.6-terra`, `12` |
| `PRICE_VERSION` | A label recording when you checked the prices, e.g. `2026-10-23` |
| `LLM_BUDGET_USD` | A nonzero total budget, e.g. `2` |
| `LLM_RUN_BUDGET_USD` | Optional per-run cap, e.g. `0.35` |
| `GOV24_API_KEY` | Your data.go.kr 대한민국 공공서비스(혜택) 정보 service key |
| `PERSON_MCP_MODE` | `stub` |

The key values must be entered in Vercel’s server environment settings, not in Build Environment Variables or frontend settings. `OPENAI_API_KEY` and `GOV24_API_KEY` are read only by the Python runtime. Vercel creates a new deployment after environment variables change.

The model and prices above are an example, and must match the model actually selected in your OpenAI project. OpenAI currently lists GPT-5.6 Terra at $2 per million input tokens and $12 per million output tokens; check the [current model page](https://developers.openai.com/api/docs/models/gpt-5.6-terra) before changing these values. This application requires model pricing and a nonzero budget to enable live calls.

## Runtime limit

Vercel Functions have a read-only filesystem except for temporary `/tmp` storage. This deployment redirects runtime files there so the app can start and make real API calls. `/tmp` is not durable and is not shared reliably between function instances. Runs, approvals, checkpoints, cached Gov24 data, and quality-job artifacts can disappear or be unavailable on a later request or cold start. FastAPI background tasks are also not a durable job queue. Use this only as a live Preview/demo; persistent workflows require a shared PostgreSQL store and durable worker/queue before public production use.
