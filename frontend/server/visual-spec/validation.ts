import {
  PROMPT_VERSION,
  RENDERER_VERSION,
  VISUAL_VERSION,
  type CodeTraceSemantic,
  type ComputerVisualAbstraction,
  type ComputerVisualSemantic,
  type DataStructureSemantic,
  type DerivationSemantic,
  type FunctionSemantic,
  type LearningVisualAbstraction,
  type LearningVisualDomain,
  type LearningVisualFrame,
  type LearningVisualKind,
  type LearningVisualSpec,
  type LegacyLearningVisualFrame,
  type LegacyLearningVisualNode,
  type LegacyLearningVisualRelation,
  type LegacyLearningVisualSpec,
  type MathematicsVisualAbstraction,
  type MathematicsVisualSemantic,
  type MathStructureSemantic,
  type ProbabilitySemantic,
  type ProtocolSequenceSemantic,
  type ReadableLearningVisualSpec,
  type StateMachineSemantic,
  type SystemStructureSemantic,
  type TensorShapeFlowSemantic,
  type TransformationSemantic,
  type VisualAccessibility,
  type VisualGenerationReport,
  type VisualInvariant,
  type VisualPatch,
  type VisualPoint,
  type VisualProvenance,
  type VisualRepair,
  type VisualScalar,
  type VisualStateSnapshot,
} from './types.ts'

type ParseContext = { repairs: VisualRepair[] }

