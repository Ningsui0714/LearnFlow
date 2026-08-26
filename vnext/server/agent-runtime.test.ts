import assert from 'node:assert/strict'
import test from 'node:test'

import {
  buildAgentProviderRequest,
  runTutorAgentTurn,
  toolCallsFromProviderResponse,
  verifyTutorTurnOutcome,
} from './agent-runtime.ts'
import { createInitialLearnerPathState } from '../src/learning-path-graph.ts'
import { executeTutorAgentTool } from './tool-runtime.ts'

test('provider tool calls are normalized for chat completions and responses APIs', () => {
  assert.deepEqual(toolCallsFromProviderResponse({
    choices: [{ message: { tool_calls: [{
      id: 'chat-1', function: { name: 'read_learning_path', arguments: '{"query":"机器学习"}' },
    }] } }],
  }), [{ id: 'chat-1', name: 'read_learning_path', arguments: { query: '机器学习' } }])

  assert.deepEqual(toolCallsFromProviderResponse({
    output: [{ type: 'function_call', call_id: 'responses-1', name: 'read_learner_context', arguments: '{"query":"先修基础"}' }],
  }), [{ id: 'responses-1', name: 'read_learner_context', arguments: { query: '先修基础' } }])
})

test('provider requests expose real tool definitions in both API dialects', () => {
  const tool = {
    name: 'read_learner_context', title: '读取', description: '读取上下文', toolClass: 'perception' as const, risk: 'read_only' as const,
    inputSchema: { type: 'object' as const, properties: {}, additionalProperties: false as const },
  }
  const chat = buildAgentProviderRequest({
    baseUrl: 'https://example.com/v1/chat/completions', model: 'm', instructions: 'system',
    messages: [{ role: 'user', content: 'hello' }], tools: [tool], includeTools: true,
  })
  assert.equal(Array.isArray((chat.body as any).tools), true)
  assert.equal((chat.body as any).tools[0].function.name, 'read_learner_context')

  const responses = buildAgentProviderRequest({
    baseUrl: 'https://example.com/v1/responses', model: 'm', instructions: 'system',
    messages: [{ role: 'user', content: 'hello' }], tools: [tool], includeTools: true,
  })
  assert.equal((responses.body as any).tools[0].name, 'read_learner_context')
})

test('final-state verifier rejects unconfirmed writes, mastery overclaims and hidden failures', () => {
  const proposalRun: any = {
    id: 'path', kind: 'path', status: 'completed', title: '路径', detail: 'proposal', durationMs: 1,
    pathProposal: { id: 'p' },
  }
  assert.deepEqual(verifyTutorTurnOutcome({
    reply: '我已经把这个节点加入个人学习路径。', mode: 'learning_plan', toolRuns: [proposalRun],
  }).violations, ['unconfirmed_path_write_claim'])
  assert.deepEqual(verifyTutorTurnOutcome({
    reply: '这说明你已经完全掌握了哈希表。', mode: 'guided_learning', toolRuns: [],
  }).violations, ['unsupported_mastery_claim'])
  assert.deepEqual(verifyTutorTurnOutcome({
    reply: '下面给出正常答案。', mode: 'free', toolRuns: [{
      id: 'search', kind: 'search', status: 'failed', title: '搜索', detail: '503', durationMs: 1,
    }],
  }).violations, ['hidden_tool_failure'])
  assert.deepEqual(verifyTutorTurnOutcome({
    reply: '我已经按新的信息更新画像，下面继续学习。', mode: 'guided_learning', toolRuns: [],
    observations: [{
      source: 'read_learner_context', authority: 'formal', answerFree: true,
      data: { conflicts: [{ subject: 'tool-calling', text: '旧 Claim 与新自述冲突' }] },
    }],
  }).violations, ['silent_memory_conflict'])
  assert.deepEqual(verifyTutorTurnOutcome({
    reply: '这里有一条新自述和旧 Claim 不一致，需要你确认保留哪一条；本轮不会静默覆盖。',
    mode: 'guided_learning', toolRuns: [],
    observations: [{
      source: 'read_learner_context', authority: 'formal', answerFree: true,
      data: { conflicts: [{ subject: 'tool-calling', text: '旧 Claim 与新自述冲突' }] },
    }],
  }).violations, [])
  const emptyEvidenceObservation: any = [{
    source: 'read_learning_workspace', authority: 'formal', answerFree: true,
    data: { learningEvidence: { manifest: { attempt_count: 0 } } },
  }]
  assert.deepEqual(verifyTutorTurnOutcome({
    reply: '这说明你是第一次正式学习贝叶斯公式。', mode: 'guided_learning', toolRuns: [],
    observations: emptyEvidenceObservation,
  }).violations, ['unsupported_learning_history_claim'])
  assert.deepEqual(verifyTutorTurnOutcome({
    reply: '当前作用域没有可见的练习记录，所以我不会假设你以前是否学过。',
    mode: 'guided_learning', toolRuns: [], observations: emptyEvidenceObservation,
  }).violations, [])
})

