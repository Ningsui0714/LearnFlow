/**
 * FunctionPlot: function curves + marked points (loss curves, gradients).
 *
 * DSL:
 * {
 *   "type": "function-plot",
 *   "functions": [{ "expr": "x^2", "label": "L(w)", "color": "#6366f1" }],
 *   "points": [{ "x": 3, "y": 9, "label": "初始点" }],
 *   "xrange": [-5, 5], "yrange": [-2, 12]
 * }
 * expr supports: + - * / ^ ( ) digits . x pi e sin cos tan exp log abs sqrt
 */
import { useMemo } from 'react'

const ALLOWED = /^[0-9a-zA-Z+\-*/().,\s^pi e x]*$/
const BAD_WORDS = ['import', 'require', 'eval', 'function', 'window', 'document', 'constructor', '__proto__', '=>', '{', '}']

function safeExpr(expr: string): (x: number) => number {
  const cleaned = expr.replace(/\^/g, '**')
  // whitelist check
  if (!ALLOWED.test(expr)) throw new Error('非法表达式')
  for (const w of BAD_WORDS) {
    if (cleaned.includes(w)) throw new Error('非法表达式')
  }
  // eslint-disable-next-line no-new-func
  return new Function('x', `with (Math) { return ${cleaned}; }`) as (x: number) => number
}

export default function FunctionPlot({ config }: { config: any }) {
  const W = 480, H = 240, PAD = 30
  const xr = config.xrange || [-5, 5]
  const yr = config.yrange || [-2, 12]

  const plot = useMemo(() => {
    const fns = (config.functions || []).map((f: any) => {
      try { return { ...f, fn: safeExpr(f.expr) } } catch { return null }
    }).filter(Boolean)

    const sx = (x: number) => PAD + ((x - xr[0]) / (xr[1] - xr[0])) * (W - PAD * 2)
    const sy = (y: number) => H - PAD - ((y - yr[0]) / (yr[1] - yr[0])) * (H - PAD * 2)

    const paths = fns.map((f: any) => {
      const pts: string[] = []
      for (let i = 0; i <= 120; i++) {
        const x = xr[0] + (i / 120) * (xr[1] - xr[0])
        const y = f.fn(x)
        if (isFinite(y)) pts.push(`${sx(x).toFixed(1)},${sy(y).toFixed(1)}`)
      }
      return { ...f, d: `M${pts.join(' L')}`, sx, sy }
    })
    return { fns, sx, sy, paths }
  }, [config, xr[0], xr[1], yr[0], yr[1]])

  const { sx, sy, paths } = plot
  const points = config.points || []

  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full max-w-[520px] rounded-lg border border-gray-200 bg-white">
      {/* grid */}
      {Array.from({ length: 7 }, (_, i) => i / 6).map(t => (
        <g key={`gx${t}`}>
          <line x1={PAD} x2={W - PAD} y1={PAD + t * (H - 2 * PAD)} y2={PAD + t * (H - 2 * PAD)}
                stroke="#f3f4f6" strokeWidth={1} />
        </g>
      ))}
      {Array.from({ length: 7 }, (_, i) => i / 6).map(t => (
        <g key={`gy${t}`}>
          <line x1={PAD + t * (W - 2 * PAD)} x2={PAD + t * (W - 2 * PAD)}
                y1={PAD} y2={H - PAD} stroke="#f3f4f6" strokeWidth={1} />
        </g>
      ))}
      {/* axes */}
      <line x1={PAD} x2={W - PAD} y1={sy(0)} y2={sy(0)} stroke="#d1d5db" />
      <line x1={sx(0)} x2={sx(0)} y1={PAD} y2={H - PAD} stroke="#d1d5db" />
      {/* curves */}
      {paths.map((p: any, i: number) => (
        <g key={i}>
          <path d={p.d} fill="none" stroke={p.color || '#6366f1'} strokeWidth={2.5} strokeLinejoin="round" />
          {p.label && (
            <text x={W - PAD - 4} y={PAD + 14 + i * 16} textAnchor="end" fontSize={10} fill={p.color || '#6366f1'}>
              {p.label}
            </text>
          )}
        </g>
      ))}
      {/* points */}
      {points.map((pt: any, i: number) => (
        <g key={i}>
          <circle cx={sx(pt.x)} cy={sy(pt.y)} r={5} fill="#ef4444" stroke="white" strokeWidth={1.5} />
          {pt.label && (
            <text x={sx(pt.x) + 7} y={sy(pt.y) - 6} fontSize={10} fill="#374151">{pt.label}</text>
          )}
        </g>
      ))}
    </svg>
  )
}
