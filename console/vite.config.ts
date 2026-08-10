import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Console shell (W1-CON-01) — proxies API to the FastAPI skeleton on :8090
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    host: true,
    proxy: {
      '/api': {
        target: process.env.VITE_API_PROXY || 'http://127.0.0.1:8090',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
    },
  },
})
