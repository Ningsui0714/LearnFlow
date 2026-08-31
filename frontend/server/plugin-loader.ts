import { readdir, stat } from 'node:fs/promises'
import { resolve } from 'node:path'
import { pathToFileURL } from 'node:url'
import { LearnFlowPluginRegistry, type LearnFlowPluginServerPackage } from '../src/plugin-api.ts'

type PluginModule = {
  default?: LearnFlowPluginServerPackage
  plugin?: LearnFlowPluginServerPackage
}

async function existingServerEntry(directory: string) {
  for (const filename of ['server.ts', 'server.js', 'server.mjs']) {
    const candidate = resolve(directory, filename)
    try {
      if ((await stat(candidate)).isFile()) return candidate
    } catch {
      // A plugin may intentionally omit its server contribution.
    }
  }
  return undefined
}

export async function loadLearnFlowPluginRegistry(root = resolve(process.cwd(), 'plugins')) {
  let entries
  try {
    entries = await readdir(root, { withFileTypes: true })
  } catch (error: any) {
    if (error?.code === 'ENOENT') return new LearnFlowPluginRegistry([])
    throw error
  }
  const packages: LearnFlowPluginServerPackage[] = []
  for (const entry of entries.filter(item => item.isDirectory() && !item.name.startsWith('.')).sort((a, b) => a.name.localeCompare(b.name))) {
    const serverEntry = await existingServerEntry(resolve(root, entry.name))
    if (!serverEntry) continue
    const loaded = await import(`${pathToFileURL(serverEntry).href}?v=${(await stat(serverEntry)).mtimeMs}`) as PluginModule
    const plugin = loaded.default || loaded.plugin
    if (!plugin) throw new Error(`plugin_contract_invalid:${entry.name} does not export default or plugin`)
    packages.push(plugin)
  }
  return new LearnFlowPluginRegistry(packages)
}
