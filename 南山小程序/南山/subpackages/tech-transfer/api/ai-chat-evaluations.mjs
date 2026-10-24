const TERMINAL_STATUSES = new Set(['succeeded', 'failed', 'stale'])
const TASK_STATUSES = new Set(['pending', 'queued', 'running', ...TERMINAL_STATUSES])

export function createChatEvaluationReader(maxRequests = 3) {
  let activeRequests = 0
  return async read => {
    if (activeRequests >= maxRequests) throw new Error('Evaluation query budget busy')
    activeRequests++
    try {
      return await read()
    } finally {
      activeRequests--
    }
  }
}

export const readChatEvaluationTask = createChatEvaluationReader()

export function createChatEvaluationMonitor({
  openStream, getTask, onUpdate, parsePreview,
  setTimer = setTimeout, clearTimer = clearTimeout,
  pollMs = 5000, maxStreams = 3, maxRequests = 3,
}) {
  const entries = new Map()
  const queue = []
  let disposed = false
  let activeRequests = 0
  let fillingStreams = false

  const current = entry => !disposed && entries.get(entry.taskId) === entry
  const active = entry => current(entry) && !TERMINAL_STATUSES.has(entry.state.status)
  const publish = entry => {
    if (current(entry)) onUpdate(entry.taskId, { ...entry.state })
  }
  const closeStream = entry => {
    entry.stream?.close()
    entry.stream = null
  }
  const stop = entry => {
    closeStream(entry)
    if (entry.timer !== null) clearTimer(entry.timer)
    entry.timer = null
  }

  function applyTask(entry, task) {
    if (!active(entry) || Number(task?.taskId) !== entry.taskId || !TASK_STATUSES.has(task.status)) return
    entry.state = {
      ...entry.state, ...task, syncError: false,
      progressStage: entry.streamStage || task.progressStage || entry.state.progressStage,
    }
    if (TERMINAL_STATUSES.has(task.status)) {
      stop(entry)
      entry.raw = ''
      entry.state.preview = null
    }
    publish(entry)
    fillStreams()
  }

  function schedule(entry) {
    if (!active(entry) || entry.timer !== null) return
    entry.timer = setTimer(() => {
      entry.timer = null
      enqueue(entry)
    }, pollMs)
  }

  function enqueue(entry) {
    if (!active(entry) || entry.polling) return
    entry.polling = true
    queue.push(entry)
    drain()
  }

  function drain() {
    while (!disposed && activeRequests < maxRequests && queue.length) {
      const entry = queue.shift()
      if (!active(entry)) { entry.polling = false; continue }
      activeRequests++
      Promise.resolve().then(() => active(entry) ? getTask(entry.taskId) : null)
        .then(task => applyTask(entry, task))
        .catch(() => {
          if (!active(entry)) return
          entry.state.syncError = true
          publish(entry)
        })
        .finally(() => {
          activeRequests--
          entry.polling = false
          schedule(entry)
          drain()
        })
    }
  }

  function streamText(entry, text, replace) {
    if (!active(entry)) return
    entry.raw = (replace ? String(text) : entry.raw + String(text)).slice(0, 512 * 1024)
    entry.state.preview = parsePreview(entry.raw)
    publish(entry)
  }

  function fillStreams() {
    if (disposed || fillingStreams) return
    fillingStreams = true
    try {
      let count = [...entries.values()].filter(entry => entry.stream).length
      for (const entry of [...entries.values()].reverse()) {
        if (count >= maxStreams) break
        if (!active(entry) || entry.streamAttempted) continue
        entry.streamAttempted = true
        const fallback = () => {
          if (!active(entry)) return
          closeStream(entry)
          entry.state.syncError = true
          publish(entry)
          enqueue(entry)
          fillStreams()
        }
        try {
          entry.stream = openStream(entry.taskId, {
            onSnapshot: text => streamText(entry, text, true),
            onContentDelta: text => streamText(entry, text, false),
            onStage: text => {
              if (!active(entry)) return
              entry.streamStage = String(text)
              entry.state.progressStage = entry.streamStage
              publish(entry)
            },
            onDone: frame => {
              if (!active(entry)) return
              closeStream(entry)
              applyTask(entry, frame?.result)
              enqueue(entry)
            },
            onTimeout: fallback, onError: fallback, onFallback: fallback,
          })
          if (!active(entry)) closeStream(entry)
          if (entry.stream) count++
        } catch {
          fallback()
        }
      }
    } finally {
      fillingStreams = false
    }
  }

  return {
    sync(taskIds) {
      if (disposed) return
      const ids = new Set(taskIds.map(Number).filter(id => Number.isSafeInteger(id) && id > 0))
      for (const [id, entry] of entries) {
        if (ids.has(id)) continue
        entries.delete(id)
        stop(entry)
      }
      const added = []
      for (const taskId of ids) {
        if (entries.has(taskId)) continue
        const entry = {
          taskId, raw: '', stream: null, streamAttempted: false, timer: null, polling: false,
          state: { taskId, status: 'pending', preview: null, syncError: false },
        }
        entries.set(taskId, entry)
        added.push(entry)
      }
      fillStreams()
      for (const entry of added) enqueue(entry)
    },
    dispose() {
      disposed = true
      for (const entry of entries.values()) stop(entry)
      entries.clear()
      queue.length = 0
    },
  }
}
