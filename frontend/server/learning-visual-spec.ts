import {
  VISUAL_VERSION,
  type GenerateText,
  type GeneratedLearningVisual,
  type LearningVisualAbstraction,
  type LearningVisualDomain,
  type LearningVisualKind,
  type LearningVisualSpec,
} from './visual-spec/types.ts'
import {
  buildDeterministicFallback,
  classifyLearningVisual,
  extractJson,
  legacyToSafeDiagram,
  parseLegacySpec,
  parseV2Spec,
} from './visual-spec/validation.ts'
import { inspectLearningVisualSpec } from './visual-spec/runtime.ts'
import { visualSpecToArtifact } from './visual-spec/render.ts'
import { deriveTeachingRequest } from './visual-spec/teaching-compiler.ts'
import { teachingDerivationToSpec } from './visual-spec/teaching-spec.ts'

export * from './visual-spec/types.ts'
export {
  classifyLearningVisual,
  readLearningVisualSpec,
} from './visual-spec/validation.ts'
export {
  describePatch,
  evaluateInvariants,
  inspectLearningVisualSpec,
  probabilityInvariantFailures,
  replayAnimation,
} from './visual-spec/runtime.ts'
export { visualSpecToArtifact } from './visual-spec/render.ts'

function semanticSchemaHint(domain: LearningVisualDomain, abstraction: LearningVisualAbstraction) {
  if (domain === 'computer' && abstraction === 'protocol_sequence') return '{"type":"protocol_sequence","participants":[{"id":"client","label":"客户端"},{"id":"server","label":"服务端"}],"messages":[{"id":"m1","from":"client","to":"server","label":"请求","order":1}]}'
  if (domain === 'computer' && abstraction === 'state_machine') return '{"type":"state_machine","states":[{"id":"idle","label":"空闲","initial":true},{"id":"busy","label":"运行"}],"transitions":[{"id":"start","from":"idle","to":"busy","event":"start"}]}'
  if (domain === 'computer' && abstraction === 'data_structure') return '{"type":"data_structure","structure":"array","items":[{"id":"i0","label":"元素0","index":0}],"links":[],"pointers":[]}'
  if (domain === 'computer' && abstraction === 'code_trace') return '{"type":"code_trace","language":"pseudocode","lines":[{"id":"line1","number":1,"text":"有限的展示文本"}],"variables":[],"stackFrames":[]}'
  if (domain === 'computer' && abstraction === 'tensor_shape_flow') return '{"type":"tensor_shape_flow","tensors":[{"id":"x","label":"X","shape":[2,4]},{"id":"y","label":"Y","shape":[2,8]}],"operations":[{"id":"op","label":"线性映射","inputIds":["x"],"outputIds":["y"]}]}'
  if (domain === 'computer' && abstraction === 'graph_algorithm') return '{"type":"graph_algorithm","id":"graph_trace","algorithm":"dijkstra","directed":true,"nodes":[{"id":"s","label":"S"},{"id":"t","label":"T"}],"edges":[{"id":"e1","from":"s","to":"t","weight":1}],"sourceId":"s","targetId":"t"}'
  if (domain === 'computer' && abstraction === 'event_loop') return '{"type":"event_loop","id":"event_trace","language":"javascript","lines":[{"id":"line_1","number":1,"text":"console.log(\"A\")"}],"operations":[{"id":"sync_1","lineId":"line_1","kind":"sync","output":"A","order":1,"label":"同步输出 A"}]}'
  if (domain === 'computer') return '{"type":"system_structure","entities":[{"id":"input","label":"输入","role":"input"},{"id":"process","label":"处理","role":"process"},{"id":"output","label":"输出","role":"output"}],"relations":[{"id":"input_to_process","from":"input","to":"process","label":"进入","kind":"flow"},{"id":"process_to_output","from":"process","to":"output","label":"产生","kind":"flow"}]}'
  if (abstraction === 'function') return '{"type":"function","axes":{"xLabel":"x","yLabel":"f(x)","xDomain":[-2,2],"yDomain":[-1,4]},"series":[{"id":"curve","label":"有限采样曲线","points":[[-2,4],[0,0],[2,4]]}],"parameters":[]}'
  if (abstraction === 'probability') return '{"type":"probability","mode":"pmf","xLabel":"x","yLabel":"P(X=x)","samples":[{"id":"p0","x":0,"y":0.5},{"id":"p1","x":1,"y":0.5}]}'
  if (abstraction === 'transformation') return '{"type":"transformation","space":"cartesian","objects":[{"id":"before","label":"变换前","points":[[0,0],[1,0]]},{"id":"after","label":"变换后","points":[[1,1],[2,1]]}],"transforms":[{"id":"shift","label":"平移","beforeId":"before","afterId":"after","kind":"translate"}],"parameters":[]}'
  if (abstraction === 'derivation') return '{"type":"derivation","steps":[{"id":"s1","expression":"a + b","relation":"definition","reason":"起点","changedTerms":[]},{"id":"s2","expression":"b + a","relation":"equals","reason":"交换律","changedTerms":["a","b"]}]}'
  if (abstraction === 'matrix_operation') return '{"type":"matrix_operation","id":"matrix_product","operation":"multiply","left":{"id":"matrix_a","label":"A","values":[[1,2]]},"right":{"id":"matrix_b","label":"B","values":[[3],[4]]},"resultId":"matrix_c","focus":{"row":0,"column":0}}'
  if (abstraction === 'natural_frequency') return '{"type":"natural_frequency","id":"natural_frequency","population":10000,"prevalence":0.01,"sensitivity":0.9,"specificity":0.95,"conditionLabel":"患病","positiveLabel":"检测阳性"}'
  if (abstraction === 'optimization') return '{"type":"optimization","id":"optimization_trace","objective":"squared_distance","center":2,"initialX":-2,"learningRate":0.25,"iterations":4,"axes":{"xLabel":"x","yLabel":"f(x)","xDomain":[-3,4],"yDomain":[0,18]}}'
  return '{"type":"math_structure","terms":[{"id":"topic","label":"数学主题"}],"relations":[]}'
}

