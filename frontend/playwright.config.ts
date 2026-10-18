import { defineConfig } from '@playwright/test';
export default defineConfig({testDir: './e2e', use: {baseURL: 'http://127.0.0.1:5173'}, webServer: [
  {command: 'uv run uvicorn backend.app.main:create_app --factory --port 8000', cwd: '..', url: 'http://127.0.0.1:8000/health', env: {DATA_MODE: 'sample', LLM_MODE: 'fake', GOV24_SERVICE_KEY: '', OPENAI_API_KEY:'', PERSON_MCP_MODE:'stub', RESOURCE_CATALOG:'fixture'}},
  {command: 'npm run dev -- --port 5173 --strictPort', url: 'http://127.0.0.1:5173'}
]});
