import { defineConfig } from 'vite';
import vue from '@vitejs/plugin-vue';
import { resolve } from 'path';
export default defineConfig({
    plugins: [vue()],
    resolve: {
        alias: {
            '@': resolve(__dirname, 'src'),
        },
    },
    server: {
        port: 5173,
        proxy: {
            // Chat SSE → existing FastAPI backend
            '/v1': {
                target: 'http://localhost:8000',
                changeOrigin: true,
            },
            // Character CRUD → existing FastAPI backend
            '/api/characters': {
                target: 'http://localhost:8000',
                changeOrigin: true,
            },
            // Health check → existing FastAPI backend
            '/health': {
                target: 'http://localhost:8000',
                changeOrigin: true,
            },
            // pg_cline queries → FastAPI backend
            '/pg-api': {
                target: 'http://localhost:8000',
                changeOrigin: true,
                rewrite: (path) => path.replace(/^\/pg-api/, '/api/pg'),
            },
        },
    },
});