function visualPlannerPrompt(kind: LearningVisualKind, domain: LearningVisualDomain, abstraction: LearningVisualAbstraction) {
  const timeline = kind === 'diagram'
    ? '图解只能有一个稳定 state，禁止 frames、initialState、finalState。state 使用 activeIds/currentStateId/activeLineId/values/pointers/positions/tensorShapes/expressions/series/stack/emittedMessageIds 的有限 JSON 数据。'
    : '动画必须给出 initialState、1-12 个 frames、invariants、finalState。每帧必须有 patches 且重放后真正改变状态；模型计划禁止 prediction，预测后揭晓只由可重新证明的确定性编译器产生。禁止只给 activeNodeIds/activeRelationIds。patch type 仅允许 send_message、transition_state、move_item、set_pointer、set_active_line、set_variable、push_stack、pop_stack、set_tensor_shape、set_parameter、set_probability_sample、replace_series、transform_object、replace_expression；patch 必须匹配当前 semantic.type，不能跨抽象借用。模型计划不得使用 set_trace_step 或任何可计算 semantic；这些由确定性编译器负责。'
  return `你是 LearnFlow 教学视觉语义规划器。只输出一个 JSON 对象，不输出 SVG、HTML、Mermaid、脚本、代码围栏或可执行表达式。\n\n目标：${kind}\n领域：${domain}\n抽象：${abstraction}\nsemantic 必须严格使用：${semanticSchemaHint(domain, abstraction)}\n\n共同字段：{"version":"${VISUAL_VERSION}","kind":"${kind}","title":"短标题","subtitle":"阅读提示","domain":"${domain}","abstraction":"${abstraction}","semantic":{...},"accessibility":{"summary":"完整文字摘要","readingOrder":["有效对象id"],"nonColorStateCue":"非颜色状态提示"},"explanation":"简短教学说明"}。${timeline}\n\n所有 ID 必须是小写 ASCII 稳定 ID；所有引用必须存在；关系缺失时不得猜测或自动连线。函数、分布和变换只能提供有限数值采样点，不能提供待 eval 的表达式。代码 trace 只是转义后的展示数据，绝不要求执行模型代码。无法确认的数值、关系或中间状态不要编造。`
}

const DETERMINISTIC_ABSTRACTIONS = new Set<LearningVisualAbstraction>([
  'matrix_operation',
  'graph_algorithm',
  'natural_frequency',
  'event_loop',
  'optimization',
])

