/**
 * VizRenderer: renders ```viz JSON blocks embedded in lecture markdown.
 *
 * v2: universal object language (VizLab engine) — 可视化 = 对象场景 + 状态序列 + 交互.
 * Legacy DSL v1 (4 dedicated components) is normalized automatically.
 */
import { useState, useMemo } from 'react'
import SceneEngine from './engine/SceneEngine'
import { normalize } from './engine/normalize'
import { validate } from './engine/validate'

export default function VizRenderer({ code }: { code: string }) {
  const [stateIndex, setStateIndex] = useState(0)
  const [playing, setPlaying] = useState(false)
  const [speed, setSpeed] = useState(1)
  const [params, setParams] = useState<Record<string, number>>({})

  let doc: any = null
  let err = ''
  try {
    doc = normalize(JSON.parse(code))
    const issues = validate(doc)
    if (issues.some(i => i.level === 'error')) {
      err = issues.filter(i => i.level === 'error').map(i => i.msg).join('；')
    }
    // init params (keep existing values)
    setParams(prev => {
      const next = { ...prev }
      for (const p of doc.interact || []) if (next[p.param] === undefined) next[p.param] = p.default
      return next
    })
  } catch (e: any) {
    err = e.message
  }

  const total = doc?.states?.length || 0

  const play = () => {
    if (stateIndex >= total - 1) setStateIndex(0)
    setPlaying(p => !p)
  }

  return (
    <div className="my-4 rounded-lg border border-gray-200 bg-white p-3">
      {doc?.title && <p className="text-xs font-semibold text-gray-500 mb-2">{doc.title}</p>}
      {err ? (
        <div className="rounded border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-700">
          ⚠️ {err}
          <pre className="mt-1 text-[10px] whitespace-pre-wrap text-amber-600">{code.slice(0, 300)}</pre>
        </div>
      ) : (
        <>
          <SceneEngine doc={doc} params={params} stateIndex={stateIndex} speed={speed} />
          {total > 0 && (
            <div className="mt-2 flex items-center gap-1.5 flex-wrap">
              <span className="text-[10px] text-gray-400">速度</span>
              <input type="range" min={0.25} max={3} step={0.25} value={speed}
                     onChange={e => setSpeed(Number(e.target.value))}
                     className="w-16 accent-indigo-600" />
              <button onClick={() => setStateIndex(0)} className="w-6 h-6 rounded bg-gray-100 text-gray-500 text-[10px] hover:bg-gray-200">⏮</button>
              <button onClick={() => setStateIndex(Math.max(0, stateIndex - 1))}
                      disabled={stateIndex === 0}
                      className="w-6 h-6 rounded bg-gray-100 text-gray-500 text-[10px] hover:bg-gray-200 disabled:opacity-40">◀</button>
              <button onClick={play} className="w-7 h-6 rounded bg-indigo-600 text-white text-[10px] hover:bg-indigo-700">
                {playing ? '⏸' : '▶'}
              </button>
              <button onClick={() => { setStateIndex(Math.min(total - 1, stateIndex + 1)); setPlaying(false) }}
                      disabled={stateIndex >= total - 1}
                      className="w-6 h-6 rounded bg-gray-100 text-gray-500 text-[10px] hover:bg-gray-200 disabled:opacity-40">▶</button>
              <span className="text-[10px] text-gray-400 ml-1">{stateIndex + 1}/{total}</span>
              {(doc.states || [])[stateIndex]?.note && (
                <span className="text-[11px] text-indigo-600 bg-indigo-50 rounded px-1.5 py-0.5">
                  💡 {(doc.states || [])[stateIndex].note}
                </span>
              )}
            </div>
          )}
          {(doc.interact || []).length > 0 && (
            <div className="mt-2 border-t border-gray-100 pt-2">
              {doc.interact.map((it: any) => (
                <label key={it.param} className="flex items-center gap-2 text-[11px] text-gray-600 mb-1">
                  <span className="w-14 font-mono">{it.param}</span>
                  <input type="range" min={it.min} max={it.max} step={it.step || 0.01}
                         value={params[it.param] ?? it.default}
                         onChange={e => setParams(p => ({ ...p, [it.param]: Number(e.target.value) }))}
                         className="flex-1 accent-indigo-600" />
                  <span className="w-9 text-right font-mono">{(params[it.param] ?? it.default).toFixed(2)}</span>
                </label>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  )
}
