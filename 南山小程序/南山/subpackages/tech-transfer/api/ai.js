/**
 * AI 任务 API —— 匹配（match）与成果评估（evaluation）
 *
 * 后端契约（openapi.yaml /ai/*）：任务排队制——创建 202 queued /
 * 去重命中 200；结果仅由 worker 写入，前端轮询展示，
 * 无 worker 时任务保持 queued（无假数据回填）。
 *
 * 任务状态机：queued → running → succeeded | failed
 */

import { apiRequest } from './client.js'

/** 任务处于未终态时前端轮询参数 */
export const POLL_INTERVAL_MS = 3000
export const POLL_MAX_MS = 120000

export function isTerminalStatus(status) {
  return status === 'succeeded' || status === 'failed'
}

// ── 需求匹配 ──────────────────────────────────────────────────

/**
 * 发起需求-成果匹配任务（去重：同需求 10 分钟内未终态任务直接复用）
 * @returns {Promise<{taskId:number, status:string}>}
 */
export async function createMatchTask(demandId) {
  return apiRequest('POST', '/ai/match-tasks', null, { demandId })
}

/**
 * 查询匹配任务（仅创建者可见）
 * @returns {Promise<{taskId, status, results, failReason, createdAt, finishedAt}>}
 * succeeded 时 results: [{achievementId, achievementTitle, orgName, score, matchReasons}]
 */
export async function getMatchTask(taskId) {
  return apiRequest('GET', `/ai/match-tasks/${taskId}`)
}

// ── 成果评估 ──────────────────────────────────────────────────

/**
 * 发起成果四维评估任务（去重：同成果 10 分钟内未终态任务直接复用）
 * @returns {Promise<{taskId:number, status:string}>}
 */
export async function createEvaluationTask(achievementId) {
  return apiRequest('POST', '/ai/evaluation-tasks', null, { achievementId })
}

/**
 * 查询评估任务（仅创建者可见）
 * @returns {Promise<{taskId, status, evaluation, failReason, createdAt, finishedAt}>}
 * succeeded 时 evaluation: {achievementId, achievementTitle, scores:{techFeature,
 * applyScope, maturity, cooperation}, totalScore, conclusion, highlights}
 */
export async function getEvaluationTask(taskId) {
  return apiRequest('GET', `/ai/evaluation-tasks/${taskId}`)
}
