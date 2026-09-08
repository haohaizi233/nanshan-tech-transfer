/**
 * 稳定错误码常量 —— 前端唯一分支判据
 * 与后端 openapi.yaml 错误码总表对齐
 */

export const TT_COMMON_40001 = 'TT_COMMON_40001'
export const TT_COMMON_40101 = 'TT_COMMON_40101'
export const TT_COMMON_40102 = 'TT_COMMON_40102'
export const TT_COMMON_40902 = 'TT_COMMON_40902'
export const TT_AUTH_40103 = 'TT_AUTH_40103'
export const TT_AUTH_40104 = 'TT_AUTH_40104'
export const TT_AUTH_40105 = 'TT_AUTH_40105'
export const TT_AUTH_40106 = 'TT_AUTH_40106'

export const ERROR_MESSAGES = {
  [TT_COMMON_40001]: '请求参数无效',
  [TT_COMMON_40101]: '请先登录',
  [TT_COMMON_40102]: '登录已过期，请重新登录',
  [TT_COMMON_40902]: '数据已变更，请刷新后重试',
  [TT_AUTH_40103]: '身份凭证无效',
  [TT_AUTH_40104]: '登录已过期，请重新登录',
  [TT_AUTH_40105]: '账号或密码错误',
  [TT_AUTH_40106]: '账号已被禁用',
}
