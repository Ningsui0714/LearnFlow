import assert from 'node:assert/strict'
import test from 'node:test'

import {
  advanceLearningSkillStep,
  appendLearningEvents,
  canAdvanceLearningSkillStep,
  createLearningTask,
  currentLearningSkillStep,
  hasExplicitLearningIntent,
  isSupportRequest,
  LEARNING_SKILLS,
  learningTaskTutorContext,
  loopLearningSkillStep,
  projectLearningTask,
  switchLearningSkill,
  type LearningSkillId,
  type LearningTask,
} from '../src/learning.ts'
import { isDisplayableTutorReply, resolveTutorMode } from '../src/tutor.ts'

test('internal provider tool protocols are never treated as Tutor teaching text', () => {
  assert.equal(isDisplayableTutorReply('先建立直觉：朴素贝叶斯会比较各类别的后验概率。'), true)
  assert.equal(isDisplayableTutorReply('<tool_call><function=trigger_start_learning></function></tool_call>'), false)
})

test('only an explicit atomic learning request starts guided learning automatically', () => {
  assert.equal(resolveTutorMode('free', '什么是操作系统'), 'simple_explain')
  assert.equal(resolveTutorMode('free', '什么是学习任务'), 'simple_explain')
  assert.equal(resolveTutorMode('free', '带我弄懂操作系统的进程调度'), 'guided_learning')
  assert.equal(resolveTutorMode('free', '我想用半年系统学习操作系统并做一个内核项目'), 'learning_plan')
  assert.equal(resolveTutorMode('free', '我未来适合走智能体工程还是机器学习科研方向'), 'learning_plan')
  assert.equal(hasExplicitLearningIntent('我想了解一下操作系统'), false)
  assert.equal(hasExplicitLearningIntent('带我学习操作系统'), true)
})

test('a task starts at the recommended skill own first step', () => {
  const created = createLearningTask('带我写一个二分查找', 100)
  const projection = projectLearningTask(created.task, created.events)
  assert.equal(created.task.objective, '写一个二分查找')
  assert.equal(projection.status, 'active')
  assert.equal(projection.skillId, 'worked_example_fading')
  assert.equal(projection.stepId, 'worked_example')
  assert.equal(projection.stepIndex, 0)
  assert.equal(projection.eventCount, 4)
})

test('each learning skill owns a distinct deterministic flow', () => {
  const skillIds = Object.keys(LEARNING_SKILLS) as LearningSkillId[]
  const paths = skillIds.map(skillId => LEARNING_SKILLS[skillId].steps.map(step => step.id).join('>'))
  assert.equal(new Set(paths).size, skillIds.length)
  assert.equal(skillIds.every(skillId => LEARNING_SKILLS[skillId].boundState === 'guided_learning'), true)
  assert.equal(skillIds.every(skillId => LEARNING_SKILLS[skillId].steps.every(
    step => Boolean(step.substateId && step.substateLabel.endsWith('态')),
  )), true)
  assert.deepEqual(LEARNING_SKILLS.guided_explanation.steps.map(step => step.id), [
    'anchor_model', 'inspect_example', 'learner_explain', 'transfer_check',
  ])
  assert.deepEqual(LEARNING_SKILLS.socratic_dialogue.steps.map(step => step.id), [
    'ground_context', 'hypothesis', 'probe_reason', 'test_boundary', 'synthesize_reasoning',
  ])
  assert.deepEqual(LEARNING_SKILLS.feynman_dialogue.steps.map(step => step.id), [
    'knowledge_anchor', 'first_teachback', 'diagnose_gap', 'revised_teachback', 'example_or_boundary',
  ])
  assert.deepEqual(LEARNING_SKILLS.worked_example_fading.steps.map(step => step.id), [
    'worked_example', 'complete_last_step', 'complete_middle_step', 'independent_problem', 'reflect_strategy',
  ])
})

test('an explicitly selected skill binds the next guided task and exposes its substate', () => {
  const created = createLearningTask('理解朴素贝叶斯', 100, [], 'feynman_dialogue')
  const projection = projectLearningTask(created.task, created.events)
  const context = learningTaskTutorContext(projection)

  assert.equal(projection.skillId, 'feynman_dialogue')
  assert.equal(context.substateId, 'guidance')
  assert.equal(context.substateLabel, '引导态')
  assert.match(created.events.at(-1)?.detail || '', /引导态/)
})

test('step movement is queue-driven and follows the current skill', () => {
  const created = createLearningTask('理解闭包', 100)
  const before = projectLearningTask(created.task, created.events)
  const withReply = appendLearningEvents(created.events, created.task.id, [{
    type: 'vnext_learning_task_learner_replied',
    detail: '学生回应',
    skillId: before.skillId,
    stepId: before.stepId,
  }], 200)
  assert.equal(projectLearningTask(created.task, withReply).stepId, 'anchor_model')

  const advanced = advanceLearningSkillStep(withReply, projectLearningTask(created.task, withReply), 300)
  assert.equal(projectLearningTask(created.task, advanced).stepId, 'inspect_example')
  assert.equal(learningTaskTutorContext(projectLearningTask(created.task, advanced)).substateId, 'demonstration')
})

