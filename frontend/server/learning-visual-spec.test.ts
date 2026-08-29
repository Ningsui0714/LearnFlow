import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'
import {
  classifyLearningVisual,
  generateLearningVisual,
  inspectLearningVisualSpec,
  readLearningVisualSpec,
  replayAnimation,
  visualSpecToArtifact,
} from './learning-visual-spec.ts'
import { GOLD_VISUAL_FIXTURES } from './visual-spec/gold-fixtures.ts'

function commonState(overrides: Record<string, unknown> = {}) {
  return {
    activeIds: [],
    values: {},
    pointers: {},
    positions: {},
    tensorShapes: {},
    expressions: {},
    series: {},
    stack: [],
    emittedMessageIds: [],
    ...overrides,
  }
}

async function generatePlan(kind: 'diagram' | 'animation', request: string, payload: Record<string, unknown>) {
  return generateLearningVisual(kind, request, async () => JSON.stringify(payload))
}

test('computer and mathematics classifiers cover every required abstraction family', () => {
  assert.deepEqual(classifyLearningVisual('演示 TCP 三次握手协议'), { domain: 'computer', abstraction: 'protocol_sequence' })
  assert.deepEqual(classifyLearningVisual('展示连接的状态机'), { domain: 'computer', abstraction: 'state_machine' })
  assert.deepEqual(classifyLearningVisual('逐步展示链表数据结构'), { domain: 'computer', abstraction: 'data_structure' })
  assert.deepEqual(classifyLearningVisual('逐行代码执行和调用栈'), { domain: 'computer', abstraction: 'code_trace' })
  assert.deepEqual(classifyLearningVisual('演示自注意力 QKV 的张量 shape 流动'), { domain: 'computer', abstraction: 'tensor_shape_flow' })
  assert.deepEqual(classifyLearningVisual('画出函数导数变化'), { domain: 'mathematics', abstraction: 'function' })
  assert.deepEqual(classifyLearningVisual('贝叶斯概率分布'), { domain: 'mathematics', abstraction: 'probability' })
  assert.deepEqual(classifyLearningVisual('矩阵线性变换'), { domain: 'mathematics', abstraction: 'transformation' })
  assert.deepEqual(classifyLearningVisual('公式等式推导'), { domain: 'mathematics', abstraction: 'derivation' })
})

test('a function diagram uses finite samples, stable state, replayable provenance and safe SVG', async () => {
  const generated = await generatePlan('diagram', '画出 y=x² 的有限采样图', {
    version: 'learnflow.visual.v2', kind: 'diagram', title: '二次函数', subtitle: '有限采样，不执行表达式',
    domain: 'mathematics', abstraction: 'function',
    semantic: {
      type: 'function',
      axes: { xLabel: 'x', yLabel: 'y', xDomain: [-2, 2], yDomain: [0, 4] },
      series: [{ id: 'curve', label: 'y=x²', points: [[-2, 4], [-1, 1], [0, 0], [1, 1], [2, 4]] }],
      parameters: [],
    },
    state: {},
    accessibility: { summary: '横轴是 x，纵轴是 y，五个有限采样点形成抛物线。', readingOrder: ['curve'], nonColorStateCue: '曲线同时使用编号与文字标签。' },
    explanation: '观察对称性。',
  })
  assert.equal(generated.plannerSucceeded, true)
  assert.equal(generated.degraded, false)
  assert.equal(generated.spec.kind, 'diagram')
  assert.equal(generated.artifact.kind, 'image')
  assert.equal(generated.artifact.specVersion, 'learnflow.visual.v2')
  assert.equal(generated.artifact.provenance.requestHash, generated.spec.provenance.requestHash)
  assert.equal(generated.artifact.replay.spec, generated.spec)
  assert.equal(generated.quality.replayable, true)
  assert.equal(generated.quality.layout.collisions, 0)
  assert.equal(generated.quality.layout.outOfBounds, 0)
  assert.match(generated.artifact.steps[0].svg, /^<svg/)
  assert.doesNotMatch(generated.artifact.steps[0].svg, /<script|foreignObject|javascript:|onload=/i)
})

