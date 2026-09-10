import { getPublicationStatus } from '../constants/review-status.js'

/**
 * 成果详情 → 对接页展示模型。
 * 归属标识必须透传：dock-detail 依此复用需求侧的“本人已发布可下架”状态。
 */
export const MATURITY_LABELS = {
  '01_idea': '概念阶段',
  '02_lab': '实验室验证',
  '03_pilot_ready': '可进入中试',
  '04_pilot_done': '中试完成',
  '05_mass_ready': '可量产',
}

export function formatMaturityLabel(level, desc) {
  const text = String(desc || '').trim()
  if (text && MATURITY_LABELS[text]) return MATURITY_LABELS[text]
  if (text) return text
  return MATURITY_LABELS[level] || ''
}

export function toAchievementDockCard(data = {}) {
  const modeLabels = {
    negotiable: '面议',
    license: '许可',
    transfer: '转让',
    cooperation: '合作',
  }
  const min = data.priceMinWan
  const max = data.priceMaxWan
  const price = data.pricingMode === 'negotiable' || !min
    ? (modeLabels[data.pricingMode] || '面议')
    : (min && max ? `${min}–${max} 万` : `${min} 万`)

  return {
    id: data.id,
    title: data.title || '',
    source: data.sourceOrgName || '',
    orgCertified: !!data.orgCertified,
    price,
    techIntro: data.techIntro || '',
    purpose: (data.applicationFields || []).join(' / '),
    techPath: data.techRoute || '',
    patentHolder: (data.inventors || []).map((v) => v.name).filter(Boolean).join('、'),
    patentNo: '',
    maturity: formatMaturityLabel(data.maturityLevel, data.maturityDesc),
    contactName: data.contactName || '',
    contactTitle: data.contactTitle || '',
    phone: data.contactPhone || '',
    email: data.contactEmail || '',
    wechat: data.contactWechat || '',
    isMine: !!data.isMine,
    status: data.status || '',
    statusLabel: data.status ? getPublicationStatus(data).label : '',
    version: data.version ?? null,
  }
}

/** 成果列表预览模型：本人成果不暴露“我要对接”入口。 */
export function toAchievementPreviewCard(item = {}, favorited = false) {
  const modeLabels = {
    negotiable: '面议',
    license: '许可',
    transfer: '转让',
    cooperation: '合作',
  }
  const min = item.priceMinWan
  const max = item.priceMaxWan
  const price = item.pricingMode === 'negotiable' || !min
    ? (modeLabels[item.pricingMode] || '面议')
    : (min && max ? `${min}–${max} 万` : `${min} 万`)

  return {
    id: String(item.id),
    title: item.title || '',
    source: item.sourceOrgName || '',
    orgCertified: !!item.orgCertified,
    techIntro: item.techIntro || '',
    price,
    favorited,
    isMine: !!item.isMine,
    canDock: !item.isMine,
  }
}
