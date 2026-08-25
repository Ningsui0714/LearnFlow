import assert from 'node:assert/strict'
import test from 'node:test'

import {
  advanceLearningPhase,
  appendLearningEvents,
  createLearningTask,
  hasExplicitLearningIntent,
  isSupportRequest,
  learningTaskTutorContext,
  projectLearningTask,
} from '../src/learning.ts'
import { resolveTutorMode } from '../src/tutor.ts'

test('only an explicit atomic learning request starts guided learning automatically', () => {
  assert.equal(resolveTutorMode('free', '什么是操作系统'), 'simple_explain')
  assert.equal(resolveTutorMode('free', '什么是学习任务'), 'simple_explain')
  assert.equal(resolveTutorMode('free', '带我弄懂操作系统的进程调度'), 'guided_learning')
  assert.equal(hasExplicitLearningIntent('我想了解一下操作系统'), false)
  assert.equal(hasExplicitLearningIntent('带我学习操作系统'), true)
})

test('a learning task starts in the conversation with a deterministic phase and skill', () => {
  const created = createLearningTask('带我写一个二分查找', 100)
  const projection = projectLearningTask(created.task, created.events)
  assert.equal(created.task.objective, '写一个二分查找')
  assert.equal(projection.status, 'active')
  assert.equal(projection.phase, 'learn')
  assert.equal(projection.skillId, 'worked_example_fading')
  assert.equal(projection.eventCount, 4)
})

test('phase movement is queue-driven and never inferred from ordinary learner text', () => {
  const created = createLearningTask('理解闭包', 100)
  const before = projectLearningTask(created.task, created.events)
  const withReply = appendLearningEvents(created.events, created.task.id, [{
    type: 'vnext_learning_task_learner_replied',
    detail: '学生回应',
    phase: before.phase,
  }], 200)
  assert.equal(projectLearningTask(created.task, withReply).phase, 'learn')

  const advanced = advanceLearningPhase(withReply, projectLearningTask(created.task, withReply), 300)
  assert.equal(projectLearningTask(created.task, advanced).phase, 'practice')
})

test('support requests are recognized without becoming an independent attempt', () => {
  assert.equal(isSupportRequest('我不知道，给个提示吧'), true)
  assert.equal(isSupportRequest('我觉得事件循环先执行同步代码'), false)

  const created = createLearningTask('理解事件循环', 100)
  const projection = projectLearningTask(created.task, created.events)
  const events = appendLearningEvents(created.events, created.task.id, [{
    type: 'vnext_learning_support_requested',
    detail: '补充支架',
    phase: projection.phase,
  }], 200)
  const after = projectLearningTask(created.task, events)
  assert.equal(after.phase, 'learn')
  assert.equal(after.supportCount, 1)
  assert.equal(after.learnerReplyCount, 0)
})

test('the model receives a bounded read-only task projection', () => {
  const created = createLearningTask('理解数据库索引', 100)
  const context = learningTaskTutorContext(projectLearningTask(created.task, created.events))
  assert.equal(context.phaseTitle, '建立理解')
  assert.equal(context.phaseCount, 4)
  assert.match(context.skillInstruction, /先直接讲清/)
})
