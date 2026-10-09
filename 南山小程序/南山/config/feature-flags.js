/**
 * 功能开关：默认值在编译期确定（保持向后兼容的标量导出），同时提供
 * 运行时可变层（FeatureFlags 对象 + getFeatureFlag/setFeatureFlag），
 * 让宿主或运营端可在不重新发版的情况下覆盖开关（R2-41）。
 *
 * 运行时覆盖存储在 tt_feature_flags（经 uni storage），
 * 形如 { AI_FEATURE_ENABLED: false }；缺省回退到下面的 DEFAULTS。
 *
 * 注意：为兼容既有测试与早期导入，AI_FEATURE_ENABLED / SHOW_AI_MATCH_ENTRY /
 * SHOW_DEV_HOST 三个标量导出保持布尔字面量；需要运行时开关的页面应改用
 * getFeatureFlag('AI_FEATURE_ENABLED') 读取，以便感知运行时覆盖。
 */

const STORAGE_KEY = 'tt_feature_flags'

const DEFAULTS = {
	AI_FEATURE_ENABLED: true,
	SHOW_AI_MATCH_ENTRY: true,
	SHOW_DEV_HOST: false,
}

function readOverrides() {
	try {
		// 直接读 uni storage（与主包存量 tt_* 缓存同源）；测试环境无 uni 时回退默认。
		// eslint-disable-next-line no-undef
		const uniRef = (typeof uni !== 'undefined') ? uni : null
		if (uniRef && typeof uniRef.getStorageSync === 'function') {
			const v = uniRef.getStorageSync(STORAGE_KEY)
			return (v && typeof v === 'object') ? v : {}
		}
	} catch (e) {
		// ignore
	}
	return {}
}

let _overrides = readOverrides()

/**
 * 可变开关对象（非冻结）：getter 读取运行时覆盖 → 回退 DEFAULTS。
 * 宿主可通过 setFeatureFlag 在运行期调整，无需重新编译。
 */
export const FeatureFlags = {
	get AI_FEATURE_ENABLED() {
		const v = _overrides.AI_FEATURE_ENABLED
		return v !== undefined ? !!v : DEFAULTS.AI_FEATURE_ENABLED
	},
	get SHOW_AI_MATCH_ENTRY() {
		const v = _overrides.SHOW_AI_MATCH_ENTRY
		return v !== undefined ? !!v : DEFAULTS.SHOW_AI_MATCH_ENTRY
	},
	get SHOW_DEV_HOST() {
		const v = _overrides.SHOW_DEV_HOST
		return v !== undefined ? !!v : DEFAULTS.SHOW_DEV_HOST
	},
}

/** 读取某个开关的当前运行时值（覆盖优先，回退默认）。 */
export function getFeatureFlag(key) {
	return FeatureFlags[key]
}

/** 运行时覆盖某个开关并持久化到 storage。 */
export function setFeatureFlag(key, value) {
	_overrides[key] = !!value
	try {
		// eslint-disable-next-line no-undef
		const uniRef = (typeof uni !== 'undefined') ? uni : null
		if (uniRef && typeof uniRef.setStorageSync === 'function') {
			uniRef.setStorageSync(STORAGE_KEY, _overrides)
		}
	} catch (e) {
		// ignore
	}
}

/** 重新从 storage 读取覆盖（登录/登出或宿主切换后调用）。 */
export function reloadFeatureFlags() {
	_overrides = readOverrides()
}

// ── 向后兼容的标量导出（编译期默认值，供既有导入与测试使用） ──
export const AI_FEATURE_ENABLED = true
/** 与 AI_FEATURE_ENABLED 同步，控制 Tab / 宫格等入口展示。 */
export const SHOW_AI_MATCH_ENTRY = true

/**
 * 外层宿主（本地开发工作台 dev-home）显示开关。
 * false：宿主页不渲染，进入即重定向到科转通业务分包首页，原生 Tab 页随之不可达。
 * 页面代码全部保留，改回 true 即恢复本地开发宿主。
 */
export const SHOW_DEV_HOST = false
