import assert from 'node:assert/strict'
import test from 'node:test'

import {
  buildAgentProviderRequest,
  runTutorAgentTurn,
  toolCallsFromProviderResponse,
} from './agent-runtime.ts'
import { createInitialLearnerPathState } from '../src/learning-path-graph.ts'

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
