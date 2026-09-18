/**
 * AI 能力总开关。false：不展示入口、不发起 /ai/* 请求，误入页面只显示即将开放。
 * 页面与接口代码全部保留，改回 true 即恢复。
 * 放在主包 config/，避免微信小程序主包引用分包模块导致白屏。
 */
export const AI_FEATURE_ENABLED = true

/** 与 AI_FEATURE_ENABLED 同步，控制 Tab / 宫格等入口展示。 */
export const SHOW_AI_MATCH_ENTRY = AI_FEATURE_ENABLED

/**
 * 外层宿主（本地开发工作台 dev-home）显示开关。
 * false：宿主页不渲染，进入即重定向到科转通业务分包首页，原生 Tab 页随之不可达。
 * 页面代码全部保留，改回 true 即恢复本地开发宿主。
 */
export const SHOW_DEV_HOST = false
