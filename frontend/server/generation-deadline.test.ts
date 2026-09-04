import assert from 'node:assert/strict'
import test from 'node:test'
import { runGenerationWithinDeadline } from './generation-deadline.ts'

test('a generation that never resolves releases its caller at the shared deadline', async () => {
  await assert.rejects(runGenerationWithinDeadline(Date.now() + 20, () => new Promise(() => {})), /deadline_exceeded/)
})

test('exhausted budget does not dispatch more generation, and successful work returns unchanged', async () => {
  let calls = 0
  await assert.rejects(runGenerationWithinDeadline(Date.now() - 1, async () => { calls += 1; return 0 }), /deadline_exceeded/)
  assert.equal(calls, 0)
  assert.equal(await runGenerationWithinDeadline(Date.now() + 1000, async remaining => {
    assert.ok(remaining > 0 && remaining <= 1000)
    return 42
  }), 42)
})
