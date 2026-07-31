/**
 * NeuralNet: layered network diagram with optional weight thickness.
 *
 * DSL:
 * {
 *   "type": "neural-net",
 *   "layers": [3, 4, 1],
 *   "activation": "relu",
 *   "weights": [[[0.5,-0.2],[0.1,0.3],[-0.4,0.8]], [[0.2],[-0.6],[0.9],[0.1]]]
 * }
 * weights[l][j][i] = weight from layer-l node j → layer-l+1 node i.
 * Without weights, edges are uniform.
 */
export default function NeuralNet({ config }: { config: any }) {
  const layers: number[] = config.layers || [3, 4, 1]
  const weights: number[][][] = config.weights || []
  const W = 420, H = 180
  const layerX = (li: number) => 40 + (li / (layers.length - 1)) * (W - 80)

  const nodePos = (li: number, ni: number) => {
    const count = layers[li]
    const y = H / 2 + (ni - (count - 1) / 2) * (H - 60) / Math.max(count - 1, 1)
    return { x: layerX(li), y }
  }

  const edges: { x1: number; y1: number; x2: number; y2: number; w: number }[] = []
  for (let l = 0; l < layers.length - 1; l++) {
    for (let j = 0; j < layers[l]; j++) {
      for (let i = 0; i < layers[l + 1]; i++) {
        const a = nodePos(l, j), b = nodePos(l + 1, i)
        let w = 0.4
        if (weights[l]?.[j]?.[i] !== undefined) {
          w = Math.min(1.6, Math.max(0.15, Math.abs(weights[l][j][i]) * 1.2 + 0.15))
        }
        edges.push({ x1: a.x, y1: a.y, x2: b.x, y2: b.y, w })
      }
    }
  }

  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full max-w-[440px] rounded-lg border border-gray-200 bg-white">
      {edges.map((e, i) => (
        <line key={i} x1={e.x1} y1={e.y1} x2={e.x2} y2={e.y2}
              stroke="#c7d2fe" strokeWidth={e.w} />
      ))}
      {layers.map((count, l) => (
        <g key={l}>
          {Array.from({ length: count }, (_, n) => {
            const p = nodePos(l, n)
            return <circle key={n} cx={p.x} cy={p.y} r={12} fill="#6366f1" stroke="white" strokeWidth={2} />
          })}
          {l === layers.length - 1 && (
            <text x={layerX(l) + 18} y={H / 2 + 4} fontSize={10} fill="#6b7280">
              {config.activation ? `σ=${config.activation}` : ''}
            </text>
          )}
        </g>
      ))}
      {/* layer size labels */}
      {layers.map((count, l) => (
        <text key={`l${l}`} x={layerX(l)} y={H - 8} textAnchor="middle" fontSize={9} fill="#9ca3af">
          {count}
        </text>
      ))}
    </svg>
  )
}
