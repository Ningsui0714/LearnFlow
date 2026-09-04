import assert from 'node:assert/strict'
import test from 'node:test'
import { LEARNFLOW_PLUGIN_OBJECT_VERSION, pluginObjectContentKey, resolvePluginObjectDrop, type LearnFlowPluginObject } from '../src/plugin-api.ts'

const object: LearnFlowPluginObject = { protocol: LEARNFLOW_PLUGIN_OBJECT_VERSION, pluginId: 'example_plugin', objectType: 'node', objectId: 'same-stable-id',
  schemaVersion: '1', label: '数据结构', value: { snapshotId: 'snapshot:1', rootHash: 'a'.repeat(64), data: { summary: '原始节点' } } }

test('drop resolves only a trusted object in the active conversation and does not accept modified identity or content', () => {
  assert.equal(resolvePluginObjectDrop(JSON.stringify(object), [object]), object)
  assert.equal(resolvePluginObjectDrop(JSON.stringify(object), []), undefined)
  assert.equal(resolvePluginObjectDrop(JSON.stringify({ ...object, label: '伪造' }), [object]), undefined)
  assert.equal(resolvePluginObjectDrop(JSON.stringify({ ...object, value: { snapshotId: 'snapshot:other' } }), [object]), undefined)
  assert.equal(resolvePluginObjectDrop('not json', [object]), undefined)
})

test('stable IDs in different immutable snapshots remain separate references', () => {
  const other = { ...object, value: { snapshotId: 'snapshot:2', rootHash: 'b'.repeat(64) } }
  assert.notEqual(pluginObjectContentKey(object), pluginObjectContentKey(other))
  assert.equal(resolvePluginObjectDrop(JSON.stringify(other), [object, other]), other)
})
