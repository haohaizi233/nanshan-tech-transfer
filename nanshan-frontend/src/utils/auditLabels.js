// 审计日志动作标签，供 OverviewView / LogView 共用，避免两处重复维护。

export const ACTION_LABELS = {
  'achievement.approve': '通过成果审核',
  'achievement.reject': '驳回成果',
  'achievement.submit': '提交成果',
  'achievement.create': '创建成果',
  'achievement.update': '更新成果',
  'achievement.offline': '下架成果',
  'demand.approve': '通过需求审核',
  'demand.reject': '驳回需求',
  'demand.submit': '提交需求',
  'demand.create': '创建需求',
  'demand.update': '更新需求',
  'demand.cancel': '取消需求',
  'demand.close': '关闭需求',
  'institution.create': '新增机构',
  'institution.update': '更新机构',
  'institution.online': '上架机构',
  'institution.offline': '下架机构'
}

export function actionLabel(action) {
  return ACTION_LABELS[action] || action || '-'
}
