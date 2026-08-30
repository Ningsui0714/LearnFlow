import { useEffect, useMemo, useState } from 'react'
import {
  runProjectPluginWorkflow,
  type PluginSurfaceNode,
  type PluginWorkflowRun,
  type ProjectPluginSurface,
} from './plugin-runtime.ts'

type FormValues = Record<string, string>

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value)
}

function displayValue(value: unknown): string {
  if (value === null || value === undefined || value === '') return '—'
  if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') return String(value)
  if (Array.isArray(value)) return value.map(displayValue).join('、')
  if (isRecord(value)) return String(value.label || value.title || value.name || value.id || '结构化对象')
  return String(value)
}

function safeLookup(data: Record<string, unknown> | undefined, path: unknown) {
  if (typeof path !== 'string' || !path) return path
  const segments = path.split('.').filter(Boolean)
  if (!segments.length || segments.some(segment => ['__proto__', 'prototype', 'constructor'].includes(segment))) return undefined
  let current: unknown = data
  for (const segment of segments) {
    if (!isRecord(current) || !Object.prototype.hasOwnProperty.call(current, segment)) return undefined
    current = current[segment]
  }
  return current
}

function nodeValue(node: PluginSurfaceNode, surface: ProjectPluginSurface) {
  return node.source ? safeLookup(surface.data, node.source) : node.value
}

function collectInputNodes(nodes: PluginSurfaceNode[], result: PluginSurfaceNode[] = []) {
  for (const node of nodes) {
    if (node.type === 'input') result.push(node)
    collectInputNodes([...(node.fields || []), ...(node.children || [])], result)
  }
  return result
}

function initialFormValues(surface: ProjectPluginSurface) {
  return Object.fromEntries(collectInputNodes(surface.schema.body).map(node => [
    node.id || node.name || '',
    Array.isArray(node.value) ? node.value.join('\n') : String(node.value ?? ''),
  ]).filter(([key]) => Boolean(key)))
}

function workflowInput(nodes: PluginSurfaceNode[], values: FormValues) {
  return Object.fromEntries(collectInputNodes(nodes).map(node => {
    const key = node.id || node.name || ''
    const value = values[key] || ''
    return [key, node.multiple ? value.split(/\n|；|;/).map(item => item.trim()).filter(Boolean) : value.trim()]
  }).filter(([key]) => Boolean(key)))
}

function tableColumn(column: unknown, index: number) {
  if (typeof column === 'string') return { key: column, label: column }
  if (isRecord(column)) {
    const key = String(column.id || column.key || index)
    return { key, label: String(column.label || column.title || key) }
  }
  return { key: String(index), label: `字段 ${index + 1}` }
}

function listItems(value: unknown, fallback: unknown[] | undefined) {
  return Array.isArray(value) ? value : fallback || []
}