test('diagram rejects timeline fields instead of displaying a content-free fallback', async () => {
  await assert.rejects(() => generatePlan('diagram', '解释模块关系', {
    version: 'learnflow.visual.v2', kind: 'diagram', title: '模块关系', domain: 'computer', abstraction: 'system_structure',
    semantic: { type: 'system_structure', entities: [{ id: 'a', label: 'A' }], relations: [] },
    state: {}, frames: [],
  }), /visual_generation_unavailable:.*diagram_timeline_forbidden/)
})

test('protocol animation replays typed send_message patches and verifies final state', async () => {
  const generated = await generatePlan('animation', '演示一次客户端请求', {
    version: 'learnflow.visual.v2', kind: 'animation', title: '请求时序', domain: 'computer', abstraction: 'protocol_sequence',
    semantic: {
      type: 'protocol_sequence',
      participants: [{ id: 'client', label: '客户端' }, { id: 'server', label: '服务端' }],
      messages: [{ id: 'request', from: 'client', to: 'server', label: '请求', order: 1 }],
    },
    initialState: {},
    frames: [{ id: 'f1', title: '发送请求', narration: '客户端向服务端发送请求。', durationMs: 900, patches: [{ type: 'send_message', messageId: 'request' }] }],
    invariants: [{ type: 'references_resolve' }, { type: 'final_state_active', targetId: 'request' }],
    finalState: { activeIds: ['request'], emittedMessageIds: ['request'] },
    accessibility: { summary: '客户端向服务端发送一条请求。', readingOrder: ['client', 'server', 'request'], nonColorStateCue: '消息按序号、方向和状态文字呈现。' },
  })
  assert.equal(generated.plannerSucceeded, true)
  assert.equal(generated.spec.kind, 'animation')
  assert.equal(generated.quality.semanticChanges, 1)
  assert.equal(generated.quality.invariants.failures.length, 0)
  assert.equal(generated.artifact.steps.length, 2)
  assert.match(generated.artifact.steps[1].text, /发送消息 request/)
})

test('state machine animation requires a real transition patch', async () => {
  const generated = await generatePlan('animation', '演示开关状态机', {
    kind: 'animation', title: '开关状态机', domain: 'computer', abstraction: 'state_machine',
    semantic: {
      type: 'state_machine', states: [{ id: 'off', label: '关闭', initial: true }, { id: 'on', label: '开启' }],
      transitions: [{ id: 'turn_on', from: 'off', to: 'on', event: '按下开关' }],
    },
    initialState: { currentStateId: 'off' },
    frames: [{ id: 'f1', title: '打开', narration: '状态从关闭转为开启。', patches: [{ type: 'transition_state', transitionId: 'turn_on', fromStateId: 'off', toStateId: 'on' }] }],
    invariants: [{ type: 'final_state_active', targetId: 'on' }],
    finalState: { activeIds: ['turn_on', 'on'], currentStateId: 'on' },
  })
  assert.equal(generated.plannerSucceeded, true)
  assert.equal(generated.quality.semanticChanges, 1)
  assert.match(generated.artifact.steps[1].svg, /当前/)
})

