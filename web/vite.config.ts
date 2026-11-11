import { readFileSync } from 'node:fs'
import path from 'node:path'
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

const pkg = JSON.parse(readFileSync(new URL('./package.json', import.meta.url), 'utf8')) as { version: string }

// `opennav serve` serves the API on this port; the dev server proxies /api to it.
const apiPort = process.env.OPENNAV_API_PORT || '8765'

// https://vite.dev/config/
export default defineConfig({
  base: './',
  plugins: [react(), tailwindcss()],
  define: { __APP_VERSION__: JSON.stringify(pkg.version) },
  resolve: {
    alias: {
      '@': path.resolve(import.meta.dirname, './src'),
    },
  },
  build: {
    // The Python package serves the built app (opennav/viewer/static), so
    // `opennav serve` works without Node installed.
    outDir: path.resolve(import.meta.dirname, '../opennav/viewer/static'),
    emptyOutDir: true,
    chunkSizeWarningLimit: 1500,
  },
  server: {
    port: 5173,
    proxy: { '/api': `http://127.0.0.1:${apiPort}` },
  },
})
