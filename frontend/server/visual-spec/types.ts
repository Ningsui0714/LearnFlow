import type { VisualArtifact, VisualStep } from '../../src/tooling.ts'

export const VISUAL_VERSION = 'learnflow.visual.v2' as const
export const PROMPT_VERSION = 'learnflow.visual-planner.v2' as const
export const RENDERER_VERSION = 'learnflow.deterministic-svg.v2' as const

export type LearningVisualKind = 'diagram' | 'animation'
export type LearningVisualDomain = 'computer' | 'mathematics'
export type ComputerVisualAbstraction =
  | 'protocol_sequence'
  | 'state_machine'
  | 'data_structure'
  | 'code_trace'
  | 'tensor_shape_flow'
  | 'system_structure'
export type MathematicsVisualAbstraction =
  | 'function'
  | 'probability'
  | 'transformation'
  | 'derivation'
  | 'math_structure'
export type LearningVisualAbstraction = ComputerVisualAbstraction | MathematicsVisualAbstraction

export type VisualScalar = string | number | boolean | null
export type VisualPoint = readonly [number, number]

export type ProtocolSequenceSemantic = {
  type: 'protocol_sequence'
  participants: Array<{ id: string; label: string; role?: string }>
  messages: Array<{ id: string; from: string; to: string; label: string; order: number; phase?: string }>
}

export type StateMachineSemantic = {
  type: 'state_machine'
  states: Array<{ id: string; label: string; initial?: boolean; terminal?: boolean }>
  transitions: Array<{ id: string; from: string; to: string; event: string; guard?: string }>
}

export type DataStructureSemantic = {
  type: 'data_structure'
  structure: 'array' | 'linked_list' | 'stack' | 'queue' | 'tree' | 'heap' | 'graph'
  items: Array<{ id: string; label: string; value?: VisualScalar; index?: number }>
  links: Array<{ id: string; from: string; to: string; kind: 'next' | 'left' | 'right' | 'parent' | 'contains' | 'edge' }>
  pointers: Array<{ id: string; label: string; targetId: string | null }>
}

export type CodeTraceSemantic = {
  type: 'code_trace'
  language: 'pseudocode' | 'python' | 'typescript' | 'javascript' | 'java' | 'cpp'
  lines: Array<{ id: string; number: number; text: string }>
  variables: Array<{ id: string; name: string; initialValue: VisualScalar }>
  stackFrames: Array<{ id: string; functionName: string; lineId: string }>
}

export type TensorShapeFlowSemantic = {
  type: 'tensor_shape_flow'
  tensors: Array<{ id: string; label: string; shape: number[]; dtype?: 'bool' | 'int32' | 'int64' | 'float16' | 'float32' | 'float64' }>
  operations: Array<{ id: string; label: string; inputIds: string[]; outputIds: string[] }>
}

export type SystemStructureSemantic = {
  type: 'system_structure'
  entities: Array<{ id: string; label: string; detail?: string; role?: 'input' | 'process' | 'state' | 'output' | 'concept' }>
  relations: Array<{ id: string; from: string; to: string; label?: string; kind: 'flow' | 'dependency' | 'transition' | 'comparison' | 'mapping' }>
}

export type FunctionSemantic = {
  type: 'function'
  axes: { xLabel: string; yLabel: string; xDomain: VisualPoint; yDomain: VisualPoint }
  series: Array<{ id: string; label: string; points: VisualPoint[] }>
  parameters: Array<{ id: string; label: string; value: number }>
}

export type ProbabilitySemantic = {
  type: 'probability'
  mode: 'pmf' | 'pdf' | 'cdf'
  xLabel: string
  yLabel: string
  samples: Array<{ id: string; x: number; y: number; label?: string }>
  highlightedRange?: VisualPoint
}

export type TransformationSemantic = {
  type: 'transformation'
  space: 'number_line' | 'cartesian' | 'vector'
  objects: Array<{ id: string; label: string; points: VisualPoint[] }>
  transforms: Array<{ id: string; label: string; beforeId: string; afterId: string; kind: 'translate' | 'rotate' | 'scale' | 'reflect' | 'linear' }>
  parameters: Array<{ id: string; label: string; value: number }>
}

