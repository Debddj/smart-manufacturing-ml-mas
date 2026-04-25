import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
      '/ws': {
        target: 'ws://localhost:8000',
        ws: true,
      },
      '/mas-ops': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
      '/dashboard': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
      '/frontend': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
      '/demand': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
      '/demand_forecast.html': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
      '/mas_ops.html': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
})
