import assert from 'node:assert/strict'
import test from 'node:test'
import { buildTutorContextMessages, recoverableTutorTurn } from '../src/turn-recovery.ts'

test('identifies a user message orphaned by reload as recoverable', () => {
  const turn = recoverableTutorTurn([
    { role: 'assistant', content: '你好' },
    { role: 'user', content: '解释一下 CNN', tutorMode: 'simple_explain' },
  ], false)

  assert.equal(turn?.content, '解释一下 CNN')
  assert.equal(turn?.tutorMode, 'simple_explain')
})

test('does not expose recovery while a turn is pending or already finished', () => {
  assert.equal(recoverableTutorTurn([{ role: 'user', content: '解释一下 CNN' }], true), undefined)
  assert.equal(recoverableTutorTurn([
    { role: 'user', content: '解释一下 CNN' },
    { role: 'assistant', content: 'CNN 是卷积神经网络。' },
  ], false), undefined)
})

test('replaying an interrupted turn does not duplicate its user message in context', () => {
  const messages = [
    { role: 'assistant' as const, content: '你好' },
    { role: 'user' as const, content: '解释一下 CNN' },
  ]

  assert.deepEqual(buildTutorContextMessages(messages, '解释一下 CNN', true), messages)
  assert.equal(buildTutorContextMessages(messages, '继续', false).at(-1)?.content, '继续')
})