export type DerivationSemantic = {
  type: 'derivation'
  steps: Array<{ id: string; expression: string; relation: 'equals' | 'implies' | 'approximately' | 'definition'; reason: string; changedTerms: string[] }>
}

export type MathStructureSemantic = {
  type: 'math_structure'
  terms: Array<{ id: string; label: string; detail?: string }>
  relations: Array<{ id: string; from: string; to: string; label?: string }>
}

export type ComputerVisualSemantic =
  | ProtocolSequenceSemantic
  | StateMachineSemantic
  | DataStructureSemantic
  | CodeTraceSemantic
  | TensorShapeFlowSemantic
  | SystemStructureSemantic

export type MathematicsVisualSemantic =
  | FunctionSemantic
  | ProbabilitySemantic
  | TransformationSemantic
  | DerivationSemantic
  | MathStructureSemantic

export type VisualStateSnapshot = {
  activeIds: string[]
  currentStateId?: string
  activeLineId?: string
  values: Record<string, VisualScalar>
  pointers: Record<string, string | null>
  positions: Record<string, VisualPoint>
  tensorShapes: Record<string, number[]>
  expressions: Record<string, string>
  series: Record<string, VisualPoint[]>
  stack: string[]
  emittedMessageIds: string[]
}

export type VisualPatch =
  | { type: 'send_message'; messageId: string }
  | { type: 'transition_state'; transitionId: string; fromStateId: string; toStateId: string }
  | { type: 'move_item'; itemId: string; to: VisualPoint }
  | { type: 'set_pointer'; pointerId: string; targetId: string | null }
  | { type: 'set_active_line'; lineId: string }
  | { type: 'set_variable'; variableId: string; value: VisualScalar }
  | { type: 'push_stack'; frameId: string }
  | { type: 'pop_stack'; frameId: string }
  | { type: 'set_tensor_shape'; tensorId: string; shape: number[] }
  | { type: 'set_parameter'; parameterId: string; value: number }
  | { type: 'set_probability_sample'; sampleId: string; y: number }
  | { type: 'replace_series'; seriesId: string; points: VisualPoint[] }
  | { type: 'transform_object'; objectId: string; points: VisualPoint[] }
  | { type: 'replace_expression'; stepId: string; expression: string }

export type LearningVisualFrame = {
  id: string
  title: string
  narration: string
  durationMs: number
  patches: VisualPatch[]
}

export type VisualInvariant =
  | { type: 'references_resolve' }
  | { type: 'final_state_active'; targetId: string }
  | { type: 'final_state_value'; targetId: string; equals: VisualScalar }
  | { type: 'tensor_shape'; tensorId: string; shape: number[] }
  | { type: 'probability_bounds'; seriesId?: string }
  | { type: 'cdf_monotonic' }

export type VisualRepair = { code: string; path: string; detail: string }

export type VisualGenerationReport = {
  source: 'model_plan' | 'deterministic_template' | 'legacy_reader'
  plannerSucceeded: boolean
  degraded: boolean
  degradedTo?: 'diagram' | 'storyboard' | 'deterministic_animation'
  modelError?: string
  repairs: VisualRepair[]
}

export type VisualProvenance = {
  schemaVersion: typeof VISUAL_VERSION
  promptVersion: typeof PROMPT_VERSION
  rendererVersion: typeof RENDERER_VERSION
  requestHash: string
  requestText: string
}

export type VisualAccessibility = {
  summary: string
  readingOrder: string[]
  nonColorStateCue: string
}

type VisualSpecCommon = {
  version: typeof VISUAL_VERSION
  title: string
  subtitle: string
  explanation: string
  accessibility: VisualAccessibility
  provenance: VisualProvenance
  generation: VisualGenerationReport
}

type DiagramTimeline = { kind: 'diagram'; state: VisualStateSnapshot }
type AnimationTimeline = {
  kind: 'animation'
  initialState: VisualStateSnapshot
  frames: LearningVisualFrame[]
  invariants: VisualInvariant[]
  finalState: VisualStateSnapshot
}

