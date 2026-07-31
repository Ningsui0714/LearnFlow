/**
 * SceneEngine v2 — object language renderer.
 * WP1: group/tree/graph/arrow/bar/stack + graph layouters (ring/tree/layered)
 * WP2: keyed value elements + CSS transform transitions → slide-swap,
 *      speed control, reverse-friendly stepping
 * WP3: click events (toggle highlight / set) + pointer click-to-move
 *      + point drag on curves
 */
import { useMemo, useState, useCallback } from 'react'
import type { VizDoc, ObjSpec, State } from './types'
import { safeExpr } from './safeExpr'

export const CANVAS_W = 720
export const CANVAS_H = 420

export interface LayoutRect { x: number; y: number; w: number; h: number }

const PRIMARY_TYPES = new Set(['array', 'stack', 'bar', 'grid', 'curve', 'group'])

/** bands: primary objects + one graph band (if node/edge present) */
export function computeRegions(objects: ObjSpec[]): { region: Map<string, LayoutRect>; graphRegion: LayoutRect | null } {
  const region = new Map<string, LayoutRect>()
  const primaries = objects.filter(o => PRIMARY_TYPES.has(o.type))
  const hasGraph = objects.some(o => o.type === 'node' || o.type === 'edge')
  const n = Math.max(1, primaries.length + (hasGraph ? 1 : 0))
  const w = CANVAS_W / n
  primaries.forEach((o, i) => {
    region.set(o.id, { x: i * w + 8, y: 34, w: w - 16, h: CANVAS_H - 48 })
  })
  let graphRegion: LayoutRect | null = null
  if (hasGraph) {
    const i = primaries.length
    graphRegion = { x: i * w + 8, y: 34, w: w - 16, h: CANVAS_H - 48 }
    // group children that are primaries: nested bands handled by group render
  }
  return { region, graphRegion }
}

/** graph layout: ring | tree | layered */
export function computeGraphLayout(
  nodes: ObjSpec[], edges: ObjSpec[], layout: { mode?: string; root?: string }, region: LayoutRect,
): Map<string, { x: number; y: number }> {
  const pos = new Map<string, { x: number; y: number }>()
  const ids = nodes.map(n => n.id)
  const adj = new Map<string, string[]>()
  const indeg = new Map<string, number>()
  for (const id of ids) { adj.set(id, []); indeg.set(id, 0) }
  for (const e of edges as any[]) {
    adj.get(e.from)?.push(e.to)
    indeg.set(e.to, (indeg.get(e.to) || 0) + 1)
  }
  const mode = layout?.mode || 'ring'
  const cx = region.x + region.w / 2, cy = region.y + region.h / 2

  if (mode === 'ring' || ids.length <= 2) {
    const R = Math.min(region.w, region.h) / 2 - 30
    ids.forEach((id, i) => {
      const a = (i / ids.length) * Math.PI * 2 - Math.PI / 2
      pos.set(id, { x: cx + R * Math.cos(a), y: cy + R * Math.sin(a) })
    })
    return pos
  }

  // tree / layered: BFS levels
  let root = layout?.root
  if (!root || !ids.includes(root)) root = ids.find(id => (indeg.get(id) || 0) === 0) || ids[0]
  const level = new Map<string, number>([[root, 0]])
  const queue = [root]
  while (queue.length) {
    const u = queue.shift()!
    for (const v of adj.get(u) || []) {
      if (!level.has(v)) { level.set(v, (level.get(u) || 0) + 1); queue.push(v) }
    }
  }
  // also level unvisited (isolated / disconnected)
  let maxLvl = Math.max(0, ...level.values())
  const byLevel = new Map<number, string[]>()
  ids.forEach(id => {
    const l = level.get(id) ?? (maxLvl + 1)
    level.set(id, l)
    maxLvl = Math.max(maxLvl, l)
    if (!byLevel.has(l)) byLevel.set(l, [])
    byLevel.get(l)!.push(id)
  })
  const pad = 40
  for (const [l, list] of byLevel) {
    const y = region.y + pad + (l / Math.max(1, maxLvl)) * (region.h - pad * 2)
    list.forEach((id, i) => {
      const x = region.x + pad + (list.length === 1 ? (region.w - pad * 2) / 2 : (i / (list.length - 1)) * (region.w - pad * 2))
      pos.set(id, { x, y })
    })
  }
  return pos
}

