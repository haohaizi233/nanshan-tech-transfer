/**
 * AI 任务 API —— 匹配（match）与成果评估（evaluation）
 *
 * 后端契约（openapi.yaml /ai/*）：任务排队制——创建 202 queued /
 * 去重命中 200；结果仅由 worker 写入，前端轮询展示，
 * 无 worker 时任务保持 queued（无假数据回填）。
 *
 * 任务状态机：queued → running → succeeded | failed
 *
 * 运行时开关：AI_FEATURE_ENABLED=false 时本模块拒绝发起请求，
 * 页面与函数保留，后续打开开关即可恢复。
 */

import { apiRequest } from './client.js'
import { AI_FEATURE_ENABLED } from '../../../config/feature-flags.js'

/** 任务处于未终态时前端轮询参数 */
export const POLL_INTERVAL_MS = 3000
export const POLL_MAX_MS = 120000

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
 * 发起需求-成果匹配任务（去重：同需求 10 分钟内未终态任务直接复用）
 * @returns {Promise<{taskId:number, status:string}>}
 */
export async function createMatchTask(demandId) {
  assertAiRuntimeEnabled()
  return apiRequest('POST', '/ai/match-tasks', null, { demandId })
}

/**
 * 查询匹配任务（仅创建者可见）
 * @returns {Promise<{taskId, status, results, failReason, createdAt, finishedAt}>}
 * succeeded 时 results: [{achievementId, achievementTitle, orgName, score, matchReasons}]
 */
export async function getMatchTask(taskId) {
  assertAiRuntimeEnabled()
  return apiRequest('GET', `/ai/match-tasks/${taskId}`)
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
