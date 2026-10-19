export function chooseAvatarImage(runtime) {
  return new Promise((resolve, reject) => {
    const fail = reason => {
      const message = String(reason?.errMsg || reason?.message || '无法打开相册，请检查微信或系统权限后重试')
      const error = new Error(message)
      error.cancelled = /cancel/i.test(message)
      error.privacyRequired = /privacy|隐私/i.test(message) || reason?.errno === 112
      reject(error)
    }
    const success = result => {
      const path = result.tempFiles?.[0]?.tempFilePath || result.tempFilePaths?.[0]
      if (path) resolve(path)
      else reject(new Error('未获取到图片，请重新选择'))
    }
    const options = { count: 1, sizeType: ['compressed'], sourceType: ['album'], success, fail }
    try {
      if (typeof runtime?.chooseMedia === 'function') {
        runtime.chooseMedia({ ...options, mediaType: ['image'] })
      } else if (typeof runtime?.chooseImage === 'function') {
        runtime.chooseImage(options)
      } else {
        fail(new Error('当前环境不支持相册选择，请更新微信或重试'))
      }
    } catch (error) {
      fail(error)
    }
  })
}