// ── state application ───────────────────────────────────────────

export type ObjState = ObjSpec & { highlight?: number[][]; hidden?: boolean; _order?: number[] }

function setPath(obj: any, path: string, value: unknown) {
  const parts = path.split('.')
  let cur = obj
  for (let i = 0; i < parts.length - 1; i++) {
    if (cur[parts[i]] === undefined) cur[parts[i]] = {}
    cur = cur[parts[i]]
  }
  cur[parts[parts.length - 1]] = value
}

export function applyState(objects: Record<string, ObjState>, st: State): Record<string, ObjState> {
  const next: Record<string, ObjState> = {}
  for (const [id, o] of Object.entries(objects)) {
    next[id] = { ...o, highlight: o.highlight ? [...o.highlight] : undefined, _order: o._order ? [...o._order] : undefined }
  }
  for (const [path, value] of Object.entries(st.set || {})) {
    const dot = path.indexOf('.')
    const id = dot === -1 ? path : path.slice(0, dot)
    if (!next[id]) continue
    setPath(next[id], dot === -1 ? 'label' : path.slice(dot + 1), value)
  }
  for (const [id, [i, j]] of Object.entries(st.swap || {})) {
    const o = next[id] as any
    if (o?.values && i < o.values.length && j < o.values.length) {
      const t = o.values[i]; o.values[i] = o.values[j]; o.values[j] = t
      if (o._order) { const t2 = o._order[i]; o._order[i] = o._order[j]; o._order[j] = t2 }
    }
  }
  for (const [id, v] of Object.entries(st.push || {})) {
    const o = next[id] as any
    if (o?.values) { o.values = [...o.values, v]; if (o._order) o._order = [...o._order, o._order.length] }
  }
  for (const [id, cnt] of Object.entries(st.pop || {})) {
    const o = next[id] as any
    if (o?.values) {
      const n = Math.min(cnt || 1, o.values.length)
      o.values = o.values.slice(0, o.values.length - n)
      if (o._order) o._order = o._order.slice(0, o._order.length - n)
    }
  }
  for (const [id, cells] of Object.entries(st.highlight || {})) {
    if (next[id]) next[id].highlight = cells
  }
  for (const id of st.hide || []) if (next[id]) next[id].hidden = true
  for (const id of st.show || []) if (next[id]) next[id].hidden = false
  return next
}

// ── expression binding ──────────────────────────────────────────

export function evalBind(bind: string, params: Record<string, number>): { path: string; value: number } {
  const eq = bind.indexOf('=')
  if (eq === -1) throw new Error('bind 需要形如 "path = expr"')
  const path = bind.slice(0, eq).trim()
  const expr = bind.slice(eq + 1).trim()
  const names = Object.keys(params)
  const fn = new Function(...names, `with (Math) { return (${expr}); }`) as (...a: number[]) => number
  return { path, value: fn(...names.map(n => params[n])) }
}

// ── cell geometry helpers ───────────────────────────────────────

function arrayCells(o: any, region: LayoutRect) {
  const values: unknown[] = o.values || []
  const n = values.length
  const vertical = o.layout === 'column'
  const cell = 36, gap = 10
  const total = n * cell + (n - 1) * gap
  const start = vertical
    ? region.y + 30 + Math.max(0, (region.h - 40 - total) / 2)
    : region.x + Math.max(0, (region.w - total) / 2)
  return values.map((_, i) => {
    const p = start + i * (cell + gap)
    return vertical
      ? { x: region.x + Math.max(0, (region.w - cell) / 2), y: p, cell, gap }
      : { x: p, y: region.y + 36, cell, gap }
  })
}

// ── main component ──────────────────────────────────────────────

