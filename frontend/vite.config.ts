import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    // same origin as the API in dev, otherwise the session cookie is
    // cross-site and SameSite=Strict drops it on every request
    proxy: {
      '/api': 'http://localhost:8000',
    },
  },
})