test('Tutor runs a bounded observe-act-observe loop and preserves tool results', async () => {
  const requests: any[] = []
  let round = 0
  const result = await runTutorAgentTurn({
    baseUrl: 'https://example.com/v1/chat/completions',
    model: 'test-model',
    mode: 'simple_explain',
    messages: [{ role: 'user', content: '机器学习之前应该先学什么？' }],
    toolChoice: 'auto',
    learnerPathState: createInitialLearnerPathState(),
    generate: async () => 'unused',
    invokeProvider: async request => {
      requests.push(request)
      round += 1
      if (round === 1) {
        return { choices: [{ message: { content: null, tool_calls: [{
          id: 'path-call', type: 'function', function: { name: 'read_learning_path', arguments: '{"query":"机器学习前置"}' },
        }] } }] }
      }
      return { choices: [{ message: { content: '建议先补线性代数、概率统计和 Python，再进入机器学习。' } }] }
    },
  })

  assert.match(result.reply, /线性代数/)
  assert.equal(result.trace.modelRounds, 2)
  assert.equal(result.trace.toolCalls, 2) // observe 阶段的五核 + 模型选择的路径读取
  assert.deepEqual(result.toolRuns.map(run => run.kind), ['memory', 'path'])
  assert.ok(requests[0].body.tools.length >= 3)
  assert.ok(requests[1].body.messages.some((message: any) => message.role === 'tool' && message.tool_call_id === 'path-call'))
})

test('duplicate tool calls are blocked and the model can recover to a final answer', async () => {
  let round = 0
  const result = await runTutorAgentTurn({
    baseUrl: 'https://example.com/v1/chat/completions',
    model: 'test-model',
    mode: 'free',
    messages: [{ role: 'user', content: '帮我看看机器学习路线' }],
    toolChoice: 'auto',
    learnerPathState: createInitialLearnerPathState(),
    generate: async () => 'unused',
    invokeProvider: async () => {
      round += 1
      if (round <= 2) return { choices: [{ message: { tool_calls: [{
        id: `path-${round}`, function: { name: 'read_learning_path', arguments: '{"query":"机器学习路线"}' },
      }] } }] }
      return { choices: [{ message: { content: '我已经依据现有路径整理出前置关系。' } }] }
    },
  })
  assert.match(result.reply, /前置关系/)
  assert.equal(result.toolRuns.filter(run => run.kind === 'path').length, 1)
  assert.ok(result.trace.events.some(event => event.status === 'blocked' && /重复/.test(event.detail)))
})

test('a transient provider failure is retried once inside the shared turn budget', async () => {
  let attempts = 0
  const result = await runTutorAgentTurn({
    baseUrl: 'https://example.com/v1/chat/completions',
    model: 'test-model',
    mode: 'free',
    messages: [{ role: 'user', content: '解释一下哈希表' }],
    toolChoice: 'auto',
    generate: async () => 'unused',
    invokeProvider: async () => {
      attempts += 1
      if (attempts === 1) throw new Error('503 temporary provider failure')
      return { choices: [{ message: { content: '哈希表把键通过哈希函数映射到数组位置。' } }] }
    },
  })
  assert.equal(attempts, 2)
  assert.match(result.reply, /哈希函数/)
  assert.ok(result.trace.events.some(event => event.status === 'retrying'))
})

