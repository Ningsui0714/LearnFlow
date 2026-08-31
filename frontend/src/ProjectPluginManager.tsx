import { useCallback, useEffect, useMemo, useState } from 'react'

import {
  enableProjectPluginInstance,
  listProjectPluginInstances,
  loadProjectPluginReleaseCatalog,
  updateProjectPluginInstance,
} from './plugin-runtime'
import type {
  PluginConfigurationProperty,
  PluginInstanceView,
  PluginReleaseView,
} from './plugin-runtime'

const HOST_PORT_COPY: Record<string, string> = {
  'project.read.v1': '读取本项目的名称、目标与归属范围。',
  'source.read.v1': '读取本项目固定版本的来源与有限片段；来源内容始终按不可信输入处理。',
  'knowledge_baseline.read.v1': '读取已确认的项目知识基线；它不代表学习者已经掌握。',
  'roadmap.read.v1': '读取当前路线版本与关卡结构，不能直接修改。',
  'checkpoint.read.v1': '读取关卡和教学合同，不能直接修改。',
  'learning_task.read.v1': '读取正式学习任务；任何修改只能形成待确认提议。',
  'learning_file.read.v1': '读取不含隐藏答案的讲义与练习投影。',
  'learner_context.read.v1': '读取按插件声明裁剪的学习者上下文，没有五核写入权限。',
  'artifact.resolve.v1': '解析固定的核心制品或插件对象引用，不提供任意写入。',
  'model.generate_structured.v1': '由 LearnFlow 代调模型并校验结构；模型密钥不会交给插件。',
  'action.propose.v1': '向 Action Board 提交待确认提议；确认后仍由核心能力执行。',
  'event.record.v1': '记录插件已声明的零五核目标事件，不能改变学习状态。',
}

type PluginGroup = {
  pluginId: string
  releases: PluginReleaseView[]
  instance?: PluginInstanceView
}

function releaseLabel(release: PluginReleaseView) {
  const trust = release.trust_state === 'trusted_signed'
    ? '受信发布者签名'
    : release.trust_state === 'built_in'
      ? 'LearnFlow 内置'
      : release.trust_state === 'untrusted_development'
        ? '未受信开发包'
        : release.trust_state
  return `${release.version} · ${trust}`
}

function initialConfiguration(release: PluginReleaseView, instance?: PluginInstanceView) {
  const configuration: Record<string, unknown> = {}
  for (const [key, property] of Object.entries(release.config_schema?.properties || {})) {
    if (property.default !== undefined) configuration[key] = property.default
  }
  if (instance?.release_id === release.id) Object.assign(configuration, instance.configuration || {})
  return configuration
}

function initialGrants(release: PluginReleaseView, instance?: PluginInstanceView) {
  if (instance?.release_id === release.id) {
    return release.host_ports.filter(port => instance.granted_host_ports?.includes(port))
  }
  return [...release.host_ports]
}

function setConfigurationValue(
  current: Record<string, unknown>,
  name: string,
  value: unknown,
) {
  const next = { ...current }
  if (value === undefined) delete next[name]
  else next[name] = value
  return next
}

function ConfigurationField({
  inputId,
  name,
  property,
  required,
  value,
  onChange,
}: {
  inputId: string
  name: string
  property: PluginConfigurationProperty
  required: boolean
  value: unknown
  onChange: (value: unknown) => void
}) {
  const id = inputId
  const label = property.title || name
  const description = property.description

  if (property.enum?.length) {
    const selectedIndex = property.enum.findIndex(item => Object.is(item, value))
    return <label className="project-plugin-config-field" htmlFor={id}>
      <span>{label}{required ? ' *' : ''}</span>
      <select id={id} value={selectedIndex < 0 ? '' : String(selectedIndex)} onChange={event => {
        if (event.target.value === '') {
          onChange(undefined)
          return
        }
        const index = Number(event.target.value)
        onChange(Number.isInteger(index) ? property.enum?.[index] : undefined)
      }}>
        {!required && <option value="">使用默认值</option>}
        {property.enum.map((item, index) => <option key={index} value={index}>{String(item)}</option>)}
      </select>
      {description && <small>{description}</small>}
    </label>
  }

  if (property.type === 'boolean') {
    return <label className="project-plugin-config-toggle" htmlFor={id}>
      <input id={id} type="checkbox" checked={Boolean(value)} onChange={event => onChange(event.target.checked)} />
      <span><strong>{label}{required ? ' *' : ''}</strong>{description && <small>{description}</small>}</span>
    </label>
  }

  if (property.type === 'integer' || property.type === 'number') {
    return <label className="project-plugin-config-field" htmlFor={id}>
      <span>{label}{required ? ' *' : ''}</span>
      <input
        id={id}
        type="number"
        step={property.type === 'integer' ? 1 : 'any'}
        min={property.minimum}
        max={property.maximum}
        value={typeof value === 'number' ? value : ''}
        onChange={event => onChange(event.target.value === '' ? undefined : Number(event.target.value))}
      />
      {description && <small>{description}</small>}
    </label>
  }

  if (property.type === 'array' && (!property.items?.type || property.items.type === 'string')) {
    const display = Array.isArray(value) ? value.join(', ') : ''
    return <label className="project-plugin-config-field" htmlFor={id}>
      <span>{label}{required ? ' *' : ''}</span>
      <input id={id} value={display} onChange={event => onChange(
        event.target.value.split(',').map(item => item.trim()).filter(Boolean),
      )} placeholder="用逗号分隔" />
      {description && <small>{description}</small>}
    </label>
  }

  if (!property.type || property.type === 'string') {
    return <label className="project-plugin-config-field" htmlFor={id}>
      <span>{label}{required ? ' *' : ''}</span>
      <input id={id} value={typeof value === 'string' ? value : ''} onChange={event => onChange(event.target.value)} />
      {description && <small>{description}</small>}
    </label>
  }

  return <p className="project-plugin-unsupported-config">配置项 {label} 使用了当前宿主不支持的声明类型，已保持只读。</p>
}

