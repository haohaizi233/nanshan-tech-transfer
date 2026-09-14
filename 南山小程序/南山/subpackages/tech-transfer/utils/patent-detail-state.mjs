function decodeRouteValue(value) {
  const text = String(value || '')
  if (!text) return ''
  try {
    return decodeURIComponent(text)
  } catch (e) {
    return text
  }
}

export function buildPatentDetailSeed(options = {}) {
  return {
    publicationNo: decodeRouteValue(options.no),
    title: decodeRouteValue(options.title),
    applicant: decodeRouteValue(options.applicant),
    inventor: decodeRouteValue(options.inventor),
    applyDate: decodeRouteValue(options.applyDate),
    publicationDate: decodeRouteValue(options.publicationDate),
    grantDate: decodeRouteValue(options.grantDate),
    patentType: decodeRouteValue(options.patentType),
    language: decodeRouteValue(options.language),
    hasPdf: options.hasPdf !== '0',
    abstract: '',
    claims: '',
    description: '',
  }
}

export function mergePatentDetail(seed = {}, remote = {}) {
  return {
    ...seed,
    ...remote,
    // 列表标题由用户的检索语言确定；详情接口未提供相同语言时不得覆盖它。
    title: seed.title || remote.title || '',
    applicant: remote.applicant || seed.applicant || '',
    inventor: remote.inventor || seed.inventor || '',
    applyDate: remote.applyDate || seed.applyDate || '',
    publicationDate: remote.publicationDate || seed.publicationDate || '',
    grantDate: remote.grantDate || seed.grantDate || '',
    language: seed.language || remote.language || '',
  }
}
