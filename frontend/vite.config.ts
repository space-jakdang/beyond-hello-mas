import { defineConfig } from 'vite';
export default defineConfig({server: {proxy: Object.fromEntries(['/analysis', '/health', '/runs', '/scenarios', '/alerts', '/reports'].map(path => [path, 'http://127.0.0.1:8000']))}});
