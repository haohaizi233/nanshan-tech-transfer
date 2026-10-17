/**
 * 确保 config/local.env.js 存在。
 *
 * 该文件是本地环境配置，已被 .gitignore 忽略、不入库。缺失时从
 * config/local.env.example.js 复制一份，让构建和开发流程可以直接跑起来。
 *
 * 调用方式：
 *   node scripts/ensure-local-env.mjs      （npm prepare / predev:h5 自动调用）
 *   import { ensureLocalEnv } from './scripts/ensure-local-env.mjs'   （vite.config.js）
 */
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const projectRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const target = path.join(projectRoot, 'config', 'local.env.js')
const template = path.join(projectRoot, 'config', 'local.env.example.js')

export function ensureLocalEnv({ quiet = false } = {}) {
  if (fs.existsSync(target)) {
    return { created: false, target }
  }
  if (!fs.existsSync(template)) {
    throw new Error(
      `缺少 ${path.relative(projectRoot, template)}，无法生成 config/local.env.js`
    )
  }
  fs.copyFileSync(template, target)
  if (!quiet) {
    console.warn('[local.env] 未找到 config/local.env.js，已按 local.env.example.js 生成。')
    console.warn('[local.env] 模板是本地开发默认值（APP_ENV=local / AUTH_PROVIDER=mock）。')
    console.warn('[local.env] 构建 staging 或 production 版本前，请先改成真实配置。')
  }
  return { created: true, target }
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  ensureLocalEnv()
}
