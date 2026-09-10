/**
 * AI 能力总开关。false：不展示入口、不发起 /ai/* 请求，误入页面只显示即将开放。
 * 页面与接口代码全部保留，改回 true 即恢复。
 * 放在主包 config/，避免微信小程序主包引用分包模块导致白屏。
 */
export const AI_FEATURE_ENABLED = false

/** 与 AI_FEATURE_ENABLED 同步，控制 Tab / 宫格等入口展示。 */
export const SHOW_AI_MATCH_ENTRY = AI_FEATURE_ENABLED
