<template>
	<view class="page" v-if="detail">
		<!-- 上方：业务信息 -->
		<view class="section">
			<view class="section-head">
				<text class="section-title">{{ type === 'demand' ? '需求信息' : '成果信息' }}</text>
				<text
					:class="favorited ? 'star-btn star-on' : 'star-btn'"
					@click="onToggleFavorite"
				>{{ favorited ? '★' : '☆' }}</text>
			</view>

			<!-- 需求详情 -->
			<block v-if="type === 'demand'">
				<text class="main-title">{{ detail.title }}</text>
				<view v-if="detail.isMine && detail.statusLabel" class="mine-status-row">
					<text class="mine-status-text">状态：{{ detail.statusLabel }}</text>
				</view>
				<view class="meta-row">
					<view class="meta-item">
						<text class="meta-label">公司名称</text>
						<text class="meta-value">{{ detail.company || '未填写' }}</text>
					</view>
					<view class="meta-item">
						<text class="meta-label">地点</text>
						<text class="meta-value">{{ detail.location || '未填写' }}</text>
					</view>
				</view>
				<view class="meta-row">
					<view class="meta-item">
						<text class="meta-label">预算</text>
						<text class="meta-value meta-em">{{ detail.budget || '未填写' }}</text>
					</view>
					<view class="meta-item">
						<text class="meta-label">期望周期</text>
						<text class="meta-value">{{ detail.deadline || '待沟通' }}</text>
					</view>
				</view>
				<view class="field">
					<text class="field-label">所属行业</text>
					<text class="field-value">{{ detail.industry || '未填写' }}</text>
				</view>
				<view class="field">
					<text class="field-label">合作方式</text>
					<text class="field-value">{{ detail.cooperationType || '面议' }}</text>
				</view>
				<view class="field">
					<text class="field-label">需求说明</text>
					<text class="field-value">{{ detail.demandDesc }}</text>
				</view>
				<view class="field">
					<text class="field-label">公司简介</text>
					<text class="field-value field-muted">{{ detail.companyIntro || '暂无简介' }}</text>
				</view>
			</block>

			<!-- 成果详情 -->
			<block v-else>
				<text class="main-title">{{ detail.title }}</text>
				<view class="meta-row">
					<view class="meta-item meta-full">
						<text class="meta-label">来源</text>
						<text class="meta-value">{{ detail.source }}</text>
					</view>
				</view>
				<view class="price-box">
					<text class="price-label">期望报价</text>
					<text class="price-value">{{ detail.price }}</text>
				</view>
				<view class="field">
					<text class="field-label">技术简介</text>
					<text class="field-value">{{ detail.techIntro }}</text>
				</view>
				<view class="field">
					<text class="field-label">成果用途</text>
					<text class="field-value">{{ detail.purpose }}</text>
				</view>
				<view class="field">
					<text class="field-label">技术路径</text>
					<text class="field-value">{{ detail.techPath }}</text>
				</view>
				<view class="field">
					<text class="field-label">专利持有人</text>
					<text class="field-value">{{ detail.patentHolder }}</text>
				</view>
				<view class="field">
					<text class="field-label">专利号</text>
					<text class="field-value">{{ detail.patentNo }}</text>
				</view>
				<view class="field">
					<text class="field-label">成熟度</text>
					<text class="field-value">{{ detail.maturity }}</text>
				</view>
			</block>
		</view>

		<!-- 下方：联系方式 -->
		<view class="section">
			<view class="section-head">
				<text class="section-title">联系方式</text>
			</view>
			<view class="contact-card">
				<view class="contact-row">
					<text class="contact-label">联系人</text>
					<text class="contact-value">{{ detail.contactName }}（{{ detail.contactTitle }}）</text>
				</view>
				<view class="contact-row" @click="onCall">
					<text class="contact-label">电话</text>
					<text class="contact-value contact-link">{{ detail.phone }}</text>
				</view>
				<view class="contact-row" @click="onCopy(detail.email, '邮箱')">
					<text class="contact-label">邮箱</text>
					<text class="contact-value contact-link">{{ detail.email }}</text>
				</view>
				<view class="contact-row" @click="onCopy(detail.wechat, '微信号')">
					<text class="contact-label">微信</text>
					<text class="contact-value contact-link">{{ detail.wechat }}</text>
				</view>
			</view>
			<text class="tip">{{ type === 'demand' ? '为保护发布方隐私，非发布方查看时联系方式已脱敏' : '以上为演示联系方式，正式上线后将对接真实数据' }}</text>
		</view>

		<!-- 底部操作区 -->
		<view class="confirm-wrap">
			<!-- 发起对接 / 取消待定 -->
			<button
				v-if="actionMode === 'propose'"
				class="confirm-btn"
				@click="onProposeDock"
			>确认对接</button>
			<button
				v-else-if="actionMode === 'cancel_pending'"
				class="confirm-btn confirm-btn-cancel"
				@click="onCancelPending"
			>取消对接</button>

			<!-- 接收方：同意 / 拒绝 -->
			<view v-else-if="actionMode === 'receiver_decide'" class="btn-row">
				<button class="confirm-btn half accept" @click="openConfirm('receiver', 'accept')">同意</button>
				<button class="confirm-btn half reject" @click="openConfirm('receiver', 'reject')">拒绝</button>
			</view>

			<!-- 发起方最终确认 -->
			<view v-else-if="actionMode === 'initiator_final'" class="btn-row">
				<button class="confirm-btn half accept" @click="openConfirm('initiator', 'accept')">最终确认</button>
				<button class="confirm-btn half reject" @click="openConfirm('initiator', 'reject')">拒绝</button>
			</view>

			<!-- 终态展示 / 不可对接提示 -->
			<view v-else-if="actionMode === 'status' || actionMode === 'blocked'" class="status-bar">
				<text
					v-if="actionMode === 'status'"
					:class="'status-text status-' + (intention && intention.status)"
				>{{ statusLabel }}</text>
				<text v-else class="status-text status-rejected">不可对接</text>
				<text class="status-hint">{{ actionMode === 'blocked' ? blockHint : statusHint }}</text>
			</view>
		</view>

		<!-- 5 秒不可撤销确认弹层 -->
		<view v-if="confirmVisible" class="mask" @click.stop="closeConfirm">
			<view class="dialog" @click.stop="stopBubble">
				<text class="dialog-title">{{ confirmTitle }}</text>
				<text class="dialog-desc">确认后不可撤销，请慎重选择</text>
				<button
					:class="confirmReady ? 'dialog-btn ready' : 'dialog-btn'"
					:disabled="!confirmReady"
					@click="onConfirmAction"
				>{{ confirmReady ? '确认' : ('请等待 ' + confirmLeft + ' 秒') }}</button>
				<button class="dialog-cancel" @click="closeConfirm">取消</button>
			</view>
		</view>
	</view>
