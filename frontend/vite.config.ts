import { defineConfig } from 'vite';
export default defineConfig({server: {proxy: Object.fromEntries(['/policies', '/analysis', '/health', '/runs', '/scenarios', '/alerts', '/reports'].map(path => [path, process.env.VITE_API_TARGET || 'http://127.0.0.1:8000']))}});