export default function SceneEngine({
  doc, params, stateIndex, speed = 1,
}: {
  doc: VizDoc
  params: Record<string, number>
  stateIndex: number
  speed?: number
}) {
  const dur = `${0.45 / speed}s`
  // interaction layer: pointer index moves, point drags, node highlight toggles
  const [interact, setInteract] = useState<Record<string, any>>({})

  const fireEvent = useCallback((target: string, attr?: string, value?: number) => {
    const ev = doc.events?.find(e => e.target === target && e.on === 'click') ||
               doc.events?.find(e => e.target === target && e.on === 'drag')
    setInteract(prev => {
      const next = { ...prev }
      const cur = { ...(next[target] || {}) }
      if (attr === 'index' || attr === 'x' || attr === 'y') {
        cur[attr] = value
      } else if (attr === 'click') {
        if (ev?.toggleHighlight) {
          cur.highlight = cur.highlight ? [] : [[0]]
        }
      }
      if (ev?.set) Object.assign(cur, ev.set)
      next[target] = cur
      return next
    })
  }, [doc.events])

  const base = useMemo(() => {
    const m: Record<string, ObjState> = {}
    for (const o of doc.scene.objects) {
      const s = { ...o } as ObjState
      if (o.type === 'array' || o.type === 'stack' || o.type === 'bar') {
        s._order = (o as any).values.map((_: unknown, i: number) => i)
      }
      m[o.id] = s
    }
    return m
  }, [doc])

  const timeline = useMemo(() => {
    let cur = base
    const states = doc.states || []
    for (let i = 0; i <= Math.min(stateIndex, states.length - 1); i++) cur = applyState(cur, states[i])
    return cur
  }, [base, stateIndex, doc.states])

  const live = useMemo(() => {
    let cur = timeline
    for (const p of doc.interact || []) {
      if (!p.bind) continue
      try {
        const { path, value } = evalBind(p.bind, params)
        cur = applyState(cur, { set: { [path]: value } })
      } catch { /* ignore */ }
    }
    return cur
  }, [timeline, params, doc.interact])

  const { region, graphRegion } = useMemo(() => computeRegions(doc.scene.objects), [doc.scene.objects])
  const nodes = useMemo(() => doc.scene.objects.filter(o => o.type === 'node'), [doc.scene.objects])
  const edges = useMemo(() => doc.scene.objects.filter(o => o.type === 'edge'), [doc.scene.objects])
  const graphPos = useMemo(() =>
    graphRegion ? computeGraphLayout(nodes, edges, doc.scene.layout || {}, graphRegion) : new Map(),
    [nodes, edges, graphRegion, doc.scene.layout])

  const events = doc.events || []

  const anchorOf = (id: string): { x: number; y: number } | null => {
    const g = graphPos.get(id)
    if (g) return g
    const o = live[id] as any
    const r = region.get(id)
    if (!o || !r) return null
    if (o.type === 'array' || o.type === 'stack' || o.type === 'bar') {
      const cells = arrayCells(o, r)
      if (!cells.length) return null
      const mid = cells[Math.floor(cells.length / 2)]
      return { x: mid.x + mid.cell / 2, y: mid.y + mid.cell / 2 }
    }
    return { x: r.x + r.w / 2, y: r.y + r.h / 2 }
  }

  const pointerPos = useMemo(() => {
    const map: Record<string, { x: number; y: number }> = {}
    for (const o of doc.scene.objects) {
      if (o.type !== 'pointer') continue
      const arr = live[o.target] as any
      const r = region.get(o.target)
      if (!arr || !r) continue
      const cells = arrayCells(arr, r)
      const idx = Math.min(Math.max(0, interact[o.id]?.index ?? o.index), cells.length - 1)
      if (!cells.length) continue
      const c = cells[idx]
      const vertical = arr.layout === 'column'
      map[o.id] = vertical
        ? { x: c.x + c.cell / 2, y: c.y - 6 }
        : { x: c.x + c.cell / 2, y: c.y - 8 }
    }
    return map
  }, [live, doc.scene.objects, region])

  // clickable cell → pointer move (click-to-move)
  const onCellClick = (arrId: string, idx: number) => {
    const p = doc.scene.objects.find(o => o.type === 'pointer' && (o as any).target === arrId)
    if (p && doc.events?.some(e => e.target === p.id && e.attr === 'index')) fireEvent(p.id, 'index', idx)
  }

  // ── render one object ──
  const renderObj = (o: ObjState, r: LayoutRect): React.ReactNode => {
    const oo = o as any
    switch (o.type) {
      case 'array': {
        const values: unknown[] = oo.values || []
        const cells = arrayCells(oo, r)
        const hi = o.highlight || []
        return (
          <g>
            {o.label && <text x={r.x} y={r.y + 14} fontSize={11} fill="#6b7280">{o.label}</text>}
            {values.map((v, i) => {
              const c = cells[i]
              if (!c) return null
              const isHi = hi.some(([h]) => h === i)
              const key = oo._order ? oo._order[i] : i
              return (
                <g key={key}
                   style={{ transition: `transform ${dur} ease-in-out` }}
                   transform={`translate(${c.x}, ${c.y})`}
                   onClick={() => onCellClick(o.id, i)}
                   className="cursor-pointer">
                  <rect width={c.cell} height={c.cell} rx={6}
                        fill={isHi ? '#eef2ff' : '#fff'}
                        stroke={isHi ? '#6366f1' : '#d1d5db'}
                        strokeWidth={isHi ? 2.5 : 1.5}
                        style={{ transition: `fill ${dur}, stroke ${dur}` }} />
                  <text x={c.cell / 2} y={c.cell / 2 + 4} textAnchor="middle"
                        fontSize={14} fontFamily="monospace" fill="#111827">{String(v)}</text>
                </g>
              )
            })}
            {!oo.layout && values.map((_, i) => {
              const c = cells[i]
              return <text key={`idx${i}`} x={c.x + c.cell / 2} y={c.y + c.cell + 12}
                           textAnchor="middle" fontSize={8} fill="#9ca3af">{i}</text>
            })}
          </g>
        )
      }
      case 'stack': {
        const values: unknown[] = oo.values || []
        const cell = 36, gap = 6
        const n = values.length
        const bottom = r.y + r.h - 20
        const hi = o.highlight || []
        return (
          <g>
            {o.label && <text x={r.x} y={r.y + 14} fontSize={11} fill="#6b7280">{o.label}</text>}
            {values.map((v, i) => {
              const y = bottom - (i + 1) * (cell + gap)
              const isHi = hi.some(([h]) => h === i)
              const x = r.x + Math.max(0, (r.w - cell) / 2)
              return (
                <g key={i} style={{ transition: `transform ${dur} ease-in-out` }} transform={`translate(${x}, ${y})`}>
                  <rect width={cell} height={cell} rx={4}
                        fill={isHi ? '#fef3c7' : '#f59e0b'} stroke={isHi ? '#f59e0b' : '#b45309'}
                        style={{ transition: `fill ${dur}, stroke ${dur}` }} />
                  <text x={cell / 2} y={cell / 2 + 4} textAnchor="middle" fontSize={13}
                        fontFamily="monospace" fill="#fff">{String(v)}</text>
                </g>
              )
            })}
            {n > 0 && <text x={r.x + r.w - 8} y={bottom - n * (cell + gap) - 8}
                            textAnchor="end" fontSize={9} fill="#b45309" fontWeight="bold">top</text>}
          </g>
        )
      }
      case 'bar': {
        const values: number[] = oo.values || []
        const maxV = Math.max(...values.map(Math.abs), 1)
        const plotH = r.h - 40
        const barW = Math.min(30, (r.w - (values.length - 1) * 6) / values.length)
        const totalW = values.length * barW + (values.length - 1) * 6
        const startX = r.x + Math.max(0, (r.w - totalW) / 2)
        const hi = o.highlight || []
        return (
          <g>
            {o.label && <text x={r.x} y={r.y + 14} fontSize={11} fill="#6b7280">{o.label}</text>}
            <line x1={r.x + 4} x2={r.x + r.w - 4} y1={r.y + plotH} y2={r.y + plotH} stroke="#e5e7eb" />
            {values.map((v, i) => {
              const h = (Math.abs(v) / maxV) * (plotH - 20)
              const x = startX + i * (barW + 6)
              const isHi = hi.some(([hx]) => hx === i)
              return (
                <g key={i} style={{ transition: `transform ${dur} ease-in-out` }} transform={`translate(${x}, ${r.y + plotH})`}>
                  <rect width={barW} height={-h} rx={3}
                        fill={isHi ? '#6366f1' : '#a5b4fc'}
                        style={{ transition: `height ${dur}, fill ${dur}` }} />
                  <text x={barW / 2} y={-h - 4} textAnchor="middle" fontSize={9} fontFamily="monospace" fill="#374151">{v}</text>
                </g>
              )
            })}
          </g>
        )
      }
      case 'grid': {
        const matrix: (number | string)[][] = oo.matrix || []
        const cell = 32, gap = 4
        const rows = matrix.length, cols = rows ? matrix[0].length : 0
        const totalW = cols * cell + (cols - 1) * gap
        const totalH = rows * cell + (rows - 1) * gap
        const startX = r.x + Math.max(0, (r.w - totalW) / 2)
        const startY = r.y + Math.max(0, (r.h - totalH) / 2)
        return (
          <g>
            {o.label && <text x={r.x} y={r.y + 14} fontSize={11} fill="#6b7280">{o.label}</text>}
            {matrix.map((row, rr) => row.map((v, c) => {
              const isHi = o.highlight?.some(([hr, hc]) => hr === rr && hc === c)
              const x = startX + c * (cell + gap)
              const y = startY + rr * (cell + gap)
              return (
                <g key={`${rr}-${c}`}>
                  <rect x={x} y={y} width={cell} height={cell} rx={4}
                        fill={isHi ? '#eef2ff' : '#fff'} stroke={isHi ? '#6366f1' : '#d1d5db'}
                        strokeWidth={isHi ? 2.5 : 1.5}
                        style={{ transition: `fill ${dur}, stroke ${dur}` }} />
                  <text x={x + cell / 2} y={y + cell / 2 + 4} textAnchor="middle"
                        fontSize={12} fontFamily="monospace" fill="#111827">{v}</text>
                </g>
              )
            }))}
          </g>
        )
      }
      case 'curve': {
        const fn = safeExpr(oo.fn)
        const [x0, x1] = oo.range || [-5, 5]
        const pad = 28
        const w = r.w, h = r.h
        const plotW = w - pad * 2, plotH = h - pad * 2
        const ys: number[] = []
        for (let i = 0; i <= 100; i++) {
          const y = fn(x0 + (i / 100) * (x1 - x0))
          if (isFinite(y)) ys.push(y)
        }
        let ymin = Math.min(...ys, 0), ymax = Math.max(...ys, 0)
        if (oo.yrange) { ymin = oo.yrange[0]; ymax = oo.yrange[1] }
        if (ymax - ymin < 1e-6) { ymax += 1; ymin -= 1 }
        const sx = (x: number) => r.x + pad + ((x - x0) / (x1 - x0)) * plotW
        const sy = (y: number) => r.y + pad + plotH - ((y - ymin) / (ymax - ymin)) * plotH
        const d: string[] = []
        for (let i = 0; i <= 120; i++) {
          const x = x0 + (i / 120) * (x1 - x0)
          const y = fn(x)
          if (isFinite(y)) d.push(`${sx(x).toFixed(1)},${sy(y).toFixed(1)}`)
        }
        return (
          <g>
            <rect x={r.x} y={r.y} width={w} height={h} rx={8} fill="#fafafa" stroke="#e5e7eb" />
            {o.label && <text x={r.x + 10} y={r.y + 14} fontSize={11} fill="#6b7280">{o.label}</text>}
            <line x1={r.x + pad} x2={r.x + w - pad} y1={sy(0)} y2={sy(0)} stroke="#e5e7eb" />
            <line x1={sx(0)} x2={sx(0)} y1={r.y + pad} y2={r.y + h - pad} stroke="#e5e7eb" />
            <path d={`M${d.join(' L')}`} fill="none" stroke={oo.color || '#6366f1'}
                  strokeWidth={2.5} strokeLinejoin="round" />
          </g>
        )
      }
      case 'point': {
        return null // rendered at top level (needs curve transform)
      }
      case 'text': {
        return <text x={r.x + 10} y={r.y + 20} fontSize={13} fill={oo.color || '#374151'}>{oo.content}</text>
      }
      case 'group': {
        const children = oo.children || []
        const childRegion: LayoutRect = { x: r.x + 4, y: r.y + 22, w: r.w - 8, h: r.h - 30 }
        return (
          <g>
            <rect x={r.x} y={r.y} width={r.w} height={r.h} rx={8} fill="#f8fafc" stroke="#cbd5e1" strokeDasharray="4 3" />
            {o.label && <text x={r.x + 10} y={r.y + 15} fontSize={11} fill="#64748b">{o.label}</text>}
            {children.map((c: ObjSpec) => renderObj(live[c.id] || (c as ObjState), childRegion))}
          </g>
        )
      }
      case 'node': {
        const p = graphPos.get(o.id)
        if (!p) return null
        const it = interact[o.id]
        const hi = it?.highlight?.length || o.highlight?.length
        return (
          <g transform={`translate(${p.x}, ${p.y})`} className="cursor-pointer"
             onClick={() => fireEvent(o.id, 'click')}>
            <circle r={18} fill={oo.color || '#6366f1'} stroke={hi ? '#f59e0b' : '#fff'}
                    strokeWidth={hi ? 4 : 2}
                    style={{ transition: `stroke ${dur}, fill ${dur}` }} />
            <text y={4} textAnchor="middle" fontSize={11} fill="#fff">{oo.value ?? o.id}</text>
          </g>
        )
      }
      default:
        return null
    }
  }

  return (
    <svg viewBox={`0 0 ${CANVAS_W} ${CANVAS_H}`} className="w-full rounded-lg border border-gray-200 bg-white">
      {/* edges */}
      {edges.map((e: any) => {
        const a = graphPos.get(e.from), b = graphPos.get(e.to)
        if (!a || !b) return null
        const w = e.weight !== undefined ? Math.min(2.2, Math.max(0.4, Math.abs(e.weight) * 1.4 + 0.4)) : 0.8
        const dx = b.x - a.x, dy = b.y - a.y
        const len = Math.hypot(dx, dy) || 1
        const ux = dx / len, uy = dy / len
        const x1 = a.x + ux * 20, y1 = a.y + uy * 20
        const x2 = b.x - ux * 20, y2 = b.y - uy * 20
        return (
          <g key={e.id}>
            <line x1={x1} y1={y1} x2={x2} y2={y2} stroke="#c7d2fe" strokeWidth={w}
                  markerEnd="url(#viz-arrow)" />
            {e.weight !== undefined && (
              <text x={(x1 + x2) / 2} y={(y1 + y2) / 2 - 4} fontSize={9} fill="#6b7280"
                    fontFamily="monospace">{e.weight}</text>
            )}
          </g>
        )
      })}
      {/* arrows (object anchors) */}
      {doc.scene.objects.filter(o => o.type === 'arrow' && !live[o.id]?.hidden).map((o: any) => {
        const a = anchorOf(o.from), b = anchorOf(o.to)
        if (!a || !b) return null
        return (
          <g key={o.id}>
            <line x1={a.x} y1={a.y} x2={b.x} y2={b.y} stroke={o.color || '#10b981'}
                  strokeWidth={1.6} strokeDasharray="5 3" markerEnd="url(#viz-arrow-green)" />
            {o.label && <text x={(a.x + b.x) / 2 - 6} y={(a.y + b.y) / 2 - 6} fontSize={9} fill={o.color || '#10b981'}>{o.label}</text>}
          </g>
        )
      })}
      <defs>
        <marker id="viz-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
          <path d="M0,0 L10,5 L0,10 z" fill="#c7d2fe" />
        </marker>
        <marker id="viz-arrow-green" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
          <path d="M0,0 L10,5 L0,10 z" fill="#10b981" />
        </marker>
      </defs>

      {/* primary objects */}
      {doc.scene.objects.filter(o => PRIMARY_TYPES.has(o.type) && !live[o.id]?.hidden).map(o =>
        <g key={o.id}>{renderObj(live[o.id], region.get(o.id) || { x: 0, y: 0, w: CANVAS_W, h: CANVAS_H })}</g>
      )}
      {/* nodes */}
      {nodes.filter(n => !live[n.id]?.hidden).map(n => renderObj(live[n.id], { x: 0, y: 0, w: 0, h: 0 }))}

      {/* pointers */}
      {doc.scene.objects.filter(o => o.type === 'pointer' && !live[o.id]?.hidden).map(o => {
        const p = pointerPos[o.id]
        if (!p) return null
        const oo = o as any
        return (
          <g key={o.id} style={{ transition: `transform ${dur} ease-in-out` }} transform={`translate(${p.x}, ${p.y})`}>
            <path d="M0,0 L8,10 L-8,10 Z" fill={oo.color || '#ef4444'} />
            <text y={-4} textAnchor="middle" fontSize={10} fontWeight="bold"
                  fill={oo.color || '#ef4444'}>{oo.label || oo.id}</text>
          </g>
        )
      })}

      {/* points on curves */}
      {doc.scene.objects.filter(o => o.type === 'point' && !live[o.id]?.hidden).map(o => {
        const oo = live[o.id] as any
        const it = interact[o.id]
        const curveObj = (oo.on ? live[oo.on] : null) as any
        const r = curveObj ? region.get(oo.on) : null
        if (!curveObj || !r) return null
        try {
          const fn = safeExpr(curveObj.fn)
          const [x0, x1] = curveObj.range || [-5, 5]
          const pad = 28
          const plotW = r.w - pad * 2, plotH = r.h - pad * 2
          const ys: number[] = []
          for (let i = 0; i <= 100; i++) {
            const y = fn(x0 + (i / 100) * (x1 - x0))
            if (isFinite(y)) ys.push(y)
          }
          let ymin = Math.min(...ys, 0), ymax = Math.max(...ys, 0)
          if (curveObj.yrange) { ymin = curveObj.yrange[0]; ymax = curveObj.yrange[1] }
          if (ymax - ymin < 1e-6) { ymax += 1; ymin -= 1 }
          const sx = (x: number) => r.x + pad + ((x - x0) / (x1 - x0)) * plotW
          const sy = (y: number) => r.y + pad + plotH - ((y - ymin) / (ymax - ymin)) * plotH
          const px = it?.x ?? oo.x, py = it?.y ?? oo.y
          const x = sx(px), y = sy(py)
          return (
            <g key={o.id}
               style={{ transition: `transform ${dur} ease-in-out`, cursor: 'grab' }}
               transform={`translate(${x}, ${y})`}
               onPointerDown={e => {
                 if (!doc.events?.some(ev => ev.target === o.id && ev.on === 'drag')) return
                 const svg = (e.target as Element & { ownerSVGElement?: SVGSVGElement }).ownerSVGElement!
                 const pt = svg.createSVGPoint()
                 pt.x = e.clientX; pt.y = e.clientY
                 const ctm = svg.getScreenCTM()!
                 const sp = pt.matrixTransform(ctm.inverse())
                 const nx = x0 + ((sp.x - r.x - pad) / plotW) * (x1 - x0)
                 const ny = ymin + (1 - (sp.y - r.y - pad) / plotH) * (ymax - ymin)
                 fireEvent(o.id, 'x', nx)
                 fireEvent(o.id, 'y', ny)
               }}>
              <circle r={5} fill="#ef4444" stroke="#fff" strokeWidth={1.5} />
              {oo.label && <text x={7} y={-6} fontSize={10} fill="#374151">{oo.label}</text>}
            </g>
          )
        } catch { return null }
      })}
    </svg>
  )
}
