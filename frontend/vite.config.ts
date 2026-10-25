import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';
import path from 'path';
import { fileURLToPath } from 'url';

// Inside Docker Compose the backend is reachable as the `finops_agent` service; the compose file
// passes that in as VITE_API_PROXY. Running the frontend straight from the shell has to default to
// the backend on localhost, or every /api call fails and the app silently falls back to mock data.
const apiTarget = process.env.VITE_API_PROXY ?? 'http://127.0.0.1:8000';

export default defineConfig({
  plugins: [
    react(),
    tailwindcss(),
  ],
  resolve: {
    alias: {
      '@': path.resolve(path.dirname(fileURLToPath(import.meta.url)), './src'),
    },
  },
  server: {
    host: '127.0.0.1',
    port: 5173,
    hmr: {
      host: '127.0.0.1',
    },
    proxy: {
      '/api': {
        target: apiTarget,
        changeOrigin: true,
        secure: false,
      }
    }
  },
  // `vite preview` serves the built output, and it is what the container runs - the image
  // bakes the source in, so a dev server in the container has nothing to hot-reload. It needs
  // the same /api proxy, because the browser still calls the backend for everything.
  preview: {
    host: '127.0.0.1',
    port: 5173,
    proxy: {
      '/api': {
        target: apiTarget,
        changeOrigin: true,
        secure: false,
      }
    }
  }
});