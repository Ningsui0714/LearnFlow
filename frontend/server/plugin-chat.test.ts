import assert from 'node:assert/strict'
import test from 'node:test'
import { readFileSync } from 'node:fs'
import {
  pluginChatContext,
  roleCapabilityArtifactFromSnapshot,
  roleCapabilityArtifactFromToolObservation,
  roleCapabilityChatState,
} from '../src/plugin-chat.ts'

const surface: any = {
  plugin_id: 'role_capability_graph', instance_id: 12, surface_id: 'role_capability_project',
  title: '岗位图谱', slot: 'project.context.tabs', schema: {}, workflows: ['generate', 'iterate'],
  data: { snapshot: {
    id: 35, version: 3, root_hash: 'a'.repeat(64), validation: { valid: true, errors: [] },
    components: {
      'semantic-graph': {
        nodes: [
          { id: 'task:1', type: 'task', label: '设计评测', summary: '建立验收标准', evidence_refs: ['source:1'] },
          { id: 'capability:1', type: 'capability', label: '评测工程' },
        ],
        edges: [{ id: 'edge:1', type: 'requires', source: 'task:1', target: 'capability:1' }],
      },
      'process-forest': {
        scenarios: [{ id: 'scenario:1', label: '交付场景', event_ids: ['event:1'] }],
        events: [{ id: 'event:1', label: '验证结果', order: 1, task_id: 'task:1', work_object_id: 'work:1' }],
        work_objects: [{ id: 'work:1', type: 'work_object', label: '评测报告' }],
        bridges: [{ id: 'bridge:1', label: '任务—过程桥', semantic_object_id: 'task:1', process_event_id: 'event:1' }],
      },
    },
  } },
}

test('plugin chat binds the selected product skill and fixed snapshot', () => {
  assert.deepEqual(pluginChatContext(surface), {
    pluginId: 'role_capability_graph', title: '岗位图谱', surfaceId: 'role_capability_project',
    instanceId: 12, snapshotId: 35, snapshotVersion: 3, snapshotRootHash: 'a'.repeat(64),
    productSkillId: 'role_capability_graphing',
  })
  assert.deepEqual(roleCapabilityChatState(surface), { id: 'ready', label: '快照 v3 可对话' })
  assert.equal(roleCapabilityChatState({ ...surface, data: { snapshot: null } }).id, 'needs_snapshot')
})

test('role snapshot projects radar, process forest and cards without copying truth', () => {
  const artifact = roleCapabilityArtifactFromSnapshot(surface.data, surface.title)
  assert.ok(artifact)
  assert.equal(artifact?.snapshot?.id, 35)
  assert.deepEqual(artifact?.nodes.map(item => item.type), ['task', 'capability'])
  assert.equal(artifact?.edges[0].source, 'task:1')
  assert.equal(artifact?.scenarios[0].eventIds[0], 'event:1')
  assert.equal(artifact?.bridges[0].semanticObjectId, 'task:1')
})

test('explain tool observations become bounded in-message artifacts', () => {
  const artifact = roleCapabilityArtifactFromToolObservation({
    snapshot_ref: { id: 35, root_hash: 'a'.repeat(64) },
    result: {
      answer: '评测能力把岗位任务转成可验证的交付标准。',
      objects: [{ id: 'capability:1', type: 'capability', label: '评测工程' }],
      citations: [{ title: '岗位说明', locator: 'source:1#chunk:2' }],
    },
  })
  assert.equal(artifact?.explanation, '评测能力把岗位任务转成可验证的交付标准。')
  assert.equal(artifact?.nodes[0].id, 'capability:1')
  assert.equal(artifact?.citations[0].locator, 'source:1#chunk:2')
})

test('plugin control stays lightweight while Tutor owns workflow and in-message projection', () => {
  const main = readFileSync(new URL('../src/main.tsx', import.meta.url), 'utf8')
  const control = readFileSync(new URL('../src/RoleCapabilityChatPlugin.tsx', import.meta.url), 'utf8')
  const composer = main.indexOf('className="composer-tools composer-tools-capability"')
  const pluginControl = main.indexOf('<RoleCapabilityChatPlugin', composer)
  assert.ok(composer > 0)
  assert.ok(pluginControl > composer)
  assert.equal(main.includes('plugin-chat-dock'), false)
  assert.equal(control.includes('任务种子'), false)
  assert.equal(control.includes('确认生成候选快照'), false)
  assert.match(main, /activateRoleCapabilityForTutor/)
  assert.match(main, /run\.pluginArtifact && <RoleCapabilityArtifactView/)
})
