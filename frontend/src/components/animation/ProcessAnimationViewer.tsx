import { useEffect, useRef, useState } from 'react'
import type { ProcessAnimation, AnimationStep } from '../../services/api'

/** 与 process-animator skill 的 interactive-template 同构的 React 版渲染器 */

const DELAY = 1600
const BAR_COLORS = {
  bar: '#94a3b8', highlight: '#fbbf24', pivot: '#f97316', sorted: '#22c55e', done: '#15803d',
}
const DEFAULT_LEGEND: [string, string][] = [
  ['#fbbf24', 'highlight：当前操作'],
  ['#f97316', 'pivot：基准'],
  ['#22c55e', 'sorted：已就位'],
  ['#94a3b8', '普通元素'],
]

// ── SVG 白名单消毒（与后端 animation_agent.sanitize_svg 同策略，双保险） ──
const SVG_TAGS = new Set(['svg', 'g', 'circle', 'rect', 'line', 'path', 'text', 'polygon', 'polyline', 'marker', 'defs', 'title', 'tspan', 'ellipse'])
const SVG_ATTRS = new Set(['fill', 'stroke', 'stroke-width', 'stroke-dasharray', 'opacity', 'transform', 'x', 'y', 'x1', 'y1', 'x2', 'y2', 'cx', 'cy', 'r', 'rx', 'ry', 'width', 'height', 'viewBox', 'd', 'font-size', 'font-weight', 'text-anchor', 'font-family', 'preserveAspectRatio', 'marker-end', 'style'])

