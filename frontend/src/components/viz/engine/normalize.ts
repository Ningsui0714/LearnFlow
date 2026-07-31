/**
 * normalize.ts — migrate legacy DSL v1 (4 dedicated components) to the
 * universal object language (VizDoc). Old lectures keep rendering.
 */
import type { VizDoc } from './types'

export function normalize(config: any): VizDoc {
  // already new format?
  if (config?.scene?.objects) return config as VizDoc
  if (!config?.type) return config as VizDoc

  const type = config.type
  if (type === 'array-pointer') {
    const arr = config.data?.array || []
    const pointers: Record<string, number> = config.data?.pointers || {}
    const steps = (config.steps || []).map((s: any) => ({
      note: s.note,
      ...(s.pointers ? { set: Object.fromEntries(Object.entries(s.pointers).map(([k, v]) => [`${k}.index`, v])) } : {}),
      ...(s.swap ? { swap: { arr: s.swap } } : {}),
      ...(s.highlight?.length ? { highlight: { arr: s.highlight.map((i: number) => [i]) } } : {}),
    }))
    return {
      title: config.title,
      scene: {
        objects: [
          { id: 'arr', type: 'array', values: arr },
          ...Object.entries(pointers).map(([label, idx], i) => ({
            id: label, type: 'pointer' as const, target: 'arr', index: idx as number, label,
            color: ['#ef4444', '#6366f1', '#10b981'][i % 3],
          })),
        ],
      },
      states: steps,
    }
  }
  if (type === 'function-plot') {
    return {
      title: config.title,
      scene: {
        objects: [
          ...(config.functions || []).map((f: any, i: number) => ({
            id: `fn${i}`, type: 'curve' as const, fn: f.expr, range: config.xrange || [-5, 5],
            label: f.label, color: f.color,
          })),
          ...(config.points || []).map((p: any, i: number) => ({
            id: `pt${i}`, type: 'point' as const, on: 'fn0', x: p.x, y: p.y, label: p.label,
          })),
        ],
      },
      states: [],
    }
  }
  if (type === 'tensor-shape') {
    return {
      title: config.title,
      scene: { objects: [{ id: 'm', type: 'grid', matrix: config.data?.matrix || [], label: config.data?.label }] },
      states: config.highlight?.length
        ? [{ note: '', highlight: { m: config.highlight } }]
        : [],
    }
  }
  if (type === 'neural-net') {
    const layers: number[] = config.layers || []
    const nodes: any[] = []
    const edges: any[] = []
    let n = 0
    layers.forEach((count, l) => {
      for (let i = 0; i < count; i++) {
        nodes.push({ id: `n${l}_${i}`, type: 'node', value: String(n) })
        if (l > 0) {
          for (let j = 0; j < layers[l - 1]; j++) {
            edges.push({ id: `e${l}_${j}_${i}`, type: 'edge', from: `n${l - 1}_${j}`, to: `n${l}_${i}` })
          }
        }
        n++
      }
    })
    return {
      title: config.title,
      scene: { layout: { mode: 'layered' }, objects: [...nodes, ...edges] },
      states: [],
    }
  }
  // unknown legacy: pass through (will show unknown-type fallback)
  return config as VizDoc
}