test('data structure animation updates a pointer without inventing links', async () => {
  const generated = await generatePlan('animation', '移动链表头指针', {
    kind: 'animation', title: '头指针移动', domain: 'computer', abstraction: 'data_structure',
    semantic: {
      type: 'data_structure', structure: 'linked_list',
      items: [{ id: 'n1', label: '节点1' }, { id: 'n2', label: '节点2' }],
      links: [{ id: 'next', from: 'n1', to: 'n2', kind: 'next' }],
      pointers: [{ id: 'head', label: 'head', targetId: 'n1' }],
    },
    initialState: { pointers: { head: 'n1' } },
    frames: [{ id: 'f1', title: '移动 head', narration: 'head 改为指向第二个节点。', patches: [{ type: 'set_pointer', pointerId: 'head', targetId: 'n2' }] }],
    invariants: [{ type: 'references_resolve' }],
    finalState: { activeIds: ['head', 'n2'], pointers: { head: 'n2' } },
  })
  assert.equal(generated.plannerSucceeded, true)
  assert.equal(generated.spec.semantic.type, 'data_structure')
  if (generated.spec.semantic.type === 'data_structure') assert.equal(generated.spec.semantic.links.length, 1)
  assert.match(generated.artifact.steps[1].text, /指针 head 指向 n2/)
})

test('code trace is inert display data with active line, variable and stack patches', async () => {
  const generated = await generatePlan('animation', '逐行展示变量更新', {
    kind: 'animation', title: '代码追踪', domain: 'computer', abstraction: 'code_trace',
    semantic: {
      type: 'code_trace', language: 'pseudocode',
      lines: [{ id: 'line1', number: 1, text: 'x ← 0' }, { id: 'line2', number: 2, text: 'x ← x + 1' }],
      variables: [{ id: 'x', name: 'x', initialValue: 0 }],
      stackFrames: [{ id: 'main_frame', functionName: 'main', lineId: 'line1' }],
    },
    initialState: { activeLineId: 'line1', values: { x: 0 }, stack: [] },
    frames: [{ id: 'f1', title: '执行第二行', narration: '进入第二行并更新 x。', patches: [{ type: 'set_active_line', lineId: 'line2' }, { type: 'set_variable', variableId: 'x', value: 1 }, { type: 'push_stack', frameId: 'main_frame' }] }],
    invariants: [{ type: 'final_state_value', targetId: 'x', equals: 1 }],
    finalState: { activeIds: ['line2', 'x', 'main_frame'], activeLineId: 'line2', values: { x: 1 }, stack: ['main_frame'] },
  })
  assert.equal(generated.plannerSucceeded, true)
  assert.match(generated.artifact.steps[1].svg, /x = 1/)
  assert.doesNotMatch(generated.artifact.steps[1].svg, /<script/)
})

test('tensor flow validates finite integer shapes and replays shape changes', async () => {
  const generated = await generatePlan('animation', '张量形状从 2×4 变到 2×8', {
    kind: 'animation', title: '张量形状流', domain: 'computer', abstraction: 'tensor_shape_flow',
    semantic: {
      type: 'tensor_shape_flow',
      tensors: [{ id: 'x', label: 'X', shape: [2, 4], dtype: 'float32' }, { id: 'y', label: 'Y', shape: [2, 4], dtype: 'float32' }],
      operations: [{ id: 'linear', label: '线性映射', inputIds: ['x'], outputIds: ['y'] }],
    },
    initialState: { tensorShapes: { y: [2, 4] } },
    frames: [{ id: 'f1', title: '映射输出', narration: '输出最后一维变为 8。', patches: [{ type: 'set_tensor_shape', tensorId: 'y', shape: [2, 8] }] }],
    invariants: [{ type: 'tensor_shape', tensorId: 'y', shape: [2, 8] }],
    finalState: { activeIds: ['y'], tensorShapes: { y: [2, 8] } },
  })
  assert.equal(generated.plannerSucceeded, true)
  assert.match(generated.artifact.steps[1].svg, /2 × 8/)
})

test('probability diagram enforces normalized PMF finite data', async () => {
  const generated = await generatePlan('diagram', '画一个伯努利分布', {
    kind: 'diagram', title: '伯努利分布', domain: 'mathematics', abstraction: 'probability',
    semantic: { type: 'probability', mode: 'pmf', xLabel: 'x', yLabel: 'P(X=x)', samples: [{ id: 'p0', x: 0, y: 0.4 }, { id: 'p1', x: 1, y: 0.6 }] },
    state: {},
  })
  assert.equal(generated.plannerSucceeded, true)
  assert.equal(generated.quality.issues.length, 0)
  assert.match(generated.artifact.steps[0].svg, /PMF/)
})