test('guided turns observe the formal task queue and never expose write tools', async () => {
  const requests: any[] = []
  const result = await runTutorAgentTurn({
    baseUrl: 'https://example.com/v1/chat/completions',
    model: 'test-model',
    mode: 'guided_learning',
    messages: [{ role: 'user', content: '继续学习二分查找' }],
    toolChoice: 'auto',
    taskQueue: [{ id: 7, objective: '实现并解释二分查找', status: 'active', sourceType: 'chat' }],
    knowledgeDomains: [],
    generate: async () => 'unused',
    invokeProvider: async request => {
      requests.push(request)
      return { choices: [{ message: { content: '我们继续围绕循环不变量，用一个最小数组检查边界更新。' } }] }
    },
  })
  assert.deepEqual(result.toolRuns.map(run => run.kind), ['memory', 'workspace'])
  assert.match(result.toolRuns[1].detail, /1 个正式队列任务/)
  const exposed = requests[0].body.tools.map((tool: any) => tool.function.name)
  assert.ok(exposed.includes('read_learning_workspace'))
  assert.ok(!exposed.some((name: string) => /write|update|commit|confirm|create|delete/.test(name)))
})

test('planning final state observes five-kernel, workspace and path without upgrading self report', async () => {
  const requests: any[] = []
  const result = await runTutorAgentTurn({
    baseUrl: 'https://example.com/v1/chat/completions',
    model: 'test-model',
    mode: 'learning_plan',
    messages: [{ role: 'user', content: '我学过机器学习，想规划 Agent 工程路线' }],
    toolChoice: 'auto',
    learnerPathState: createInitialLearnerPathState(),
    formalLearnerContext: {
      snapshot_id: 'snapshot-1',
      kernel_heads: {
        knowledge: { summary: '自述接触过机器学习，尚无独立验证' },
        value: { summary: '希望学习 Agent 工程' },
      },
      items: [], conflicts: [], missing_facets: ['practice.transfer'],
    },
    taskQueue: [],
    knowledgeDomains: [],
    generate: async () => 'unused',
    invokeProvider: async request => {
      requests.push(request)
      return { choices: [{ message: { content: '路线会保留机器学习验证节点，不把“学过”直接当作掌握。' } }] }
    },
  })
  assert.deepEqual(result.toolRuns.map(run => run.kind), ['memory', 'workspace', 'path'])
  assert.match(result.reply, /不把“学过”直接当作掌握/)
  assert.ok(requests[0].body.messages.filter((message: any) => message.role === 'tool').length === 3)
})

test('a path gap is searched and returned as an uncommitted personal-node proposal', async () => {
  const state = createInitialLearnerPathState()
  let round = 0
  const result = await runTutorAgentTurn({
    baseUrl: 'https://example.com/v1/chat/completions',
    model: 'test-model',
    mode: 'learning_plan',
    messages: [{ role: 'user', content: '我想系统学习量子机器学习' }],
    toolChoice: 'auto',
    learnerPathState: state,
    generate: async () => 'unused',
    executeTool: async (name, args, options, meta) => {
      if (name === 'search_computer_knowledge') {
        return {
          run: {
            id: 'search-gap', kind: 'search', toolName: name, toolCallId: meta?.callId,
            status: 'completed', title: '搜索', detail: '找到一条大学课程来源',
            durationMs: 1,
            sources: [{ title: 'QML course', url: 'https://example.edu/qml', snippet: 'course', source: 'University', quality: 'academic', role: 'course', reason: '课程来源' }],
          },
          observation: { authority: 'untrusted_web_evidence_bundle' },
          searchSourceUrls: ['https://example.edu/qml'],
        }
      }
      return executeTutorAgentTool(name, args, options, meta)
    },
    invokeProvider: async () => {
      round += 1
      if (round === 1) return { choices: [{ message: { tool_calls: [{
        id: 'search-qml', function: { name: 'search_computer_knowledge', arguments: '{"query":"量子机器学习 大学课程 前置"}' },
      }] } }] }
      return { choices: [{ message: { content: '现有官方图没有可靠节点；我已形成个人节点提案，只有你确认后才会加入。' } }] }
    },
  })
  const refreshedPath = result.toolRuns.filter(run => run.kind === 'path').at(-1)
  assert.ok(refreshedPath?.pathProposal)
  assert.match(result.reply, /只有你确认后/)
  assert.equal(state.events.some(event => event.type === 'vnext_personal_path_node_added'), false)
})

