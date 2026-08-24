// Keep Monaco in editor route chunks. Importing it from main.tsx made even the
// login page download and parse the full editor runtime.
import { loader } from '@monaco-editor/react'
import * as monaco from 'monaco-editor'
import editorWorker from 'monaco-editor/esm/vs/editor/editor.worker?worker'

let configured = false

export function configureMonacoRuntime() {
  if (configured) return
  configured = true
  ;(self as any).MonacoEnvironment = {
    getWorker: () => new editorWorker(),
  }
  loader.config({ monaco })
}
