const IMPORT_ACCEPT = '.pptx,.pdf'

export function isAchievementImportFile(name) {
  return /\.(pptx|pdf)$/i.test(String(name || ''))
}

export function snapshotFileList(fileList) {
  return Array.from(fileList || [])
}

export function pickAchievementImportFiles(fileList) {
  const files = []
  const skippedPpt = []
  const skippedOther = []
  for (const file of snapshotFileList(fileList)) {
    const name = file?.name || ''
    if (isAchievementImportFile(name)) files.push(file)
    else if (/\.ppt$/i.test(name)) skippedPpt.push(name)
    else if (name) skippedOther.push(name)
  }
  files.sort((a, b) => {
    const left = a.webkitRelativePath || a.name
    const right = b.webkitRelativePath || b.name
    return String(left).localeCompare(String(right), 'zh')
  })
  return { files, skippedPpt, skippedOther }
}

export function describeImportSelection(fileList) {
  const picked = pickAchievementImportFiles(fileList)
  if (!picked.files.length) {
    return {
      ...picked,
      message: picked.skippedPpt.length
        ? '选中的是旧版 .ppt，请先另存为 .pptx 后再导入。'
        : '未找到可导入的 .pptx 或 .pdf 文件。',
    }
  }
  const parts = [`将导入 ${picked.files.length} 个 PPTX/PDF 文件`]
  if (picked.skippedPpt.length) parts.push(`跳过 ${picked.skippedPpt.length} 个旧版 .ppt`)
  if (picked.skippedOther.length) parts.push(`忽略 ${picked.skippedOther.length} 个其他文件`)
  return {
    ...picked,
    message: `${parts.join('，')}。确认后开始解析并写入导入暂存。`,
  }
}

export async function readDirectoryFiles(handle) {
  const files = []
  async function walk(dir) {
    for await (const entry of dir.values()) {
      if (entry.kind === 'file') files.push(await entry.getFile())
      else if (entry.kind === 'directory') await walk(entry)
    }
  }
  await walk(handle)
  return files
}

export function buildAchievementImportForm(files, sourceOrg = '') {
  const { files: list, skippedPpt } = pickAchievementImportFiles(files)
  if (!list.length) {
    if (skippedPpt.length) throw new Error('选中的是旧版 .ppt，请先另存为 .pptx 后再导入')
    throw new Error('未找到可导入的 .pptx 或 .pdf 文件')
  }
  const form = new FormData()
  const org = String(sourceOrg || '').trim()
  if (org) form.append('sourceOrg', org)
  for (const file of list) form.append('files', file)
  return form
}

export async function runAchievementImport(fileList, { api, sourceOrg = '', onProgress } = {}) {
  const picked = pickAchievementImportFiles(fileList)
  if (!picked.files.length) {
    if (picked.skippedPpt.length) throw new Error('选中的是旧版 .ppt，请先另存为 .pptx 后再导入')
    throw new Error('未找到可导入的 .pptx 或 .pdf。请选择文件，或选择包含这些文件的文件夹。')
  }
  const list = []
  const errors = []
  let total = 0
  let staged = 0
  let failed = 0
  const totalFiles = picked.files.length
  for (let index = 0; index < totalFiles; index += 1) {
    const file = picked.files[index]
    onProgress?.({
      current: index + 1,
      total: totalFiles,
      filename: file.name,
      percent: Math.round((index / totalFiles) * 100),
    })
    try {
      const data = await api('/admin/achievement-imports', {
        method: 'POST',
        body: buildAchievementImportForm([file], sourceOrg),
      })
      list.push(...(data.list || []))
      errors.push(...(data.errors || []))
      total += Number(data.total || 0)
      staged += Number(data.staged || 0)
      failed += Number(data.failed || 0)
    } catch (error) {
      errors.push({ filename: file.name, message: error.message || '导入失败' })
    }
    onProgress?.({
      current: index + 1,
      total: totalFiles,
      filename: file.name,
      percent: Math.round(((index + 1) / totalFiles) * 100),
    })
  }
  if (!list.length) {
    throw new Error(errors[0]?.message || '导入失败')
  }
  return {
    list,
    errors,
    total,
    staged,
    failed,
    batchId: list[0]?.batchId,
    skippedPpt: picked.skippedPpt,
    skippedOtherCount: picked.skippedOther.length,
  }
}

export async function confirmAndRunAchievementImport(fileList, {
  api,
  sourceOrg = '',
  confirmDialog,
  openProgressDialog,
  updateProgressDialog,
  closeProgressDialog,
} = {}) {
  const files = snapshotFileList(fileList)
  const selection = describeImportSelection(files)
  if (!selection.files.length) {
    const error = new Error(selection.message)
    error.code = 'NO_IMPORT_FILES'
    throw error
  }
  const ok = await confirmDialog({
    title: '确认导入成果资料',
    message: selection.message,
    confirmText: '开始导入',
    cancelText: '取消',
    tone: 'primary',
  })
  if (!ok) return null
  openProgressDialog({
    title: '正在导入成果资料',
    message: `共 ${selection.files.length} 个文件`,
    percent: 0,
    detail: '准备开始…',
  })
  try {
    return await runAchievementImport(selection.files, {
      api,
      sourceOrg,
      onProgress: ({ current, total, filename, percent }) => {
        updateProgressDialog({
          percent,
          message: `正在导入第 ${current} / ${total} 个文件`,
          detail: filename,
        })
      },
    })
  } finally {
    closeProgressDialog()
  }
}

export function summarizeAchievementImport(data) {
  const batches = data?.list || []
  const errors = data?.errors || []
  const parts = [`解析 ${data?.total || 0} 条，可暂存 ${data?.staged || 0} 条`]
  if (batches.length > 1) parts.unshift(`成功 ${batches.length} 个文件`)
  if (errors.length) parts.push(`${errors.length} 个文件失败：${errors.map(item => item.filename).join('、')}`)
  if (data?.skippedPpt?.length) parts.push(`跳过 ${data.skippedPpt.length} 个旧版 .ppt`)
  if (data?.skippedOtherCount) parts.push(`已忽略文件夹中 ${data.skippedOtherCount} 个其他文件`)
  return parts.join('；')
}

export { IMPORT_ACCEPT }
