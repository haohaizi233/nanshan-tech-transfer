import assert from 'node:assert/strict'
import test from 'node:test'
import { createChatEvaluationMonitor, createChatEvaluationReader } from '../subpackages/tech-transfer/api/ai-chat-evaluations.mjs'

function deferred() {
  let resolve
  let reject
  const promise = new Promise((yes, no) => { resolve = yes; reject = no })
  return { promise, resolve, reject }
}

async function flush() {
  for (let index = 0; index < 12; index++) await Promise.resolve()
}

function setup(overrides = {}) {
  const streams = new Map()
  const requests = []
  const updates = new Map()
  const timers = new Set()
  const monitor = createChatEvaluationMonitor({
    openStream(taskId, handlers) {
      const stream = { handlers, closed: false, close() { this.closed = true } }
      streams.set(taskId, stream)
      return stream
    },
    getTask(taskId) {
      const request = { taskId, ...deferred() }
      requests.push(request)
      return request.promise
    },
    onUpdate(taskId, state) { updates.set(taskId, state) },
    parsePreview(raw) { return { conclusion: raw, dimensions: [], sections: [], highlights: [] } },
    setTimer(callback) { timers.add(callback); return callback },
    clearTimer(callback) { timers.delete(callback) },
    ...overrides,
  })
  return { monitor, streams, requests, updates, timers }
}

test('chat subscribes once and renders SSE snapshot, deltas, stage and final report', async () => {
  const state = setup()
  state.monitor.sync([204, 204])
  await flush()
  assert.equal(state.streams.size, 1)
  const { handlers } = state.streams.get(204)
  handlers.onSnapshot('已有')
  handlers.onContentDelta('内容')
  handlers.onStage('生成报告中')
  assert.equal(state.updates.get(204).preview.conclusion, '已有内容')
  assert.equal(state.updates.get(204).progressStage, '生成报告中')
  const evaluation = { totalScore: 85, conclusion: '已完成', report: [{ heading: '分析', content: '报告内容' }] }
  handlers.onDone({ status: 'succeeded', result: { taskId: 204, status: 'succeeded', evaluation } })
  assert.equal(state.updates.get(204).evaluation, evaluation)
  assert.equal(state.updates.get(204).status, 'succeeded')
  assert.equal(state.streams.get(204).closed, true)
  state.requests[0].resolve({ taskId: 204, status: 'running' })
  await flush()
  handlers.onContentDelta('迟到数据')
  assert.equal(state.updates.get(204).status, 'succeeded')
  assert.equal(state.timers.size, 0)
  state.monitor.dispose()
})

test('already finished tasks converge from GET without waiting for stream events', async () => {
  const state = setup()
  state.monitor.sync([204])
  await flush()
  state.requests[0].resolve({ taskId: 204, status: 'succeeded', evaluation: { conclusion: '缓存任务也显示' } })
  await flush()
  assert.equal(state.updates.get(204).evaluation.conclusion, '缓存任务也显示')
  assert.equal(state.streams.get(204).closed, true)
  state.monitor.dispose()
})

test('polls authoritative state even when SSE is connected to a different worker', async () => {
  const state = setup()
  state.monitor.sync([204])
  await flush()
  state.requests[0].resolve({ taskId: 204, status: 'running', progressStage: '检索中' })
  await flush()
  assert.equal(state.timers.size, 1)
  const timer = [...state.timers][0]
  state.timers.delete(timer)
  timer()
  await flush()
  state.requests[1].resolve({ taskId: 204, status: 'failed', failReason: '报告生成失败' })
  await flush()
  assert.equal(state.updates.get(204).status, 'failed')
  assert.equal(state.updates.get(204).failReason, '报告生成失败')
  assert.equal(state.timers.size, 0)
  state.monitor.dispose()
})

test('missing stream capability and transport errors retain polling recovery', async () => {
  const state = setup({ openStream() { return null } })
  state.monitor.sync([204])
  await flush()
  state.requests[0].reject(new Error('offline'))
  await flush()
  assert.equal(state.updates.get(204).syncError, true)
  assert.equal(state.timers.size, 1)
  state.monitor.dispose()
  assert.equal(state.timers.size, 0)
})

test('removal, disposal and stale task responses cannot repopulate another conversation', async () => {
  const state = setup()
  state.monitor.sync([204])
  await flush()
  const oldHandlers = state.streams.get(204).handlers
  state.monitor.sync([])
  state.updates.clear()
  oldHandlers.onContentDelta('旧会话')
  state.requests[0].resolve({ taskId: 204, status: 'succeeded', evaluation: {} })
  await flush()
  assert.equal(state.updates.size, 0)
  state.monitor.sync([205])
  await flush()
  state.monitor.dispose()
  state.updates.clear()
  state.requests[1].resolve({ taskId: 205, status: 'succeeded', evaluation: {} })
  state.streams.get(205).handlers.onStage('旧账号')
  await flush()
  assert.equal(state.updates.size, 0)
  assert.equal(state.timers.size, 0)
})

test('bounded streams and GET concurrency cover all cards without trusting mismatched IDs', async () => {
  const state = setup({ maxStreams: 2, maxRequests: 2 })
  state.monitor.sync([1, 2, 3, 4, 0, 'bad'])
  await flush()
  assert.equal(state.streams.size, 2)
  assert.equal(state.requests.length, 2)
  state.requests[0].resolve({ taskId: 999, status: 'succeeded', evaluation: {} })
  state.requests[1].resolve({ taskId: 2, status: 'succeeded', evaluation: {} })
  await flush()
  assert.notEqual(state.updates.get(1)?.status, 'succeeded')
  assert.equal(state.requests.length, 4)
  assert.equal([...state.streams.values()].filter(stream => !stream.closed).length, 2)
  state.monitor.dispose()
})

test('recreating monitors cannot reset the shared in-flight GET budget', async () => {
  const read = createChatEvaluationReader(2)
  const requests = []
  const getTask = taskId => read(() => {
    const request = { taskId, ...deferred() }
    requests.push(request)
    return request.promise
  })
  const first = setup({ getTask, maxRequests: 2 })
  first.monitor.sync([1, 2])
  await flush()
  first.monitor.dispose()
  const second = setup({ getTask, maxRequests: 2 })
  second.monitor.sync([1, 2])
  await flush()
  second.monitor.dispose()
  const third = setup({ getTask, maxRequests: 2 })
  third.monitor.sync([1, 2])
  await flush()
  assert.equal(requests.length, 2)
  assert.equal(third.timers.size, 2)
  for (const request of requests) request.resolve({ taskId: request.taskId, status: 'running' })
  await flush()
  for (const timer of [...third.timers]) { third.timers.delete(timer); timer() }
  await flush()
  assert.equal(requests.length, 4)
  third.monitor.dispose()
})
