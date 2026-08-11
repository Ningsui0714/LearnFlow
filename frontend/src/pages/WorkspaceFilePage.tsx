import Editor from '@monaco-editor/react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  AlertTriangle, Binary, ExternalLink, FileCode2, Loader2, RefreshCw, Save,
} from 'lucide-react'
import { useLocation, useParams, useSearchParams } from 'react-router-dom'
import { useWorkspace, useWorkspaceTitle } from '../components/workspace/WorkspaceContext'
import {
  getWorkspaceFile, revealWorkspaceItem, saveWorkspaceFile, type WorkspaceFile,
} from '../services/api'
import { getDesktopRuntime } from '../services/desktopRuntime'


const languageByExtension: Record<string, string> = {
  py: 'python', ts: 'typescript', tsx: 'typescript', js: 'javascript', jsx: 'javascript',
  json: 'json', md: 'markdown', html: 'html', css: 'css', scss: 'scss',
  yml: 'yaml', yaml: 'yaml', toml: 'ini', ini: 'ini', sh: 'shell', bash: 'shell',
  sql: 'sql', rs: 'rust', go: 'go', java: 'java', cpp: 'cpp', c: 'c', h: 'cpp',
  txt: 'plaintext', csv: 'plaintext', xml: 'xml', svg: 'xml',
}

function editorLanguage(path: string) {
  const extension = path.split('.').pop()?.toLowerCase() || ''
  return languageByExtension[extension] || 'plaintext'
}

