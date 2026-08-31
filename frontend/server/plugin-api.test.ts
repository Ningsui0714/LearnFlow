import assert from 'node:assert/strict'
import test from 'node:test'
import {
  defineLearnFlowPlugin,
  LEARNFLOW_PLUGIN_API_VERSION,
  LEARNFLOW_PLUGIN_OBJECT_VERSION,
  LearnFlowPluginRegistry,
} from '../src/plugin-api.ts'
import { runTutorAgentTurn } from './agent-runtime.ts'

function fixturePlugin(options: { id?: string; defaultEnabled?: boolean } = {}) {
  const id = options.id || 'fixture_graph'
  return defineLearnFlowPlugin({
    manifest: {
      apiVersion: LEARNFLOW_PLUGIN_API_VERSION,
      id,
      name: 'Fixture Graph',
      version: '1.0.0',
      description: 'Exercises the generic extension points.',
      defaultEnabled: options.defaultEnabled,
      objects: [{
        type: 'node', title: 'Node', description: 'A graph node.', schemaVersion: 'fixture.node.v1',
        schema: { type: 'object', properties: { score: { type: 'number' } }, required: ['score'], additionalProperties: false },
        validate: value => typeof value === 'object' && value !== null && Number.isFinite((value as any).score) ? [] : ['score is required'],
      }],
      tools: [{
        id: 'read_graph', title: 'Read graph', description: 'Reads a bounded graph.',
        whenToUse: 'The learner asks about this graph.', whenNotToUse: 'The request needs a core-object write.',
        toolClass: 'perception', risk: 'read_only',
        inputSchema: { type: 'object', properties: { query: { type: 'string' } }, required: ['query'], additionalProperties: false },
        outputObjectTypes: ['node'], renderer: 'radar', availableInModes: ['free', 'simple_explain'],
      }],
      skills: [{
        id: 'graph_reading', title: 'Graph reading', description: 'Read before explaining.',
        whenToUse: 'A graph explanation is requested.', whenNotToUse: 'No graph is active.',
        instructions: 'Read the graph once, cite the returned object IDs, and do not infer mastery.',
        tools: ['read_graph'], objectTypes: ['node'],
      }],
      renderers: [{ id: 'radar', title: 'Radar', description: 'Renders node scores.' }],
    },
    handlers: {
      read_graph: async input => ({
        summary: `matched ${String(input.query)}`,
        objects: [{
          protocol: LEARNFLOW_PLUGIN_OBJECT_VERSION,
          pluginId: id,
          objectType: 'node', objectId: 'node:1', schemaVersion: 'fixture.node.v1', label: 'Node 1', value: { score: 0.8 },
        }],
        presentation: { renderer: 'radar', state: { selected: 'node:1' } },
      }),
    },
  })
}

test('plugin contributions are namespaced and inactive packages expose no tools or skills', () => {
  const registry = new LearnFlowPluginRegistry([fixturePlugin()])
  const inactive = { mode: 'free' as const }
  assert.deepEqual(registry.toolDefinitions(inactive), [])
  assert.equal(registry.skillInstructions(inactive), '')
  const active = { mode: 'free' as const, activePluginIds: ['fixture_graph'] }
  assert.deepEqual(registry.toolDefinitions(active).map(item => item.name), ['fixture_graph__read_graph'])
  assert.match(registry.skillInstructions(active), /fixture_graph__read_graph/)
  assert.match(registry.toolDefinitions(active)[0].description, /不要用于/)
})

test('tool execution validates input, object ownership and renderer declaration', async () => {
  const registry = new LearnFlowPluginRegistry([fixturePlugin({ defaultEnabled: true })])
  const context = { mode: 'free' as const, scope: { mode: 'free' as const }, signal: AbortSignal.timeout(1_000) }
  await assert.rejects(() => registry.execute('fixture_graph__read_graph', { query: 'x', extra: true }, context), /unknown fields/)
  await assert.rejects(() => registry.execute('fixture_graph__read_graph', { query: 42 }, context), /must be string/)
  const execution = await registry.execute('fixture_graph__read_graph', { query: 'x' }, context)
  assert.equal(execution.result.objects?.[0].objectId, 'node:1')
  assert.equal(execution.result.presentation?.renderer, 'fixture_graph:radar')
})

test('a plugin handler cannot hold the Tutor turn beyond the host signal', async () => {
  const plugin = fixturePlugin({ defaultEnabled: true })
  plugin.handlers.read_graph = async () => new Promise(() => undefined)
  const registry = new LearnFlowPluginRegistry([plugin])
  await assert.rejects(() => registry.execute('fixture_graph__read_graph', { query: 'x' }, {
    mode: 'free', scope: { mode: 'free' }, signal: AbortSignal.timeout(10),
  }), /plugin_tool_timeout/)
})

test('duplicate plugin ids and cross-plugin object forgery are rejected', async () => {
  assert.throws(() => new LearnFlowPluginRegistry([fixturePlugin(), fixturePlugin()]), /duplicate ids/)
  const forged = fixturePlugin({ id: 'forged_graph', defaultEnabled: true })
  forged.handlers.read_graph = async () => ({
    summary: 'forged',
    objects: [{
      protocol: LEARNFLOW_PLUGIN_OBJECT_VERSION,
      pluginId: 'another_plugin', objectType: 'node', objectId: 'node:1', schemaVersion: 'fixture.node.v1', label: 'Node', value: { score: 1 },
    }],
  })
  const registry = new LearnFlowPluginRegistry([forged])
  await assert.rejects(() => registry.execute('forged_graph__read_graph', { query: 'x' }, {
    mode: 'free', scope: { mode: 'free' }, signal: AbortSignal.timeout(1_000),
  }), /owned by another plugin/)
})

test('Tutor discovers plugin tools, applies plugin Skill instructions and returns renderer metadata without plugin branches', async () => {
  const registry = new LearnFlowPluginRegistry([fixturePlugin()])
  const requests: any[] = []
  let round = 0
  const result = await runTutorAgentTurn({
    baseUrl: 'https://example.com/v1/chat/completions', model: 'test-model', mode: 'simple_explain',
    messages: [{ role: 'user', content: '解释当前图谱节点' }], toolChoice: 'auto',
    pluginRegistry: registry, activePluginIds: ['fixture_graph'], generate: async () => 'unused',
    invokeProvider: async request => {
      requests.push(request)
      round += 1
      if (round === 1) return { choices: [{ message: { content: null, tool_calls: [{
        id: 'plugin-call', type: 'function', function: { name: 'fixture_graph__read_graph', arguments: '{"query":"当前节点"}' },
      }] } }] }
      return { choices: [{ message: { content: '当前节点的结构化分数是 0.8；这只是插件对象，不表示学习者掌握。' } }] }
    },
  })
  assert.ok(requests[0].body.tools.some((tool: any) => tool.function?.name === 'fixture_graph__read_graph'))
  assert.match(JSON.stringify(requests[0].body), /Read the graph once/)
  assert.equal(result.toolRuns[0].kind, 'plugin')
  assert.equal(result.toolRuns[0].plugin?.pluginId, 'fixture_graph')
  assert.equal(result.toolRuns[0].plugin?.result.presentation?.renderer, 'fixture_graph:radar')
  assert.match(result.reply, /0\.8/)
})
