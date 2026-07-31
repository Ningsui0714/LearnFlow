/**
 * ArrayPointer: array cells + named pointers + highlight + step timeline.
 * The workhorse for sorting/search/pointer-movement lessons.
 *
 * DSL:
 * {
 *   "type": "array-pointer",
 *   "data": { "array": [5,3,8,1], "pointers": ["i","j","k"] },
 *   "steps": [
 *     { "pointers": {"i":0}, "highlight": [0,1], "action": "compare", "note": "比较" },
 *     { "pointers": {"i":1,"j":2}, "swap": [1,2], "note": "交换" }
 *   ]
 * }
 */
import { useState, useEffect, useRef } from 'react'
import TimelineControls from './TimelineControls'

export default function ArrayPointer({ config }: { config: any }) {
  const data = config.data || {}
  const array: any[] = data.array || []
  const pointerNames: string[] = data.pointers || ['i']
  const steps: any[] = config.steps || []
  const hasSteps = steps.length > 0

  const [step, setStep] = useState(0)
  const [playing, setPlaying] = useState(false)
  const timerRef = useRef<any>(null)

  useEffect(() => {
    if (playing) {
      timerRef.current = setInterval(() => {
        setStep(s => {
          if (s >= steps.length - 1) { setPlaying(false); return s }
          return s + 1
        })
      }, 1200)
    }
    return () => clearInterval(timerRef.current)
  }, [playing, steps.length])

  const current: any = hasSteps ? (steps[step] || {}) : {}
  const pointers: Record<string, number> = hasSteps ? (current.pointers || {}) : {}
  const highlight: number[] = hasSteps ? (current.highlight || []) : []
  const swap: number[] | null = current.swap || null
  const note = hasSteps ? current.note : ''

  // base pointer positions (for no-step mode)
  if (!hasSteps) {
    pointerNames.forEach((p, i) => { pointers[p] = Math.min(i, array.length - 1) })
  }

  const cellColor = (i: number) => {
    if (swap?.includes(i)) return 'bg-amber-200 border-amber-400'
    if (highlight.includes(i)) return 'bg-indigo-100 border-indigo-400'
    return 'bg-white border-gray-300'
  }

  return (
    <div>
      <div className="flex items-end gap-1 overflow-x-auto py-1">
        {array.map((v, i) => (
          <div key={i} className="flex flex-col items-center shrink-0">
            {/* pointers above */}
            {pointerNames.map(p => (
              <div key={p} className="h-5 text-[10px] font-mono text-indigo-600 leading-5">
                {pointers[p] === i ? p : ''}
              </div>
            ))}
            <div className={`w-10 h-10 rounded flex items-center justify-center text-sm font-mono border-2 transition-colors ${cellColor(i)}`}>
              {v}
            </div>
            <div className="text-[9px] text-gray-400 font-mono mt-0.5">{i}</div>
          </div>
        ))}
      </div>
      <TimelineControls
        total={hasSteps ? steps.length : 1}
        current={step}
        playing={playing}
        onStep={i => { setStep(i); setPlaying(false) }}
        onPlay={() => { if (step >= steps.length - 1) setStep(0); setPlaying(!playing) }}
        note={note}
      />
    </div>
  )
}
