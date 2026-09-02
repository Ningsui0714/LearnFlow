import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import test from 'node:test'
import { directLearningTaskDraftRequest } from './agent-runtime.ts'
import { loadLearnFlowPluginRegistry } from './plugin-loader.ts'

const activation = {
  mode: 'learning_plan' as const,
  activePluginIds: ['learning_task_conversion'],
  projectId: 7,
}

function sampleCandidate() {
  return {
    schemaVersion: 'role-learning-task-candidate.v1',
    candidateId: 'ltc_1234567890abcdef',
    requestId: 'request-12345678',
    packageId: 'learnflow-project:7', packageVersion: 'source-set.abc',
    snapshotId: 'source_snapshot_abc', rootHash: 'a'.repeat(64),
    lifecycle: 'candidate', confirmationStatus: 'unconfirmed',
    groundingStatus: 'ungrounded',
    sourceSnapshot: { packageId: 'learnflow-project:7', packageVersion: 'source-set.abc', snapshotId: 'source_snapshot_abc', rootHash: 'a'.repeat(64) },
    sourceBindings: [], citations: [],
    task: {
      title: '部署服务学习型工作任务', workContext: '在实训环境中部署并验收服务。',
      learningObjective: '完成部署并留下可检查证据。', prerequisites: [], estimatedMinutes: 120,
      inputs: [], resources: ['测试服务器'],
      steps: [1, 2, 3].map(index => ({
        id: `step_${index}`, order: index, title: `步骤 ${index}`, action: `执行操作 ${index}`,
        prerequisiteStepIds: index === 1 ? [] : [`step_${index - 1}`], dependencyDerivation: 'provider',
        inputs: [], resources: [], deliverables: [`产物 ${index}`], successCriteria: [`检查 ${index}`],
        safetyRequirements: [], knowledgeTargetIds: [], skillTargetIds: [], citationIds: [],
      })),
      deliverables: ['产物 1', '产物 2', '产物 3'], successCriteria: ['检查 1', '检查 2', '检查 3'], safetyRequirements: [],
    },
    mappings: { knowledgeTargets: [], skillTargets: [], capabilityTargets: [] },
    assessment: { evidenceRequired: ['产物 1'], rubric: [], independentVerification: { required: true } },
    coverage: { partial: false, truncated: false, omitted: 0, source: { truncated: false, omittedSegmentCount: 0 }, task: { truncated: false, omittedStepCount: 0 } },
    warnings: [{ code: 'ungrounded', message: '没有来源片段。' }], assumptions: [],
    validation: { valid: true, issues: [], warnings: [], kernelWrites: 0, masteryChanged: false },
    provenance: { provider: 'xunfei-xingchen', workflowId: 'flow', workflowRunIds: ['run'], kernelTargets: [], masteryUnchanged: true },
  }
}

async function registry() {
  return loadLearnFlowPluginRegistry(resolve(process.cwd(), 'plugins'))
}

test('explicit project plugin request maps directly to the candidate drafting tool', () => {
  assert.deepEqual(
    directLearningTaskDraftRequest(
      ['learning_task_conversion'],
      7,
      '请把“在 Ubuntu 服务器配置 Fail2ban 并完成封禁与解封验收”转化为学习型任务，生成 6 个可验收步骤。',
    ),
    {
      taskTitle: '在 Ubuntu 服务器配置 Fail2ban 并完成封禁与解封验收',
      taskDescription: '请把“在 Ubuntu 服务器配置 Fail2ban 并完成封禁与解封验收”转化为学习型任务，生成 6 个可验收步骤。',
      targetStepCount: 6,
    },
  )
  assert.equal(directLearningTaskDraftRequest([], 7, '生成学习型任务'), undefined)
  assert.equal(directLearningTaskDraftRequest(['learning_task_conversion'], undefined, '生成学习型任务'), undefined)
  assert.equal(directLearningTaskDraftRequest(['learning_task_conversion'], 7, '解释一下学习型任务是什么'), undefined)
})

test('learning-task conversion contributes one artifact tool and four read-only tools', async () => {
  const loaded = await registry()
  const tools = loaded.toolDefinitions(activation).filter(tool => tool.name.startsWith('learning_task_conversion__'))
  assert.deepEqual(tools.map(tool => tool.name), [
    'learning_task_conversion__draft_learning_task',
    'learning_task_conversion__read_learning_task_candidate',
    'learning_task_conversion__inspect_learning_task_evidence',
    'learning_task_conversion__audit_learning_task_candidate',
    'learning_task_conversion__prepare_learning_handoff',
  ])
  assert.equal(tools.filter(tool => tool.risk === 'artifact').length, 1)
  assert.equal(tools.filter(tool => tool.risk === 'read_only').length, 4)
  assert.match(loaded.skillInstructions(activation), /第一步直接调用 learning_task_conversion__draft_learning_task/)
  assert.match(loaded.skillInstructions(activation), /不得声称已进入个性化学习或正式发布/)
})

