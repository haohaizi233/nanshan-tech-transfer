import App from './App'

// #ifdef H5
// Phase B 分包迁移前的主包路由（pages/index 等）与 packageA 前缀路由，
// 在 H5 端重定向到分包新地址，避免浏览器书签/历史记录落在已删除页面而白屏
;(function redirectLegacyRoutes() {
	const LEGACY = {
		'/pages/index/index': '/subpackages/tech-transfer/pages/home/home',
		'/pages/ai-match/ai-match': '/subpackages/tech-transfer/pages/ai-match/ai-match',
		'/pages/mine/mine': '/subpackages/tech-transfer/pages/mine/mine',
		'/pages/capital-list/capital-list': '/subpackages/tech-transfer/pages/capital-list/capital-list',
	}
	const raw = (window.location.hash || '').replace(/^#/, '')
	if (!raw || raw === '/') return
	const qIdx = raw.indexOf('?')
	const path = qIdx >= 0 ? raw.slice(0, qIdx) : raw
	const query = qIdx >= 0 ? raw.slice(qIdx) : ''
	let target = LEGACY[path]
	if (!target && path.indexOf('/packageA/') === 0) {
		target = '/subpackages/tech-transfer/' + path.slice('/packageA/'.length)
	}
	if (target) {
		window.location.replace(window.location.pathname + window.location.search + '#' + target + query)
	}
})()
// #endif

// #ifndef VUE3
import Vue from 'vue'
import './uni.promisify.adaptor'
Vue.config.productionTip = false
App.mpType = 'app'
const app = new Vue({
	...App
})
app.$mount()
// #endif

// #ifdef VUE3
import {
	createSSRApp
} from 'vue'
export function createApp() {
	const app = createSSRApp(App)
	return {
		app
	}
}
// #endif