function assertRequestIntent(
  spec: LearningVisualSpec,
  inferred: { domain: LearningVisualDomain; abstraction: LearningVisualAbstraction },
) {
  if (spec.domain !== inferred.domain || spec.abstraction !== inferred.abstraction) {
    throw new Error(
      `visual_spec_domain_abstraction_mismatch:expected_${inferred.domain}.${inferred.abstraction}:received_${spec.domain}.${spec.abstraction}`,
    )
  }
}

export async function generateLearningVisual(
  kind: LearningVisualKind,
  request: string,
  generate: GenerateText,
): Promise<GeneratedLearningVisual> {
  const inferred = classifyLearningVisual(request)
  const deterministic = deriveTeachingRequest(kind, request)
  if (deterministic) {
    try {
      const compiled = teachingDerivationToSpec(deterministic)
      if (!compiled) throw new Error('visual_deterministic_spec_unsupported')
      const canonical = parseV2Spec(compiled as unknown as Record<string, unknown>, kind, request, { preserveMetadata: true })
      const inspected = inspectLearningVisualSpec(canonical)
      if (inspected.status === 'rejected' || inspected.verification.level !== 'derived_verified' || inspected.score < 85) {
        throw new Error(`visual_deterministic_quality_gate:${inspected.issues.join(',')}`)
      }
      const rendered = visualSpecToArtifact(canonical)
      return {
        spec: canonical,
        artifact: rendered.artifact,
        explanation: canonical.explanation,
        quality: rendered.quality,
        plannerSucceeded: true,
        degraded: false,
      }
    } catch (error) {
      const reason = error instanceof Error ? error.message : 'visual_deterministic_compiler_failed'
      throw new Error(`visual_generation_unavailable:${reason}`)
    }
  }
  if (DETERMINISTIC_ABSTRACTIONS.has(inferred.abstraction)) {
    throw new Error(`visual_generation_unavailable:visual_deterministic_inputs_ambiguous:${inferred.abstraction}`)
  }
  let spec: LearningVisualSpec
  let modelError: string | undefined
  let rendered: ReturnType<typeof visualSpecToArtifact> | undefined
  try {
    const raw = await generate(
      visualPlannerPrompt(kind, inferred.domain, inferred.abstraction),
      `学习者请求：\n${request.slice(0, 2200)}`,
      kind === 'animation' ? 14_000 : 9_000,
      kind === 'animation' ? 2200 : 1700,
    )
    const payload = extractJson(raw)
    if (payload.nodes !== undefined || (Array.isArray(payload.frames) && payload.semantic === undefined)) {
      const legacy = parseLegacySpec(payload, kind, request)
      modelError = kind === 'animation' ? 'animation_requires_typed_semantic_patches' : 'legacy_visual_plan_not_v3'
      spec = legacyToSafeDiagram(legacy, request, modelError)
    } else {
      spec = parseV2Spec(payload, kind, request)
    }
    assertRequestIntent(spec, inferred)
    const inspected = inspectLearningVisualSpec(spec)
    if (inspected.status === 'rejected' || inspected.score < 68) throw new Error(`visual_spec_quality_gate:${inspected.issues.join(',')}`)
    rendered = visualSpecToArtifact(spec)
  } catch (error) {
    modelError = error instanceof Error ? error.message.slice(0, 260) : 'visual_planner_failed'
    try {
      spec = buildDeterministicFallback(kind, request, modelError)
      const inspected = inspectLearningVisualSpec(spec)
      if (inspected.status === 'rejected' || inspected.score < 68) throw new Error(`visual_fallback_quality_gate:${inspected.issues.join(',')}`)
      rendered = visualSpecToArtifact(spec)
    } catch (fallbackError) {
      const fallbackReason = fallbackError instanceof Error ? fallbackError.message : 'visual_fallback_unavailable'
      throw new Error(`visual_generation_unavailable:${modelError};${fallbackReason}`)
    }
  }
  const { artifact, quality } = rendered
  return {
    spec,
    artifact,
    explanation: spec.explanation || (spec.kind === 'animation'
      ? '先查看初始状态，再逐帧核对文字化的状态变更。'
      : '按阅读顺序查看稳定单状态中的对象和已验证关系。'),
    quality,
    modelError: spec.generation.modelError || modelError,
    plannerSucceeded: spec.generation.plannerSucceeded,
    degraded: spec.generation.degraded,
    degradedTo: spec.generation.degradedTo,
  }
}