function PluginReleaseCard({
  group,
  busy,
  error,
  notice,
  onApply,
  onDisable,
  onOpenPluginWorkspace,
}: {
  group: PluginGroup
  busy: boolean
  error?: string
  notice?: string
  onApply: (release: PluginReleaseView, configuration: Record<string, unknown>, grants: string[]) => Promise<void>
  onDisable: (instance: PluginInstanceView) => Promise<void>
  onOpenPluginWorkspace: (pluginId: string) => void
}) {
  const { releases, instance } = group
  const initialReleaseId = instance?.release_id ?? releases[0]?.id ?? 0
  const [releaseId, setReleaseId] = useState(initialReleaseId)
  const selectedRelease = releases.find(item => item.id === releaseId) || releases[0]
  const [configuration, setConfiguration] = useState<Record<string, unknown>>(
    selectedRelease ? initialConfiguration(selectedRelease, instance) : {},
  )
  const [grants, setGrants] = useState<string[]>(selectedRelease ? initialGrants(selectedRelease, instance) : [])
  const [portsConfirmed, setPortsConfirmed] = useState(false)

  if (!selectedRelease) return null

  const currentRelease = releases.find(item => item.id === instance?.release_id) || instance?.release
  const isUpgrade = Boolean(instance && selectedRelease.id !== instance.release_id)
  const isDisabledUpgrade = Boolean(isUpgrade && instance?.status === 'disabled' && instance.current_snapshot_id)
  const canApply = !busy && selectedRelease.status === 'active' && (selectedRelease.host_ports.length === 0 || portsConfirmed) && !isDisabledUpgrade
  const required = new Set(selectedRelease.config_schema?.required || [])
  const properties = Object.entries(selectedRelease.config_schema?.properties || {})
  const actionLabel = !instance
    ? '启用插件'
    : instance.status === 'disabled'
      ? '重新启用'
      : isUpgrade
        ? `升级到 ${selectedRelease.version}`
        : '保存配置与授权'

  const chooseRelease = (nextId: number) => {
    const next = releases.find(item => item.id === nextId)
    if (!next) return
    setReleaseId(next.id)
    setConfiguration(initialConfiguration(next, instance))
    setGrants(initialGrants(next, instance))
    setPortsConfirmed(false)
  }

  const toggleGrant = (port: string, checked: boolean) => {
    setGrants(current => checked
      ? [...current.filter(item => item !== port), port]
      : current.filter(item => item !== port))
    setPortsConfirmed(false)
  }

  return <article className="project-plugin-card">
    <header>
      <div>
        <strong>{selectedRelease.name || group.pluginId}</strong>
        <span>{group.pluginId}</span>
      </div>
      <i className={instance?.status === 'enabled' ? 'enabled' : ''}>{instance?.status === 'enabled' ? '已启用' : instance ? '已停用' : '未启用'}</i>
    </header>
    {selectedRelease.description && <p>{selectedRelease.description}</p>}
    <label className="project-plugin-release-picker">
      <span>固定版本</span>
      <select value={selectedRelease.id} disabled={busy} onChange={event => chooseRelease(Number(event.target.value))}>
        {releases.map(release => <option key={release.id} value={release.id} disabled={release.status !== 'active' && release.id !== instance?.release_id}>
          {releaseLabel(release)}{release.id === instance?.release_id ? '（当前）' : ''}
        </option>)}
      </select>
    </label>
    {selectedRelease.trust_state === 'untrusted_development' && <div className="project-plugin-trust-warning">未受信开发包：仅在管理员显式允许的开发环境中运行。</div>}
    {currentRelease?.status === 'revoked' && <div className="project-plugin-trust-warning">当前 release 已撤销，宿主会阻止新的运行。</div>}

    <fieldset className="project-plugin-permissions">
      <legend>Host Ports 授权</legend>
      {!selectedRelease.host_ports.length && <p>这个 release 没有声明宿主端口。</p>}
      {selectedRelease.host_ports.map(port => <label key={port}>
        <input type="checkbox" checked={grants.includes(port)} disabled={busy} onChange={event => toggleGrant(port, event.target.checked)} />
        <span><strong>{port}</strong><small>{HOST_PORT_COPY[port] || '仅在插件 manifest 声明且本项目授权后可调用。'}</small></span>
      </label>)}
      {selectedRelease.host_ports.length > 0 && <label className="project-plugin-confirm-ports">
        <input type="checkbox" checked={portsConfirmed} disabled={busy} onChange={event => setPortsConfirmed(event.target.checked)} />
        <span>我已核对并确认以上 {grants.length} 个 Host Port 授权。</span>
      </label>}
    </fieldset>

    {properties.length > 0 && <fieldset className="project-plugin-configuration">
      <legend>插件配置</legend>
      {properties.map(([name, property]) => <ConfigurationField
        key={name}
        inputId={`plugin-config-${group.pluginId}-${name}`}
        name={name}
        property={property}
        required={required.has(name)}
        value={configuration[name]}
        onChange={value => setConfiguration(current => setConfigurationValue(current, name, value))}
      />)}
    </fieldset>}

    {isDisabledUpgrade && <p className="project-plugin-inline-warning">该实例已有固定快照。请先重新启用当前版本，再执行升级，避免绕过迁移 workflow。</p>}
    {error && <div className="project-plugin-card-error" role="alert">{error}</div>}
    {notice && <div className="project-plugin-card-notice" role="status">{notice}</div>}
    <footer>
      <button type="button" disabled={!canApply} onClick={() => void onApply(selectedRelease, configuration, grants)}>{busy ? '处理中…' : actionLabel}</button>
      {instance?.status === 'enabled' && <button type="button" className="project-plugin-open-workspace" disabled={busy} onClick={() => onOpenPluginWorkspace(group.pluginId)}>在 Tutor 对话中使用</button>}
      {instance?.status === 'enabled' && <button type="button" className="project-plugin-disable" disabled={busy} onClick={() => void onDisable(instance)}>停用</button>}
    </footer>
  </article>
}

