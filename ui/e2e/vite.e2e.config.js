import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

/* The Vite server the end-to-end tests drive: the same app as the dev server, on its own port, talking to its own
   backend on 5002 - so a test run never touches the dev servers on 5173 and 5001, or the graph someone is using
   there. Its cache is kept apart from the dev server's for the same reason. */
export default defineConfig({
    root: new URL("..", import.meta.url).pathname,
    cacheDir: "node_modules/.vite-e2e",
    plugins: [react()],
    server: {
        port: 5183,
        strictPort: true,
        proxy: {
            "/api": "http://127.0.0.1:5002",
        },
        fs: {
            // shared/error_types.json lives outside ui/, as in vite.config.js
            allow: [".", "../shared"],
        },
    },
});