test('probability animation updates finite samples with a domain-specific patch', async () => {
  const generated = await generatePlan('animation', '展示伯努利分布参数变化', {
    kind: 'animation', title: '伯努利分布变化', domain: 'mathematics', abstraction: 'probability',
    semantic: { type: 'probability', mode: 'pmf', xLabel: 'x', yLabel: 'P(X=x)', samples: [{ id: 'p0', x: 0, y: 0.4 }, { id: 'p1', x: 1, y: 0.6 }] },
    initialState: {},
    frames: [{ id: 'f1', title: '调整概率', narration: '两个有限样本保持归一化。', patches: [{ type: 'set_probability_sample', sampleId: 'p0', y: 0.3 }, { type: 'set_probability_sample', sampleId: 'p1', y: 0.7 }] }],
    invariants: [{ type: 'probability_bounds' }],
    finalState: { activeIds: ['p0', 'p1'], values: { p0: 0.3, p1: 0.7 } },
  })
  assert.equal(generated.plannerSucceeded, true)
  assert.equal(generated.quality.semanticChanges, 1)
  assert.equal(generated.quality.invariants.failures.length, 0)
  assert.match(generated.artifact.steps[1].text, /概率样本 p0 更新为 0.3/)
})

test('typed patches cannot borrow targets or operations from another abstraction', async () => {
  await assert.rejects(() => generatePlan('animation', '演示一次客户端请求', {
    kind: 'animation', title: '错误 patch', domain: 'computer', abstraction: 'protocol_sequence',
    semantic: { type: 'protocol_sequence', participants: [{ id: 'client', label: '客户端' }, { id: 'server', label: '服务端' }], messages: [{ id: 'request', from: 'client', to: 'server', label: '请求', order: 1 }] },
    initialState: {},
    frames: [{ id: 'f1', title: '伪变化', narration: '把参与者误当变量。', patches: [{ type: 'set_variable', variableId: 'client', value: 1 }] }],
    invariants: [{ type: 'references_resolve' }],
    finalState: { activeIds: ['client'], values: { client: 1 } },
  }), /visual_generation_unavailable:.*patch_not_allowed:protocol_sequence.set_variable/)
})

test('mathematical transformation animation uses finite coordinates and parameter patches', async () => {
  const generated = await generatePlan('animation', '展示向量平移', {
    kind: 'animation', title: '向量平移', domain: 'mathematics', abstraction: 'transformation',
    semantic: {
      type: 'transformation', space: 'cartesian',
      objects: [{ id: 'before', label: '变换前', points: [[0, 0], [1, 0]] }, { id: 'after', label: '变换后', points: [[0, 0], [1, 0]] }],
      transforms: [{ id: 'shift', label: '向右上平移', beforeId: 'before', afterId: 'after', kind: 'translate' }],
      parameters: [{ id: 'distance', label: '位移', value: 0 }],
    },
    initialState: { values: { distance: 0 }, series: { after: [[0, 0], [1, 0]] } },
    frames: [{ id: 'f1', title: '执行平移', narration: '两个端点同时平移。', patches: [{ type: 'set_parameter', parameterId: 'distance', value: 1 }, { type: 'transform_object', objectId: 'after', points: [[1, 1], [2, 1]] }] }],
    invariants: [{ type: 'final_state_value', targetId: 'distance', equals: 1 }],
    finalState: { activeIds: ['distance', 'after'], values: { distance: 1 }, series: { after: [[1, 1], [2, 1]] } },
  })
  assert.equal(generated.plannerSucceeded, true)
  assert.equal(generated.spec.semantic.type, 'transformation')
  assert.equal(replayAnimation(generated.spec as typeof generated.spec & { kind: 'animation' }).semanticChanges, 1)
})

