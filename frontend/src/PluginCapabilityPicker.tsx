import { installedClientPlugins } from './PluginToolResultView.tsx'

export default function PluginCapabilityPicker({
  activePluginIds,
  disabled,
  onChange,
}: {
  activePluginIds: readonly string[]
  disabled?: boolean
  onChange: (pluginIds: string[]) => void
}) {
  if (!installedClientPlugins.length) return null
  const active = new Set(activePluginIds)
  return (
    <details className="plugin-capability-picker">
      <summary role="button" aria-label="选择对话插件">
        <span aria-hidden="true">▱</span>
        <strong>插件</strong>
        <small>{active.size ? `已启用 ${active.size}` : '未启用'}</small>
      </summary>
      <div className="plugin-capability-popover">
        <header><strong>本轮对话插件</strong><span>插件只为 Tutor 增加声明过的工具、Skill、对象和结果显示。</span></header>
        {installedClientPlugins.map(plugin => {
          const selected = active.has(plugin.pluginId)
          return (
            <button
              type="button"
              key={plugin.pluginId}
              className={selected ? 'selected' : ''}
              aria-pressed={selected}
              disabled={disabled}
              onClick={() => onChange(selected
                ? activePluginIds.filter(id => id !== plugin.pluginId)
                : [...activePluginIds, plugin.pluginId])}
            >
              <i aria-hidden="true">{plugin.icon || '◇'}</i>
              <span><strong>{plugin.name || plugin.pluginId}</strong><small>{plugin.description || plugin.pluginId}</small></span>
              <b>{selected ? '已启用' : '启用'}</b>
            </button>
          )
        })}
        <footer>选择只作用于当前对话；插件结果不会直接写入五核或核心学习对象。</footer>
      </div>
    </details>
  )
}
