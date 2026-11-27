function cleanText(value) {
  return value == null ? '' : String(value).trim()
}

export function buildContactRows(contact, options = {}) {
  const source = contact && typeof contact === 'object' ? contact : {}
  const { counterpartName = '', separateTitle = false } = options
  const rows = []

  const counterpart = cleanText(counterpartName)
  if (counterpart) {
    rows.push({ key: 'counterpart', label: '对接对象', value: counterpart, action: '' })
  }

  const name = cleanText(source.displayName ?? source.contactName)
  const orgTitle = cleanText(source.orgTitle ?? source.contactTitle)

  if (separateTitle) {
    if (name) {
      rows.push({ key: 'name', label: '联系人', value: name, action: '' })
    }
    if (orgTitle) {
      rows.push({ key: 'title', label: '职务', value: orgTitle, action: '' })
    }
  } else if (name || orgTitle) {
    const value = name && orgTitle ? `${name}（${orgTitle}）` : (name || orgTitle)
    rows.push({ key: 'contact', label: '联系人', value, action: '' })
  }

  const phone = cleanText(source.phone ?? source.contactPhone)
  if (phone) {
    rows.push({ key: 'phone', label: '电话', value: phone, action: 'call' })
  }

  const email = cleanText(source.email ?? source.contactEmail)
  if (email) {
    rows.push({ key: 'email', label: '邮箱', value: email, action: 'copy', copyLabel: '邮箱' })
  }

  const wechat = cleanText(source.wechat ?? source.contactWechat)
  if (wechat) {
    rows.push({ key: 'wechat', label: '微信', value: wechat, action: 'copy', copyLabel: '微信号' })
  }

  return rows
}
