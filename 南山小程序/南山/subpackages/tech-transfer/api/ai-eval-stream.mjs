/**
 * 评估任务 SSE 流式通道（打字机）—— H5 fetch + ReadableStream
 *
 * 后端：GET /ai/evaluation-tasks/{taskId}/stream（text/event-stream，data: 帧为 JSON）
 *   {"type":"snapshot","text":"<已生成全文>"}                  订阅回放（迟到连接补齐历史）
 *   {"type":"content_delta","text":"<增量>"}                   LLM 实时增量（报告原文）
 *   {"type":"stage","text":"正在生成评价报告"}                  阶段文案
 *   {"type":"done","status":"succeeded","result":{...}}        终态（result 同 GET 任务视图）
 *   {"type":"timeout"}                                        服务端流到时 → 前端转轮询兜底
 *   {"type":"error","message":"..."}                          流内异常 → 前端转轮询兜底
 *
 * 运行时能力检测：无 fetch / ReadableStream / AbortController（微信小程序等）
 * 时 openEvalTaskStream 返回 null，页面降级为既有 GET 轮询，轮询契约不变。
 *
 * extractStreamSections(raw)：把累计的 LLM 流式原文（半截 JSON）容错解析成
 * 可渲染的报告分节，供打字机实时渲染（最后一段加 ▍ 光标）。
 */

import HostBridge from '../../../host/host-bridge.js'

const ACCESS_TOKEN_KEY = 'tt_access_token'

/** SSE 流式能力检测：仅 H5（浏览器 fetch + ReadableStream）可用，其余降级轮询。 */
export function canUseEvalStream() {
  return (
    typeof fetch === 'function' &&
    typeof ReadableStream !== 'undefined' &&
    typeof AbortController === 'function' &&
    typeof TextDecoder === 'function'
  )
}

/** SSE 端点绝对/相对 URL：与请求层同构（apiBase + apiPrefix + path）。 */
export function buildEvalStreamUrl(env, taskId) {
  const base = String((env && env.apiBase) || '').replace(/\/$/, '')
  const prefix = String((env && env.apiPrefix) || '')
  return base + prefix + '/ai/evaluation-tasks/' + taskId + '/stream'
}

/**
 * SSE 帧解析：从缓冲区切出完整的 "data: {...}\n\n" 帧。
 * 心跳注释（":" 开头行）与 event:/id:/retry: 行忽略；半截帧留在 rest 里等下一片。
 * @returns {{frames: Array<object>, rest: string}}
 */
export function parseSseFrames(buffer) {
  const frames = []
  let rest = String(buffer == null ? '' : buffer).replace(/\r\n/g, '\n')
  let idx
  while ((idx = rest.indexOf('\n\n')) >= 0) {
    const block = rest.slice(0, idx)
    rest = rest.slice(idx + 2)
    const payload = extractDataPayload(block)
    if (payload === null) continue
    try {
      frames.push(JSON.parse(payload))
    } catch (e) {
      // 单帧 JSON 损坏：丢弃该帧，不断流
    }
  }
  return { frames, rest }
}

function extractDataPayload(block) {
  const lines = String(block).split('\n')
  const dataLines = []
  for (const line of lines) {
    if (!line.startsWith('data:')) continue
    dataLines.push(line.slice(5).replace(/^ /, ''))
  }
  if (!dataLines.length) return null
  return dataLines.join('\n')
}

/**
 * 打开评估任务 SSE 流。能力不足（无 fetch 等）返回 null → 页面降级轮询。
 *
 * handlers：onSnapshot(text) / onContentDelta(text) / onStage(text) /
 *   onDone({status, result}) / onTimeout() / onError(message) /
 *   onFallback(reason)（流意外中断，页面应转轮询兜底）。
 * 返回 { close() }；close() 主动断流（切页/切任务），不会再触发任何回调。
 */
