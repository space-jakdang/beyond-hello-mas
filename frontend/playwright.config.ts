import {randomUUID} from 'node:crypto';
import { defineConfig } from '@playwright/test';
const apiPort=Number(process.env.E2E_API_PORT||8000), uiPort=Number(process.env.E2E_UI_PORT||5173);
export default defineConfig({testDir: './e2e', use: {baseURL: `http://127.0.0.1:${uiPort}`}, webServer: [
  {command: `uv run uvicorn backend.app.main:create_app --factory --port ${apiPort}`, cwd: '..', url: `http://127.0.0.1:${apiPort}/health`, env: {EVALUATION_ID:randomUUID(),DATA_MODE: 'sample', LLM_MODE: 'fake', GOV24_SERVICE_KEY: '', OPENAI_API_KEY:'', PERSON_MCP_MODE:'stub', RESOURCE_CATALOG:'fixture', MCP_PYTHON:'', MCP_ALLOW_FALLBACK:'false'}},
  {env:{VITE_API_TARGET:`http://127.0.0.1:${apiPort}`},command: `npm run dev -- --port ${uiPort} --strictPort`, url: `http://127.0.0.1:${uiPort}`}
]});
