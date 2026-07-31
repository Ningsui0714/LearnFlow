/**
 * Timeline controls: the "step-ability" that makes algorithm animations
 * comprehensible (VisuAlgo / Python Tutor pattern).
 */
interface Props {
  total: number
  current: number
  playing: boolean
  onStep: (i: number) => void
  onPlay: () => void
  note?: string
}

export default function TimelineControls({ total, current, playing, onStep, onPlay, note }: Props) {
  if (total <= 1) return null
  return (
    <div className="flex items-center gap-2 mt-2 flex-wrap">
      <div className="flex items-center gap-1">
        <button onClick={() => onStep(0)} title="回到开头"
          className="w-6 h-6 rounded bg-gray-100 text-gray-600 text-[10px] hover:bg-gray-200">⏮</button>
        <button onClick={() => onStep(Math.max(0, current - 1))} disabled={current === 0}
          className="w-6 h-6 rounded bg-gray-100 text-gray-600 text-[10px] hover:bg-gray-200 disabled:opacity-40">◀</button>
        <button onClick={onPlay}
          className="w-8 h-6 rounded bg-indigo-600 text-white text-[10px] hover:bg-indigo-700">
          {playing ? '⏸' : '▶'}
        </button>
        <button onClick={() => onStep(Math.min(total - 1, current + 1))} disabled={current >= total - 1}
          className="w-6 h-6 rounded bg-gray-100 text-gray-600 text-[10px] hover:bg-gray-200 disabled:opacity-40">▶</button>
        <button onClick={() => onStep(total - 1)} title="到结尾"
          className="w-6 h-6 rounded bg-gray-100 text-gray-600 text-[10px] hover:bg-gray-200">⏭</button>
      </div>
      {/* progress bar */}
      <div className="flex-1 h-1.5 bg-gray-100 rounded-full overflow-hidden min-w-[80px]">
        <div className="h-full bg-indigo-400 transition-all"
             style={{ width: `${((current + 1) / total) * 100}%` }} />
      </div>
      <span className="text-[10px] text-gray-400">{current + 1}/{total}</span>
      {note && <span className="text-[10px] text-gray-500">{note}</span>}
    </div>
  )
}
