/**
 * 跳转外部小程序配置（首页「检索」入口）
 *
 * 有了目标小程序 appId 后，只改本文件 + manifest 白名单即可，见文件末尾说明。
 * 【决策 D11】上级分包合并方式（C-08）确认前保留本能力。
 */
export const EXTERNAL_SEARCH_MINIPROGRAM = {
	/** 目标小程序 AppID，例如：wx1234567890abcdef */
	appId: '',
	/** 可选：打开后的页面路径，例如 pages/index/index */
	path: '',
	/** 可选：传给对方小程序的数据 */
	extraData: {},
	/**
	 * 打开版本：
	 * - develop 开发版
	 * - trial 体验版
	 * - release 正式版
	 */
	envVersion: 'release'
}

/**
 * 打开外部「检索」小程序
 * @returns {boolean} 是否已发起跳转
 */
export function openExternalSearchMiniProgram() {
	const conf = EXTERNAL_SEARCH_MINIPROGRAM
	const appId = (conf.appId || '').trim()
	if (!appId) {
		uni.showToast({
			title: '检索功能暂未开通',
			icon: 'none'
		})
		return false
	}

	uni.navigateToMiniProgram({
		appId,
		path: conf.path || '',
		extraData: conf.extraData || {},
		envVersion: conf.envVersion || 'release',
		fail(err) {
			console.error('navigateToMiniProgram fail', err)
			uni.showToast({
				title: '跳转失败，请检查配置',
				icon: 'none'
			})
		}
	})
	return true
}

/*
 * ========== 配置步骤（拿到 appId 后）==========
 * 1. 本文件 EXTERNAL_SEARCH_MINIPROGRAM.appId 填入目标小程序 AppID
 * 2. 如需指定落地页，填写 path；需要传参则写 extraData
 * 3. 打开 manifest.json → mp-weixin → navigateToMiniProgramAppIdList
 *    加入同一个 appId（数组），例如：["wx1234567890abcdef"]
 * 4. 微信公众平台：本小程序后台 → 设置 → 第三方设置 / 跳转小程序
 *    把目标小程序加入可跳转名单（按微信当期后台文案操作）
 * 5. 重新发行/上传后，真机验证「检索」跳转
 */