export type ComputerLearningVisualSpec = VisualSpecCommon & { domain: 'computer' } & (
  | { abstraction: 'protocol_sequence'; semantic: ProtocolSequenceSemantic }
  | { abstraction: 'state_machine'; semantic: StateMachineSemantic }
  | { abstraction: 'data_structure'; semantic: DataStructureSemantic }
  | { abstraction: 'code_trace'; semantic: CodeTraceSemantic }
  | { abstraction: 'tensor_shape_flow'; semantic: TensorShapeFlowSemantic }
  | { abstraction: 'system_structure'; semantic: SystemStructureSemantic }
) & (DiagramTimeline | AnimationTimeline)

export type MathematicsLearningVisualSpec = VisualSpecCommon & { domain: 'mathematics' } & (
  | { abstraction: 'function'; semantic: FunctionSemantic }
  | { abstraction: 'probability'; semantic: ProbabilitySemantic }
  | { abstraction: 'transformation'; semantic: TransformationSemantic }
  | { abstraction: 'derivation'; semantic: DerivationSemantic }
  | { abstraction: 'math_structure'; semantic: MathStructureSemantic }
) & (DiagramTimeline | AnimationTimeline)

export type LearningVisualSpec = ComputerLearningVisualSpec | MathematicsLearningVisualSpec

export type LegacyLearningVisualNode = {
  id: string
  label: string
  detail?: string
  role: 'input' | 'process' | 'state' | 'output' | 'concept' | 'formula'
  shape: 'card' | 'circle' | 'capsule'
  column: number
  lane: number
}
export type LegacyLearningVisualRelation = {
  id: string
  from: string
  to: string
  label?: string
  kind: 'flow' | 'dependency' | 'transition' | 'comparison' | 'mapping'
}
export type LegacyLearningVisualFrame = {
  id: string
  title: string
  narration: string
  activeNodeIds: string[]
  activeRelationIds: string[]
}
export type LegacyLearningVisualSpec = {
  version: 'learnflow.visual.v1'
  title: string
  subtitle: string
  domain: 'computer' | 'mathematics' | 'general'
  abstraction: string
  kind: 'diagram' | 'animation'
  nodes: LegacyLearningVisualNode[]
  relations: LegacyLearningVisualRelation[]
  frames: LegacyLearningVisualFrame[]
  explanation: string
  provenance: VisualProvenance
  generation: VisualGenerationReport
}

export type ReadableLearningVisualSpec = LearningVisualSpec | LegacyLearningVisualSpec

export type LearningVisualQuality = {
  score: number
  status: 'passed' | 'degraded' | 'rejected'
  issues: string[]
  warnings: string[]
  repaired: boolean
  repairs: VisualRepair[]
  semanticChanges: number
  invariants: { checked: number; passed: number; failures: string[] }
  layout: { collisions: number; outOfBounds: number }
  security: { executableContentRejected: boolean; finiteDataOnly: boolean }
  replayable: boolean
}

export type ReadableVisualStep = VisualStep & { durationMs?: number; stateDescription?: string }

export type ReplayableVisualArtifact = VisualArtifact & {
  status: 'usable' | 'degraded'
  degraded: boolean
  degradedTo?: VisualGenerationReport['degradedTo']
  modelError?: string
  plannerSucceeded: boolean
  provenance: VisualProvenance
  quality: LearningVisualQuality
  readable: {
    summary: string
    readingOrder: string[]
    frameDescriptions: string[]
    nonColorStateCue: string
  }
  replay: { spec: ReadableLearningVisualSpec; rendererVersion: typeof RENDERER_VERSION }
}

export type GenerateText = (
  instructions: string,
  input: string,
  timeoutMs?: number,
  maxTokens?: number,
) => Promise<string>

export type GeneratedLearningVisual = {
  spec: LearningVisualSpec
  artifact: ReplayableVisualArtifact
  explanation: string
  quality: LearningVisualQuality
  modelError?: string
  plannerSucceeded: boolean
  degraded: boolean
  degradedTo?: VisualGenerationReport['degradedTo']
}
