export function mergeAdminRow(rows, updated, idField = 'id') {
  return (Array.isArray(rows) ? rows : []).map(row =>
    String(row[idField]) === String(updated?.[idField]) ? { ...row, ...updated } : row,
  )
}

export function insertAdminRow(rows, created, pageSize, idField = 'id') {
  const current = Array.isArray(rows) ? rows : []
  const withoutDuplicate = current.filter(row => String(row[idField]) !== String(created?.[idField]))
  return [created, ...withoutDuplicate].slice(0, Math.max(0, Number(pageSize) || 0))
}

export function removeAdminRow(rows, id, idField = 'id') {
  return (Array.isArray(rows) ? rows : []).filter(row => String(row[idField]) !== String(id))
}

export function rowMatchesAdminFilters(row, filters = {}, keywordFields = [], exactFields = ['status', 'categoryCode']) {
  if (exactFields.some(field => filters[field] && row[field] !== filters[field])) return false
  const keyword = String(filters.keyword || '').trim().toLocaleLowerCase()
  if (!keyword) return true
  return keywordFields.some(field => String(row[field] || '').toLocaleLowerCase().includes(keyword))
}

export function reconcileAdminRow(rows, updated, {
  filters,
  keywordFields,
  page = 1,
  pageSize,
  created = false,
  idField = 'id',
  exactFields = ['status', 'categoryCode'],
} = {}) {
  const current = Array.isArray(rows) ? rows : []
  const id = updated?.[idField]
  const exists = current.some(row => String(row[idField]) === String(id))
  if (!rowMatchesAdminFilters(updated || {}, filters, keywordFields, exactFields)) {
    return { rows: removeAdminRow(current, id, idField), totalDelta: exists ? -1 : 0 }
  }
  if (created) {
    return {
      rows: Number(page) === 1 ? insertAdminRow(current, updated, pageSize, idField) : current,
      totalDelta: 1,
    }
  }
  if (!exists) return { rows: current, totalDelta: 0 }
  return { rows: mergeAdminRow(current, updated, idField), totalDelta: 0 }
}

