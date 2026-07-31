/**
 * validate.ts — WP4: schema + semantic validation with auto-fix.
 *
 * validate(doc) → { ok, errors, fixed? }  (errors are human-readable)
 * fix(doc) → { doc, fixes }              (mutating repairs)
 */
import type { VizDoc, ObjSpec, State } from './types'
import { safeExpr } from './safeExpr'

export interface Issue { level: 'error' | 'warn'; msg: string; path?: string }

const OBJ_TYPES = new Set(['array', 'stack', 'bar', 'pointer', 'grid', 'curve', 'point', 'node', 'edge', 'arrow', 'text', 'group'])

// ── schema validation ───────────────────────────────────────────

export function validate(doc: any): Issue[] {
  const issues: Issue[] = []
  if (!doc || typeof doc !== 'object') return [{ level: 'error', msg: '文档必须是 JSON 对象' }]
  if (!doc.scene || !Array.isArray(doc.scene.objects)) {
    return [{ level: 'error', msg: '缺少 scene.objects 数组' }]
  }
  const ids = new Set<string>()
  doc.scene.objects.forEach((o: any, i: number) => {
    const p = `scene.objects[${i}]`
    if (!o || typeof o !== 'object') { issues.push({ level: 'error', msg: `${p} 不是对象` }); return }
    if (!o.id) issues.push({ level: 'error', msg: `${p} 缺少 id` })
    else if (ids.has(o.id)) issues.push({ level: 'error', msg: `${p} id 重复: ${o.id}` })
    else ids.add(o.id)
    if (!OBJ_TYPES.has(o.type)) issues.push({ level: 'error', msg: `${p} 未知对象类型: ${o.type}` })
    if (o.type === 'array' && (!Array.isArray(o.values) || o.values.length === 0)) {
      issues.push({ level: 'error', msg: `${p} array 需要非空 values` })
    }
    if (o.type === 'bar' && (!Array.isArray(o.values) || o.values.some((v: any) => typeof v !== 'number'))) {
      issues.push({ level: 'error', msg: `${p} bar 需要数值 values` })
    }
    if (o.type === 'grid' && (!Array.isArray(o.matrix) || !o.matrix.length)) {
      issues.push({ level: 'error', msg: `${p} grid 需要 matrix` })
    }
    if (o.type === 'curve') {
      if (typeof o.fn !== 'string') issues.push({ level: 'error', msg: `${p} curve 需要 fn` })
      else {
        try { safeExpr(o.fn) } catch (e: any) { issues.push({ level: 'error', msg: `${p} 表达式非法: ${e.message}` }) }
      }
    }
    if (o.type === 'pointer' && typeof o.index !== 'number') {
      issues.push({ level: 'error', msg: `${p} pointer 需要 index` })
    }
  })

  // references
  const refs: [string, string, string][] = []
  doc.scene.objects.forEach((o: any) => {
    if (o.type === 'pointer' || o.type === 'arrow') refs.push([o.type, o.target || o.from, o.id])
    if (o.type === 'arrow') refs.push(['arrow', o.to, o.id])
    if (o.type === 'edge') { refs.push(['edge.from', o.from, o.id]); refs.push(['edge.to', o.to, o.id]) }
  })
  for (const [kind, ref, id] of refs) {
    if (!ids.has(ref)) issues.push({ level: 'error', msg: `${kind} 引用不存在的对象 "${ref}"（${id}）` })
  }

  // states
  ;(doc.states || []).forEach((st: any, i: number) => {
    if (!st || typeof st !== 'object') { issues.push({ level: 'error', msg: `states[${i}] 不是对象` }); return }
    for (const path of Object.keys(st.set || {})) {
      const id = path.split('.')[0]
      if (!ids.has(id)) issues.push({ level: 'error', msg: `states[${i}].set 引用未知对象: ${id}` })
    }
    for (const id of Object.keys(st.swap || {})) if (!ids.has(id)) issues.push({ level: 'error', msg: `states[${i}].swap 引用未知对象: ${id}` })
    for (const id of Object.keys(st.highlight || {})) if (!ids.has(id)) issues.push({ level: 'error', msg: `states[${i}].highlight 引用未知对象: ${id}` })
    for (const id of [...(st.hide || []), ...(st.show || [])]) if (!ids.has(id)) issues.push({ level: 'error', msg: `states[${i}] 引用未知对象: ${id}` })
  })

  // interact
  ;(doc.interact || []).forEach((p: any, i: number) => {
    if (typeof p.param !== 'string' || typeof p.min !== 'number' || typeof p.max !== 'number' || typeof p.default !== 'number') {
      issues.push({ level: 'error', msg: `interact[${i}] 需要 param/min/max/default` })
    }
    if (p.bind && p.bind.indexOf('=') === -1) issues.push({ level: 'error', msg: `interact[${i}].bind 需要 "path = expr"` })
  })

  // events
  ;(doc.events || []).forEach((ev: any, i: number) => {
    if (!ev || !ev.target || !ids.has(ev.target)) issues.push({ level: 'error', msg: `events[${i}] target 未知对象` })
  })

  return issues
}

// ── auto-fix ────────────────────────────────────────────────────

export function fix(doc: any): { doc: VizDoc; fixes: string[] } {
  const fixes: string[] = []
  const objects = JSON.parse(JSON.stringify(doc.scene?.objects || []))
  const ids = new Set(objects.map((o: any) => o.id))

  // clamp pointer index to array bounds
  for (const o of objects) {
    if (o.type === 'pointer') {
      const target = objects.find((t: any) => t.id === o.target)
      const len = target?.values?.length
      if (typeof len === 'number' && len > 0 && (o.index < 0 || o.index >= len)) {
        o.index = Math.min(Math.max(0, o.index), len - 1)
        fixes.push(`指针 ${o.id} 索引越界 → 已钳制为 ${o.index}`)
      }
    }
    if (o.type === 'curve' && typeof o.fn === 'string') {
      try { safeExpr(o.fn) } catch {
        o.fn = 'x'
        fixes.push(`曲线 ${o.id} 表达式非法 → 回退为 x`)
      }
    }
  }
  // drop invalid edges/arrows whose refs don't exist
  const valid = objects.filter((o: any) => {
    const badRefs = (o.type === 'pointer' && !ids.has(o.target))
      || (o.type === 'arrow' && (!ids.has(o.from) || !ids.has(o.to)))
      || (o.type === 'edge' && (!ids.has(o.from) || !ids.has(o.to)))
    if (badRefs) fixes.push(`对象 ${o.id} 引用缺失 → 已移除`)
    return !badRefs
  })

  // drop states referencing unknown objects
  const states = (doc.states || []).map((st: any) => {
    const next: any = { ...st }
    for (const key of ['set', 'swap', 'highlight']) {
      if (next[key]) next[key] = Object.fromEntries(
        Object.entries(next[key]).filter(([id]) => ids.has(id)),
      )
    }
    next.hide = (next.hide || []).filter((id: string) => ids.has(id))
    next.show = (next.show || []).filter((id: string) => ids.has(id))
    return next
  })

  return {
    doc: { ...doc, scene: { ...doc.scene, objects: valid }, states },
    fixes,
  }
}
