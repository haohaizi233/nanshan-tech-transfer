/**
 * AI API —— 需求匹配（同步）+ 成果评估（异步任务）+ 自然语言对话
 *
 * 需求匹配 / 对话：同步经后端转发到 nanshan-ai-agent，直接返回成果卡片。
 * 成果评估：任务排队制——创建 202 queued / 去重命中 200；结果仅由 worker 写入，
 * 前端轮询展示，无 worker 时任务保持 queued（无假数据回填）。
 * 任务状态机：queued → running → succeeded | failed
 *
 * 运行时开关：AI_FEATURE_ENABLED=false 时本模块拒绝发起请求，
 * 页面与函数保留，后续打开开关即可恢复。
 */

import { apiRequest } from './client.js'
import { clearQueueState } from './ai-chat-queue.mjs'
import { clearTurns } from './ai-chat-wal.mjs'
import { AI_FEATURE_ENABLED } from '../../../config/feature-flags.js'

/** 任务处于未终态时前端轮询参数 */
export const POLL_INTERVAL_MS = 3000
export const POLL_MAX_MS = 120000

/** E5: AI 对话/匹配同步链路最长等待（与后端 MAX_REQUEST_SECONDS=60s 对齐，留 10s 余量） */
export const AI_CHAT_TIMEOUT_MS = 70000

export function isTerminalStatus(status) {
  return status === 'succeeded' || status === 'failed'
}

export function assertAiRuntimeEnabled() {
  if (AI_FEATURE_ENABLED) return
  const err = new Error('该功能即将开放')
  err.code = 'AI_DISABLED'
  throw err
}

// ── 需求匹配 ──────────────────────────────────────────────────

/**
 * 需求-成果匹配（同步）：把指定需求当成一次成果检索，返回命中的成果卡片。
 * 后端做角色校验（仅需求所有者）与状态校验（仅 published/matched），
 * 命中成果由 ai-agent 侧 status='published' 过滤，与前端成果列表可见集合一致。
 * @returns {Promise<{demandId, demandTitle, intent, agentMessage, cards:Array}>}
 */
export async function matchDemand(demandId) {
  assertAiRuntimeEnabled()
  return apiRequest('POST', '/ai/match', null, { demandId }, { timeout: AI_CHAT_TIMEOUT_MS })
}

// ── 成果评估 ──────────────────────────────────────────────────

/**
 * 发起成果四维评估任务（去重：同成果 10 分钟内未终态任务直接复用）
 * @returns {Promise<{taskId:number, status:string}>}
 */
export async function createEvaluationTask(achievementId) {
  assertAiRuntimeEnabled()
  return apiRequest('POST', '/ai/evaluation-tasks', null, { achievementId })
}

/**
 * 查询评估任务（仅创建者可见）
 * @returns {Promise<{taskId, status, evaluation, failReason, createdAt, finishedAt}>}
 * succeeded 时 evaluation: {achievementId, achievementTitle, scores:{techFeature,
 * applyScope, maturity, cooperation}, totalScore, conclusion, highlights}
 */
export async function getEvaluationTask(taskId) {
  assertAiRuntimeEnabled()
  return apiRequest('GET', `/ai/evaluation-tasks/${taskId}`)
}

// ── 自然语言对话（nanshan-ai-agent demo）─────────────────────

/**
 * 与 AI 助手对话：自然语言查询科技成果 / 技术需求。
 * 后端转发到 nanshan-ai-agent，返回 {success, intent, message, data:[卡片]}。
 * 卡片 card_type: 'achievement' | 'demand'。
 * @param {string} turnId 客户端在发送前持久化的幂等轮次 ID
 * @returns {Promise<{success:boolean, intent:string, message:string, data:Array}>}
 */
export async function chatWithAgent(message, turnId) {
  assertAiRuntimeEnabled()
  return apiRequest('POST', '/ai/chat', null, { message, turnId: turnId || undefined }, { timeout: AI_CHAT_TIMEOUT_MS })
}

/** 查询指定 AI 对话轮次，供页面切换或请求超时后的 WAL 恢复使用。 */
export async function getChatTurn(turnId) {
  assertAiRuntimeEnabled()
  return apiRequest('GET', `/ai/chat/turns/${encodeURIComponent(String(turnId || ''))}`)
}

// ── 聊天记录持久化（切页/重登后历史不丢）─────────────────────

/**
 * 拉取当前用户的 AI 聊天历史（按时间升序）。
 * @returns {Promise<{messages:Array<{id,role,content,cards,createdAt}>}>}
 */
export async function getChatHistory() {
  assertAiRuntimeEnabled()
  return apiRequest('GET', '/ai/chat/messages')
}

/**
 * 清空当前用户的 AI 聊天历史。
 * @returns {Promise<{deleted:number}>}
 */
export async function clearChatHistory() {
  assertAiRuntimeEnabled()
  const result = await apiRequest('DELETE', '/ai/chat/messages')
  clearTurns()
  clearQueueState()
  return result
}
