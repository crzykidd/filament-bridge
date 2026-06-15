import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import * as fs from 'fs'
import * as path from 'path'

export default defineConfig({
  plugins: [
    react(),
    // In dev mode, serve ../docs/*.md as /docs-md/<file>.md so DocsViewer
    // works without a Docker build.
    {
      name: 'docs-md-dev-server',
      configureServer(server) {
        server.middlewares.use((req, res, next) => {
          const url = req.url ?? ''
          const match = url.match(/^\/docs-md\/([^/?#]+\.md)(\?.*)?$/)
          if (!match) return next()
          const filename = match[1]
          const docsDir = path.resolve(__dirname, '../docs')
          const filePath = path.join(docsDir, filename)
          // Security: ensure the resolved path is within docs/
          if (!filePath.startsWith(docsDir + path.sep) && filePath !== docsDir) {
            res.writeHead(403)
            res.end()
            return
          }
          if (!fs.existsSync(filePath)) {
            res.writeHead(404)
            res.end()
            return
          }
          res.setHeader('Content-Type', 'text/plain; charset=utf-8')
          res.end(fs.readFileSync(filePath, 'utf-8'))
        })
      },
    },
  ],
  build: {
    outDir: 'dist',
  },
  server: {
    proxy: {
      '/api': {
        target: 'http://localhost:8090',
        changeOrigin: true,
      },
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test-setup.ts'],
  },
})
