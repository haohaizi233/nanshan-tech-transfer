const EMAIL_RE = /[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}/g
const PHONE_RE = /(?<!\d)(1[3-9]\d{9})(?!\d)/g
const URL_RE = /https?:\/\/[^\s）\]>，,;；]+/gi
const LABEL_RE = /^\s*([^:：]{1,32})\s*[:：]\s*(.*)$/

const FIELD_ALIASES = {
  成果名称: 'title', 中文名称: 'title', 项目名称: 'title', 标题: 'title',
  成果简介: 'techIntro', 技术简介: 'techIntro', 项目简介: 'techIntro', 简介: 'techIntro',
  来源单位: 'sourceOrgName', 完成单位: 'sourceOrgName', 依托单位: 'sourceOrgName',
  技术路线: 'techRoute', 技术路径: 'techRoute',
  联系人: 'contactName', 联系人姓名: 'contactName', 对接人: 'contactName',
  团队负责人: 'contactName', 负责人: 'contactName',
  联系电话: 'contactPhone', 电话: 'contactPhone', 手机: 'contactPhone', 手机号: 'contactPhone',
  联系邮箱: 'contactEmail', 邮箱: 'contactEmail', 电子邮箱: 'contactEmail', Email: 'contactEmail',
  微信: 'contactWechat', 微信号: 'contactWechat',
  成熟度: 'maturityLevel', 技术成熟度: 'maturityLevel',
  定价方式: 'pricingMode',
  发明人: 'inventorNames', 完成人: 'inventorNames', 成果完成人: 'inventorNames',
  应用领域: 'applicationFields', 可应用领域: 'applicationFields',
}

const LINK_ALIASES = {
  个人网站: 'personal_homepage',
  个人主页: 'personal_homepage',
  官网: 'official_site',
  官方网站: 'official_site',
  机构网站: 'company_site',
}

const MATURITY_VALUES = {
  '01_idea': '01_idea', 概念: '01_idea', 概念阶段: '01_idea',
  '02_lab': '02_lab', 实验室: '02_lab', 实验室验证: '02_lab',
  '03_pilot_ready': '03_pilot_ready', 中试: '03_pilot_ready', 可中试: '03_pilot_ready', 可进入中试: '03_pilot_ready',
  '04_pilot_done': '04_pilot_done', 中试完成: '04_pilot_done',
  '05_mass_ready': '05_mass_ready', 量产: '05_mass_ready', 可量产: '05_mass_ready', 量产准备: '05_mass_ready',
}

const PRICING_VALUES = {
  面议: 'negotiable', 许可: 'license', 转让: 'transfer', 合作: 'cooperation', 其他: 'other',
}

function cleanLabel(label) {
  return String(label || '').replace(/[\s（）()【】[\]\-]/g, '')
}

function parseLabeledLine(line) {
  const text = String(line || '').trim()
  if (!text) return { label: '', content: '' }
  const matched = text.match(LABEL_RE)
  if (matched) {
    const cleaned = cleanLabel(matched[1])
    const alias = Object.keys(FIELD_ALIASES).find((key) => cleanLabel(key) === cleaned)
      || Object.keys(LINK_ALIASES).find((key) => cleanLabel(key) === cleaned)
    return { label: alias || matched[1].trim(), content: String(matched[2] || '').trim() }
  }
  const alias = Object.keys(FIELD_ALIASES).find((key) => cleanLabel(key) === cleanLabel(text))
    || Object.keys(LINK_ALIASES).find((key) => cleanLabel(key) === cleanLabel(text))
  return alias ? { label: alias, content: '' } : { label: '', content: '' }
}

function splitNames(value) {
  return String(value || '').split(/[，,、;；/\n]+/).map((item) => item.trim()).filter(Boolean)
}

function mapMaturity(value) {
  const text = String(value || '').trim()
  if (MATURITY_VALUES[text] || MATURITY_VALUES[cleanLabel(text)]) {
    return MATURITY_VALUES[text] || MATURITY_VALUES[cleanLabel(text)]
  }
  return Object.keys(MATURITY_VALUES).find((key) => key && text.includes(key)) ? MATURITY_VALUES[Object.keys(MATURITY_VALUES).find((key) => key && text.includes(key))] : ''
}

