/** 本人发布内容的审核状态展示。 */
const STATUS_META = {
  draft: { label: '草稿', cls: 'draft', hint: '尚未提交审核' },
  pending_review: { label: '待审核', cls: 'pending', hint: '管理员审核中，请耐心等待' },
  published: { label: '已发布', cls: 'success', hint: '审核已通过，已对外发布' },
  matched: { label: '已匹配', cls: 'accepted', hint: '已进入对接流程' },
  rejected: { label: '已驳回', cls: 'rejected', hint: '管理员已驳回，请补充后重新提交' },
  offline: { label: '已下架', cls: 'rejected', hint: '内容已下架，不再对外展示' },
  closed: { label: '已关闭', cls: 'rejected', hint: '内容已关闭' },
  cancelled: { label: '已取消', cls: 'rejected', hint: '发布已取消' },
}

export function getPublicationStatus(item = {}) {
  const meta = STATUS_META[item.status] || {
    label: item.status || '状态未知',
    cls: 'draft',
    hint: '',
  }
  const reason = (item.rejectReason || '').trim()
  return {
    ...meta,
    hint: item.status === 'rejected' && reason ? `管理员已驳回：${reason}` : meta.hint,
  }
}

export function getPendingReviewCount(items = []) {
  return items.filter((item) => item && item.status === 'pending_review').length
}