test('a failed tool is visible and the model can switch observations before answering', async () => {
  let round = 0
  const result = await runTutorAgentTurn({
    baseUrl: 'https://example.com/v1/chat/completions',
    model: 'test-model',
    mode: 'free',
    messages: [{ role: 'user', content: '查一下机器学习路线；如果联网失败就看内置路径' }],
    toolChoice: 'auto',
    learnerPathState: createInitialLearnerPathState(),
    generate: async () => 'unused',
    executeTool: async (name, args, options, meta) => {
      if (name === 'search_computer_knowledge') return {
        run: {
          id: 'failed-search', kind: 'search', toolName: name, toolCallId: meta?.callId,
          status: 'failed', title: '搜索', detail: '503 temporary search failure', errorType: 'transient', durationMs: 1,
        },
        observation: { error: '503 temporary search failure', recoverableByModel: true },
      }
      return executeTutorAgentTool(name, args, options, meta)
    },
    invokeProvider: async () => {
      round += 1
      if (round === 1) return { choices: [{ message: { tool_calls: [{
        id: 'search-fails', function: { name: 'search_computer_knowledge', arguments: '{"query":"机器学习路线"}' },
      }] } }] }
      if (round === 2) return { choices: [{ message: { tool_calls: [{
        id: 'fallback-path', function: { name: 'read_learning_path', arguments: '{"query":"机器学习路线"}' },
      }] } }] }
      return { choices: [{ message: { content: '联网检索暂时失败；下面仅依据内置课程图给出前置关系。' } }] }
    },
  })
  assert.equal(result.toolRuns.find(run => run.kind === 'search')?.status, 'failed')
  assert.equal(result.toolRuns.find(run => run.kind === 'path')?.status, 'completed')
  assert.match(result.reply, /联网检索暂时失败/)
})

test('learner conflicts and project source domains remain observations, never write tools', async () => {
  const requests: any[] = []
  const result = await runTutorAgentTurn({
    baseUrl: 'https://example.com/v1/chat/completions',
    model: 'test-model',
    mode: 'guided_learning',
    messages: [{ role: 'user', content: '继续完成仓库里的 Agent 工具调用章节' }],
    toolChoice: 'auto',
    formalLearnerContext: {
      snapshot_id: 'conflict-snapshot', kernel_heads: {}, items: [],
      conflicts: [{ subject: 'tool-calling', text: '旧 Claim 与本轮自述冲突，等待学习者确认' }],
    },
    taskQueue: [{ id: 8, objective: '完成 Agent 工具调用章节', status: 'active' }],
    formalWorkspaceContext: {
      authority: 'LearningAttempt + scoped project sources',
      scope: { learner_id: 1, project_id: 8, checkpoint_id: 12 },
      recent_attempts: [{
        id: 91, item_type: 'exercise', item_id: 17, attempt_role: 'original',
        status: 'evaluated', outcome: 'failed', assistance_level: 'hint', independent: false,
      }],
      open_remediations: [{
        id: 32, item_type: 'exercise', item_id: 17, status: 'explaining',
        error_class: 'tool_result_handling', misconception_tag: 'ignored_tool_failure',
      }],
      review: {
        summary: { total: 1, due: 1, policy_version: 'review-policy-v1' },
        items: [{ id: 44, item_type: 'exercise', item_id: 17, bucket: 'due' }],
      },
      project_sources: [{ id: 8, type: 'github', role: 'main', status: 'processed' }],
      knowledge_domains: [{
        id: 'repo-agent-tools', title: 'Agent 工具调用', labels: ['tool calling', 'function calling'],
        summary: '来源仓库覆盖工具定义、调用结果和失败恢复。', source_ids: ['source-8'],
      }],
      boundaries: ['有提示成功与独立成功必须区分'],
      manifest: { answer_free: true, read_only: true },
    },
    generate: async () => 'unused',
    invokeProvider: async request => {
      requests.push(request)
      return { choices: [{ message: { content: '我会按仓库覆盖范围继续，并把记忆冲突留给你确认，不会静默覆盖。' } }] }
    },
  })
  const serialized = JSON.stringify(requests[0].body.messages)
  assert.match(serialized, /旧 Claim 与本轮自述冲突/)
  assert.match(serialized, /来源仓库覆盖工具定义/)
  assert.match(serialized, /ignored_tool_failure/)
  assert.match(serialized, /review-policy-v1/)
  assert.match(serialized, /有提示成功与独立成功必须区分/)
  assert.match(serialized, /sourceConstraint/)
  assert.match(serialized, /路线节点必须能由当前来源知识领域支持/)
  assert.match(serialized, /来源覆盖只表示资料包含相关内容/)
  assert.match(result.reply, /不会静默覆盖/)
  const exposed = requests[0].body.tools.map((tool: any) => tool.function.name)
  assert.ok(!exposed.some((name: string) => /write|update|commit|confirm|create|delete/.test(name)))
})