function sanitizeSvg(raw: string): string {
  let svg = raw.slice(0, 65536)
    .replace(/<script[\s\S]*?<\/script>/gi, '')
    .replace(/\son\w+\s*=\s*("[^"]*"|'[^']*')/gi, '')
    .replace(/javascript:/gi, '')
  svg = svg.replace(/<(\w+)([^>]*)>/g, (_m, tag: string, attrs: string) => {
    if (!SVG_TAGS.has(tag.toLowerCase())) return ''
    const kept: string[] = []
    for (const mm of attrs.matchAll(/([\w-]+)\s*=\s*("[^"]*"|'[^']*')/g)) {
      if (SVG_ATTRS.has(mm[1].toLowerCase())) kept.push(`${mm[1]}=${mm[2]}`)
    }
    return `<${tag}${kept.length ? ' ' + kept.join(' ') : ''}>`
  })
  svg = svg.replace(/<\/(\w+)>/g, (_m, tag: string) => (SVG_TAGS.has(tag.toLowerCase()) ? `</${tag}>` : ''))
  return svg
}

function renderBars(bars: any): string {
  const vals: number[] = bars.values || []
  if (!vals.length) return ''
  const n = vals.length
  const max = Math.max(...vals, 1)
  const W = 700, H = 260, pad = 4
  const gap = Math.min(10, (W - pad * 2) / n / 4)
  const bw = (W - pad * 2) / n - gap
  const mark = (key: string) => new Set<number>((bars[key] || []).map((i: number) => i))
  const highlight = mark('highlight'), pivot = mark('pivot'), sorted = mark('sorted'), done = mark('done')
  let svg = `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="xMidYMid meet" style="width:100%;height:auto;max-height:240px">`
  vals.forEach((v, i) => {
    const h = (v / max) * (H - 40)
    const x = pad + i * (bw + gap), y = H - 20 - h
    let fill = BAR_COLORS.bar
    if (done.has(i)) fill = BAR_COLORS.done
    else if (sorted.has(i)) fill = BAR_COLORS.sorted
    else if (pivot.has(i)) fill = BAR_COLORS.pivot
    else if (highlight.has(i)) fill = BAR_COLORS.highlight
    svg += `<rect x="${x.toFixed(1)}" y="${y.toFixed(1)}" width="${bw.toFixed(1)}" height="${h.toFixed(1)}" rx="3" fill="${fill}"><title>索引 ${i} = ${v}</title></rect>`
  })
  return svg + '</svg>'
}

interface Props {
  animation: ProcessAnimation
  className?: string
}

export default function ProcessAnimationViewer({ animation, className }: Props) {
  const steps: AnimationStep[] = animation?.steps || []
  const [idx, setIdx] = useState(0)
  const [playing, setPlaying] = useState(false)
  const containerRef = useRef<HTMLDivElement>(null)

  const hasBars = steps.some(s => s.bars)
  const legend = animation?.legend?.length ? animation.legend : hasBars ? DEFAULT_LEGEND : []

  useEffect(() => {
    if (!playing) return
    const t = setInterval(() => setIdx(i => i + 1), DELAY)
    return () => clearInterval(t)
  }, [playing])

  useEffect(() => {
    if (playing && idx >= steps.length - 1) setPlaying(false)
  }, [idx, playing, steps.length])

  useEffect(() => { setIdx(0); setPlaying(false) }, [animation?.id])

  const step = steps[Math.min(idx, Math.max(steps.length - 1, 0))]
  const go = (i: number) => {
    setPlaying(false)
    setIdx(Math.max(0, Math.min(steps.length - 1, i)))
  }
  const toggle = () => {
    if (steps.length < 2) return
    if (playing) { setPlaying(false); return }
    if (idx >= steps.length - 1) setIdx(0)
    setPlaying(true)
  }

  if (!steps.length) return null

  // 静态图模式：只有一张 SVG，无控制条/图例/步骤文案
  if (animation?.kind === 'static') {
    const svg = steps[0]?.svg ? sanitizeSvg(steps[0].svg) : ''
    return (
      <figure className={`my-4 rounded-xl border border-gray-200 bg-white overflow-hidden ${className || ''}`}>
        {animation.title && (
          <figcaption className="px-4 pt-3 text-sm font-bold text-gray-900">{animation.title}</figcaption>
        )}
        <div className="px-4 py-4" dangerouslySetInnerHTML={{ __html: svg }} />
      </figure>
    )
  }

  const showBars = !!step?.bars
  const showSvg = !!step?.svg
  const svgSafe = step?.svg ? sanitizeSvg(step.svg) : ''

  return (
    <div
      ref={containerRef}
      tabIndex={0}
      onKeyDown={e => {
        if (e.key === 'ArrowRight') go(idx + 1)
        else if (e.key === 'ArrowLeft') go(idx - 1)
        else if (e.key === ' ') { e.preventDefault(); toggle() }
      }}
      className={`my-4 rounded-xl border border-gray-200 bg-white overflow-hidden focus:outline-none focus:ring-2 focus:ring-primary-200 ${className || ''}`}
    >
      <div className="px-4 pt-3">
        {animation?.title && <div className="text-sm font-bold text-gray-900">{animation.title}</div>}
        {animation?.subtitle && <div className="text-xs text-gray-500 mt-0.5">{animation.subtitle}</div>}
      </div>

      <div className="min-h-[260px] flex items-center justify-center px-4 py-4">
        {showBars && <div dangerouslySetInnerHTML={{ __html: renderBars(step.bars) }} />}
        {showSvg && <div dangerouslySetInnerHTML={{ __html: svgSafe }} />}
        {!showBars && !showSvg && (
          <div className="text-base text-gray-400 text-center max-w-md leading-relaxed">{step?.text}</div>
        )}
      </div>

      {legend.length > 0 && (
        <div className="flex flex-wrap gap-x-4 gap-y-1 px-4 pb-2 text-xs text-gray-500">
          {legend.map(([c, label], i) => (
            <span key={i} className="inline-flex items-center gap-1">
              <i className="inline-block w-3 h-3 rounded-sm" style={{ background: c }} />
              {label}
            </span>
          ))}
        </div>
      )}

      <div className="border-t border-gray-100 px-4 py-3">
        <div className="text-sm font-semibold text-gray-900">{step?.title}</div>
        <p className="text-sm text-gray-600 leading-relaxed mt-1 whitespace-pre-line">{step?.text}</p>
      </div>

      <div className="flex items-center gap-2 border-t border-gray-100 bg-gray-50 px-4 py-2.5">
        <button
          onClick={() => go(idx - 1)}
          disabled={idx === 0}
          className="px-2.5 py-1 rounded-md border border-gray-200 bg-white text-xs text-gray-700 hover:border-primary-400 disabled:opacity-40 disabled:cursor-not-allowed"
        >
          ← 上一步
        </button>
        <button
          onClick={toggle}
          disabled={steps.length < 2}
          className="px-2.5 py-1 rounded-md bg-primary-600 text-white text-xs hover:bg-primary-700 disabled:opacity-40"
        >
          {playing ? '⏸ 暂停' : '▶ 播放'}
        </button>
        <button
          onClick={() => go(idx + 1)}
          disabled={idx >= steps.length - 1}
          className="px-2.5 py-1 rounded-md border border-gray-200 bg-white text-xs text-gray-700 hover:border-primary-400 disabled:opacity-40 disabled:cursor-not-allowed"
        >
          下一步 →
        </button>
        <input
          type="range"
          min={0}
          max={Math.max(steps.length - 1, 0)}
          value={idx}
          onChange={e => go(Number(e.target.value))}
          className="flex-1 accent-primary-600"
        />
        <span className="text-xs text-gray-500 tabular-nums min-w-[52px] text-center">
          {idx + 1} / {steps.length}
        </span>
      </div>
    </div>
  )
}
