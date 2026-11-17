// Revocable random installation hint; never an authentication credential.
const KEY = 'nanshan_device_instance_v1'
export function getDeviceInstanceId() {
  try {
    let id = localStorage.getItem(KEY)
    if (!/^[a-f0-9-]{32,36}$/.test(id || '')) {
      const bytes = new Uint8Array(16)
      globalThis.crypto.getRandomValues(bytes)
      id = Array.from(bytes, b => b.toString(16).padStart(2, '0')).join('')
      localStorage.setItem(KEY, id)
    }
    return id
  } catch {
    return '' // Server still applies IP, phone and account limits.
  }
}
