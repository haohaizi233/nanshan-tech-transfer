import HostBridge from '../../../host/host-bridge.js'

/** 上传后端受控媒体；本方法只返回 file_object 元数据，不把二进制写进小程序缓存。 */
export async function uploadContentFile(filePath, formData = {}) {
  const response = await HostBridge.upload(filePath, { formData })
  if (response && response.code === 0) return response.data
  const error = new Error((response && response.message) || '文件上传失败')
  error.code = response && response.code
  throw error
}