</template>

<script>
	import { getResultById, getMyResults } from '../../common/mock-data.js'
	import { getDemandDetail, toDemandCard, getMyDemands as fetchMyDemands } from '../../common/demand-api.js'
	import {
		isFavorite,
		toggleFavorite,
		ensureLoginForDock,
		addIntention,
		removeIntention,
		getMySentIntention,
		getIntentionById,
		getIntentionStatusLabel,
		receiverRespondIntention,
		initiatorFinalizeIntention,
		getUserProfile,
		canProposeDock,
		getDockBlockMessage
	} from '../../common/user.js'

	export default {
		data() {
			return {
				type: 'demand',
				detail: null,
				favorited: false,
				entryRole: '',
				intentId: '',
				intention: null,
				myDemands: [],
				confirmVisible: false,
				confirmRole: '',
				confirmAction: '',
				confirmLeft: 5,
				confirmReady: false,
				confirmTimer: null
			}
		},
		computed: {
			statusLabel() {
				if (!this.intention) return ''
				return getIntentionStatusLabel(this.intention.status)
			},
			statusHint() {
				if (!this.intention) return ''
				const me = getUserProfile()
				const phone = me && me.phone ? me.phone : ''
				const isSender = phone && this.intention.fromPhone === phone
				const s = this.intention.status
				if (s === 'pending') {
					return isSender ? '等待对方处理' : '请选择同意或拒绝'
				}
				if (s === 'accepted') {
					return isSender ? '对方已同意，请最终确认' : '已同意，等待对方最终确认'
				}
				if (s === 'rejected') return '该对接已拒绝，不可撤销'
				if (s === 'success') return '双方均已同意，对接成功'
				return ''
			},
			actionMode() {
				const me = getUserProfile()
				const phone = me && me.phone ? me.phone : ''
				const row = this.intention
				if (!row) {
					if (this.detail && this.type === 'demand' && this.detail.isMine) return 'blocked'
					if (this.detail && !canProposeDock(this.type, this.detail)) return 'blocked'
					return 'propose'
				}

				const isSender = phone && row.fromPhone === phone
				const isReceiver = phone && row.toPhone === phone

				if (row.status === 'rejected' || row.status === 'success') return 'status'
				if (isReceiver && row.status === 'pending') return 'receiver_decide'
				if (isSender && row.status === 'accepted') return 'initiator_final'
				if (isSender && row.status === 'pending') return 'cancel_pending'
				if (isReceiver && row.status === 'accepted') return 'status'
				return 'status'
			},
			blockHint() {
				if (this.type === 'demand' && this.detail && this.detail.isMine) {
					return '这是您自己发布的需求，无法申请对接'
				}
				return getDockBlockMessage(this.type, this.detail)
			},
			confirmTitle() {
				if (this.confirmRole === 'initiator' && this.confirmAction === 'accept') {
					return '确认最终同意对接？'
				}
				const act = this.confirmAction === 'accept' ? '同意' : '拒绝'
				return '确认' + act + '该对接意向？'
			}
		},
		onLoad(options) {
			const type = options.type || 'demand'
			const id = options.id || ''
			this.type = type
			this.entryRole = options.role || ''
			this.intentId = options.intentId || ''

			uni.setNavigationBarTitle({
				title: type === 'result' ? '成果对接' : '需求对接'
			})

			if (type === 'demand') {
				this.loadDemandDetail(id)
				return
			}

			// 成果（Mock 数据，Phase B 后续迁移）
			const detail = getResultById(id)
			if (!detail) {
				uni.showToast({
					title: '未找到对应信息',
					icon: 'none'
				})
				setTimeout(() => {
					uni.navigateBack()
				}, 1200)
				return
			}
			this.detail = detail
			this.favorited = isFavorite(type, detail.id)
			this.refreshIntention()
		},
		onUnload() {
			this.clearConfirmTimer()
		},
		onShow() {
			if (this.detail) this.refreshIntention()
			this.prefetchMyDemands()
		},
		methods: {
			async loadDemandDetail(id) {
				if (!id) {
					uni.showToast({ title: '未找到对应信息', icon: 'none' })
					setTimeout(() => uni.navigateBack(), 1200)
					return
				}
				try {
					const data = await getDemandDetail(id)
					this.detail = toDemandCard(data)
					this.favorited = isFavorite('demand', this.detail.id)
					this.refreshIntention()
				} catch (e) {
					console.error('[dock-detail] loadDemand failed:', e)
					uni.showToast({ title: (e && e.message) || '未找到对应信息', icon: 'none' })
					setTimeout(() => uni.navigateBack(), 1200)
				}
			},
			async prefetchMyDemands() {
				try {
					const data = await fetchMyDemands({ page: 1, pageSize: 5 })
					this.myDemands = (data.list || []).map(toDemandCard)
				} catch (e) {
					this.myDemands = []
				}
			},
			refreshIntention() {
				if (this.intentId) {
					this.intention = getIntentionById(this.intentId)
					return
				}
				this.intention = getMySentIntention(this.type, this.detail.id)
				if (this.intention) this.intentId = this.intention.intentId
			},
			clearConfirmTimer() {
				if (this.confirmTimer) {
					clearInterval(this.confirmTimer)
					this.confirmTimer = null
				}
			},
			openConfirm(role, action) {
				if (!ensureLoginForDock()) return
				this.clearConfirmTimer()
				this.confirmRole = role
				this.confirmAction = action
				this.confirmLeft = 5
				this.confirmReady = false
				this.confirmVisible = true
				this.confirmTimer = setInterval(() => {
					if (this.confirmLeft <= 1) {
						this.confirmLeft = 0
						this.confirmReady = true
						this.clearConfirmTimer()
						return
					}
					this.confirmLeft -= 1
				}, 1000)
			},
			closeConfirm() {
				this.clearConfirmTimer()
				this.confirmVisible = false
				this.confirmReady = false
				this.confirmLeft = 5
			},
			stopBubble() {},
			onConfirmAction() {
				if (!this.confirmReady) return
				const intentId = this.intentId || (this.intention && this.intention.intentId)
				if (!intentId) {
					uni.showToast({ title: '意向不存在', icon: 'none' })
					this.closeConfirm()
					return
				}
				let res
				if (this.confirmRole === 'receiver') {
					res = receiverRespondIntention(intentId, this.confirmAction)
				} else {
					res = initiatorFinalizeIntention(intentId, this.confirmAction)
				}
				this.closeConfirm()
				if (!res || !res.ok) {
					uni.showToast({ title: (res && res.message) || '操作失败', icon: 'none' })
					return
				}
				this.intention = res.intention
				const tip =
					res.intention.status === 'success'
						? '对接成功'
						: res.intention.status === 'rejected'
							? '已拒绝'
							: '已同意，等待发起方最终确认'
				uni.showToast({ title: tip, icon: 'none' })
			},
			onCall() {
				if (!ensureLoginForDock()) return
				if (!this.detail || !this.detail.phone) return
				if (this.detail.phone.indexOf('*') >= 0) {
					uni.showToast({ title: '联系方式已脱敏，正式对接后可见', icon: 'none' })
					return
				}
				uni.makePhoneCall({
					phoneNumber: this.detail.phone
				})
			},
			onCopy(text, label) {
				if (!ensureLoginForDock()) return
				if (!text) {
					uni.showToast({ title: '暂无' + label, icon: 'none' })
					return
				}
				uni.setClipboardData({
					data: text,
					success() {
						uni.showToast({
							title: label + '已复制',
							icon: 'none'
						})
					}
				})
			},
			onToggleFavorite() {
				if (!ensureLoginForDock()) return
				if (!this.detail) return
				this.favorited = toggleFavorite(this.type, this.detail.id)
				uni.showToast({
					title: this.favorited ? '已收藏' : '已取消收藏',
					icon: 'none'
				})
			},
			onCancelPending() {
				if (!ensureLoginForDock()) return
				if (!this.detail) return
				const ok = removeIntention(this.type, this.detail.id)
				if (!ok) {
					uni.showToast({ title: '当前状态不可取消', icon: 'none' })
					return
				}
				this.intention = null
				this.intentId = ''
				uni.showToast({ title: '已取消对接', icon: 'none' })
			},
			onProposeDock() {
				if (!ensureLoginForDock()) return
				if (!this.detail) return
				if (this.type === 'demand' && this.detail.isMine) {
					uni.showToast({ title: '这是您自己发布的需求，无法申请对接', icon: 'none' })
					return
				}
				if (!canProposeDock(this.type, this.detail)) {
					uni.showToast({
						title: getDockBlockMessage(this.type, this.detail) || '无法对接',
						icon: 'none'
					})
					return
				}
				const title = this.detail.title
				const desc = this.type === 'result' ? this.detail.techIntro : this.detail.demandDesc
				const toPhone = (this.detail.phone || '').trim()
				if (!toPhone) {
					uni.showToast({ title: '对方联系方式缺失', icon: 'none' })
					return
				}
				const me = getUserProfile()
				const myPhone = me && me.phone ? me.phone : ''
				let fromSide = { fromSideType: '', fromSideId: '', fromSideTitle: '', fromSideDesc: '' }
				if (me && me.identity === 'supply') {
					const mine = getMyResults(myPhone)[0]
					if (mine) {
						fromSide = {
							fromSideType: 'result',
							fromSideId: mine.id,
							fromSideTitle: mine.title,
							fromSideDesc: mine.techIntro
						}
					}
				} else {
					const mine = (this.myDemands || []).find((d) => d.status === 'published') || (this.myDemands || [])[0]
					if (mine) {
						fromSide = {
							fromSideType: 'demand',
							fromSideId: mine.id,
							fromSideTitle: mine.title,
							fromSideDesc: mine.demandDesc
						}
					}
				}
				const res = addIntention({
					type: this.type,
					id: this.detail.id,
					title,
					desc,
					toPhone,
					toName: this.detail.contactName || this.detail.patentHolder || this.detail.company || '',
					...fromSide
				})
				if (!res.ok) {
					uni.showToast({ title: res.message || '提交失败，请先登录', icon: 'none' })
					return
				}
				this.refreshIntention()
				uni.showToast({ title: '对接意向已提交', icon: 'success' })
			}
		}
	}