function PluginNode({ node, surface, values, busy, onInput, onAction }: {
  node: PluginSurfaceNode
  surface: ProjectPluginSurface
  values: FormValues
  busy: string
  onInput: (id: string, value: string) => void
  onAction: (node: PluginSurfaceNode, scopedNodes?: PluginSurfaceNode[]) => void
}) {
  const value = nodeValue(node, surface)
  const label = node.label || node.title || ''
  const children = [...(node.fields || []), ...(node.children || [])]
  const childProps = { surface, values, busy, onInput, onAction }

  if (node.type === 'section') return <section className="plugin-surface-section">
    {label ? <h3>{label}</h3> : null}
    {node.text ? <p>{node.text}</p> : null}
    <div className="plugin-surface-section-body">{children.map((child, index) => <PluginNode key={child.id || `${child.type}-${index}`} node={child} {...childProps} />)}</div>
  </section>

  if (node.type === 'text') return <p className="plugin-surface-text">{node.text || displayValue(value)}</p>

  if (node.type === 'metric') return <div className="plugin-surface-metric"><strong>{displayValue(value)}</strong><span>{label}</span></div>

  if (node.type === 'list') {
    const items = listItems(value, node.items)
    return <section className="plugin-surface-list">{label ? <strong>{label}</strong> : null}<ul>{items.map((item, index) => <li key={isRecord(item) ? String(item.id || index) : index}>{displayValue(item)}</li>)}</ul></section>
  }

  if (node.type === 'table') {
    const rows = listItems(value, node.rows)
    const columns = (node.columns?.length ? node.columns : (isRecord(rows[0]) ? Object.keys(rows[0]) : [])).map(tableColumn)
    return <section className="plugin-surface-table-wrap">{label ? <strong>{label}</strong> : null}<div className="plugin-surface-table-scroll"><table><thead><tr>{columns.map(column => <th key={column.key}>{column.label}</th>)}</tr></thead><tbody>{rows.map((row, rowIndex) => <tr key={isRecord(row) ? String(row.id || rowIndex) : rowIndex}>{columns.map(column => <td key={column.key}>{displayValue(isRecord(row) ? row[column.key] : row)}</td>)}</tr>)}</tbody></table></div></section>
  }

  if (node.type === 'graph') {
    const boundNodes = listItems(safeLookup(surface.data, node.nodes), node.items)
    const boundEdges = listItems(safeLookup(surface.data, node.edges), node.rows)
    return <section className="plugin-surface-graph" aria-label={label || '插件关系图'}>
      {label ? <strong>{label}</strong> : null}
      <div className="plugin-surface-graph-nodes">{boundNodes.slice(0, 40).map((item, index) => <span key={isRecord(item) ? String(item.id || index) : index}>{displayValue(item)}</span>)}</div>
      {boundEdges.length ? <small>{boundEdges.length} 条已固定关系</small> : <small>当前快照暂无可显示关系</small>}
    </section>
  }

  if (node.type === 'form') return <section className="plugin-surface-form" role="form" aria-label={label || node.title || node.id}>
    {label ? <strong>{label}</strong> : null}
    {children.map((child, index) => <PluginNode key={child.id || `${child.type}-${index}`} node={child} {...childProps} />)}
    {node.workflow_id ? <button type="button" disabled={Boolean(busy)} onClick={() => onAction(node, children)}>{busy === node.workflow_id ? '正在运行…' : node.submit_label || '提交'}</button> : null}
  </section>

  if (node.type === 'input') {
    const fieldId = node.id || node.name || ''
    if (node.multiple) return <label className="plugin-surface-input">{label}<textarea required={node.required} value={values[fieldId] || ''} onChange={event => onInput(fieldId, event.target.value)} /></label>
    return <label className="plugin-surface-input">{label}<input required={node.required} value={values[fieldId] || ''} onChange={event => onInput(fieldId, event.target.value)} /></label>
  }

  if (node.type === 'citation') return <div className="plugin-surface-citation"><span>依据</span><p>{node.text || displayValue(value)}</p></div>

  if (node.type === 'status') return <div className="plugin-surface-status"><span>{label}</span><strong>{displayValue(value)}</strong></div>

  if (node.type === 'action') return <button className="plugin-surface-action" type="button" disabled={Boolean(busy)} onClick={() => onAction(node)}>{busy === node.workflow_id ? '正在运行…' : label || node.workflow_id}</button>

  return null
}

export default function PluginSurfaceHost({ projectId, surface, onChanged }: {
  projectId: number
  surface: ProjectPluginSurface
  onChanged?: () => Promise<void> | void
}) {
  const initialValues = useMemo(() => initialFormValues(surface), [surface])
  const [values, setValues] = useState<FormValues>(initialValues)
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const [lastRun, setLastRun] = useState<PluginWorkflowRun>()

  useEffect(() => { setValues(initialValues); setError('') }, [initialValues])

  const onAction = async (node: PluginSurfaceNode, scopedNodes: PluginSurfaceNode[] = []) => {
    const workflowId = node.workflow_id
    if (!workflowId) return
    const missing = collectInputNodes(scopedNodes).find(field => field.required && !(values[field.id || field.name || ''] || '').trim())
    if (missing) {
      setError(`请填写${missing.label ? `“${missing.label}”` : '必填字段'}`)
      return
    }
    if (node.requires_confirmation && !globalThis.confirm(`确认执行“${node.label || workflowId}”？插件只能提交候选结果，最终写入仍由 LearnFlow 宿主校验。`)) return
    setBusy(workflowId); setError('')
    try {
      const input = { ...(node.input || {}), ...workflowInput(scopedNodes, values) }
      const run = await runProjectPluginWorkflow(projectId, surface, workflowId, input)
      setLastRun(run)
      await onChanged?.()
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : '插件 workflow 运行失败')
    } finally {
      setBusy('')
    }
  }

  const lastRunView = isRecord(lastRun?.run) ? lastRun.run : lastRun

  return <div className="plugin-surface-host" data-plugin-id={surface.plugin_id}>
    <div className="plugin-surface-boundary">声明式插件界面 · 对象写入、版本和权限由 LearnFlow 宿主校验</div>
    {surface.schema.body.map((node, index) => <PluginNode
      key={node.id || `${node.type}-${index}`}
      node={node}
      surface={surface}
      values={values}
      busy={busy}
      onInput={(id, value) => setValues(current => ({ ...current, [id]: value }))}
      onAction={(action, nodes) => void onAction(action, nodes)}
    />)}
    {lastRunView ? <div className="plugin-surface-run" role="status">运行 {String(lastRunView.run_id || lastRunView.id || '—')} · {String(lastRunView.status || '已提交')}</div> : null}
    {error ? <div className="project-panel-error" role="alert">{error}</div> : null}
  </div>
}