test('support and explicit repeats loop inside the current skill step', () => {
  assert.equal(isSupportRequest('我不知道，给个提示吧'), true)
  assert.equal(isSupportRequest('我觉得事件循环先执行同步代码'), false)

  const created = createLearningTask('理解事件循环', 100)
  const before = projectLearningTask(created.task, created.events)
  const withSupport = appendLearningEvents(created.events, created.task.id, [
    { type: 'vnext_learning_support_requested', detail: '补充支架', skillId: before.skillId, stepId: before.stepId },
    { type: 'vnext_learning_skill_looped', detail: '支架后重做', skillId: before.skillId, stepId: before.stepId },
  ], 200)
  const once = projectLearningTask(created.task, withSupport)
  assert.equal(once.stepId, 'anchor_model')
  assert.equal(once.supportCount, 1)
  assert.equal(once.loopCount, 1)

  const twice = projectLearningTask(created.task, loopLearningSkillStep(withSupport, once, '换例子', 300))
  assert.equal(twice.stepId, 'anchor_model')
  assert.equal(twice.loopCount, 2)
  assert.equal(twice.totalLoopCount, 2)
})

test('switching skill resets orchestration to that skill first step', () => {
  const created = createLearningTask('理解索引', 100)
  const guided = projectLearningTask(created.task, advanceLearningSkillStep(
    created.events, projectLearningTask(created.task, created.events), 200,
  ))
  assert.equal(guided.stepId, 'inspect_example')

  const switchedEvents = switchLearningSkill(created.events, guided, 'feynman_dialogue', 300)
  const switched = projectLearningTask(created.task, switchedEvents)
  assert.equal(switched.skillId, 'feynman_dialogue')
  assert.equal(switched.stepId, 'knowledge_anchor')
  assert.equal(switched.stepIndex, 0)
})

test('skill steps that require learner work cannot advance before a reply', () => {
  const created = createLearningTask('理解索引', 100)
  const initial = projectLearningTask(created.task, created.events)
  const switched = projectLearningTask(
    created.task,
    switchLearningSkill(created.events, initial, 'feynman_dialogue', 200),
  )
  const teachbackEvents = advanceLearningSkillStep(
    switchLearningSkill(created.events, initial, 'feynman_dialogue', 200), switched, 300,
  )
  const awaitingReply = projectLearningTask(created.task, teachbackEvents)
  assert.equal(awaitingReply.stepId, 'first_teachback')
  assert.equal(canAdvanceLearningSkillStep(awaitingReply), false)

  const withReply = appendLearningEvents(teachbackEvents, created.task.id, [{
    type: 'vnext_learning_task_learner_replied', detail: '学生完成复述', skillId: awaitingReply.skillId, stepId: awaitingReply.stepId,
  }], 400)
  assert.equal(canAdvanceLearningSkillStep(projectLearningTask(created.task, withReply)), true)

  const looped = loopLearningSkillStep(withReply, projectLearningTask(created.task, withReply), '缩小范围', 500)
  assert.equal(canAdvanceLearningSkillStep(projectLearningTask(created.task, looped)), false)
})

test('legacy four-phase browser events migrate into the selected skill path', () => {
  const task: LearningTask = { id: 'legacy-task', objective: '理解闭包', createdAt: 100 }
  const events = appendLearningEvents([], task.id, [
    { type: 'vnext_learning_task_started', detail: '开始' },
    { type: 'vnext_learning_task_phase_entered', detail: '旧版检查', phase: 'verify' },
    { type: 'vnext_learning_skill_selected', detail: '旧版技能', skillId: 'feynman_dialogue' },
  ], 100)
  const projection = projectLearningTask(task, events)
  assert.equal(projection.skillId, 'feynman_dialogue')
  assert.equal(projection.stepId, 'revised_teachback')
})

test('the model receives a bounded read-only skill-step projection', () => {
  const created = createLearningTask('理解数据库索引', 100)
  const projection = projectLearningTask(created.task, created.events)
  const context = learningTaskTutorContext(projection)
  assert.equal(context.skillName, '清晰讲解')
  assert.equal(context.substateLabel, '引导态')
  assert.equal(context.stepTitle, '建立最小模型')
  assert.equal(context.stepCount, LEARNING_SKILLS.guided_explanation.steps.length)
  assert.match(context.stepInstruction, /先直接解释/)
  assert.match(currentLearningSkillStep(projection).loopInstruction || '', /换一种表征/)
})