export function openEvalTaskStream(taskId, handlers = {}) {
  if (!canUseEvalStream()) return null
  const id = Number(taskId)
  if (!Number.isSafeInteger(id) || id <= 0) return null

  let env
  try {
    env = HostBridge.getEnvironment()
  } catch (e) {
    return null
  }

  const controller = new AbortController()
  let closed = false // close() 主动关闭：静默退出
  let finished = false // done/timeout/error 已交代终态：不再触发 onFallback

  const safeCall = (fn, ...args) => {
    if (typeof fn !== 'function') return
    try {
      fn(...args)
    } catch (e) {
      console.error('[ai-eval-stream] handler failed:', e)
    }
  }

  const dispatch = (frame) => {
    if (!frame || typeof frame !== 'object') return
    switch (frame.type) {
      case 'snapshot':
        safeCall(handlers.onSnapshot, String(frame.text || ''))
        break
      case 'content_delta':
        safeCall(handlers.onContentDelta, String(frame.text || ''))
        break
      case 'stage':
        safeCall(handlers.onStage, String(frame.text || ''))
        break
      case 'done':
        finished = true
        safeCall(handlers.onDone, { status: frame.status, result: frame.result })
        break
      case 'timeout':
        finished = true
        safeCall(handlers.onTimeout)
        break
      case 'error':
        finished = true
        safeCall(handlers.onError, String(frame.message || ''))
        break
      default:
        break // 未知事件忽略，向前兼容
    }
  }

  const run = async () => {
    try {
      const headers = {
        Accept: 'text/event-stream',
        'Cache-Control': 'no-cache',
      }
      let token = ''
      try {
        token = HostBridge.getStorage(ACCESS_TOKEN_KEY) || ''
      } catch (e) {
        token = ''
      }
      if (token) headers['Authorization'] = 'Bearer ' + token

      const res = await fetch(buildEvalStreamUrl(env, id), {
        headers,
        signal: controller.signal,
      })
      if (closed) return
      if (!res || !res.ok) {
        finished = true
        safeCall(handlers.onError, 'HTTP ' + (res ? res.status : ''))
        return
      }
      const reader = res.body && typeof res.body.getReader === 'function'
        ? res.body.getReader()
        : null
      if (!reader) {
        // 环境有 fetch 但拿不到流式 body：转轮询
        finished = true
        safeCall(handlers.onFallback, 'no-stream-body')
        return
      }

      const decoder = new TextDecoder('utf-8')
      let buffer = ''
      for (;;) {
        const { done, value } = await reader.read()
        if (closed) return
        if (done) break
        buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, '\n')
        const { frames, rest } = parseSseFrames(buffer)
        buffer = rest
        for (const frame of frames) {
          if (closed) return
          dispatch(frame)
          if (finished) return
        }
      }
      // 流自然结束但没收到终态事件：交给页面转轮询兜底
      if (!finished && !closed) {
        finished = true
        safeCall(handlers.onFallback, 'stream-closed')
      }
    } catch (e) {
      if (closed || finished) return
      finished = true
      safeCall(handlers.onFallback, 'stream-error')
    }
  }

  run()

  return {
    close() {
      closed = true
      finished = true
      try {
        controller.abort()
      } catch (e) {
        // ignore
      }
    },
  }
}

// ══════════════════════════════════════════════════════════════
// 增量容错解析：LLM 流式原文（半截 JSON）→ 可渲染的报告分节
// ══════════════════════════════════════════════════════════════

function emptySections() {
  return { conclusion: '', highlights: [], sections: [] }
}

/**
 * 增量容错解析 LLM 流式原文（累计全文，可能为半截 JSON）。
 * 返回 { conclusion, highlights: string[], sections: [{heading, content}] }。
 * 完整 JSON 直接解析；半截 JSON 先修复再解析；再不行按字段正则兜底。
 */
export function extractStreamSections(raw) {
  const text = trimToJsonObject(stripFence(String(raw == null ? '' : raw)))
  if (!text.trim()) return emptySections()
  try {
    return normalizeSections(JSON.parse(text))
  } catch (e) {
    // 半截 JSON：走修复解析
  }
  try {
    return normalizeSections(JSON.parse(repairPartialJson(text)))
  } catch (e) {
    // 修复仍失败：按字段容错提取
  }
  return regexExtract(text)
}

