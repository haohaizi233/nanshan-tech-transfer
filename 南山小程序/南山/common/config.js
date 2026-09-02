/**
 * 运行环境配置
 *
 * USE_CAPITAL_DEMO = false：资本对接用本地写死演示数据（真机无需连电脑 API）
 * USE_CAPITAL_DEMO = false：走 API_BASE 请求本机/云端接口
 *
 * 真机若关闭演示模式，API_BASE 须为电脑局域网 IP 或正式 HTTPS 域名。
 */
export const USE_CAPITAL_DEMO = false

// 【交接说明】API_BASE 为后端 api-server 的地址，请勿提交真实 IP。
// 模拟器调试填 http://127.0.0.1:8787；
// 真机调试填运行 api-server 那台电脑的局域网 IP（可用 ipconfig 查询）。
export const API_BASE = 'http://127.0.0.1:8787'