const MAX_ENTITIES = 24
const MAX_RELATIONS = 32
const MAX_FRAMES = 12
const MAX_PATCHES_PER_FRAME = 8
const MAX_POINTS = 96
const ID_PATTERN = /^[a-z][a-z0-9_-]{0,35}$/
export const FORBIDDEN_EXECUTABLE = /<\/?(?:script|iframe|object|embed|foreignObject)\b|javascript:|data:text\/html|\beval\s*\(|\bnew\s+Function\s*\(|\bFunction\s*\(|\brequire\s*\(|\bimport\s*\(/i

export function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value)
}

function record(value: unknown, path: string): Record<string, unknown> {
  if (!isRecord(value)) throw new Error(`visual_spec_object_required:${path}`)
  return value
}

export function compact(value: unknown, limit: number, context?: ParseContext, path = 'text') {
  const sanitized = String(value ?? '').replace(/<[^>]*>/g, ' ').replace(/\s+/g, ' ').trim()
  if (sanitized.length > limit && context) context.repairs.push({ code: 'text_truncated', path, detail: `kept_first_${limit}_characters` })
  return sanitized.slice(0, limit)
}

function text(value: unknown, path: string, limit: number, context: ParseContext, allowEmpty = false) {
  const output = compact(value, limit, context, path)
  if (!allowEmpty && !output) throw new Error(`visual_spec_text_required:${path}`)
  return output
}

function id(value: unknown, path: string) {
  const output = String(value ?? '').trim()
  if (!ID_PATTERN.test(output)) throw new Error(`visual_spec_id_invalid:${path}`)
  return output
}

function finiteNumber(value: unknown, path: string, min = -1_000_000, max = 1_000_000) {
  const output = typeof value === 'number' ? value : Number(value)
  if (!Number.isFinite(output) || output < min || output > max) throw new Error(`visual_spec_number_invalid:${path}`)
  return output
}

function integer(value: unknown, path: string, min: number, max: number) {
  const output = finiteNumber(value, path, min, max)
  if (!Number.isInteger(output)) throw new Error(`visual_spec_integer_required:${path}`)
  return output
}

function scalar(value: unknown, path: string, context?: ParseContext): VisualScalar {
  if (value === null) return null
  if (typeof value === 'boolean') return value
  if (typeof value === 'number') return finiteNumber(value, path)
  if (typeof value === 'string') return compact(value, 80, context, path)
  throw new Error(`visual_spec_scalar_invalid:${path}`)
}

function point(value: unknown, path: string): VisualPoint {
  if (!Array.isArray(value) || value.length !== 2) throw new Error(`visual_spec_point_invalid:${path}`)
  return [finiteNumber(value[0], `${path}[0]`), finiteNumber(value[1], `${path}[1]`)]
}

function boundedArray(value: unknown, path: string, minimum: number, maximum: number): unknown[] {
  if (!Array.isArray(value)) throw new Error(`visual_spec_array_required:${path}`)
  if (value.length < minimum) throw new Error(`visual_spec_array_too_short:${path}`)
  if (value.length > maximum) throw new Error(`visual_spec_array_too_long:${path}`)
  return value
}

function records(value: unknown, path: string, minimum: number, maximum: number) {
  return boundedArray(value, path, minimum, maximum).map((item, index) => record(item, `${path}[${index}]`))
}

function optionalRecords(value: unknown, path: string, maximum: number) {
  if (value === undefined || value === null) return []
  return records(value, path, 0, maximum)
}

function ids(value: unknown, path: string, maximum = MAX_ENTITIES) {
  return boundedArray(value, path, 0, maximum).map((item, index) => id(item, `${path}[${index}]`))
}

function points(value: unknown, path: string, minimum = 1, maximum = MAX_POINTS) {
  return boundedArray(value, path, minimum, maximum).map((item, index) => point(item, `${path}[${index}]`))
}

function shape(value: unknown, path: string) {
  return boundedArray(value, path, 1, 8).map((item, index) => integer(item, `${path}[${index}]`, 1, 1_000_000))
}

function uniqueIds(items: Array<{ id: string }>, path: string) {
  const seen = new Set<string>()
  for (const item of items) {
    if (seen.has(item.id)) throw new Error(`visual_spec_duplicate_id:${path}.${item.id}`)
    seen.add(item.id)
  }
}

function assertReferences(items: string[], available: Set<string>, path: string) {
  for (const item of items) if (!available.has(item)) throw new Error(`visual_spec_dangling_reference:${path}.${item}`)
}

function hashText(value: string) {
  let hash = 0x811c9dc5
  for (const character of value) {
    hash ^= character.codePointAt(0) || 0
    hash = Math.imul(hash, 0x01000193)
  }
  return `fnv1a-${(hash >>> 0).toString(16).padStart(8, '0')}`
}

export function provenance(request: string): VisualProvenance {
  const requestText = compact(request, 2200)
  return {
    schemaVersion: VISUAL_VERSION,
    promptVersion: PROMPT_VERSION,
    rendererVersion: RENDERER_VERSION,
    requestHash: hashText(requestText),
    requestText,
  }
}

export function emptyState(): VisualStateSnapshot {
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
  }
}

export function cloneState(state: VisualStateSnapshot): VisualStateSnapshot {
  return {
    ...state,
    activeIds: [...state.activeIds],
    values: { ...state.values },
    pointers: { ...state.pointers },
    positions: Object.fromEntries(Object.entries(state.positions).map(([key, value]) => [key, [...value] as VisualPoint])),
    tensorShapes: Object.fromEntries(Object.entries(state.tensorShapes).map(([key, value]) => [key, [...value]])),
    expressions: { ...state.expressions },
    series: Object.fromEntries(Object.entries(state.series).map(([key, value]) => [key, value.map(item => [...item] as VisualPoint)])),
    stack: [...state.stack],
    emittedMessageIds: [...state.emittedMessageIds],
  }
}

function sortedValue(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(sortedValue)
  if (!isRecord(value)) return value
  return Object.fromEntries(Object.keys(value).sort().map(key => [key, sortedValue(value[key])]))
}

export function equivalent(left: unknown, right: unknown) {
  return JSON.stringify(sortedValue(left)) === JSON.stringify(sortedValue(right))
}

export function extractJson(raw: string) {
  const fenced = raw.match(/```(?:json)?\s*([\s\S]*?)```/i)?.[1]
  const source = (fenced || raw).trim()
  const start = source.indexOf('{')
  const end = source.lastIndexOf('}')
  if (start < 0 || end <= start) throw new Error('visual_spec_json_missing')
  const json = source.slice(start, end + 1)
  if (FORBIDDEN_EXECUTABLE.test(json)) throw new Error('visual_spec_executable_content_rejected')
  return record(JSON.parse(json), 'root')
}

function classificationForMath(value: string): MathematicsVisualAbstraction {
  if (/(?:概率|分布|贝叶斯|随机变量|pmf|pdf|cdf|probability)/i.test(value)) return 'probability'
  if (/(?:推导|证明|等式|化简|恒等|derivation|proof)/i.test(value)) return 'derivation'
  if (/(?:变换|矩阵|向量|旋转|平移|缩放|参数变化|线性映射|transform)/i.test(value)) return 'transformation'
  return 'function'
}

export function classifyLearningVisual(query: string):
  | { domain: 'computer'; abstraction: ComputerVisualAbstraction }
  | { domain: 'mathematics'; abstraction: MathematicsVisualAbstraction } {
  const normalized = query.toLowerCase()
  if (/(?:张量|shape|qkv|神经网络|注意力|transformer|tensor)/i.test(normalized)) return { domain: 'computer', abstraction: 'tensor_shape_flow' }
  if (/(?:协议|握手|请求.*响应|客户端|服务端|tcp|http|sequence)/i.test(normalized)) return { domain: 'computer', abstraction: 'protocol_sequence' }
  if (/(?:状态机|状态转移|生命周期|state machine)/i.test(normalized)) return { domain: 'computer', abstraction: 'state_machine' }
  if (/(?:代码执行|逐行|变量变化|调用栈|递归栈|code trace)/i.test(normalized)) return { domain: 'computer', abstraction: 'code_trace' }
  if (/(?:树|链表|栈|队列|堆|数组|数据结构|二分|排序)/i.test(normalized)) return { domain: 'computer', abstraction: 'data_structure' }
  const math = /(?:公式|定理|证明|函数|导数|积分|矩阵|向量|概率|分布|几何|极限|梯度|方程|math|theorem|probability)/i.test(normalized)
  if (math) return { domain: 'mathematics', abstraction: classificationForMath(normalized) }
  return { domain: 'computer', abstraction: 'system_structure' }
}

function parseProtocol(value: unknown, context: ParseContext): ProtocolSequenceSemantic {
  const source = record(value, 'semantic')
  const participants = records(source.participants, 'semantic.participants', 2, 8).map((item, index) => ({
    id: id(item.id, `semantic.participants[${index}].id`),
    label: text(item.label, `semantic.participants[${index}].label`, 32, context),
    role: compact(item.role, 24, context, `semantic.participants[${index}].role`) || undefined,
  }))
  uniqueIds(participants, 'semantic.participants')
  const participantIds = new Set(participants.map(item => item.id))
  const messages = records(source.messages, 'semantic.messages', 1, 16).map((item, index) => ({
    id: id(item.id, `semantic.messages[${index}].id`),
    from: id(item.from, `semantic.messages[${index}].from`),
    to: id(item.to, `semantic.messages[${index}].to`),
    label: text(item.label, `semantic.messages[${index}].label`, 42, context),
    order: integer(item.order, `semantic.messages[${index}].order`, 1, 99),
    phase: compact(item.phase, 28, context, `semantic.messages[${index}].phase`) || undefined,
  }))
  uniqueIds(messages, 'semantic.messages')
  for (const message of messages) assertReferences([message.from, message.to], participantIds, `semantic.messages.${message.id}`)
  if (new Set(messages.map(item => item.order)).size !== messages.length) throw new Error('visual_spec_duplicate_message_order')
  messages.sort((left, right) => left.order - right.order)
  return { type: 'protocol_sequence', participants, messages }
}

function parseStateMachine(value: unknown, context: ParseContext): StateMachineSemantic {
  const source = record(value, 'semantic')
  const states = records(source.states, 'semantic.states', 2, 12).map((item, index) => ({
    id: id(item.id, `semantic.states[${index}].id`),
    label: text(item.label, `semantic.states[${index}].label`, 32, context),
    initial: item.initial === true || undefined,
    terminal: item.terminal === true || undefined,
  }))
  uniqueIds(states, 'semantic.states')
  if (states.filter(item => item.initial).length > 1) throw new Error('visual_spec_multiple_initial_states')
  const stateIds = new Set(states.map(item => item.id))
  const transitions = records(source.transitions, 'semantic.transitions', 1, 20).map((item, index) => ({
    id: id(item.id, `semantic.transitions[${index}].id`),
    from: id(item.from, `semantic.transitions[${index}].from`),
    to: id(item.to, `semantic.transitions[${index}].to`),
    event: text(item.event, `semantic.transitions[${index}].event`, 42, context),
    guard: compact(item.guard, 48, context, `semantic.transitions[${index}].guard`) || undefined,
  }))
  uniqueIds(transitions, 'semantic.transitions')
  for (const transition of transitions) assertReferences([transition.from, transition.to], stateIds, `semantic.transitions.${transition.id}`)
  return { type: 'state_machine', states, transitions }
}

function parseDataStructure(value: unknown, context: ParseContext): DataStructureSemantic {
  const source = record(value, 'semantic')
  const structure = String(source.structure)
  if (!['array', 'linked_list', 'stack', 'queue', 'tree', 'heap', 'graph'].includes(structure)) throw new Error('visual_spec_data_structure_kind_invalid')
  const items = records(source.items, 'semantic.items', 1, 20).map((item, index) => ({
    id: id(item.id, `semantic.items[${index}].id`),
    label: text(item.label, `semantic.items[${index}].label`, 28, context),
    value: item.value === undefined ? undefined : scalar(item.value, `semantic.items[${index}].value`, context),
    index: item.index === undefined ? undefined : integer(item.index, `semantic.items[${index}].index`, -1, 999),
  }))
  uniqueIds(items, 'semantic.items')
  const itemIds = new Set(items.map(item => item.id))
  const links = optionalRecords(source.links, 'semantic.links', 28).map((item, index) => {
    const kind = String(item.kind)
    if (!['next', 'left', 'right', 'parent', 'contains', 'edge'].includes(kind)) throw new Error(`visual_spec_link_kind_invalid:semantic.links[${index}]`)
    const output = {
      id: id(item.id, `semantic.links[${index}].id`),
      from: id(item.from, `semantic.links[${index}].from`),
      to: id(item.to, `semantic.links[${index}].to`),
      kind: kind as DataStructureSemantic['links'][number]['kind'],
    }
    assertReferences([output.from, output.to], itemIds, `semantic.links[${index}]`)
    return output
  })
  uniqueIds(links, 'semantic.links')
  const pointers = optionalRecords(source.pointers, 'semantic.pointers', 12).map((item, index) => {
    const targetId = item.targetId === null || item.targetId === undefined ? null : id(item.targetId, `semantic.pointers[${index}].targetId`)
    if (targetId) assertReferences([targetId], itemIds, `semantic.pointers[${index}]`)
    return { id: id(item.id, `semantic.pointers[${index}].id`), label: text(item.label, `semantic.pointers[${index}].label`, 24, context), targetId }
  })
  uniqueIds(pointers, 'semantic.pointers')
  return { type: 'data_structure', structure: structure as DataStructureSemantic['structure'], items, links, pointers }
}

function parseCodeTrace(value: unknown, context: ParseContext): CodeTraceSemantic {
  const source = record(value, 'semantic')
  const language = String(source.language)
  if (!['pseudocode', 'python', 'typescript', 'javascript', 'java', 'cpp'].includes(language)) throw new Error('visual_spec_code_language_invalid')
  const lines = records(source.lines, 'semantic.lines', 1, 16).map((item, index) => ({
    id: id(item.id, `semantic.lines[${index}].id`),
    number: integer(item.number, `semantic.lines[${index}].number`, 1, 9999),
    text: text(item.text, `semantic.lines[${index}].text`, 100, context),
  }))
  uniqueIds(lines, 'semantic.lines')
  const lineIds = new Set(lines.map(item => item.id))
  const variables = optionalRecords(source.variables, 'semantic.variables', 7).map((item, index) => ({
    id: id(item.id, `semantic.variables[${index}].id`),
    name: text(item.name, `semantic.variables[${index}].name`, 24, context),
    initialValue: scalar(item.initialValue, `semantic.variables[${index}].initialValue`, context),
  }))
  uniqueIds(variables, 'semantic.variables')
  const stackFrames = optionalRecords(source.stackFrames, 'semantic.stackFrames', 12).map((item, index) => {
    const output = {
      id: id(item.id, `semantic.stackFrames[${index}].id`),
      functionName: text(item.functionName, `semantic.stackFrames[${index}].functionName`, 28, context),
      lineId: id(item.lineId, `semantic.stackFrames[${index}].lineId`),
    }
    assertReferences([output.lineId], lineIds, `semantic.stackFrames[${index}]`)
    return output
  })
  uniqueIds(stackFrames, 'semantic.stackFrames')
  return { type: 'code_trace', language: language as CodeTraceSemantic['language'], lines, variables, stackFrames }
}

function parseTensor(value: unknown, context: ParseContext): TensorShapeFlowSemantic {
  const source = record(value, 'semantic')
  const tensors = records(source.tensors, 'semantic.tensors', 2, 16).map((item, index) => {
    const dtype = item.dtype === undefined ? undefined : String(item.dtype)
    if (dtype && !['bool', 'int32', 'int64', 'float16', 'float32', 'float64'].includes(dtype)) throw new Error(`visual_spec_tensor_dtype_invalid:semantic.tensors[${index}]`)
    return {
      id: id(item.id, `semantic.tensors[${index}].id`),
      label: text(item.label, `semantic.tensors[${index}].label`, 28, context),
      shape: shape(item.shape, `semantic.tensors[${index}].shape`),
      dtype: dtype as TensorShapeFlowSemantic['tensors'][number]['dtype'],
    }
  })
  uniqueIds(tensors, 'semantic.tensors')
  const tensorIds = new Set(tensors.map(item => item.id))
  const operations = records(source.operations, 'semantic.operations', 1, 16).map((item, index) => {
    const inputIds = ids(item.inputIds, `semantic.operations[${index}].inputIds`, 8)
    const outputIds = ids(item.outputIds, `semantic.operations[${index}].outputIds`, 8)
    if (!inputIds.length || !outputIds.length) throw new Error(`visual_spec_tensor_operation_io_required:semantic.operations[${index}]`)
    assertReferences([...inputIds, ...outputIds], tensorIds, `semantic.operations[${index}]`)
    return { id: id(item.id, `semantic.operations[${index}].id`), label: text(item.label, `semantic.operations[${index}].label`, 32, context), inputIds, outputIds }
  })
  uniqueIds(operations, 'semantic.operations')
  return { type: 'tensor_shape_flow', tensors, operations }
}

function parseStructure(value: unknown, context: ParseContext): SystemStructureSemantic {
  const source = record(value, 'semantic')
  const entities = records(source.entities, 'semantic.entities', 1, MAX_ENTITIES).map((item, index) => {
    const role = item.role === undefined ? undefined : String(item.role)
    if (role && !['input', 'process', 'state', 'output', 'concept'].includes(role)) throw new Error(`visual_spec_entity_role_invalid:semantic.entities[${index}]`)
    return {
      id: id(item.id, `semantic.entities[${index}].id`),
      label: text(item.label, `semantic.entities[${index}].label`, 32, context),
      detail: compact(item.detail, 56, context, `semantic.entities[${index}].detail`) || undefined,
      role: role as SystemStructureSemantic['entities'][number]['role'],
    }
  })
  uniqueIds(entities, 'semantic.entities')
  const entityIds = new Set(entities.map(item => item.id))
  const relations = optionalRecords(source.relations, 'semantic.relations', MAX_RELATIONS).map((item, index) => {
    const kind = String(item.kind)
    if (!['flow', 'dependency', 'transition', 'comparison', 'mapping'].includes(kind)) throw new Error(`visual_spec_relation_kind_invalid:semantic.relations[${index}]`)
    const output = {
      id: id(item.id, `semantic.relations[${index}].id`),
      from: id(item.from, `semantic.relations[${index}].from`),
      to: id(item.to, `semantic.relations[${index}].to`),
      label: compact(item.label, 32, context, `semantic.relations[${index}].label`) || undefined,
      kind: kind as SystemStructureSemantic['relations'][number]['kind'],
    }
    assertReferences([output.from, output.to], entityIds, `semantic.relations[${index}]`)
    return output
  })
  uniqueIds(relations, 'semantic.relations')
  return { type: 'system_structure', entities, relations }
}

function parseFunction(value: unknown, context: ParseContext): FunctionSemantic {
  const source = record(value, 'semantic')
  const axes = record(source.axes, 'semantic.axes')
  const xDomain = point(axes.xDomain, 'semantic.axes.xDomain')
  const yDomain = point(axes.yDomain, 'semantic.axes.yDomain')
  if (xDomain[0] >= xDomain[1] || yDomain[0] >= yDomain[1]) throw new Error('visual_spec_axis_domain_invalid')
  const series = records(source.series, 'semantic.series', 1, 5).map((item, index) => ({
    id: id(item.id, `semantic.series[${index}].id`),
    label: text(item.label, `semantic.series[${index}].label`, 28, context),
    points: points(item.points, `semantic.series[${index}].points`, 2, MAX_POINTS),
  }))
  uniqueIds(series, 'semantic.series')
  for (const item of series) {
    for (const [x, y] of item.points) {
      if (x < xDomain[0] || x > xDomain[1] || y < yDomain[0] || y > yDomain[1]) {
        throw new Error(`visual_spec_point_outside_domain:semantic.series.${item.id}`)
      }
    }
  }
  const parameters = optionalRecords(source.parameters, 'semantic.parameters', 12).map((item, index) => ({
    id: id(item.id, `semantic.parameters[${index}].id`),
    label: text(item.label, `semantic.parameters[${index}].label`, 24, context),
    value: finiteNumber(item.value, `semantic.parameters[${index}].value`),
  }))
  uniqueIds(parameters, 'semantic.parameters')
  return { type: 'function', axes: { xLabel: text(axes.xLabel, 'semantic.axes.xLabel', 20, context), yLabel: text(axes.yLabel, 'semantic.axes.yLabel', 20, context), xDomain, yDomain }, series, parameters }
}

function parseProbability(value: unknown, context: ParseContext): ProbabilitySemantic {
  const source = record(value, 'semantic')
  const mode = String(source.mode)
  if (!['pmf', 'pdf', 'cdf'].includes(mode)) throw new Error('visual_spec_probability_mode_invalid')
  const samples = records(source.samples, 'semantic.samples', 2, MAX_POINTS).map((item, index) => ({
    id: id(item.id, `semantic.samples[${index}].id`),
    x: finiteNumber(item.x, `semantic.samples[${index}].x`),
    y: finiteNumber(item.y, `semantic.samples[${index}].y`, 0, mode === 'cdf' ? 1 : 1_000_000),
    label: compact(item.label, 20, context, `semantic.samples[${index}].label`) || undefined,
  }))
  uniqueIds(samples, 'semantic.samples')
  samples.sort((left, right) => left.x - right.x)
  const highlightedRange = source.highlightedRange === undefined ? undefined : point(source.highlightedRange, 'semantic.highlightedRange')
  if (highlightedRange && highlightedRange[0] > highlightedRange[1]) throw new Error('visual_spec_probability_range_invalid')
  return { type: 'probability', mode: mode as ProbabilitySemantic['mode'], xLabel: text(source.xLabel, 'semantic.xLabel', 20, context), yLabel: text(source.yLabel, 'semantic.yLabel', 20, context), samples, highlightedRange }
}

function parseTransformation(value: unknown, context: ParseContext): TransformationSemantic {
  const source = record(value, 'semantic')
  const space = String(source.space)
  if (!['number_line', 'cartesian', 'vector'].includes(space)) throw new Error('visual_spec_transformation_space_invalid')
  const objects = records(source.objects, 'semantic.objects', 1, 12).map((item, index) => ({
    id: id(item.id, `semantic.objects[${index}].id`),
    label: text(item.label, `semantic.objects[${index}].label`, 28, context),
    points: points(item.points, `semantic.objects[${index}].points`, 1, 24),
  }))
  uniqueIds(objects, 'semantic.objects')
  const objectIds = new Set(objects.map(item => item.id))
  const transforms = optionalRecords(source.transforms, 'semantic.transforms', 12).map((item, index) => {
    const kind = String(item.kind)
    if (!['translate', 'rotate', 'scale', 'reflect', 'linear'].includes(kind)) throw new Error(`visual_spec_transform_kind_invalid:semantic.transforms[${index}]`)
    const beforeId = id(item.beforeId, `semantic.transforms[${index}].beforeId`)
    const afterId = id(item.afterId, `semantic.transforms[${index}].afterId`)
    assertReferences([beforeId, afterId], objectIds, `semantic.transforms[${index}]`)
    return { id: id(item.id, `semantic.transforms[${index}].id`), label: text(item.label, `semantic.transforms[${index}].label`, 32, context), beforeId, afterId, kind: kind as TransformationSemantic['transforms'][number]['kind'] }
  })
  uniqueIds(transforms, 'semantic.transforms')
  const parameters = optionalRecords(source.parameters, 'semantic.parameters', 12).map((item, index) => ({ id: id(item.id, `semantic.parameters[${index}].id`), label: text(item.label, `semantic.parameters[${index}].label`, 24, context), value: finiteNumber(item.value, `semantic.parameters[${index}].value`) }))
  uniqueIds(parameters, 'semantic.parameters')
  return { type: 'transformation', space: space as TransformationSemantic['space'], objects, transforms, parameters }
}

function parseDerivation(value: unknown, context: ParseContext): DerivationSemantic {
  const source = record(value, 'semantic')
  const steps = records(source.steps, 'semantic.steps', 1, 8).map((item, index) => {
    const relation = String(item.relation)
    if (!['equals', 'implies', 'approximately', 'definition'].includes(relation)) throw new Error(`visual_spec_derivation_relation_invalid:semantic.steps[${index}]`)
    const expression = text(item.expression, `semantic.steps[${index}].expression`, 120, context)
    if (FORBIDDEN_EXECUTABLE.test(expression)) throw new Error(`visual_spec_executable_content_rejected:semantic.steps[${index}].expression`)
    return {
      id: id(item.id, `semantic.steps[${index}].id`),
      expression,
      relation: relation as DerivationSemantic['steps'][number]['relation'],
      reason: text(item.reason, `semantic.steps[${index}].reason`, 80, context, true),
      changedTerms: item.changedTerms === undefined
        ? []
        : boundedArray(item.changedTerms, `semantic.steps[${index}].changedTerms`, 0, 8).map((term, termIndex) => text(term, `semantic.steps[${index}].changedTerms[${termIndex}]`, 32, context)),
    }
  })
  uniqueIds(steps, 'semantic.steps')
  return { type: 'derivation', steps }
}

function parseMathStructure(value: unknown, context: ParseContext): MathStructureSemantic {
  const source = record(value, 'semantic')
  const terms = records(source.terms, 'semantic.terms', 1, MAX_ENTITIES).map((item, index) => ({ id: id(item.id, `semantic.terms[${index}].id`), label: text(item.label, `semantic.terms[${index}].label`, 32, context), detail: compact(item.detail, 56, context, `semantic.terms[${index}].detail`) || undefined }))
  uniqueIds(terms, 'semantic.terms')
  const termIds = new Set(terms.map(item => item.id))
  const relations = optionalRecords(source.relations, 'semantic.relations', MAX_RELATIONS).map((item, index) => {
    const output = { id: id(item.id, `semantic.relations[${index}].id`), from: id(item.from, `semantic.relations[${index}].from`), to: id(item.to, `semantic.relations[${index}].to`), label: compact(item.label, 32, context, `semantic.relations[${index}].label`) || undefined }
    assertReferences([output.from, output.to], termIds, `semantic.relations[${index}]`)
    return output
  })
  uniqueIds(relations, 'semantic.relations')
  return { type: 'math_structure', terms, relations }
}

function parseSemantic(domain: LearningVisualDomain, abstraction: LearningVisualAbstraction, value: unknown, context: ParseContext): ComputerVisualSemantic | MathematicsVisualSemantic {
  if (domain === 'computer') {
    if (abstraction === 'protocol_sequence') return parseProtocol(value, context)
    if (abstraction === 'state_machine') return parseStateMachine(value, context)
    if (abstraction === 'data_structure') return parseDataStructure(value, context)
    if (abstraction === 'code_trace') return parseCodeTrace(value, context)
    if (abstraction === 'tensor_shape_flow') return parseTensor(value, context)
    if (abstraction === 'system_structure') return parseStructure(value, context)
  } else {
    if (abstraction === 'function') return parseFunction(value, context)
    if (abstraction === 'probability') return parseProbability(value, context)
    if (abstraction === 'transformation') return parseTransformation(value, context)
    if (abstraction === 'derivation') return parseDerivation(value, context)
    if (abstraction === 'math_structure') return parseMathStructure(value, context)
  }
  throw new Error(`visual_spec_domain_abstraction_mismatch:${domain}.${abstraction}`)
}

export function entityIdsForSemantic(semantic: ComputerVisualSemantic | MathematicsVisualSemantic) {
  const output = new Set<string>()
  const add = (items: Array<{ id: string }> | undefined) => items?.forEach(item => output.add(item.id))
  switch (semantic.type) {
    case 'protocol_sequence': add(semantic.participants); add(semantic.messages); break
    case 'state_machine': add(semantic.states); add(semantic.transitions); break
    case 'data_structure': add(semantic.items); add(semantic.links); add(semantic.pointers); break
    case 'code_trace': add(semantic.lines); add(semantic.variables); add(semantic.stackFrames); break
    case 'tensor_shape_flow': add(semantic.tensors); add(semantic.operations); break
    case 'system_structure': add(semantic.entities); add(semantic.relations); break
    case 'function': add(semantic.series); add(semantic.parameters); break
    case 'probability': add(semantic.samples); break
    case 'transformation': add(semantic.objects); add(semantic.transforms); add(semantic.parameters); break
    case 'derivation': add(semantic.steps); break
    case 'math_structure': add(semantic.terms); add(semantic.relations); break
  }
  return output
}

function parseMap<T>(value: unknown, path: string, references: Set<string>, parseValue: (value: unknown, path: string) => T): Record<string, T> {
  if (value === undefined) return {}
  const source = record(value, path)
  if (Object.keys(source).length > MAX_ENTITIES) throw new Error(`visual_spec_object_too_large:${path}`)
  return Object.fromEntries(Object.entries(source).map(([key, item]) => {
    const targetId = id(key, `${path}.${key}`)
    assertReferences([targetId], references, path)
    return [targetId, parseValue(item, `${path}.${key}`)]
  }))
}

function parseState(value: unknown, path: string, references: Set<string>, context: ParseContext): VisualStateSnapshot {
  const source = record(value, path)
  const activeIds = source.activeIds === undefined ? [] : ids(source.activeIds, `${path}.activeIds`)
  assertReferences(activeIds, references, `${path}.activeIds`)
  const currentStateId = source.currentStateId === undefined ? undefined : id(source.currentStateId, `${path}.currentStateId`)
  const activeLineId = source.activeLineId === undefined ? undefined : id(source.activeLineId, `${path}.activeLineId`)
  if (currentStateId) assertReferences([currentStateId], references, `${path}.currentStateId`)
  if (activeLineId) assertReferences([activeLineId], references, `${path}.activeLineId`)
  const pointers = parseMap(source.pointers, `${path}.pointers`, references, (item, itemPath) => {
    if (item === null) return null
    const targetId = id(item, itemPath)
    assertReferences([targetId], references, itemPath)
    return targetId
  })
  const stack = source.stack === undefined ? [] : ids(source.stack, `${path}.stack`, 12)
  const emittedMessageIds = source.emittedMessageIds === undefined ? [] : ids(source.emittedMessageIds, `${path}.emittedMessageIds`, 16)
  assertReferences(stack, references, `${path}.stack`)
  assertReferences(emittedMessageIds, references, `${path}.emittedMessageIds`)
  return {
    activeIds,
    currentStateId,
    activeLineId,
    values: parseMap(source.values, `${path}.values`, references, (item, itemPath) => scalar(item, itemPath, context)),
    pointers,
    positions: parseMap(source.positions, `${path}.positions`, references, point),
    tensorShapes: parseMap(source.tensorShapes, `${path}.tensorShapes`, references, shape),
    expressions: parseMap(source.expressions, `${path}.expressions`, references, (item, itemPath) => {
      const expression = text(item, itemPath, 120, context)
      if (FORBIDDEN_EXECUTABLE.test(expression)) throw new Error(`visual_spec_executable_content_rejected:${itemPath}`)
      return expression
    }),
    series: parseMap(source.series, `${path}.series`, references, (item, itemPath) => points(item, itemPath, 1, MAX_POINTS)),
    stack,
    emittedMessageIds,
  }
}

function assertPatchMatchesSemantic(
  patch: VisualPatch,
  semantic: ComputerVisualSemantic | MathematicsVisualSemantic,
  path: string,
) {
  const targetInvalid = (target: string) => { throw new Error(`visual_spec_patch_target_invalid:${path}.${target}`) }
  const notAllowed = () => { throw new Error(`visual_spec_patch_not_allowed:${semantic.type}.${patch.type}`) }
  const has = (items: Array<{ id: string }>, target: string) => items.some(item => item.id === target)

  if (semantic.type === 'protocol_sequence') {
    if (patch.type !== 'send_message') return notAllowed()
    if (!has(semantic.messages, patch.messageId)) targetInvalid(patch.messageId)
    return
  }
  if (semantic.type === 'state_machine') {
    if (patch.type !== 'transition_state') return notAllowed()
    const transition = semantic.transitions.find(item => item.id === patch.transitionId)
    if (!transition || transition.from !== patch.fromStateId || transition.to !== patch.toStateId) targetInvalid(patch.transitionId)
    return
  }
  if (semantic.type === 'data_structure') {
    if (patch.type === 'move_item') {
      if (!has(semantic.items, patch.itemId)) targetInvalid(patch.itemId)
      return
    }
    if (patch.type === 'set_pointer') {
      if (!has(semantic.pointers, patch.pointerId)) targetInvalid(patch.pointerId)
      if (patch.targetId && !has(semantic.items, patch.targetId)) targetInvalid(patch.targetId)
      return
    }
    return notAllowed()
  }
  if (semantic.type === 'code_trace') {
    if (patch.type === 'set_active_line' && has(semantic.lines, patch.lineId)) return
    if (patch.type === 'set_variable' && has(semantic.variables, patch.variableId)) return
    if ((patch.type === 'push_stack' || patch.type === 'pop_stack') && has(semantic.stackFrames, patch.frameId)) return
    if (patch.type === 'set_active_line' || patch.type === 'set_variable' || patch.type === 'push_stack' || patch.type === 'pop_stack') {
      return targetInvalid(patchTargetsForValidation(patch)[0])
    }
    return notAllowed()
  }
  if (semantic.type === 'tensor_shape_flow') {
    if (patch.type !== 'set_tensor_shape') return notAllowed()
    if (!has(semantic.tensors, patch.tensorId)) targetInvalid(patch.tensorId)
    return
  }
  if (semantic.type === 'system_structure') {
    if (patch.type !== 'move_item') return notAllowed()
    if (!has(semantic.entities, patch.itemId)) targetInvalid(patch.itemId)
    return
  }
  if (semantic.type === 'function') {
    if (patch.type === 'set_parameter') {
      if (!has(semantic.parameters, patch.parameterId)) targetInvalid(patch.parameterId)
      return
    }
    if (patch.type === 'replace_series') {
      if (!has(semantic.series, patch.seriesId)) targetInvalid(patch.seriesId)
      for (const [x, y] of patch.points) {
        if (x < semantic.axes.xDomain[0] || x > semantic.axes.xDomain[1] || y < semantic.axes.yDomain[0] || y > semantic.axes.yDomain[1]) {
          throw new Error(`visual_spec_point_outside_domain:${path}.points`)
        }
      }
      return
    }
    return notAllowed()
  }
  if (semantic.type === 'probability') {
    if (patch.type !== 'set_probability_sample') return notAllowed()
    if (!has(semantic.samples, patch.sampleId)) targetInvalid(patch.sampleId)
    if ((semantic.mode === 'pmf' || semantic.mode === 'cdf') && patch.y > 1) throw new Error(`visual_spec_probability_value_invalid:${path}.y`)
    return
  }
  if (semantic.type === 'transformation') {
    if (patch.type === 'set_parameter') {
      if (!has(semantic.parameters, patch.parameterId)) targetInvalid(patch.parameterId)
      return
    }
    if (patch.type === 'transform_object') {
      if (!has(semantic.objects, patch.objectId)) targetInvalid(patch.objectId)
      return
    }
    return notAllowed()
  }
  if (semantic.type === 'derivation') {
    if (patch.type !== 'replace_expression') return notAllowed()
    if (!has(semantic.steps, patch.stepId)) targetInvalid(patch.stepId)
    return
  }
  if (semantic.type === 'math_structure') {
    if (patch.type !== 'move_item') return notAllowed()
    if (!has(semantic.terms, patch.itemId)) targetInvalid(patch.itemId)
  }
}

function patchTargetsForValidation(patch: VisualPatch) {
  if (patch.type === 'set_active_line') return [patch.lineId]
  if (patch.type === 'set_variable') return [patch.variableId]
  if (patch.type === 'push_stack' || patch.type === 'pop_stack') return [patch.frameId]
  return []
}

function parsePatch(
  value: unknown,
  path: string,
  references: Set<string>,
  semantic: ComputerVisualSemantic | MathematicsVisualSemantic,
  context: ParseContext,
): VisualPatch {
  const source = record(value, path)
  const type = String(source.type)
  const ref = (valueToRead: unknown, field: string) => {
    const targetId = id(valueToRead, `${path}.${field}`)
    assertReferences([targetId], references, `${path}.${field}`)
    return targetId
  }
  let patch: VisualPatch | undefined
  if (type === 'send_message') patch = { type, messageId: ref(source.messageId, 'messageId') }
  else if (type === 'transition_state') patch = { type, transitionId: ref(source.transitionId, 'transitionId'), fromStateId: ref(source.fromStateId, 'fromStateId'), toStateId: ref(source.toStateId, 'toStateId') }
  else if (type === 'move_item') patch = { type, itemId: ref(source.itemId, 'itemId'), to: point(source.to, `${path}.to`) }
  else if (type === 'set_pointer') patch = { type, pointerId: ref(source.pointerId, 'pointerId'), targetId: source.targetId === null ? null : ref(source.targetId, 'targetId') }
  else if (type === 'set_active_line') patch = { type, lineId: ref(source.lineId, 'lineId') }
  else if (type === 'set_variable') patch = { type, variableId: ref(source.variableId, 'variableId'), value: scalar(source.value, `${path}.value`, context) }
  else if (type === 'push_stack' || type === 'pop_stack') patch = { type, frameId: ref(source.frameId, 'frameId') }
  else if (type === 'set_tensor_shape') patch = { type, tensorId: ref(source.tensorId, 'tensorId'), shape: shape(source.shape, `${path}.shape`) }
  else if (type === 'set_parameter') patch = { type, parameterId: ref(source.parameterId, 'parameterId'), value: finiteNumber(source.value, `${path}.value`) }
  else if (type === 'set_probability_sample') patch = { type, sampleId: ref(source.sampleId, 'sampleId'), y: finiteNumber(source.y, `${path}.y`, 0, 1_000_000) }
  else if (type === 'replace_series') patch = { type, seriesId: ref(source.seriesId, 'seriesId'), points: points(source.points, `${path}.points`, 2, MAX_POINTS) }
  else if (type === 'transform_object') patch = { type, objectId: ref(source.objectId, 'objectId'), points: points(source.points, `${path}.points`, 1, 24) }
  if (type === 'replace_expression') {
    const expression = text(source.expression, `${path}.expression`, 120, context)
    if (FORBIDDEN_EXECUTABLE.test(expression)) throw new Error(`visual_spec_executable_content_rejected:${path}.expression`)
    patch = { type, stepId: ref(source.stepId, 'stepId'), expression }
  }
  if (!patch) throw new Error(`visual_spec_patch_type_invalid:${path}.${type}`)
  assertPatchMatchesSemantic(patch, semantic, path)
  return patch
}

function parseFrames(value: unknown, references: Set<string>, semantic: ComputerVisualSemantic | MathematicsVisualSemantic, context: ParseContext): LearningVisualFrame[] {
  const output = records(value, 'frames', 1, MAX_FRAMES).map((item, index) => ({
    id: id(item.id, `frames[${index}].id`),
    title: text(item.title, `frames[${index}].title`, 64, context),
    narration: text(item.narration, `frames[${index}].narration`, 220, context),
    durationMs: integer(item.durationMs ?? 1500, `frames[${index}].durationMs`, 250, 10_000),
    patches: records(item.patches, `frames[${index}].patches`, 1, MAX_PATCHES_PER_FRAME).map((patch, patchIndex) => parsePatch(patch, `frames[${index}].patches[${patchIndex}]`, references, semantic, context)),
  }))
  uniqueIds(output, 'frames')
  return output
}

function parseInvariants(value: unknown, references: Set<string>, context: ParseContext): VisualInvariant[] {
  return records(value, 'invariants', 1, 12).map((item, index) => {
    const type = String(item.type)
    const ref = (valueToRead: unknown, field: string) => {
      const targetId = id(valueToRead, `invariants[${index}].${field}`)
      assertReferences([targetId], references, `invariants[${index}].${field}`)
      return targetId
    }
    if (type === 'references_resolve' || type === 'cdf_monotonic') return { type }
    if (type === 'final_state_active') return { type, targetId: ref(item.targetId, 'targetId') }
    if (type === 'final_state_value') return { type, targetId: ref(item.targetId, 'targetId'), equals: scalar(item.equals, `invariants[${index}].equals`, context) }
    if (type === 'tensor_shape') return { type, tensorId: ref(item.tensorId, 'tensorId'), shape: shape(item.shape, `invariants[${index}].shape`) }
    if (type === 'probability_bounds') return { type, seriesId: item.seriesId === undefined ? undefined : ref(item.seriesId, 'seriesId') }
    throw new Error(`visual_spec_invariant_type_invalid:invariants[${index}].${type}`)
  })
}

function readingOrder(semantic: ComputerVisualSemantic | MathematicsVisualSemantic) {
  switch (semantic.type) {
    case 'protocol_sequence': return [...semantic.participants.map(item => item.id), ...semantic.messages.map(item => item.id)]
    case 'state_machine': return [...semantic.states.map(item => item.id), ...semantic.transitions.map(item => item.id)]
    case 'data_structure': return [...semantic.items.map(item => item.id), ...semantic.pointers.map(item => item.id)]
    case 'code_trace': return [...semantic.lines.map(item => item.id), ...semantic.variables.map(item => item.id), ...semantic.stackFrames.map(item => item.id)]
    case 'tensor_shape_flow': return [...semantic.tensors.map(item => item.id), ...semantic.operations.map(item => item.id)]
    case 'system_structure': return semantic.entities.map(item => item.id)
    case 'function': return [...semantic.series.map(item => item.id), ...semantic.parameters.map(item => item.id)]
    case 'probability': return semantic.samples.map(item => item.id)
    case 'transformation': return [...semantic.objects.map(item => item.id), ...semantic.transforms.map(item => item.id)]
    case 'derivation': return semantic.steps.map(item => item.id)
    case 'math_structure': return semantic.terms.map(item => item.id)
  }
}

function parseAccessibility(value: unknown, title: string, semantic: ComputerVisualSemantic | MathematicsVisualSemantic, context: ParseContext): VisualAccessibility {
  const source = value === undefined ? {} : record(value, 'accessibility')
  const references = entityIdsForSemantic(semantic)
  const requestedOrder = source.readingOrder === undefined ? readingOrder(semantic) : ids(source.readingOrder, 'accessibility.readingOrder')
  assertReferences(requestedOrder, references, 'accessibility.readingOrder')
  if (source.summary === undefined) context.repairs.push({ code: 'accessibility_summary_defaulted', path: 'accessibility.summary', detail: 'derived_from_title' })
  return {
    summary: compact(source.summary, 220, context, 'accessibility.summary') || `${title}：按文字顺序阅读视觉对象与状态变化。`,
    readingOrder: requestedOrder,
    nonColorStateCue: compact(source.nonColorStateCue, 160, context, 'accessibility.nonColorStateCue') || '当前状态同时使用“当前”文字、步骤标题和帧说明表示，不只依赖颜色。',
  }
}

export function generationReport(source: VisualGenerationReport['source'], plannerSucceeded: boolean, repairs: VisualRepair[], modelError?: string, degradedTo?: VisualGenerationReport['degradedTo']): VisualGenerationReport {
  return { source, plannerSucceeded, degraded: !plannerSucceeded || Boolean(degradedTo), degradedTo, modelError, repairs }
}

function parseStoredRepairs(value: unknown): VisualRepair[] {
  return optionalRecords(value, 'generation.repairs', 32).map((item, index) => ({
    code: text(item.code, `generation.repairs[${index}].code`, 64, { repairs: [] }),
    path: text(item.path, `generation.repairs[${index}].path`, 120, { repairs: [] }),
    detail: text(item.detail, `generation.repairs[${index}].detail`, 260, { repairs: [] }),
  }))
}

function parseStoredGeneration(value: unknown): VisualGenerationReport {
  const source = record(value, 'generation')
  const origin = String(source.source)
  if (!['model_plan', 'deterministic_template', 'legacy_reader'].includes(origin)) throw new Error('visual_spec_generation_source_invalid')
  if (typeof source.plannerSucceeded !== 'boolean' || typeof source.degraded !== 'boolean') throw new Error('visual_spec_generation_status_invalid')
  const degradedTo = source.degradedTo === undefined ? undefined : String(source.degradedTo)
  if (degradedTo && !['diagram', 'storyboard', 'deterministic_animation'].includes(degradedTo)) throw new Error('visual_spec_generation_degraded_to_invalid')
  const modelError = source.modelError === undefined ? undefined : compact(source.modelError, 260)
  if (source.plannerSucceeded && (source.degraded || degradedTo || modelError || origin !== 'model_plan')) throw new Error('visual_spec_generation_success_claim_invalid')
  if (!source.plannerSucceeded && !source.degraded) throw new Error('visual_spec_generation_failure_claim_invalid')
  if (!source.degraded && degradedTo) throw new Error('visual_spec_generation_degradation_invalid')
  return {
    source: origin as VisualGenerationReport['source'],
    plannerSucceeded: source.plannerSucceeded,
    degraded: source.degraded,
    degradedTo: degradedTo as VisualGenerationReport['degradedTo'],
    modelError,
    repairs: parseStoredRepairs(source.repairs),
  }
}

function parseStoredProvenance(value: unknown): VisualProvenance {
  const source = record(value, 'provenance')
  if (source.schemaVersion !== VISUAL_VERSION || source.promptVersion !== PROMPT_VERSION || source.rendererVersion !== RENDERER_VERSION) {
    throw new Error('visual_spec_provenance_version_invalid')
  }
  const requestText = compact(source.requestText, 2200)
  const requestHash = String(source.requestHash || '')
  if (requestHash !== hashText(requestText)) throw new Error('visual_spec_provenance_hash_mismatch')
  return { schemaVersion: VISUAL_VERSION, promptVersion: PROMPT_VERSION, rendererVersion: RENDERER_VERSION, requestHash, requestText }
}

type ParseSpecOptions = { preserveMetadata?: boolean }

export function parseV2Spec(payload: Record<string, unknown>, requestedKind: LearningVisualKind, request: string, options: ParseSpecOptions = {}): LearningVisualSpec {
  if (payload.version !== undefined && payload.version !== VISUAL_VERSION) throw new Error(`visual_spec_version_unsupported:${String(payload.version)}`)
  if (payload.kind !== undefined && payload.kind !== requestedKind) throw new Error(`visual_spec_kind_mismatch:${String(payload.kind)}`)
  const context: ParseContext = { repairs: [] }
  const storedGeneration = options.preserveMetadata && payload.generation !== undefined ? parseStoredGeneration(payload.generation) : undefined
  if (storedGeneration) context.repairs.push(...storedGeneration.repairs)
  if (options.preserveMetadata && payload.version === undefined) throw new Error('visual_spec_version_required')
  if (options.preserveMetadata && payload.kind === undefined) throw new Error('visual_spec_kind_required')
  if (!options.preserveMetadata && payload.version === undefined) context.repairs.push({ code: 'schema_version_defaulted', path: 'version', detail: VISUAL_VERSION })
  if (!options.preserveMetadata && payload.kind === undefined) context.repairs.push({ code: 'visual_kind_defaulted', path: 'kind', detail: requestedKind })
  if (payload.domain !== 'computer' && payload.domain !== 'mathematics') throw new Error('visual_spec_domain_required')
  if (typeof payload.abstraction !== 'string' || !payload.abstraction) throw new Error('visual_spec_abstraction_required')
  const domain = payload.domain
  const abstraction = payload.abstraction as LearningVisualAbstraction
  const semantic = parseSemantic(domain, abstraction, payload.semantic, context)
  if (semantic.type !== abstraction) throw new Error(`visual_spec_semantic_discriminator_mismatch:${abstraction}.${semantic.type}`)
  const title = compact(payload.title, 100, context, 'title') || compact(request, 72) || '学习视觉'
  const common = {
    version: VISUAL_VERSION,
    title,
    subtitle: compact(payload.subtitle, 180, context, 'subtitle'),
    explanation: compact(payload.explanation, 1800, context, 'explanation'),
    domain,
    abstraction,
    semantic,
    accessibility: parseAccessibility(payload.accessibility, title, semantic, context),
    provenance: options.preserveMetadata && payload.provenance !== undefined ? parseStoredProvenance(payload.provenance) : provenance(request),
    generation: storedGeneration ? { ...storedGeneration, repairs: context.repairs } : generationReport('model_plan', true, context.repairs),
  }
  const references = entityIdsForSemantic(semantic)
  if (requestedKind === 'diagram') {
    if (payload.frames !== undefined || payload.initialState !== undefined || payload.finalState !== undefined || payload.invariants !== undefined) {
      throw new Error('visual_spec_diagram_timeline_forbidden')
    }
    return { ...common, kind: 'diagram', state: parseState(payload.state, 'state', references, context) } as LearningVisualSpec
  }
  if (payload.state !== undefined) throw new Error('visual_spec_animation_stable_state_forbidden')
  return {
    ...common,
    kind: 'animation',
    initialState: parseState(payload.initialState, 'initialState', references, context),
    frames: parseFrames(payload.frames, references, semantic, context),
    invariants: parseInvariants(payload.invariants, references, context),
    finalState: parseState(payload.finalState, 'finalState', references, context),
  } as LearningVisualSpec
}

export function parseLegacySpec(payload: Record<string, unknown>, requestedKind: LearningVisualKind, request: string, options: ParseSpecOptions = {}): LegacyLearningVisualSpec {
  const storedGeneration = options.preserveMetadata && payload.generation !== undefined ? parseStoredGeneration(payload.generation) : undefined
  const context: ParseContext = { repairs: storedGeneration
    ? [...storedGeneration.repairs]
    : [{ code: 'legacy_visual_v1_read', path: 'version', detail: 'preserved_without_semantic_inference' }] }
  const nodes = records(payload.nodes, 'nodes', 1, MAX_ENTITIES).map((node, index) => {
    const role = String(node.role || 'concept')
    const shapeValue = String(node.shape || 'card')
    if (!['input', 'process', 'state', 'output', 'concept', 'formula'].includes(role)) throw new Error(`legacy_visual_role_invalid:nodes[${index}]`)
    if (!['card', 'circle', 'capsule'].includes(shapeValue)) throw new Error(`legacy_visual_shape_invalid:nodes[${index}]`)
    return {
      id: id(node.id, `nodes[${index}].id`),
      label: text(node.label, `nodes[${index}].label`, 32, context),
      detail: compact(node.detail, 56, context, `nodes[${index}].detail`) || undefined,
      role: role as LegacyLearningVisualNode['role'],
      shape: shapeValue as LegacyLearningVisualNode['shape'],
      column: integer(node.column ?? index, `nodes[${index}].column`, 0, 31),
      lane: integer(node.lane ?? 0, `nodes[${index}].lane`, 0, 15),
    }
  })
  uniqueIds(nodes, 'nodes')
  const nodeIds = new Set(nodes.map(item => item.id))
  const relations = optionalRecords(payload.relations, 'relations', MAX_RELATIONS).map((relation, index) => {
    const kind = String(relation.kind || 'flow')
    if (!['flow', 'dependency', 'transition', 'comparison', 'mapping'].includes(kind)) throw new Error(`legacy_visual_relation_kind_invalid:relations[${index}]`)
    const output = { id: id(relation.id, `relations[${index}].id`), from: id(relation.from, `relations[${index}].from`), to: id(relation.to, `relations[${index}].to`), label: compact(relation.label, 32, context, `relations[${index}].label`) || undefined, kind: kind as LegacyLearningVisualRelation['kind'] }
    assertReferences([output.from, output.to], nodeIds, `relations[${index}]`)
    return output
  })
  uniqueIds(relations, 'relations')
  const relationIds = new Set(relations.map(item => item.id))
  const frames = optionalRecords(payload.frames, 'frames', 16).map((frame, index) => {
    const activeNodeIds = frame.activeNodeIds === undefined ? [] : ids(frame.activeNodeIds, `frames[${index}].activeNodeIds`)
    const activeRelationIds = frame.activeRelationIds === undefined ? [] : ids(frame.activeRelationIds, `frames[${index}].activeRelationIds`)
    assertReferences(activeNodeIds, nodeIds, `frames[${index}].activeNodeIds`)
    assertReferences(activeRelationIds, relationIds, `frames[${index}].activeRelationIds`)
    return { id: id(frame.id, `frames[${index}].id`), title: text(frame.title, `frames[${index}].title`, 64, context), narration: text(frame.narration, `frames[${index}].narration`, 220, context, true), activeNodeIds, activeRelationIds } as LegacyLearningVisualFrame
  })
  const rawKind = String(payload.kind || requestedKind)
  const kind = rawKind === 'animation' ? 'animation' : 'diagram'
  const rawDomain = String(payload.domain || 'general')
  const domain = rawDomain === 'computer' || rawDomain === 'mathematics' ? rawDomain : 'general'
  return {
    version: 'learnflow.visual.v1',
    title: compact(payload.title, 100, context, 'title') || compact(request, 72) || '旧版学习视觉',
    subtitle: compact(payload.subtitle, 180, context, 'subtitle'),
    domain,
    abstraction: compact(payload.abstraction, 48) || 'legacy_graph',
    kind,
    nodes,
    relations,
    frames,
    explanation: compact(payload.explanation, 1800, context, 'explanation'),
    provenance: options.preserveMetadata && payload.provenance !== undefined ? parseStoredProvenance(payload.provenance) : provenance(request),
    generation: storedGeneration
      ? { ...storedGeneration, repairs: context.repairs }
      : generationReport('legacy_reader', false, context.repairs, kind === 'animation' ? 'legacy_highlight_only_animation' : 'legacy_visual_v1', kind === 'animation' ? 'storyboard' : 'diagram'),
  }
}

export function readLearningVisualSpec(value: unknown, requestedKind: LearningVisualKind = 'diagram', request = ''): ReadableLearningVisualSpec {
  const payload = record(value, 'root')
  if (payload.version === VISUAL_VERSION || payload.semantic !== undefined) return parseV2Spec(payload, requestedKind, request, { preserveMetadata: true })
  if (payload.nodes !== undefined) return parseLegacySpec(payload, requestedKind, request, { preserveMetadata: true })
  throw new Error('visual_spec_reader_unsupported')
}

export function legacyToSafeDiagram(legacy: LegacyLearningVisualSpec, request: string, modelError: string): LearningVisualSpec {
  const common = {
    version: VISUAL_VERSION,
    title: legacy.title,
    subtitle: legacy.subtitle,
    explanation: legacy.explanation,
    state: emptyState(),
    provenance: provenance(request),
    generation: generationReport('legacy_reader', false, [...legacy.generation.repairs, { code: 'legacy_animation_degraded', path: 'frames', detail: 'highlight_only_frames_cannot_claim_state_change' }], modelError, 'diagram'),
  }
  if (legacy.domain === 'mathematics') {
    const semantic: MathStructureSemantic = { type: 'math_structure', terms: legacy.nodes.map(node => ({ id: node.id, label: node.label, detail: node.detail })), relations: legacy.relations.map(relation => ({ id: relation.id, from: relation.from, to: relation.to, label: relation.label })) }
    return { ...common, kind: 'diagram', domain: 'mathematics', abstraction: 'math_structure', semantic, accessibility: { summary: `${legacy.title}：旧版视觉已按静态关系安全呈现。`, readingOrder: semantic.terms.map(item => item.id), nonColorStateCue: '旧版高亮不被视为状态变化，当前内容已降级为静态图解。' } }
  }
  const semantic: SystemStructureSemantic = { type: 'system_structure', entities: legacy.nodes.map(node => ({ id: node.id, label: node.label, detail: node.detail, role: node.role === 'formula' ? 'concept' : node.role })), relations: legacy.relations }
  return { ...common, kind: 'diagram', domain: 'computer', abstraction: 'system_structure', semantic, accessibility: { summary: `${legacy.title}：旧版视觉已按静态关系安全呈现。`, readingOrder: semantic.entities.map(item => item.id), nonColorStateCue: '旧版高亮不被视为状态变化，当前内容已降级为静态图解。' } }
}

function topicLabel(request: string) {
  return compact(request.replace(/^(?:请|帮我|给我|画|生成|演示|解释|讲解|用图解|用动画)+/i, ''), 46) || '当前学习主题'
}

function topicDiagram(request: string, modelError: string): LearningVisualSpec {
  const classification = classifyLearningVisual(request)
  const common = {
    version: VISUAL_VERSION,
    kind: 'diagram' as const,
    title: compact(request, 72) || '学习图解',
    subtitle: '确定性安全降级：仅保留可确认的主题，不补造关系或数值。',
    explanation: '视觉规划未通过语义门。本图只保留原请求中的主题锚点，避免把猜测画成事实。',
    state: emptyState(),
    provenance: provenance(request),
    generation: generationReport('deterministic_template', false, [{ code: 'model_plan_rejected', path: 'root', detail: modelError }], modelError, 'diagram'),
  }
  if (classification.domain === 'mathematics') {
    const semantic: MathStructureSemantic = { type: 'math_structure', terms: [{ id: 'topic', label: topicLabel(request) }], relations: [] }
    return { ...common, domain: 'mathematics', abstraction: 'math_structure', semantic, accessibility: { summary: `${common.title}。当前仅保留数学主题锚点，未生成未经验证的函数、分布或推导。`, readingOrder: ['topic'], nonColorStateCue: '此产物已明确标记为静态降级图解。' } }
  }
  const semantic: SystemStructureSemantic = { type: 'system_structure', entities: [{ id: 'topic', label: topicLabel(request), role: 'concept' }], relations: [] }
  return { ...common, domain: 'computer', abstraction: 'system_structure', semantic, accessibility: { summary: `${common.title}。当前仅保留计算机主题锚点，未补造数据流、状态或协议关系。`, readingOrder: ['topic'], nonColorStateCue: '此产物已明确标记为静态降级图解。' } }
}

function tcpAnimation(request: string, modelError: string): LearningVisualSpec {
  const semantic: ProtocolSequenceSemantic = {
    type: 'protocol_sequence',
    participants: [{ id: 'client', label: '客户端', role: '主动打开' }, { id: 'server', label: '服务端', role: '监听端' }],
    messages: [
      { id: 'syn', from: 'client', to: 'server', label: 'SYN', order: 1, phase: '发起同步' },
      { id: 'syn_ack', from: 'server', to: 'client', label: 'SYN + ACK', order: 2, phase: '确认并同步' },
      { id: 'ack', from: 'client', to: 'server', label: 'ACK', order: 3, phase: '最终确认' },
    ],
  }
  const initialState = emptyState()
  const frames: LearningVisualFrame[] = semantic.messages.map((message, index) => ({ id: `frame_${index + 1}`, title: `第 ${index + 1} 步：${message.label}`, narration: `${semantic.participants.find(item => item.id === message.from)?.label}发送 ${message.label}，${message.phase}。`, durationMs: 1500, patches: [{ type: 'send_message', messageId: message.id }] }))
  const finalState = cloneState(initialState)
  finalState.emittedMessageIds = semantic.messages.map(item => item.id)
  finalState.activeIds = ['ack']
  return {
    version: VISUAL_VERSION,
    kind: 'animation',
    title: 'TCP 三次握手',
    subtitle: '逐条消息确认双方的收发能力',
    domain: 'computer',
    abstraction: 'protocol_sequence',
    semantic,
    initialState,
    frames,
    invariants: [{ type: 'references_resolve' }, { type: 'final_state_active', targetId: 'ack' }],
    finalState,
    explanation: '先查看初始状态，再逐帧核对消息方向、顺序与文字状态。',
    accessibility: { summary: '客户端与服务端通过 SYN、SYN 加 ACK、ACK 三条有序消息建立连接。', readingOrder: ['client', 'server', 'syn', 'syn_ack', 'ack'], nonColorStateCue: '当前消息同时显示序号、方向、消息名和“当前步骤”文字。' },
    provenance: provenance(request),
    generation: generationReport('deterministic_template', false, [{ code: 'model_plan_rejected', path: 'root', detail: modelError }], modelError, 'deterministic_animation'),
  }
}

export function buildDeterministicFallback(kind: LearningVisualKind, request: string, modelError: string): LearningVisualSpec {
  if (kind === 'animation' && /(?:tcp|三次握手)/i.test(request)) return tcpAnimation(request, modelError)
  return topicDiagram(request, modelError)
}