test('derivation animation replaces an expression as inert text', async () => {
  const generated = await generatePlan('animation', '展示交换律推导', {
    kind: 'animation', title: '交换律', domain: 'mathematics', abstraction: 'derivation',
    semantic: { type: 'derivation', steps: [{ id: 's1', expression: 'a + b', relation: 'definition', reason: '起点', changedTerms: [] }, { id: 's2', expression: 'a + b', relation: 'equals', reason: '交换律', changedTerms: ['a', 'b'] }] },
    initialState: { expressions: { s2: 'a + b' } },
    frames: [{ id: 'f1', title: '交换项', narration: '交换加数位置。', patches: [{ type: 'replace_expression', stepId: 's2', expression: 'b + a' }] }],
    invariants: [{ type: 'final_state_active', targetId: 's2' }],
    finalState: { activeIds: ['s2'], expressions: { s2: 'b + a' } },
  })
  assert.equal(generated.plannerSucceeded, true)
  assert.match(generated.artifact.steps[1].svg, /b \+ a/)
})

test('a frame whose patch changes only focus is rejected as a fake animation', async () => {
  await assert.rejects(() => generatePlan('animation', '变量保持不变', {
    kind: 'animation', title: '无变化', domain: 'computer', abstraction: 'code_trace',
    semantic: { type: 'code_trace', language: 'pseudocode', lines: [{ id: 'line1', number: 1, text: 'x ← 1' }], variables: [{ id: 'x', name: 'x', initialValue: 1 }], stackFrames: [] },
    initialState: { values: { x: 1 } },
    frames: [{ id: 'f1', title: '仍为 1', narration: '数值没有变化。', patches: [{ type: 'set_variable', variableId: 'x', value: 1 }] }],
    invariants: [{ type: 'references_resolve' }],
    finalState: { activeIds: ['x'], values: { x: 1 } },
  }), /visual_generation_unavailable:.*(?:frame_without_semantic_change|visual_patch_no_change)/)
})

test('setting a tensor to its declared shape is a no-op even when initialState omits the duplicate value', async () => {
  await assert.rejects(() => generatePlan('animation', '保持张量形状不变', {
    kind: 'animation', title: '无变化张量', domain: 'computer', abstraction: 'tensor_shape_flow',
    semantic: { type: 'tensor_shape_flow', tensors: [{ id: 'x', label: 'X', shape: [2, 4] }, { id: 'y', label: 'Y', shape: [2, 4] }], operations: [{ id: 'copy', label: '复制', inputIds: ['x'], outputIds: ['y'] }] },
    initialState: {},
    frames: [{ id: 'f1', title: '仍为 2×4', narration: '形状没有改变。', patches: [{ type: 'set_tensor_shape', tensorId: 'y', shape: [2, 4] }] }],
    invariants: [{ type: 'tensor_shape', tensorId: 'y', shape: [2, 4] }],
    finalState: { activeIds: ['y'], tensorShapes: { y: [2, 4] } },
  }), /visual_generation_unavailable:.*visual_patch_no_change:set_tensor_shape.y/)
})

test('legacy highlight-only animation deterministically degrades to a diagram', async () => {
  const generated = await generatePlan('animation', '旧版流程', {
    version: 'learnflow.visual.v1', kind: 'animation', title: '旧版流程', domain: 'computer', abstraction: 'sequence',
    nodes: [{ id: 'a', label: 'A', role: 'input', shape: 'card', column: 0, lane: 0 }, { id: 'b', label: 'B', role: 'output', shape: 'card', column: 1, lane: 0 }],
    relations: [{ id: 'r1', from: 'a', to: 'b', kind: 'flow' }],
    frames: [{ id: 'f1', title: '高亮', narration: '只高亮', activeNodeIds: ['a', 'b'], activeRelationIds: ['r1'] }],
  })
  assert.equal(generated.plannerSucceeded, false)
  assert.equal(generated.spec.kind, 'diagram')
  assert.equal(generated.artifact.kind, 'image')
  assert.equal(generated.artifact.degraded, true)
  assert.equal(generated.artifact.degradedTo, 'diagram')
  assert.match(generated.artifact.modelError || '', /typed_semantic_patches/)
})