function formatBytes(size: number) {
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`
  return `${(size / 1024 / 1024).toFixed(1)} MB`
}

function errorMessage(error: any) {
  const detail = error?.response?.data?.detail
  if (typeof detail === 'string') return detail
  if (detail?.message) return detail.message
  return error instanceof Error ? error.message : '文件操作失败'
}

export default function WorkspaceFilePage() {
  const { projectId } = useParams()
  const [searchParams] = useSearchParams()
  const location = useLocation()
  const pid = Number(projectId)
  const path = searchParams.get('path') || ''
  const desktop = getDesktopRuntime()
  const { setTabDirty } = useWorkspace()
  const [file, setFile] = useState<WorkspaceFile | null>(null)
  const [content, setContent] = useState('')
  const [savedContent, setSavedContent] = useState('')
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [message, setMessage] = useState('')
  const saveKeyRef = useRef<string | null>(null)
  const title = path.split('/').pop() || '项目文件'
  const tabId = useMemo(() => `${location.pathname}${location.search}`, [location.pathname, location.search])
  const dirty = Boolean(file?.kind === 'workspace_text' && content !== savedContent)

  useWorkspaceTitle(title, { kind: 'file', projectId: pid, workspacePath: path })

  const load = useCallback(async () => {
    if (!desktop.available || !pid || !path) return
    setLoading(true)
    setMessage('')
    try {
      const next = await getWorkspaceFile(pid, path)
      setFile(next)
      setContent(next.content || '')
      setSavedContent(next.content || '')
      saveKeyRef.current = null
    } catch (error) {
      setFile(null)
      setMessage(errorMessage(error))
    } finally {
      setLoading(false)
    }
  }, [desktop.available, path, pid])

  useEffect(() => { void load() }, [load])
  useEffect(() => {
    setTabDirty(tabId, dirty)
    return () => setTabDirty(tabId, false)
  }, [dirty, setTabDirty, tabId])
  useEffect(() => {
    const guard = (event: BeforeUnloadEvent) => {
      if (!dirty) return
      event.preventDefault()
      event.returnValue = ''
    }
    window.addEventListener('beforeunload', guard)
    return () => window.removeEventListener('beforeunload', guard)
  }, [dirty])

  const save = useCallback(async () => {
    if (!file || file.kind !== 'workspace_text' || !dirty || saving) return
    setSaving(true)
    setMessage('')
    if (!saveKeyRef.current) saveKeyRef.current = crypto.randomUUID()
    try {
      const operation = await saveWorkspaceFile(pid, path, {
        content,
        base_hash: file.sha256,
        idempotency_key: saveKeyRef.current,
      })
      setFile(previous => previous ? {
        ...previous,
        sha256: operation.result.sha256,
        size: new TextEncoder().encode(content).length,
        modified_at: new Date().toISOString(),
      } : previous)
      setSavedContent(content)
      saveKeyRef.current = null
      setMessage('已保存')
      window.dispatchEvent(new CustomEvent('learnflow:workspace-changed', { detail: { projectId: pid } }))
    } catch (error) {
      setMessage(errorMessage(error))
    } finally {
      setSaving(false)
    }
  }, [content, dirty, file, path, pid, saving])

  useEffect(() => {
    const keyboardSave = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 's') {
        event.preventDefault()
        void save()
      }
    }
    window.addEventListener('keydown', keyboardSave)
    return () => window.removeEventListener('keydown', keyboardSave)
  }, [save])

  if (!desktop.available) {
    return (
      <div className="flex h-full items-center justify-center bg-slate-950 p-8 text-center text-sm text-slate-300">
        真实本地文件仅在 LearnFlow 桌面版中启用。
      </div>
    )
  }

  return (
    <div className="flex h-full min-h-0 flex-col bg-slate-950 text-slate-100">
      <header className="flex h-11 shrink-0 items-center gap-2 border-b border-slate-700 bg-slate-900 px-3">
        <FileCode2 size={15} className="text-emerald-400" />
        <div className="min-w-0 flex-1 truncate text-xs text-slate-300">
          <span className="text-slate-500">项目文件 / </span>{path}
        </div>
        {message && (
          <span className={`max-w-64 truncate text-[10px] ${message === '已保存' ? 'text-emerald-400' : 'text-amber-300'}`}>
            {message}
          </span>
        )}
        <button
          type="button"
          onClick={() => void load()}
          title="从磁盘重新载入"
          className="flex h-7 w-7 items-center justify-center rounded text-slate-400 hover:bg-slate-700 hover:text-white"
        >
          <RefreshCw size={13} />
        </button>
        <button
          type="button"
          onClick={() => void revealWorkspaceItem(pid, path)}
          title="在 Finder / Explorer 中显示"
          className="flex h-7 w-7 items-center justify-center rounded text-slate-400 hover:bg-slate-700 hover:text-white"
        >
          <ExternalLink size={13} />
        </button>
        <button
          type="button"
          disabled={!dirty || saving || file?.kind !== 'workspace_text'}
          onClick={() => void save()}
          className="flex h-7 items-center gap-1.5 rounded bg-emerald-700 px-2.5 text-[11px] font-semibold text-white enabled:hover:bg-emerald-600 disabled:cursor-not-allowed disabled:opacity-40"
        >
          {saving ? <Loader2 size={12} className="animate-spin" /> : <Save size={12} />}
          保存
        </button>
      </header>

      <div className="min-h-0 flex-1">
        {loading && (
          <div className="flex h-full items-center justify-center text-xs text-slate-400">
            <Loader2 size={16} className="mr-2 animate-spin" /> 正在读取本地文件…
          </div>
        )}
        {!loading && !file && (
          <div className="flex h-full flex-col items-center justify-center gap-3 p-8 text-center text-sm text-slate-400">
            <AlertTriangle size={28} className="text-amber-400" />
            <p>{message || '文件不存在或已移动'}</p>
            <button type="button" onClick={() => void load()} className="rounded bg-slate-800 px-3 py-2 text-xs text-white">重试</button>
          </div>
        )}
        {!loading && file?.kind === 'workspace_text' && (
          <Editor
            height="100%"
            language={editorLanguage(path)}
            value={content}
            onChange={value => {
              setContent(value || '')
              saveKeyRef.current = null
              if (message === '已保存') setMessage('')
            }}
            theme="vs-dark"
            path={`learnflow-workspace://${pid}/${path}`}
            options={{
              automaticLayout: true,
              minimap: { enabled: true },
              fontSize: 13,
              tabSize: 4,
              insertSpaces: true,
              wordWrap: 'off',
              scrollBeyondLastLine: false,
              renderWhitespace: 'selection',
            }}
          />
        )}
        {!loading && file?.kind !== 'workspace_text' && file && (
          <div className="flex h-full items-center justify-center p-8">
            <div className="w-full max-w-md rounded-xl border border-slate-700 bg-slate-900 p-6 text-center">
              <Binary size={38} className="mx-auto mb-4 text-sky-400" />
              <h2 className="text-base font-semibold">大型或二进制文件</h2>
              <p className="mt-2 text-xs leading-5 text-slate-400">为保护编辑器，该文件只显示元数据，不载入正文。</p>
              <dl className="mt-5 grid grid-cols-[90px_1fr] gap-2 text-left text-xs">
                <dt className="text-slate-500">路径</dt><dd className="break-all text-slate-300">{file.path}</dd>
                <dt className="text-slate-500">大小</dt><dd>{formatBytes(file.size)}</dd>
                <dt className="text-slate-500">SHA-256</dt><dd className="break-all font-mono text-[10px] text-slate-400">{file.sha256}</dd>
              </dl>
            </div>
          </div>
        )}
      </div>

      <footer className="flex h-6 shrink-0 items-center gap-4 border-t border-slate-800 bg-emerald-800 px-3 text-[10px] text-emerald-50">
        <span>可信本地工作区</span>
        <span>{file ? formatBytes(file.size) : '—'}</span>
        <span className="ml-auto">{dirty ? '● 未保存' : '已与磁盘同步'}</span>
        <span>{navigator.platform}</span>
      </footer>
    </div>
  )
}
