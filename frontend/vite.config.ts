import path from 'node:path'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { defineConfig } from 'vite'

// In Docker Compose set VITE_API_PROXY=http://backend:8000 (service name).
// Falls back to 127.0.0.1 for local Windows IPv4 routing.
const apiTarget = process.env.VITE_API_PROXY ?? 'http://127.0.0.1:8000'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: { alias: { '@': path.resolve(import.meta.dirname, './src') } },
  server: {
    port: 5173,
    host: true, // listen on 0.0.0.0 so the container port is reachable
    proxy: { '/api': apiTarget },
  },
})