</script>

<style>
	.page {
		min-height: 100vh;
		background-color: #f5f6f8;
		padding: 24rpx;
		padding-bottom: 60rpx;
	}

	.section {
		background-color: #ffffff;
		border-radius: 16rpx;
		border: 1rpx solid #e8ecf2;
		padding: 28rpx;
		margin-bottom: 24rpx;
	}

	.section-head {
		display: flex;
		flex-direction: row;
		align-items: center;
		justify-content: space-between;
		margin-bottom: 20rpx;
	}

	.star-btn {
		font-size: 52rpx;
		color: #cccccc;
		line-height: 1;
		padding: 4rpx 8rpx;
		flex-shrink: 0;
	}

	.star-on {
		color: #f5a623;
	}

	.section-title {
		font-size: 36rpx;
		color: #1a1a1a;
		font-weight: 600;
	}

	.main-title {
		display: block;
		font-size: 32rpx;
		color: #1a1a1a;
		font-weight: 600;
		line-height: 1.4;
		margin-bottom: 20rpx;
	}

	.mine-status-row {
		display: inline-flex;
		background: rgba(43, 115, 248, 0.1);
		border-radius: 8rpx;
		padding: 6rpx 16rpx;
		margin-bottom: 20rpx;
	}

	.mine-status-text {
		font-size: 24rpx;
		color: #2b73f8;
	}

	.meta-row {
		display: flex;
		flex-direction: row;
		background-color: #f7f9fc;
		border-radius: 12rpx;
		padding: 18rpx 20rpx;
		margin-bottom: 20rpx;
	}

	.meta-item {
		flex: 1;
		display: flex;
		flex-direction: column;
	}

	.meta-full {
		flex: 1;
	}

	.meta-label {
		font-size: 30rpx;
		color: #333333;
		font-weight: 600;
		margin-bottom: 8rpx;
	}

	.meta-value {
		font-size: 26rpx;
		color: #555555;
		font-weight: 400;
	}

	.meta-em {
		color: #2b73f8;
		font-weight: 500;
	}

	.price-box {
		display: flex;
		flex-direction: row;
		align-items: center;
		justify-content: space-between;
		background-color: #fff8f0;
		border-radius: 12rpx;
		padding: 18rpx 20rpx;
		margin-bottom: 20rpx;
	}

	.price-label {
		font-size: 30rpx;
		color: #a67c52;
		font-weight: 600;
	}

	.price-value {
		font-size: 26rpx;
		color: #e67e22;
		font-weight: 500;
	}

	.field {
		margin-bottom: 22rpx;
	}

	.field:last-child {
		margin-bottom: 0;
	}

	.field-label {
		display: block;
		font-size: 30rpx;
		color: #222222;
		font-weight: 600;
		margin-bottom: 10rpx;
	}

	.field-value {
		display: block;
		font-size: 26rpx;
		color: #555555;
		line-height: 1.6;
	}

	.field-muted {
		color: #666666;
	}

	.contact-card {
		background-color: #f7f9fc;
		border-radius: 12rpx;
		padding: 8rpx 20rpx;
	}

	.contact-row {
		display: flex;
		flex-direction: row;
		align-items: center;
		padding: 22rpx 0;
		border-bottom: 1rpx solid #e8ecf2;
	}

	.contact-row:last-child {
		border-bottom: none;
	}

	.contact-label {
		width: 120rpx;
		font-size: 28rpx;
		color: #555555;
		flex-shrink: 0;
	}

	.contact-value {
		flex: 1;
		font-size: 28rpx;
		color: #222222;
	}

	.contact-link {
		color: #2b73f8;
	}

	.tip {
		display: block;
		margin-top: 20rpx;
		font-size: 24rpx;
		color: #999999;
		line-height: 1.5;
	}

	.confirm-wrap {
		margin-top: 8rpx;
		padding-bottom: calc(20rpx + env(safe-area-inset-bottom));
	}

	.confirm-btn {
		background: #2b73f8 !important;
		color: #ffffff !important;
		border-radius: 12rpx;
		font-size: 32rpx;
		font-weight: 600;
	}

	.confirm-btn-cancel {
		background: #c8c8c8 !important;
		color: #ffffff !important;
		font-weight: 500;
	}

	.btn-row {
		display: flex;
		flex-direction: row;
		gap: 20rpx;
	}

	.half {
		flex: 1;
	}

	.accept {
		background: #2b73f8 !important;
	}

	.reject {
		background: #e74c3c !important;
	}

	.status-bar {
		background: #ffffff;
		border-radius: 12rpx;
		border: 1rpx solid #e8ecf2;
		padding: 28rpx;
		text-align: center;
	}

	.status-text {
		display: block;
		font-size: 34rpx;
		font-weight: 600;
		margin-bottom: 8rpx;
	}

	.status-pending {
		color: #f5a623;
	}

	.status-accepted {
		color: #2b73f8;
	}

	.status-rejected {
		color: #999999;
	}

	.status-success {
		color: #0f9d58;
	}

	.status-hint {
		display: block;
		font-size: 24rpx;
		color: #999999;
	}

	.mask {
		position: fixed;
		left: 0;
		top: 0;
		right: 0;
		bottom: 0;
		background: rgba(0, 0, 0, 0.45);
		display: flex;
		align-items: center;
		justify-content: center;
		z-index: 1000;
	}

	.dialog {
		width: 560rpx;
		background: #ffffff;
		border-radius: 16rpx;
		padding: 40rpx 36rpx 28rpx;
		box-sizing: border-box;
	}

	.dialog-title {
		display: block;
		font-size: 32rpx;
		font-weight: 600;
		color: #1a1a1a;
		text-align: center;
		margin-bottom: 12rpx;
	}

	.dialog-desc {
		display: block;
		font-size: 26rpx;
		color: #888888;
		text-align: center;
		margin-bottom: 32rpx;
	}

	.dialog-btn {
		background: #c8c8c8 !important;
		color: #ffffff !important;
		border-radius: 12rpx;
		font-size: 30rpx;
		margin-bottom: 16rpx;
	}

	.dialog-btn.ready {
		background: #2b73f8 !important;
	}

	.dialog-cancel {
		background: transparent !important;
		color: #888888 !important;
		font-size: 28rpx;
	}
</style>