function onlyContacts(line, emails, phones, urls) {
  let leftover = line
  for (const item of [...emails, ...phones, ...urls]) leftover = leftover.replace(item, ' ')
  return leftover.replace(/[\s:：/]+/g, '') === ''
}

function fillEmpty(target, key, value) {
  if (!value || target[key]) return
  target[key] = value
}

function appendLink(target, label, url) {
  const href = String(url || '').trim()
  if (!href) return
  const normalized = /^https?:\/\//i.test(href) ? href : `https://${href}`
  if (target.links.some((item) => item.url === normalized)) return
  target.links.push({ type: LINK_ALIASES[label] || 'other', label: label || '相关链接', url: normalized })
}

export function extractAchievementFields(text, current = {}) {
  const result = {
    techIntro: '',
    sourceOrgName: current.sourceOrgName || '',
    techRoute: current.techRoute || '',
    contactName: current.contactName || '',
    contactPhone: current.contactPhone || '',
    contactEmail: current.contactEmail || '',
    contactWechat: current.contactWechat || '',
    maturityLevel: current.maturityLevel || '',
    pricingMode: current.pricingMode || '',
    applicationFields: current.applicationFields || '',
    inventorNames: current.inventorNames || '',
    links: [...(current.links || [])],
  }
  const kept = []
  let pending = null
  for (const raw of String(text || '').split(/\r?\n/)) {
    const line = raw.trim()
    if (!line) continue
    const { label, content } = parseLabeledLine(line)
    if (label && FIELD_ALIASES[label] && FIELD_ALIASES[label] !== 'techIntro' && FIELD_ALIASES[label] !== 'title') {
      const key = FIELD_ALIASES[label]
      const value = content
      if (!value) {
        pending = { type: 'field', key }
        continue
      }
      applyField(result, key, value)
      pending = null
      continue
    }
    if (label && LINK_ALIASES[label]) {
      if (content) {
        appendLink(result, label, content)
        pending = null
      } else {
        pending = { type: 'link', label }
      }
      continue
    }
    if (pending) {
      if (pending.type === 'field') applyField(result, pending.key, line)
      else appendLink(result, pending.label, line)
      pending = null
      continue
    }
    const emails = line.match(EMAIL_RE) || []
    const phones = line.match(PHONE_RE) || []
    const urls = line.match(URL_RE) || []
    let consumed = false
    if (emails.length) {
      fillEmpty(result, 'contactEmail', emails[0])
      consumed = true
    }
    if (phones.length) {
      fillEmpty(result, 'contactPhone', phones[0])
      consumed = true
    }
    urls.forEach((url) => {
      appendLink(result, '相关链接', url)
      consumed = true
    })
    if (consumed && onlyContacts(line, emails, phones, urls)) continue
    kept.push(line)
  }
  result.techIntro = kept.join('\n').trim()
  return result
}

function applyField(result, key, value) {
  if (key === 'maturityLevel') {
    fillEmpty(result, key, mapMaturity(value))
    return
  }
  if (key === 'pricingMode') {
    fillEmpty(result, key, PRICING_VALUES[cleanLabel(value)] || PRICING_VALUES[value.trim()] || '')
    return
  }
  if (key === 'inventorNames') {
    const merged = splitNames([result.inventorNames, value].filter(Boolean).join('，'))
    result.inventorNames = [...new Set(merged)].join('，')
    return
  }
  if (key === 'applicationFields') {
    if (!result.applicationFields) result.applicationFields = splitNames(value).join('，')
    return
  }
  fillEmpty(result, key, value)
}

export function mergeExtractedFields(form, extracted) {
    return {
    techIntro: extracted.techIntro,
    sourceOrgName: form.sourceOrgName || extracted.sourceOrgName,
    techRoute: form.techRoute || extracted.techRoute,
    contactName: form.contactName || extracted.contactName,
    contactPhone: form.contactPhone || extracted.contactPhone,
    contactEmail: form.contactEmail || extracted.contactEmail,
    contactWechat: form.contactWechat || extracted.contactWechat,
    maturityLevel: form.maturityLevel || extracted.maturityLevel,
    pricingMode: form.pricingMode || extracted.pricingMode,
    applicationFieldsText: form.applicationFieldsText || extracted.applicationFields,
    inventorNamesText: form.inventorNamesText || extracted.inventorNames,
    links: (form.links && form.links.length) ? form.links : extracted.links,
  }
}
