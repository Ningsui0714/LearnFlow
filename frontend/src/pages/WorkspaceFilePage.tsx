import Editor from '@monaco-editor/react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  AlertTriangle, Binary, Braces, ExternalLink, FileCode2, Loader2, Play, RefreshCw, Save,
} from 'lucide-react'
import { useLocation, useParams, useSearchParams } from 'react-router-dom'
import { useWorkspace, useWorkspaceTitle } from '../components/workspace/WorkspaceContext'
import {
  confirmWorkspaceOperation, getWorkspaceFile, getWorkspaceRuntimeConfig,
  revealWorkspaceItem, runWorkspacePython, saveWorkspaceFile, setWorkspaceRuntimeConfig,
  type WorkspaceFile, type WorkspaceOperation, type WorkspaceRuntimeConfig,
} from '../services/api'
import { choosePythonInterpreter, getDesktopRuntime } from '../services/desktopRuntime'


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
  const [runtime, setRuntime] = useState<WorkspaceRuntimeConfig | null>(null)
  const [runtimeBusy, setRuntimeBusy] = useState(false)
  const [runArgs, setRunArgs] = useState('[]')
  const [runOperation, setRunOperation] = useState<WorkspaceOperation | null>(null)
  const saveKeyRef = useRef<string | null>(null)
  const title = path.split('/').pop() || '项目文件'
  const tabId = useMemo(() => `${location.pathname}${location.search}`, [location.pathname, location.search])
  const dirty = Boolean(file?.kind === 'workspace_text' && content !== savedContent)
  const isPython = path.toLowerCase().endsWith('.py')

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
    if (!desktop.available || !pid || !isPython) return
    getWorkspaceRuntimeConfig(pid).then(setRuntime).catch(() => setRuntime(null))
  }, [desktop.available, isPython, pid])
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

  const chooseInterpreter = async () => {
    const selected = await choosePythonInterpreter()
    if (!selected) return
    setRuntimeBusy(true)
    setMessage('')
    try {
      setRuntime(await setWorkspaceRuntimeConfig(pid, selected))
      setMessage('Python 解释器已更新')
    } catch (error) {
      setMessage(errorMessage(error))
    } finally {
      setRuntimeBusy(false)
    }
  }

  const proposeRun = async (mode: 'syntax' | 'run') => {
    if (!runtime?.configured) {
      setMessage('请先选择项目 Python 解释器')
      return
    }
    if (dirty) {
      setMessage('请先保存文件，再生成运行计划')
      return
    }
    let args: string[] = []
    try {
      const parsed = JSON.parse(runArgs || '[]')
      if (!Array.isArray(parsed) || parsed.some(value => typeof value !== 'string')) throw new Error()
      args = parsed
    } catch {
      setMessage('参数必须是 JSON 字符串数组，例如 ["--seed", "7"]')
      return
    }
    setRuntimeBusy(true)
    try {
      setRunOperation(await runWorkspacePython(pid, {
        actor: 'user', mode, path, args, confirmed: false,
        idempotency_key: crypto.randomUUID(),
      }))
      setMessage('请核对运行计划并确认')
    } catch (error) {
      setMessage(errorMessage(error))
    } finally {
      setRuntimeBusy(false)
    }
  }

  const confirmRun = async () => {
    if (!runOperation) return
    setRuntimeBusy(true)
    try {
      const completed = await confirmWorkspaceOperation(pid, runOperation.id)
      setRunOperation(completed)
      setMessage(completed.result.passed ? '运行完成' : '运行结束，请检查输出')
    } catch (error) {
      setMessage(errorMessage(error))
    } finally {
      setRuntimeBusy(false)
    }
  }

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
        {isPython && (
          <>
            <button type="button" onClick={() => void chooseInterpreter()} disabled={runtimeBusy} title={runtime?.interpreter_path || '选择 Python 解释器'} className="flex h-7 items-center gap-1 rounded border border-slate-600 px-2 text-[10px] text-slate-300 hover:bg-slate-700 disabled:opacity-50">
              <Braces size={12} />{runtime?.configured ? runtime.version || 'Python' : '选择解释器'}
            </button>
            <button type="button" onClick={() => void proposeRun('syntax')} disabled={runtimeBusy || dirty} className="h-7 rounded border border-sky-700 px-2 text-[10px] text-sky-300 hover:bg-sky-950 disabled:opacity-40">语法检查</button>
            <button type="button" onClick={() => void proposeRun('run')} disabled={runtimeBusy || dirty} className="flex h-7 items-center gap-1 rounded bg-sky-700 px-2 text-[10px] font-semibold text-white hover:bg-sky-600 disabled:opacity-40"><Play size={11} />运行</button>
          </>
        )}
      </header>

      {isPython && (
        <div className="shrink-0 border-b border-slate-700 bg-slate-900 px-3 py-2 text-[10px] text-slate-300">
          <div className="flex items-center gap-2">
            <span className="text-slate-500">参数 JSON</span>
            <input value={runArgs} onChange={event => setRunArgs(event.target.value)} className="h-6 min-w-0 flex-1 rounded border border-slate-700 bg-slate-950 px-2 font-mono outline-none focus:border-sky-600" />
            <span className="text-amber-300">可信本地执行，不是容器沙箱；不会自动安装依赖</span>
          </div>
          {runOperation?.status === 'proposed' && (
            <div className="mt-2 grid grid-cols-[72px_1fr_auto] gap-x-2 gap-y-1 rounded border border-amber-800 bg-amber-950/30 p-2">
              <span className="text-slate-500">解释器</span><code className="break-all">{runOperation.result.plan?.interpreter?.interpreter_path}</code><span />
              <span className="text-slate-500">脚本</span><code>{runOperation.result.plan?.script}</code><span />
              <span className="text-slate-500">工作目录</span><code className="break-all">{runOperation.result.plan?.working_directory}</code><span />
              <span className="text-slate-500">参数</span><code>{JSON.stringify(runOperation.result.plan?.args || [])}</code>
              <div className="flex gap-1">
                <button type="button" onClick={() => setRunOperation(null)} className="rounded px-2 py-1 text-slate-400 hover:bg-slate-800">取消</button>
                <button type="button" onClick={() => void confirmRun()} disabled={runtimeBusy} className="rounded bg-amber-600 px-2 py-1 font-semibold text-white hover:bg-amber-500 disabled:opacity-50">确认执行</button>
              </div>
            </div>
          )}
          {runOperation?.status === 'applied' && (
            <div className="mt-2 max-h-36 overflow-auto rounded border border-slate-700 bg-slate-950 p-2 font-mono">
              <p className={runOperation.result.passed ? 'text-emerald-400' : 'text-red-400'}>
                {runOperation.result.passed ? '执行成功' : `退出码 ${runOperation.result.exit_code ?? '超时'}`} · {runOperation.result.elapsed}s
              </p>
              {runOperation.result.stdout && <pre className="mt-1 whitespace-pre-wrap text-slate-200">{runOperation.result.stdout}</pre>}
              {runOperation.result.stderr && <pre className="mt-1 whitespace-pre-wrap text-red-300">{runOperation.result.stderr}</pre>}
            </div>
          )}
        </div>
      )}

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
