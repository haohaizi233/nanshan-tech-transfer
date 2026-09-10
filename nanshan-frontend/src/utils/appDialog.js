import { reactive } from 'vue'

const DEFAULTS = {
  visible: false,
  type: 'confirm',
  title: '请确认',
  message: '',
  confirmText: '确定',
  cancelText: '取消',
  tone: 'primary',
  inputValue: '',
  inputPlaceholder: '',
  inputRequired: false,
  error: '',
}

export const dialogState = reactive({ ...DEFAULTS })

let pendingResolve = null
const queue = []

function show(job) {
  pendingResolve = job.resolve
  Object.assign(dialogState, DEFAULTS, job.options, {
    visible: true,
    inputValue: '',
    error: '',
  })
}

function openDialog(options) {
  return new Promise((resolve) => {
    const job = { options, resolve }
    if (dialogState.visible) {
      queue.push(job)
      return
    }
    show(job)
  })
}

function finish(result) {
  const resolve = pendingResolve
  pendingResolve = null
  dialogState.visible = false
  dialogState.inputValue = ''
  dialogState.error = ''
  resolve?.(result)
  const next = queue.shift()
  if (next) show(next)
}

export function confirmDialog({
  title = '请确认',
  message,
  confirmText = '确定',
  cancelText = '取消',
  tone = 'danger',
} = {}) {
  return openDialog({
    type: 'confirm',
    title,
    message: message || '',
    confirmText,
    cancelText,
    tone,
  })
}

export function alertDialog({
  title = '提示',
  message,
  confirmText = '知道了',
} = {}) {
  return openDialog({
    type: 'alert',
    title,
    message: message || '',
    confirmText,
    tone: 'primary',
  })
}

export function promptDialog({
  title = '请输入',
  message,
  confirmText = '确定',
  cancelText = '取消',
  placeholder = '请输入',
  required = true,
  tone = 'danger',
} = {}) {
  return openDialog({
    type: 'prompt',
    title,
    message: message || '',
    confirmText,
    cancelText,
    tone,
    inputPlaceholder: placeholder,
    inputRequired: required,
  })
}

export function submitDialog() {
  if (!dialogState.visible) return
  if (dialogState.type === 'prompt') {
    const value = String(dialogState.inputValue || '').trim()
    if (dialogState.inputRequired && !value) {
      dialogState.error = '请填写后再确定'
      return
    }
    finish(value)
    return
  }
  finish(dialogState.type === 'alert' ? undefined : true)
}

export function cancelDialog() {
  if (!dialogState.visible) return
  finish(dialogState.type === 'prompt' ? null : dialogState.type === 'alert' ? undefined : false)
}
