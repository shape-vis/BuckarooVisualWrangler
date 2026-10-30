import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': 'http://localhost:5001',
    },
    host:true,
    fs: {
      // shared/ holds what the backend and the frontend both read, such as error_types.json - outside ui/, which
      // the dev server only serves when told to. Both paths are relative to ui/, the project's root.
      allow: ['.', '../shared'],
    },
  }
})