function stripFence(text) {
  let t = text.trim()
  if (t.startsWith('```')) {
    t = t.replace(/^```[a-zA-Z]*\s*/, '')
    if (t.endsWith('```')) t = t.slice(0, -3)
  }
  return t
}

/** 与后端 parse_json_content 对齐：从第一个 { 起截取（容忍 JSON 前的杂文字）。 */
function trimToJsonObject(text) {
  const start = text.indexOf('{')
  return start > 0 ? text.slice(start) : text
}

function normalizeSections(data) {
  const out = emptySections()
  if (!data || typeof data !== 'object') return out
  if (typeof data.conclusion === 'string') out.conclusion = data.conclusion
  if (Array.isArray(data.highlights)) {
    out.highlights = data.highlights.filter((x) => typeof x === 'string')
  }
  if (Array.isArray(data.report)) {
    out.sections = data.report
      .filter((sec) => sec && typeof sec === 'object')
      .map((sec) => ({
        heading: typeof sec.heading === 'string' ? sec.heading : '',
        content: typeof sec.content === 'string' ? sec.content : '',
      }))
      .filter((sec) => sec.heading || sec.content)
  }
  return out
}

/**
 * 半截 JSON 修复：闭合未结束的字符串、清掉悬空的逗号/半截字面量、
 * 补齐未闭合的 } ]。只做「能解析出已有内容」级别的容错，不追求语义完备。
 */
function repairPartialJson(text) {
  let out = ''
  let inString = false
  let escaped = false
  const stack = []
  for (let i = 0; i < text.length; i++) {
    const ch = text[i]
    if (inString) {
      out += ch
      if (escaped) escaped = false
      else if (ch === '\\') escaped = true
      else if (ch === '"') inString = false
      continue
    }
    if (ch === '"') {
      inString = true
      out += ch
      continue
    }
    if (ch === '{' || ch === '[') stack.push(ch)
    if (ch === '}' || ch === ']') stack.pop()
    out += ch
  }
  if (inString) out += '"'
  // 尾部悬空：半截 true/false/null/数字 → 截掉；悬空冒号 → 补 null；悬空逗号 → 去掉
  out = out.replace(/(?:[0-9]+[.eE][+-]?[0-9]*|t(?:r(?:u(?:e)?)?)?|f(?:a(?:l(?:s(?:e)?)?)?)?|n(?:u(?:l(?:l)?)?)?)$/, '')
  out = out.replace(/\s+$/, '')
  if (out.endsWith(':')) out += 'null'
  if (out.endsWith(',')) out = out.slice(0, -1)
  while (stack.length) {
    out += stack.pop() === '{' ? '}' : ']'
  }
  return out
}

/** 字段级容错提取：半截 JSON 也能取出 conclusion / highlights / report 分节。 */
function regexExtract(text) {
  const out = emptySections()
  out.conclusion = readJsonString(text, 'conclusion')
  out.highlights = readJsonStringArray(text, 'highlights')
  out.sections = readReportSections(text)
  return out
}

function readJsonString(text, key) {
  const re = new RegExp('"' + key + '"\\s*:\\s*"((?:[^"\\\\]|\\\\.)*)')
  const m = re.exec(text)
  return m ? unescapeJsonString(m[1]) : ''
}

function readJsonStringArray(text, key) {
  const start = findArrayStart(text, key)
  if (start < 0) return []
  const slice = text.slice(start)
  const out = []
  const re = /"((?:[^"\\]|\\.)*)"/g
  let m
  while ((m = re.exec(slice))) {
    out.push(unescapeJsonString(m[1]))
  }
  return out
}

function readReportSections(text) {
  const start = findArrayStart(text, 'report')
  if (start < 0) return []
  const slice = text.slice(start)
  const sections = []
  for (const obj of scanObjects(slice)) {
    const sec = {
      heading: readJsonString(obj.text, 'heading'),
      content: readJsonString(obj.text, 'content'),
    }
    if (sec.heading || sec.content) sections.push(sec)
  }
  return sections
}

/** 定位 "key" : [ 之后的数组内容起点（含则从方括号后开始）。 */
function findArrayStart(text, key) {
  const re = new RegExp('"' + key + '"\\s*:\\s*\\[')
  const m = re.exec(text)
  return m ? m.index + m[0].length : -1
}

/**
 * 扫描数组切片里的 JSON 对象（完整 + 尾部半截各一个）。
 * 跟踪字符串状态与花括号深度，内容里出现 { } 字面量也不会切错。
 */
function scanObjects(slice) {
  const objects = []
  let depth = 0
  let start = -1
  let inString = false
  let escaped = false
  for (let i = 0; i < slice.length; i++) {
    const ch = slice[i]
    if (inString) {
      if (escaped) escaped = false
      else if (ch === '\\') escaped = true
      else if (ch === '"') inString = false
      continue
    }
    if (ch === '"') {
      inString = true
      continue
    }
    if (ch === '{') {
      if (depth === 0) start = i
      depth++
    } else if (ch === '}') {
      depth--
      if (depth === 0 && start >= 0) {
        objects.push({ text: slice.slice(start, i + 1), complete: true })
        start = -1
      }
    } else if (ch === ']' && depth === 0) {
      break // report 数组结束
    }
  }
  if (start >= 0) {
    objects.push({ text: slice.slice(start), complete: false })
  }
  return objects
}

function unescapeJsonString(value) {
  return String(value).replace(/\\(.)/g, (_m, ch) => {
    if (ch === 'n') return '\n'
    if (ch === 't') return '\t'
    if (ch === 'r') return '\r'
    return ch
  })
}
