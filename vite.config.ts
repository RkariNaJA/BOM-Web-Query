import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Builds into src/static so FastAPI's existing StaticFiles mount and the
// FileResponse at "/" serve the app with no change to main.py.
export default defineConfig(({ command }) => ({
  root: 'web',
  base: command === 'build' ? '/static/' : '/',
  plugins: [react()],
  server: {
    host: '0.0.0.0',
    port: 5180,
    proxy: {
      '/api': { target: 'http://127.0.0.1:8000', changeOrigin: false },
    },
  },
  build: {
    outDir: '../src/static',
    emptyOutDir: true,
  },
}))
