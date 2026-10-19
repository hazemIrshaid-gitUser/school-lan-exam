import path from 'path';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';
import { defineConfig } from 'vite';

// Static build for the offline exam server. The server serves these files under /monitor-ui/ (see monitor_ui_asset in server.py)
// and the page itself at /monitor. No external requests of any kind.
export default defineConfig({
  base: '/monitor-ui/',
  plugins: [react(), tailwindcss()],
  resolve: { alias: { '@': path.resolve(import.meta.dirname, 'src') }, dedupe: ['react', 'react-dom'] },
  build: { outDir: path.resolve(import.meta.dirname, 'dist'), emptyOutDir: true },
});