test('draft tool uses the project-scoped host integration and returns only an unconfirmed candidate', async () => {
  const loaded = await registry()
  const calls: Array<{ operation: string; payload: any }> = []
  const execution = await loaded.execute('learning_task_conversion__draft_learning_task', {
    taskTitle: '部署 Nginx 并验收 HTTPS', targetStepCount: 6,
  }, {
    ...activation,
    scope: { mode: 'learning_plan', conversationId: 'conversation-1', projectId: 7 },
    signal: AbortSignal.timeout(5_000),
    projectIntegration: {
      request: async (operation, payload) => {
        calls.push({ operation, payload })
        return sampleCandidate() as any
      },
    },
  })
  assert.equal(calls.length, 1)
  assert.equal(calls[0].operation, 'create_candidate')
  assert.equal(calls[0].payload.taskTitle, '部署 Nginx 并验收 HTTPS')
  assert.match(calls[0].payload.requestId, /^plugin:7:/)
  assert.equal(execution.result.objects?.[0].objectType, 'learning_task_candidate')
  assert.equal((execution.result.objects?.[0].value as any).lifecycle, 'candidate')
  assert.equal((execution.result.objects?.[0].value as any).confirmationStatus, 'unconfirmed')
  assert.equal((execution.result.payload as any).formalLearningTaskCreated, false)
  assert.equal((execution.result.payload as any).kernelWrites, 0)
  assert.equal(execution.result.presentation?.renderer, 'learning_task_conversion:learning_task_candidate')
})

test('candidate tools are unavailable outside project scope and do not expose transport secrets', async () => {
  const loaded = await registry()
  const noProject = loaded.toolDefinitions({ mode: 'learning_plan', activePluginIds: ['learning_task_conversion'] })
  assert.equal(noProject.some(tool => tool.name.startsWith('learning_task_conversion__')), false)
  const sources = [
    readFileSync(resolve(process.cwd(), 'plugins/learning_task_conversion/runtime.ts'), 'utf8'),
    readFileSync(resolve(process.cwd(), 'plugins/learning_task_conversion/client.tsx'), 'utf8'),
  ].join('\n')
  assert.doesNotMatch(sources, /XFYUN_API_KEY|XFYUN_API_SECRET|Authorization:|requestCookie|backendBase/)
  assert.match(sources, /formalLearningTaskCreated/)
})

test('read-only handoff explicitly remains a Tutor review candidate', async () => {
  const loaded = await registry()
  const candidate = sampleCandidate()
  const handoff = {
    schemaVersion: 'learnflow.personalized-learning-handoff.v1', candidateId: candidate.candidateId,
    status: 'ready_for_tutor_review', consumer: 'Tutor', requiresUserConfirmation: true,
    knowledgeId: '', taskSteps: candidate.task.steps, skills: [], resources: [], citations: [],
    returnContract: { schemaVersion: 'learnflow.personalized-learning-return.v1', allowedActions: ['review'] },
    candidate, validation: candidate.validation,
    instruction: '等待用户确认。', formalLearningTaskCreated: false, kernelWrites: 0,
  }
  const execution = await loaded.execute('learning_task_conversion__prepare_learning_handoff', {
    candidateId: candidate.candidateId,
  }, {
    ...activation,
    scope: { mode: 'learning_plan', projectId: 7 }, signal: AbortSignal.timeout(5_000),
    projectIntegration: { request: async operation => {
      assert.equal(operation, 'prepare_handoff')
      return handoff as any
    } },
  })
  assert.equal((execution.result.objects?.[0].value as any).requiresUserConfirmation, true)
  assert.equal((execution.result.objects?.[0].value as any).formalLearningTaskCreated, false)
  assert.equal((execution.result.objects?.[0].value as any).schemaVersion, 'learnflow.personalized-learning-handoff.v1')
  assert.equal((execution.result.objects?.[0].value as any).taskSteps.length, 3)
  assert.match(execution.result.summary, /用户确认前不会创建正式学习任务/)
})
