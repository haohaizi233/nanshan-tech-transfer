const DEMAND_STATUS_LABELS = {
  draft: '草稿',
  pending_review: '待审核',
  published: '已发布',
  matched: '对接中',
  closed: '已关闭',
  cancelled: '已取消',
  rejected: '已驳回',
}

const ACHIEVEMENT_STATUS_LABELS = {
  draft: '草稿',
  pending_review: '待审核',
  published: '已发布',
  offline: '已下架',
  rejected: '已驳回',
}

function fromStatuses(kind, action) {
  if (kind === 'achievement') {
    if (action === 'draft') return ['draft', 'rejected', 'offline']
    if (action === 'submit') return ['draft', 'rejected', 'offline']
    if (action === 'publish') return ['draft', 'rejected', 'pending_review', 'offline']
    return []
  }
  if (action === 'draft') return ['draft', 'rejected']
  if (action === 'submit') return ['draft', 'rejected']
  if (action === 'publish') return ['draft', 'rejected', 'pending_review']
  return []
}

export function statusLabel(kind, status) {
  const labels = kind === 'achievement' ? ACHIEVEMENT_STATUS_LABELS : DEMAND_STATUS_LABELS
  return labels[status] || status || ''
}

/**
 * 后台新增/编辑弹窗按钮：随角色和当前状态机变化。
 * - 机构管理员不能直接发布；已发布/对接中等内容只保存字段，不带 saveAction。
 * - 未传 saveAction 时后端只改内容、不改状态，避免对 published 误提交审核导致 400/404。
 */
export function resolveContentFormActions({ kind = 'demand', isPlatformAdmin = false, formMode = 'create', status = '' } = {}) {
  const isCreate = formMode === 'create'
  const current = isCreate ? 'create' : String(status || '')
  const canSaveDraft = isCreate || fromStatuses(kind, 'draft').includes(current)
  const canSubmit = !isPlatformAdmin && (isCreate || fromStatuses(kind, 'submit').includes(current))
  const canPublish = Boolean(isPlatformAdmin) && (isCreate || fromStatuses(kind, 'publish').includes(current))
  const canSaveContent = !isCreate && !canSaveDraft && !canSubmit
  const label = isCreate ? '' : statusLabel(kind, current)

  let hint = ''
  if (isCreate) {
    hint = isPlatformAdmin
      ? '保存草稿后可继续编辑；直接发布将跳过审核。'
      : '保存草稿后可继续编辑；提交后由平台审核，不能直接发布。'
  } else if (canSubmit) {
    hint = `当前状态为「${label}」，提交后进入平台审核。`
  } else if (canPublish && canSaveContent) {
    hint = `当前状态为「${label}」，可保存修改并保持待审核，或直接发布。`
  } else if (canPublish) {
    hint = `当前状态为「${label}」，可保存草稿或直接发布。`
  } else if (canSaveContent) {
    hint = `当前状态为「${label}」，保存后保持该状态，不会重新提交审核或改发布状态。`
  } else if (canSaveDraft) {
    hint = `当前状态为「${label}」，可继续保存草稿。`
  }

  return {
    canSaveDraft,
    canSubmit,
    canPublish,
    canSaveContent,
    statusLabel: label,
    hint,
  }
}
