import { defineConfig } from "vite";

// GitHub Pages serves the site at /world-attention/; the dev server at /.
export default defineConfig(({ command }) => ({
  base: command === "build" ? (process.env.SITE_BASE || "/world-attention/") : "/",
  build: { outDir: "dist", emptyOutDir: true, target: "es2020" },
  // dev only: lets the dev server show the reference boards at /@fs/<repo>/docs/boards/*.html
  server: { port: 5173, strictPort: true, fs: { allow: [".."] } },
}));
