import { useState, useEffect, useRef } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import SplitPane from "../components/layout/SplitPane"
import Editor from '@monaco-editor/react'
import {
  listExercises, getExercise, runCode, reviewCode, submitExercise, getExerciseTask, lectureTaskEventsUrl,
} from '../services/api'
import ConceptQuestions from '../components/exercise/ConceptQuestions'

interface CodeMsg {
  role: 'user' | 'assistant'
  content: string
}

export default function ExercisePage() {
  const { projectId, checkpointId } = useParams()
  const navigate = useNavigate()
  const pid = Number(projectId)
  const cid = Number(checkpointId)

  const [exercises, setExercises] = useState<any[]>([])
  const [activeEx, setActiveEx] = useState<any>(null)
  const [code, setCode] = useState('')
  const [stdout, setStdout] = useState('')
  const [stderr, setStderr] = useState('')
  const [running, setRunning] = useState(false)
  const [loading, setLoading] = useState(true)

  // Code workspace
  const [wsMessages, setWsMessages] = useState<CodeMsg[]>([])
  const [wsInput, setWsInput] = useState('')
  const [wsLoading, setWsLoading] = useState(false)
  const [selectedCode, setSelectedCode] = useState('')
  const [showDesc, setShowDesc] = useState(true)
  const [tab, setTab] = useState<'concepts' | 'code'>('code')
  const [submitResult, setSubmitResult] = useState<any>(null)
  const [submitting, setSubmitting] = useState(false)
  const [genTaskId, setGenTaskId] = useState<number | null>(null)
  const [genProgress, setGenProgress] = useState('')
  // IDE extras
  const editorRef = useRef<any>(null)
  const vimDisposeRef = useRef<any>(null)
  const [vimEnabled, setVimEnabled] = useState(false)
  const [darkTheme, setDarkTheme] = useState(true)
  const [fontSize, setFontSize] = useState(13)
  const [vimLoading, setVimLoading] = useState(false)
  const wsEndRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    loadExercises()
  }, [cid])

  useEffect(() => {
    wsEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [wsMessages])

  const loadExercises = async () => {
    setLoading(true)
    try {
      const data = await listExercises(cid)
      setExercises(data)
      if (data.length > 0) {
        selectExercise(data[0])
      }
    } catch { /* no exercises yet */ }
    setLoading(false)
  }

  const selectExercise = (ex: any) => {
    setActiveEx(ex)
    setCode(ex.starter_code || '')
    setStdout('')
    setStderr('')
    setWsMessages([])
    setSelectedCode('')
  }

  const handleGenerateEx = async () => {
    setLoading(true)
    try {
      const { default: api } = await import('../services/api')
      const res = await api.post(`/checkpoints/${cid}/exercises/generate`)
      setGenTaskId(res.data.task_id)
      setGenProgress('排队中...')
      // subscribe SSE
      const es = new EventSource(lectureTaskEventsUrl(res.data.task_id))
      es.onmessage = (ev) => {
        try {
          const snap = JSON.parse(ev.data)
          if (snap.progress?.message) setGenProgress(snap.progress.message)
          if (snap.status === 'completed') {
            setGenProgress('✅ 完成')
            es.close()
            loadExercises()
          } else if (snap.status === 'failed') {
            setGenProgress('❌ ' + (snap.error?.guidance || snap.error?.message || '失败'))
            es.close()
          }
        } catch {}
      }
    } catch (e: any) {
      alert('生成失败: ' + (e?.response?.data?.detail || e.message))
    }
    setLoading(false)
  }

  const handleSubmit = async () => {
    if (!activeEx || !code.trim()) return
    setSubmitting(true)
    setSubmitResult(null)
    try {
      const result = await submitExercise(activeEx.id, code)
      setSubmitResult(result)
    } catch (e: any) {
      setSubmitResult({ error: e?.response?.data?.detail || e.message })
    }
    setSubmitting(false)
  }

  const handleRun = async () => {
    setRunning(true)
    setStdout('')
    setStderr('')
    try {
      const result = await runCode(code, activeEx?.id)
      setStdout(result.stdout || '')
      setStderr(result.stderr || '')
    } catch (e: any) {
      setStderr(String(e?.response?.data?.detail || e.message))
    }
    setRunning(false)
  }

  const handleReview = async () => {
    if (!activeEx) return
    setWsLoading(true)
    const msg: CodeMsg = { role: 'user', content: '请审阅这段代码' }
    setWsMessages(prev => [...prev, msg])
    try {
      const result = await reviewCode(activeEx.id, code, selectedCode)
      setWsMessages(prev => [...prev, { role: 'assistant', content: result.answer }])
    } catch (e: any) {
      setWsMessages(prev => [...prev, { role: 'assistant', content: '❌ ' + (e?.response?.data?.detail || '请求失败') }])
    }
    setWsLoading(false)
  }

  const handleAskInWorkspace = async () => {
    if (!wsInput.trim() || wsLoading) return
    const text = wsInput.trim()
    setWsInput('')
    const msg: CodeMsg = { role: 'user', content: text }
    setWsMessages(prev => [...prev, msg])
    setWsLoading(true)

    try {
      const { askCodeQuestion } = await import('../services/api')
      const result = await askCodeQuestion({
        code,
        selection: selectedCode,
        question: text,
        context: activeEx?.title || '',
      })
      setWsMessages(prev => [...prev, { role: 'assistant', content: result.answer }])
    } catch (e: any) {
      setWsMessages(prev => [...prev, { role: 'assistant', content: '❌ ' + (e?.response?.data?.detail || '请求失败') }])
    }
    setWsLoading(false)
  }

  // Monaco Editor mount & selection handler + IDE extras
  const handleEditorMount = (editor: any) => {
    editorRef.current = editor
    editor.onDidChangeCursorSelection(() => {
      const selection = editor.getModel()?.getValueInRange(editor.getSelection())
      if (selection) {
        setSelectedCode(selection)
      }
    })
  }

  const editorAction = (cmd: string) => {
    editorRef.current?.trigger('ide-toolbar', cmd, null)
  }

  const toggleVim = async () => {
    if (!editorRef.current) return
    if (vimDisposeRef.current) {
      vimDisposeRef.current.dispose()
      vimDisposeRef.current = null
      setVimEnabled(false)
      return
    }
    setVimLoading(true)
    try {
      const { initVimMode } = await import('monaco-vim')
      vimDisposeRef.current = initVimMode(editorRef.current, document.getElementById('vim-status'))
      setVimEnabled(true)
    } catch (e: any) {
      alert('Vim 模式加载失败: ' + e.message)
    }
    setVimLoading(false)
  }

  const changeFontSize = (delta: number) => {
    const next = Math.min(24, Math.max(10, fontSize + delta))
    setFontSize(next)
    editorRef.current?.updateOptions({ fontSize: next })
  }

  if (loading) return <div className="p-8 text-gray-400">加载中...</div>

  return (
    <div className="h-full flex flex-col overflow-hidden">
      {/* Header */}
      <div className="bg-white border-b border-gray-200 px-6 py-3 shrink-0 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <button onClick={() => navigate(`/projects/${pid}/checkpoints/${cid}`)}
            className="text-sm text-gray-400 hover:text-gray-600">
            ← 返回讲义
          </button>
          <span className="text-gray-300">|</span>
          <h1 className="text-lg font-semibold text-gray-900">练习</h1>
          {/* Tabs */}
          <div className="flex bg-gray-100 rounded-lg p-0.5 ml-2">
            <button
              onClick={() => setTab('concepts')}
              className={`px-3 py-1 rounded-md text-xs transition-colors ${
                tab === 'concepts' ? 'bg-white shadow text-primary-700 font-medium' : 'text-gray-500'
              }`}
            >
              🧠 概念题
            </button>
            <button
              onClick={() => setTab('code')}
              className={`px-3 py-1 rounded-md text-xs transition-colors ${
                tab === 'code' ? 'bg-white shadow text-primary-700 font-medium' : 'text-gray-500'
              }`}
            >
              💻 代码题
            </button>
          </div>
        </div>
        {tab === 'code' && exercises.length === 0 && !genTaskId && (
          <button onClick={handleGenerateEx}
            className="bg-primary-600 text-white px-3 py-1 rounded text-sm ml-auto
                       hover:bg-primary-700 transition-colors">
            🤖 生成习题
          </button>
        )}
        {tab === 'code' && genTaskId && (
          <span className="text-xs text-primary-600 flex items-center gap-2 ml-auto">
            <span className="w-2 h-2 rounded-full bg-primary-400 animate-pulse" />
            {genProgress || '生成中...'}
          </span>
        )}
      </div>

      {/* Main area */}
      {tab === 'concepts' ? (
        <ConceptQuestions checkpointId={cid} />
      ) : (
      <div className="flex-1 flex overflow-hidden">
        <SplitPane
          direction="vertical"
          initialRatio={0.7}
          minLeft={200}
          minRight={120}
          left={
            <div className="h-full flex overflow-hidden">
              {/* Left: exercise list */}
              <div className="w-56 border-r border-gray-200 bg-white overflow-y-auto shrink-0 p-3">
                <h2 className="text-xs font-semibold text-gray-500 uppercase mb-2">题目列表</h2>
                {exercises.length === 0 && (
                  <p className="text-xs text-gray-400">此关卡暂无练习题</p>
                )}
                {exercises.map((ex, i) => (
                  <button
                    key={ex.id}
                    onClick={() => selectExercise(ex)}
                    className={`w-full text-left text-xs p-2 rounded-lg mb-1 transition-colors ${
                      activeEx?.id === ex.id
                        ? 'bg-primary-100 text-primary-700'
                        : 'hover:bg-gray-100 text-gray-700'
                    }`}
                  >
                    <span className="font-medium">{i + 1}. {ex.title}</span>
                  </button>
                ))}
              </div>

              {/* Center: Editor + Output (horizontal split) */}
              <div className="flex-1 flex flex-col overflow-hidden">
                {!activeEx ? (
                  <div className="flex-1 flex items-center justify-center text-gray-400 text-sm">
                    暂无练习题
                  </div>
                ) : (
                  <>
                    {/* Description — collapsible */}
                    <div className="bg-gray-50 border-b border-gray-200 shrink-0">
                      <button
                        onClick={() => setShowDesc(!showDesc)}
                        className="w-full flex items-center justify-between px-4 py-2 text-xs hover:bg-gray-100 transition-colors"
                      >
                        <span className="font-semibold text-gray-700">{activeEx.title}</span>
                        <span className="text-gray-400">{showDesc ? '▲ 收起' : '▼ 展开描述'}</span>
                      </button>
                      {showDesc && (
                        <div className="px-4 pb-2 max-h-32 overflow-y-auto text-xs space-y-1">
                          <p className="text-gray-600 whitespace-pre-wrap">{activeEx.description}</p>
                          {activeEx.hints?.length > 0 && (
                            <div className="text-yellow-700 bg-yellow-50 rounded px-2 py-1">
                              💡 {activeEx.hints.join(' | ')}
                            </div>
                          )}
                        </div>
                      )}
                    </div>

                    {/* Editor + Output (resizable) */}
                    <div className="flex-1 flex overflow-hidden">
                      <SplitPane
                        direction="horizontal"
                        initialRatio={0.65}
                        minLeft={200}
                        minRight={180}
                        left={
                          <div className="h-full flex flex-col">
                            <div className="flex-1">
                              <Editor
                                height="100%"
                                defaultLanguage="python"
                                theme={darkTheme ? 'vs-dark' : 'light'}
                                value={code}
                                onChange={val => setCode(val || '')}
                                onMount={handleEditorMount}
                                options={{
                                  minimap: { enabled: false },
                                  fontSize,
                                  lineNumbers: 'on',
                                  scrollBeyondLastLine: false,
                                  renderWhitespace: 'none',
                                }}
                              />
                            </div>
                            {/* IDE toolbar: undo/redo/vim/theme/font */}
                            <div className="border-t border-gray-200 px-3 py-1 flex items-center gap-1 bg-gray-50 shrink-0">
                              <button onClick={() => editorAction('undo')} title="撤销 (Ctrl+Z)"
                                className="text-[11px] bg-white border border-gray-200 text-gray-600 px-2 py-0.5 rounded hover:bg-gray-100">↩️ 撤销</button>
                              <button onClick={() => editorAction('redo')} title="重做 (Ctrl+Shift+Z)"
                                className="text-[11px] bg-white border border-gray-200 text-gray-600 px-2 py-0.5 rounded hover:bg-gray-100">↪️ 重做</button>
                              <span className="w-px h-4 bg-gray-200 mx-1" />
                              <button onClick={toggleVim} disabled={vimLoading}
                                className={`text-[11px] px-2 py-0.5 rounded transition-colors ${
                                  vimEnabled
                                    ? 'bg-violet-600 text-white'
                                    : 'bg-white border border-gray-200 text-gray-600 hover:bg-gray-100'
                                } disabled:opacity-50`}
                                title="Vim 键位模式 (Esc 切回 NORMAL)">
                                {vimLoading ? '加载中...' : (vimEnabled ? 'Vim: ON' : 'Vim: OFF')}
                              </button>
                              <span className="w-px h-4 bg-gray-200 mx-1" />
                              <button onClick={() => setDarkTheme(!darkTheme)} title="切换主题"
                                className="text-[11px] bg-white border border-gray-200 text-gray-600 px-2 py-0.5 rounded hover:bg-gray-100">
                                {darkTheme ? '☀️' : '🌙'}
                              </button>
                              <button onClick={() => changeFontSize(-1)} title="缩小字号"
                                className="text-[11px] bg-white border border-gray-200 text-gray-600 px-1.5 py-0.5 rounded hover:bg-gray-100">A-</button>
                              <span className="text-[10px] text-gray-400 w-7 text-center">{fontSize}</span>
                              <button onClick={() => changeFontSize(1)} title="放大字号"
                                className="text-[11px] bg-white border border-gray-200 text-gray-600 px-1.5 py-0.5 rounded hover:bg-gray-100">A+</button>
                            </div>
                            {/* Vim status bar */}
                            {vimEnabled && (
                              <div id="vim-status"
                                   className="border-t border-violet-200 bg-violet-50 text-violet-700 text-[10px] font-mono px-3 py-0.5 shrink-0">
                                -- NORMAL --
                              </div>
                            )}
                            <div className="border-t border-gray-200 px-3 py-1.5 flex gap-2 bg-white shrink-0">
                              <button onClick={handleRun} disabled={running}
                                className="bg-green-600 text-white px-3 py-1 rounded text-xs hover:bg-green-700 disabled:bg-gray-300">
                                {running ? '运行中...' : '▶ 运行'}
                              </button>
                              <button onClick={handleSubmit} disabled={submitting || !code.trim()}
                                className="bg-gray-900 text-white px-3 py-1 rounded text-xs hover:bg-gray-700 disabled:bg-gray-300">
                                {submitting ? '判题中...' : '📋 提交判题'}
                              </button>
                              <button onClick={handleReview} disabled={wsLoading}
                                className="bg-primary-600 text-white px-3 py-1 rounded text-xs hover:bg-primary-700 disabled:bg-gray-300">
                                ✔ 审阅
                              </button>
                              {selectedCode && (
                                <span className="text-[10px] text-gray-400 self-center">
                                  已选中 {selectedCode.length} 字符
                                </span>
                              )}
                            </div>
                          </div>
                        }
                        right={
                          <div className="h-full bg-gray-900 text-gray-100 text-xs font-mono p-3 overflow-y-auto">
                            <div className="text-gray-500 text-[10px] uppercase mb-2">输出面板</div>
                            {submitResult && (
                              <div className={`mb-3 rounded p-2 ${submitResult.error ? 'bg-red-900/40 text-red-300' : 'bg-gray-800'}`}>
                                {submitResult.error ? (
                                  <p>❌ {submitResult.error}</p>
                                ) : (
                                  <>
                                    <p className={`font-bold mb-1 ${submitResult.passed === submitResult.total ? 'text-green-400' : 'text-amber-400'}`}>
                                      {submitResult.passed === submitResult.total
                                        ? `✅ 全部通过 (${submitResult.passed}/${submitResult.total})`
                                        : `❌ ${submitResult.passed}/${submitResult.total} 通过`}
                                    </p>
                                    {submitResult.results?.map((r: any, i: number) => (
                                      <div key={i} className={`mt-1 ${r.passed ? 'text-green-400' : 'text-red-400'}`}>
                                        {r.passed ? '✓' : '✗'} 用例 {i + 1}
                                        {!r.passed && (
                                          <span className="text-gray-400">
                                            {' '}期望 {r.expected} → 实际 {r.actual}
                                            {r.stderr ? `（${r.stderr.slice(0, 60)}）` : ''}
                                          </span>
                                        )}
                                      </div>
                                    ))}
                                  </>
                                )}
                              </div>
                            )}
                            {stdout && <pre className="whitespace-pre-wrap">{stdout}</pre>}
                            {stderr && <pre className="whitespace-pre-wrap text-red-400">{stderr}</pre>}
                            {!stdout && !stderr && !submitResult && (
                              <div className="text-gray-600">点击「▶ 运行」执行代码，或「📋 提交判题」跑测试用例</div>
                            )}
                          </div>
                        }
                      />
                    </div>
                  </>
                )}
              </div>
            </div>
          }
          right={
            <div className="h-full flex flex-col bg-white">
              <div className="flex items-center justify-between px-4 py-1.5 border-b border-gray-100 shrink-0">
                <div className="flex items-center gap-2 text-xs">
                  <span className="w-2 h-2 rounded-full bg-primary-400" />
                  <span className="font-medium text-gray-700">代码工作区</span>
                  {selectedCode && (
                    <span className="text-gray-400 truncate max-w-[200px]">
                      「{selectedCode.slice(0, 40)}...」
                    </span>
                  )}
                </div>
              </div>
              <div className="flex-1 overflow-y-auto px-4 py-1.5 space-y-1.5 text-xs">
                {wsMessages.length === 0 && (
                  <div className="text-gray-400 text-center py-4">
                    选中代码后提问，或点击「审阅」获取反馈
                  </div>
                )}
                {wsMessages.map((m, i) => (
                  <div key={i} className={`flex ${m.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                    <div className={`max-w-[85%] rounded-lg px-2.5 py-1.5 whitespace-pre-wrap ${
                      m.role === 'user' ? 'bg-primary-600 text-white' : 'bg-gray-100 text-gray-800'
                    }`}>
                      {m.content}
                    </div>
                  </div>
                ))}
                {wsLoading && <div className="text-gray-400 animate-pulse">思考中...</div>}
                <div ref={wsEndRef} />
              </div>
              <div className="border-t border-gray-100 px-4 py-1.5 shrink-0 flex gap-2">
                <input type="text" value={wsInput}
                  onChange={e => setWsInput(e.target.value)}
                  onKeyDown={e => e.key === 'Enter' && !e.shiftKey && handleAskInWorkspace()}
                  placeholder="输入问题... (Enter 发送)"
                  className="flex-1 border border-gray-300 rounded px-2 py-1 text-xs focus:outline-none focus:ring-2 focus:ring-primary-400"
                />
                <button onClick={handleAskInWorkspace} disabled={wsLoading || !wsInput.trim()}
                  className="bg-primary-600 text-white px-2.5 py-1 rounded text-xs hover:bg-primary-700 disabled:bg-gray-300">
                  发送
                </button>
              </div>
            </div>
          }
        />
      </div>
      )}
    </div>
  )
}
