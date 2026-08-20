import path from 'node:path'
import { fileURLToPath } from 'node:url'

import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

const ROOT = path.dirname(fileURLToPath(import.meta.url))
const SWITCH = path.resolve(ROOT, 'src/api/index.js')

/* Slice-1 Task 25 — route screen imports through the mock/live switch.

   Screens do `import * as api from '../mock/api.js'`. Task 25 requires the
   live data layer to prove itself with NO edits inside src/screens/, so the
   redirect happens at resolve time instead of in the components.

   Only importers under src/screens/ and src/shell/ are redirected. The switch
   and the HTTP client both import the mock themselves — for ApiError and for
   the fallback implementations — and redirecting those would be circular. */
function apiSwitch() {
  const isConsumer = (importer) => {
    const p = importer.split(path.sep).join('/')
    return p.includes('/src/screens/') || p.includes('/src/shell/')
  }

  return {
    name: 'itr-api-switch',
    enforce: 'pre',
    async resolveId(source, importer, options) {
      if (!importer || !source.endsWith('mock/api.js')) return null
      if (!isConsumer(importer)) return null
      const resolved = await this.resolve(SWITCH, importer, { ...options, skipSelf: true })
      return resolved?.id ?? SWITCH
    },
  }
}

export default defineConfig({
  plugins: [react(), apiSwitch()],
  server: { port: 5173, open: false },
})