test('legacy image, static and animation specs remain readable without semantic invention', () => {
  const base = {
    version: 'learnflow.visual.v1', title: '旧图', domain: 'general', abstraction: 'concept_map',
    nodes: [{ id: 'a', label: 'A', role: 'concept', shape: 'card', column: 0, lane: 0 }], relations: [], frames: [],
  }
  for (const kind of ['image', 'static']) {
    const spec = readLearningVisualSpec({ ...base, kind }, 'diagram', '旧图')
    assert.equal(spec.version, 'learnflow.visual.v1')
    assert.equal(spec.kind, 'diagram')
    const { artifact } = visualSpecToArtifact(spec)
    assert.equal(artifact.kind, 'image')
    assert.equal(artifact.replay.spec.version, 'learnflow.visual.v1')
  }
  const animation = readLearningVisualSpec({ ...base, kind: 'animation', frames: [{ id: 'f1', title: '帧1', narration: '旧高亮', activeNodeIds: ['a'], activeRelationIds: [] }] }, 'animation', '旧动画')
  const { artifact } = visualSpecToArtifact(animation)
  assert.equal(artifact.kind, 'image')
  assert.equal(artifact.degradedTo, 'storyboard')
  assert.equal(artifact.steps.length, 1)
})

test('dangling references are rejected instead of filtered or auto-connected', async () => {
  assert.throws(() => readLearningVisualSpec({
    version: 'learnflow.visual.v1', kind: 'diagram', title: '坏图', nodes: [{ id: 'a', label: 'A' }],
    relations: [{ id: 'r1', from: 'a', to: 'missing', kind: 'flow' }], frames: [],
  }, 'diagram', '坏图'), /dangling_reference/)

  await assert.rejects(() => generatePlan('diagram', '坏关系', {
    kind: 'diagram', title: '坏关系', domain: 'computer', abstraction: 'system_structure',
    semantic: { type: 'system_structure', entities: [{ id: 'a', label: 'A' }], relations: [{ id: 'r1', from: 'a', to: 'missing', kind: 'flow' }] }, state: {},
  }), /visual_generation_unavailable:.*dangling_reference/)
})

test('missing relations stay missing and are never silently repaired', async () => {
  const generated = await generatePlan('diagram', '三个独立组件', {
    kind: 'diagram', title: '独立组件', domain: 'computer', abstraction: 'system_structure',
    semantic: { type: 'system_structure', entities: [{ id: 'a', label: 'A' }, { id: 'b', label: 'B' }, { id: 'c', label: 'C' }], relations: [] },
    state: {},
  })
  assert.equal(generated.plannerSucceeded, true)
  assert.equal(generated.spec.semantic.type, 'system_structure')
  if (generated.spec.semantic.type === 'system_structure') assert.equal(generated.spec.semantic.relations.length, 0)
  assert.equal(generated.quality.repairs.some(repair => /relation/i.test(repair.code)), false)
  assert.ok(generated.quality.warnings.includes('relations_missing_not_repaired'))
})