export default function ProjectPluginManager({ projectId, onChanged, onOpenPluginWorkspace }: {
  projectId: number
  onChanged?: () => Promise<void> | void
  onOpenPluginWorkspace: (pluginId: string) => void
}) {
  const [releases, setReleases] = useState<PluginReleaseView[]>([])
  const [instances, setInstances] = useState<PluginInstanceView[]>([])
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState('')
  const [busyPlugin, setBusyPlugin] = useState('')
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [notices, setNotices] = useState<Record<string, string>>({})

  const refresh = useCallback(async () => {
    const [catalog, page] = await Promise.all([
      loadProjectPluginReleaseCatalog(projectId),
      listProjectPluginInstances(projectId),
    ])
    setReleases(catalog.releases)
    setInstances(page.instances)
    setLoadError('')
  }, [projectId])

  useEffect(() => {
    let active = true
    setLoading(true)
    Promise.all([loadProjectPluginReleaseCatalog(projectId), listProjectPluginInstances(projectId)])
      .then(([catalog, page]) => {
        if (!active) return
        setReleases(catalog.releases)
        setInstances(page.instances)
        setLoadError('')
      })
      .catch(failure => {
        if (!active) return
        setLoadError(failure instanceof Error ? failure.message : '插件目录读取失败')
      })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [projectId])

  const groups = useMemo(() => {
    const byPlugin = new Map<string, PluginGroup>()
    for (const release of releases) {
      const group = byPlugin.get(release.plugin_id) || { pluginId: release.plugin_id, releases: [] }
      group.releases.push(release)
      byPlugin.set(release.plugin_id, group)
    }
    for (const instance of instances) {
      const group = byPlugin.get(instance.plugin_id) || { pluginId: instance.plugin_id, releases: [] }
      group.instance = instance
      if (instance.release && !group.releases.some(release => release.id === instance.release?.id)) {
        group.releases.push(instance.release)
      }
      byPlugin.set(instance.plugin_id, group)
    }
    const collator = new Intl.Collator(undefined, { numeric: true, sensitivity: 'base' })
    return [...byPlugin.values()]
      .filter(group => group.releases.length > 0)
      .map(group => ({ ...group, releases: [...group.releases].sort((a, b) => collator.compare(b.version, a.version)) }))
      .sort((a, b) => a.pluginId.localeCompare(b.pluginId))
  }, [instances, releases])

  const apply = async (group: PluginGroup, release: PluginReleaseView, configuration: Record<string, unknown>, grants: string[]) => {
    const { instance, pluginId } = group
    const changingRelease = Boolean(instance && release.id !== instance.release_id)
    const prompt = changingRelease
      ? `确认把“${release.name}”升级到 ${release.version}，并授权 ${grants.length} 个 Host Port？升级会先运行插件声明的迁移 workflow，失败时保留旧版本。`
      : `确认${instance ? '更新' : '启用'}“${release.name}” ${release.version}，并授权 ${grants.length} 个 Host Port？`
    if (!confirm(prompt)) return
    setBusyPlugin(pluginId)
    setErrors(current => ({ ...current, [pluginId]: '' }))
    setNotices(current => ({ ...current, [pluginId]: '' }))
    try {
      if (!instance || instance.status === 'disabled') {
        await enableProjectPluginInstance(projectId, pluginId, {
          release_id: release.id,
          configuration,
          granted_host_ports: grants,
        })
      } else if (changingRelease) {
        const suffix = globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(16).slice(2)}`
        await updateProjectPluginInstance(projectId, pluginId, {
          release_id: release.id,
          configuration,
          granted_host_ports: grants,
          expected_snapshot_id: instance.current_snapshot_id ?? null,
          upgrade_idempotency_key: `plugin-upgrade:${pluginId}:${suffix}`,
        })
      } else {
        await updateProjectPluginInstance(projectId, pluginId, { configuration, granted_host_ports: grants, status: 'enabled' })
      }
      setNotices(current => ({ ...current, [pluginId]: changingRelease ? '升级完成，实例已原子切换到新 release。' : '插件实例已更新。' }))
      await Promise.all([refresh(), Promise.resolve(onChanged?.())])
    } catch (failure) {
      setErrors(current => ({ ...current, [pluginId]: failure instanceof Error ? failure.message : '插件实例更新失败' }))
    } finally {
      setBusyPlugin('')
    }
  }

  const disable = async (instance: PluginInstanceView) => {
    if (!confirm(`确认停用“${instance.release?.name || instance.plugin_id}”？历史快照与对象引用会保留，但项目工具和界面会被移除。`)) return
    setBusyPlugin(instance.plugin_id)
    setErrors(current => ({ ...current, [instance.plugin_id]: '' }))
    try {
      await updateProjectPluginInstance(projectId, instance.plugin_id, { status: 'disabled' })
      setNotices(current => ({ ...current, [instance.plugin_id]: '插件已停用；历史数据仍被保留。' }))
      await Promise.all([refresh(), Promise.resolve(onChanged?.())])
    } catch (failure) {
      setErrors(current => ({ ...current, [instance.plugin_id]: failure instanceof Error ? failure.message : '插件停用失败' }))
    } finally {
      setBusyPlugin('')
    }
  }

  return <div className="project-drawer-body project-plugin-manager">
    <div className="project-plugin-manager-boundary">
      <strong>插件运行边界</strong>
      <p>签名只证明发布者身份与包内容完整性，不代表安全隔离。当前文件系统、网络、密钥、CPU 和内存隔离均为 false；只有操作员显式开启 trusted_signed_process 后才能运行本机插件进程。</p>
    </div>
    {loading && <p className="project-drawer-empty">正在读取已安装插件目录…</p>}
    {loadError && <div className="project-plugin-card-error" role="alert">{loadError}</div>}
    {!loading && !loadError && !groups.length && <p className="project-drawer-empty">管理员尚未安装可供此项目启用的插件 release。</p>}
    {groups.map(group => <PluginReleaseCard
      key={`${group.pluginId}:${group.instance?.release_id || 'new'}:${group.instance?.status || 'none'}:${String(group.instance?.updated_at || '')}`}
      group={group}
      busy={busyPlugin === group.pluginId}
      error={errors[group.pluginId]}
      notice={notices[group.pluginId]}
      onApply={(release, configuration, grants) => apply(group, release, configuration, grants)}
      onDisable={disable}
      onOpenPluginWorkspace={onOpenPluginWorkspace}
    />)}
  </div>
}
