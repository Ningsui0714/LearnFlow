import type { ComponentType } from 'react'
import type { LearnFlowPluginObject, PluginToolResult } from './plugin-api.ts'
import type { TutorToolRun } from './tooling.ts'

export type PluginToolRendererProps = {
  pluginId: string
  toolId: string
  result: PluginToolResult
  objects: readonly LearnFlowPluginObject[]
  onPrompt?: (prompt: string) => void
}

export type LearnFlowPluginClientPackage = {
  pluginId: string
  name?: string
  description?: string
  icon?: string
  renderers: Record<string, ComponentType<PluginToolRendererProps>>
}

type ClientPluginModule = {
  default?: LearnFlowPluginClientPackage
  plugin?: LearnFlowPluginClientPackage
}

const clientModules = import.meta.glob('../plugins/*/client.tsx', { eager: true }) as Record<string, ClientPluginModule>
const rendererRegistry = new Map<string, ComponentType<PluginToolRendererProps>>()
const installedPlugins: Array<Pick<LearnFlowPluginClientPackage, 'pluginId' | 'name' | 'description' | 'icon'>> = []

for (const [path, loaded] of Object.entries(clientModules).sort(([left], [right]) => left.localeCompare(right))) {
  const plugin = loaded.default || loaded.plugin
  if (!plugin) throw new Error(`plugin_renderer_invalid:${path} does not export default or plugin`)
  if (!/^[a-z][a-z0-9_]{1,23}$/.test(plugin.pluginId)) throw new Error(`plugin_renderer_invalid:${path} has invalid pluginId`)
  if (installedPlugins.some(item => item.pluginId === plugin.pluginId)) throw new Error(`plugin_renderer_invalid:duplicate plugin ${plugin.pluginId}`)
  installedPlugins.push({ pluginId: plugin.pluginId, name: plugin.name, description: plugin.description, icon: plugin.icon })
  for (const [rendererId, component] of Object.entries(plugin.renderers || {})) {
    const qualifiedId = `${plugin.pluginId}:${rendererId}`
    if (rendererRegistry.has(qualifiedId)) throw new Error(`plugin_renderer_invalid:duplicate ${qualifiedId}`)
    rendererRegistry.set(qualifiedId, component)
  }
}

export const installedClientPlugins = Object.freeze(installedPlugins.map(item => Object.freeze({ ...item })))

function GenericPluginObjects({ objects }: { objects: readonly LearnFlowPluginObject[] }) {
  if (!objects.length) return null
  return (
    <div className="project-tool-proposal">
      {objects.map(object => (
        <details key={`${object.objectType}:${object.objectId}`}>
          <summary><strong>{object.label}</strong> <small>{object.objectType} · {object.schemaVersion}</small></summary>
          <pre>{JSON.stringify(object.value, null, 2)}</pre>
        </details>
      ))}
    </div>
  )
}

export default function PluginToolResultView({ run, onPrompt }: { run: TutorToolRun; onPrompt?: (prompt: string) => void }) {
  const plugin = run.plugin
  if (!plugin) return null
  const objects = plugin.result.objects || []
  const rendererId = plugin.result.presentation?.renderer
  const Renderer = rendererId ? rendererRegistry.get(rendererId) : undefined
  if (Renderer) {
    return <Renderer pluginId={plugin.pluginId} toolId={plugin.toolId} result={plugin.result} objects={objects} onPrompt={onPrompt} />
  }
  return (
    <div aria-label={`${run.title}插件结果`}>
      <GenericPluginObjects objects={objects} />
      {plugin.result.payload !== undefined && (
        <details>
          <summary>查看结构化结果</summary>
          <pre>{JSON.stringify(plugin.result.payload, null, 2)}</pre>
        </details>
      )}
    </div>
  )
}

export function defineLearnFlowPluginClient(plugin: LearnFlowPluginClientPackage) {
  return plugin
}