test('provider failure uses only a verified deterministic template and otherwise returns no artifact', async () => {
  const tcp = await generateLearningVisual('animation', '逐步演示 TCP 三次握手', async () => { throw new Error('provider timeout') })
  assert.equal(tcp.plannerSucceeded, false)
  assert.equal(tcp.degraded, true)
  assert.equal(tcp.degradedTo, 'deterministic_animation')
  assert.equal(tcp.spec.kind, 'animation')
  assert.match(tcp.modelError || '', /provider timeout/)
  assert.equal(tcp.quality.semanticChanges, 3)

  const federatedDiagram = await generateLearningVisual('diagram', '画一张联邦学习的一轮训练流程图', async () => { throw new Error('provider timeout') })
  assert.equal(federatedDiagram.degradedTo, 'diagram')
  assert.equal(federatedDiagram.spec.semantic.type, 'system_structure')
  if (federatedDiagram.spec.semantic.type === 'system_structure') {
    assert.equal(federatedDiagram.spec.semantic.entities.length, 5)
    assert.equal(federatedDiagram.spec.semantic.relations.length, 5)
  }
  assert.match(federatedDiagram.artifact.steps[0]?.svg || '', /本地数据/)
  assert.match(federatedDiagram.artifact.steps[0]?.svg || '', /聚合服务/)

  const federatedAnimation = await generateLearningVisual('animation', '逐步演示联邦学习的一轮训练', async () => { throw new Error('provider timeout') })
  assert.equal(federatedAnimation.degradedTo, 'deterministic_animation')
  assert.equal(federatedAnimation.spec.kind, 'animation')
  assert.equal(federatedAnimation.quality.semanticChanges, 5)

  await assert.rejects(
    () => generateLearningVisual('animation', '演示一个没有足够事实的主题', async () => { throw new Error('empty model output') }),
    /visual_generation_unavailable:empty model output/,
  )
})

test('degraded generation metadata and provenance survive persisted-spec replay', async () => {
  const generated = await generateLearningVisual('animation', '逐步演示 TCP 三次握手', async () => { throw new Error('planner unavailable') })
  const persistedSpec = JSON.parse(JSON.stringify(generated.artifact.replay.spec))
  const replayed = readLearningVisualSpec(persistedSpec, 'animation', 'this argument must not replace stored provenance')
  const rerendered = visualSpecToArtifact(replayed)

  assert.equal(replayed.generation.plannerSucceeded, false)
  assert.equal(replayed.generation.degraded, true)
  assert.equal(replayed.generation.degradedTo, 'deterministic_animation')
  assert.match(replayed.generation.modelError || '', /planner unavailable/)
  assert.deepEqual(rerendered.artifact.provenance, generated.artifact.provenance)
  assert.equal(rerendered.artifact.plannerSucceeded, false)
  assert.equal(rerendered.artifact.status, 'degraded')
})

test('executable model content and non-finite numeric plans are rejected without a fake fallback', async () => {
  await assert.rejects(() => generateLearningVisual('diagram', '展示函数', async () => JSON.stringify({
    kind: 'diagram', title: '危险', domain: 'mathematics', abstraction: 'derivation',
    semantic: { type: 'derivation', steps: [{ id: 's1', expression: 'eval(x)', relation: 'definition', reason: '', changedTerms: [] }] }, state: {},
  })), /visual_generation_unavailable:.*executable_content_rejected/)

  await assert.rejects(() => generatePlan('diagram', '画函数', {
    kind: 'diagram', title: '超界', domain: 'mathematics', abstraction: 'function',
    semantic: { type: 'function', axes: { xLabel: 'x', yLabel: 'y', xDomain: [-2, 2], yDomain: [0, 4] }, series: [{ id: 'curve', label: 'curve', points: [[0, 0], [1, 1e50]] }], parameters: [] }, state: {},
  }), /visual_generation_unavailable:.*number_invalid/)
})

test('deterministic layout keeps an eight-node gold fixture in bounds without collision', async () => {
  const entities = Array.from({ length: 8 }, (_, index) => ({ id: `n${index}`, label: `节点${index}` }))
  const generated = await generatePlan('diagram', '八个独立节点', {
    kind: 'diagram', title: '八节点布局', domain: 'computer', abstraction: 'system_structure',
    semantic: { type: 'system_structure', entities, relations: [] }, state: {},
  })
  assert.equal(generated.plannerSucceeded, true)
  assert.deepEqual(generated.quality.layout, { collisions: 0, outOfBounds: 0 })
  assert.match(generated.artifact.steps[0].svg, /viewBox="0 0 800 450"/)
})

test('every gold fixture validates, renders and replays without a model or network', () => {
  for (const [name, payload] of Object.entries(GOLD_VISUAL_FIXTURES)) {
    const expectedKind = payload.kind === 'animation' ? 'animation' : 'diagram'
    const spec = readLearningVisualSpec(payload, expectedKind, `gold:${name}`)
    const quality = inspectLearningVisualSpec(spec)
    const rendered = visualSpecToArtifact(spec)

    assert.notEqual(quality.status, 'rejected', name)
    assert.equal(rendered.quality.layout.collisions, 0, name)
    assert.equal(rendered.quality.layout.outOfBounds, 0, name)
    assert.match(rendered.artifact.steps[0].svg, /^<svg/, name)
    if (spec.version === 'learnflow.visual.v2' && spec.kind === 'animation') {
      assert.ok(quality.semanticChanges >= 1, name)
      assert.deepEqual(replayAnimation(spec).finalState, spec.finalState, name)
    }
  }
})

test('a semantic plan that fails the deterministic layout gate is not displayed', async () => {
  const entities = Array.from({ length: 24 }, (_, index) => ({ id: `n${index}`, label: `节点${index}` }))
  await assert.rejects(() => generatePlan('diagram', '画出二十四个系统节点', {
    kind: 'diagram', title: '过密布局', domain: 'computer', abstraction: 'system_structure',
    semantic: { type: 'system_structure', entities, relations: [] }, state: {},
  }), /visual_generation_unavailable:.*visual_spec_quality_gate:layout_collisions/)
})

test('artifact replay survives JSON round-trip with provenance and quality report intact', async () => {
  const generated = await generatePlan('diagram', '静态系统图', {
    kind: 'diagram', title: '系统图', domain: 'computer', abstraction: 'system_structure',
    semantic: { type: 'system_structure', entities: [{ id: 'input', label: '输入' }, { id: 'core', label: '核心' }], relations: [{ id: 'flow', from: 'input', to: 'core', kind: 'flow' }] }, state: {},
  })
  const persisted = JSON.parse(JSON.stringify(generated.artifact)) as typeof generated.artifact
  const replayed = readLearningVisualSpec(persisted.replay.spec, 'diagram', persisted.provenance.requestText)
  const rerendered = visualSpecToArtifact(replayed)
  assert.equal(rerendered.artifact.provenance.requestHash, persisted.provenance.requestHash)
  assert.equal(rerendered.artifact.renderer, persisted.renderer)
  assert.deepEqual(rerendered.quality.layout, persisted.quality.layout)
  assert.equal(rerendered.artifact.readable.summary, persisted.readable.summary)
})

test('a one-node topic anchor is rejected as non-instructional', async () => {
  await assert.rejects(() => generatePlan('diagram', '未知系统主题', {
    kind: 'diagram', title: '未知系统主题', domain: 'computer', abstraction: 'system_structure',
    semantic: { type: 'system_structure', entities: [{ id: 'topic', label: '未知系统主题' }], relations: [] }, state: {},
  }), /visual_generation_unavailable:.*insufficient_semantic_structure/)
})

test('VisualArtifact source exposes keyboard, pause, live frame text and reduced-motion contracts', async () => {
  const source = await readFile(new URL('../src/VisualArtifact.tsx', import.meta.url), 'utf8')
  assert.match(source, /prefers-reduced-motion: reduce/)
  assert.match(source, /onKeyDown=\{handleKeyboard\}/)
  assert.match(source, /aria-live="polite"/)
  assert.match(source, /aria-pressed=\{playing\}/)
  assert.match(source, /暂停/)
  assert.match(source, /nonColorStateCue/)
})
