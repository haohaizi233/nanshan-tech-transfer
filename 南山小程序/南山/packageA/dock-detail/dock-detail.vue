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
			<text class="tip">为保护发布方隐私，对接被接受前联系方式已脱敏</text>
		</view>

		<!-- 底部操作区 -->
			<view class="confirm-wrap">
				<view v-if="intention && intentionIntentLabel" class="intent-type-bar">
					<text class="intent-type-label">合作意向</text>
					<text class="intent-type-value">{{ intentionIntentLabel }}</text>
				</view>
				<!-- 发起对接 / 取消待定 -->
				<button
					v-if="actionMode === 'propose'"
					class="confirm-btn"
					@click="onProposeDock"
				>申请对接</button>
				<button
					v-else-if="actionMode === 'cancel_pending'"
					class="confirm-btn confirm-btn-cancel"
					@click="onCancelPending"
				>取消对接</button>

				<!-- 接收方：同意 / 拒绝 -->
				<view v-else-if="actionMode === 'receiver_decide'" class="btn-row">
					<button class="confirm-btn half accept" @click="openConfirm('accept')">同意</button>
					<button class="confirm-btn half reject" @click="openConfirm('reject')">拒绝</button>
				</view>

				<!-- 已同意：双方均可确认 / 取消 -->
				<view v-else-if="actionMode === 'confirm_or_cancel'" class="btn-row">
					<button class="confirm-btn half accept" @click="openConfirm('confirm')">确认对接</button>
					<button class="confirm-btn half reject" @click="openConfirm('cancel')">取消对接</button>
				</view>

				<!-- 已确认：标记完成 -->
				<button
					v-else-if="actionMode === 'complete'"
					class="confirm-btn"
					@click="openConfirm('complete')"
				>完成对接</button>

				<!-- 终态展示 / 不可对接提示 -->
				<view v-else-if="actionMode === 'status' || actionMode === 'blocked'" class="status-bar">
					<text
						v-if="actionMode === 'status'"
						:class="'status-text status-' + statusCls"
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

		<!-- 合作意向选择弹层：每次对接的角色由当次选择决定 -->
		<view v-if="intentDialogVisible" class="mask" @click.stop="closeIntentDialog">
			<view class="sheet" @click.stop="stopBubble">
				<text class="sheet-title">{{ type === 'demand' ? '您希望以什么方式参与？' : '您的合作意向' }}</text>
				<text class="sheet-sub">针对「{{ detail ? detail.title : '' }}」</text>
				<scroll-view scroll-y class="sheet-scroll">
					<view
						v-for="opt in intentOptions"
						:key="opt.value"
						:class="selectedIntentType === opt.value ? 'sheet-option active' : 'sheet-option'"
						@click="selectedIntentType = opt.value"
					>
						<text class="sheet-option-text">{{ opt.label }}</text>
						<text class="sheet-option-check">{{ selectedIntentType === opt.value ? '✓' : '' }}</text>
					</view>
				</scroll-view>
				<view class="sheet-msg">
					<text class="sheet-msg-label">留言（选填）</text>
					<textarea
						class="sheet-textarea"
						:value="intentMessage"
						maxlength="200"
						placeholder="补充说明您的合作诉求…"
						@input="onIntentMsgInput"
					></textarea>
				</view>
				<button
					:class="selectedIntentType ? 'sheet-btn ready' : 'sheet-btn'"
					:disabled="!selectedIntentType"
					@click="onSubmitIntent"
				>提交对接意向</button>
				<button class="sheet-cancel" @click="closeIntentDialog">取消</button>
			</view>
		</view>
	</view>
</template>

<script>
	import { getDemandDetail, toDemandCard } from '../../common/demand-api.js'
	import { getAchievementDetail, formatAchPrice } from '../../common/achievement-api.js'
	import { ensureLoginForDock, canProposeDock, getDockBlockMessage } from '../../common/user.js'
	import {
		addFavorite,
		removeFavorite,
		getFavoriteIdSet,
		createCooperation,
		getCooperationDetail,
		getMyActiveIntentForTarget,
		getIntentTypeOptions,
		getIntentTypeLabel,
		acceptCooperation,
		rejectCooperation,
		confirmCooperation,
		cancelCooperation,
		completeCooperation,
		getCooperationDisplayLabel,
		getCooperationDisplayCls,
		getAssistedHint
	} from '../../common/interaction-api.js'

	const ACTION_TIPS = {
		accepted: '已同意，等待双方确认对接',
		rejected: '已拒绝',
		confirmed: '对接已确认',
		cancelled: '已取消',
		completed: '对接已完成'
	}

	export default {
		data() {
			return {
				type: 'demand',
				detail: null,
				favorited: false,
				intentId: '',
				intention: null,
				confirmVisible: false,
				confirmOp: '',
				confirmLeft: 5,
				confirmReady: false,
				confirmTimer: null,
				intentDialogVisible: false,
				selectedIntentType: '',
				intentMessage: '',
				submitting: false
			}
		},
		computed: {
			statusLabel() {
				if (!this.intention) return ''
				return getCooperationDisplayLabel(
					this.intention.status,
					this.intention.handlingMode,
					this.intention.assistStatus
				)
			},
			statusCls() {
				if (!this.intention) return 'pending'
				return getCooperationDisplayCls(
					this.intention.status,
					this.intention.handlingMode,
					this.intention.assistStatus
				)
			},
			intentionIntentLabel() {
				return this.intention
					? getIntentTypeLabel(this.type, this.intention.intentType)
					: ''
			},
			intentOptions() {
				return getIntentTypeOptions(this.type)
			},
			isAssisted() {
				return this.intention && this.intention.handlingMode === 'assisted'
			},
			statusHint() {
				const row = this.intention
				if (!row) return ''
				// assisted 模式：使用平台协助状态提示
				if (row.handlingMode === 'assisted') {
					const hint = getAssistedHint(row.status, row.assistStatus)
					if (hint) return hint
				}
				const isInitiator = row.myRole === 'initiator'
				if (row.status === 'pending') {
					return isInitiator ? '等待对方处理' : '请选择同意或拒绝'
				}
				if (row.status === 'accepted') return '对方已同意，双方均可确认或取消对接'
				if (row.status === 'confirmed') return '双方已确认对接，可标记完成'
				if (row.status === 'completed') return '本次对接已完成'
				if (row.status === 'rejected') return '该对接已被拒绝'
				if (row.status === 'cancelled') return '该对接已取消'
				return ''
			},
			actionMode() {
				const row = this.intention
				if (!row) {
					if (this.detail && !canProposeDock(this.type, this.detail)) return 'blocked'
					return 'propose'
				}
				// assisted 模式：目标方没有平台账号，永远不显示接收方操作按钮
				if (row.handlingMode === 'assisted') {
					if (row.status === 'pending' && row.myRole === 'initiator') {
						return 'cancel_pending'
					}
					return 'status'
				}
				if (row.status === 'pending') {
					return row.myRole === 'target_owner' ? 'receiver_decide' : 'cancel_pending'
				}
				if (row.status === 'accepted') return 'confirm_or_cancel'
				if (row.status === 'confirmed') return 'complete'
				return 'status'
			},
			blockHint() {
				return getDockBlockMessage(this.type, this.detail)
			},
			confirmTitle() {
				const titles = {
					accept: '确认同意该对接意向？',
					reject: '确认拒绝该对接意向？',
					confirm: '确认与对方建立对接？',
					cancel: '确认取消该对接？',
					complete: '确认本次对接已完成？'
				}
				return titles[this.confirmOp] || '确认操作？'
			}
		},
		onLoad(options) {
			const type = options.type || 'demand'
			const id = options.id || ''
			this.type = type
			this.intentId = options.intentId || ''

			uni.setNavigationBarTitle({
				title: type === 'result' ? '成果对接' : '需求对接'
			})

			if (type === 'demand') {
				this.loadDemandDetail(id)
			} else {
				this.loadResultDetail(id)
			}
			this.loadFavoriteState(id)
			this.loadIntent(id)
		},
		onUnload() {
			this.clearConfirmTimer()
		},
		onShow() {
			if (this.detail) this.loadIntent(this.detail.id)
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
				} catch (e) {
					console.error('[dock-detail] loadDemand failed:', e)
					uni.showToast({ title: (e && e.message) || '未找到对应信息', icon: 'none' })
					setTimeout(() => uni.navigateBack(), 1200)
				}
			},
			async loadResultDetail(id) {
				if (!id) {
					uni.showToast({ title: '未找到对应信息', icon: 'none' })
					setTimeout(() => uni.navigateBack(), 1200)
					return
				}
				try {
					const data = await getAchievementDetail(id)
					if (!data) throw new Error('未找到对应信息')
					this.detail = {
						id: data.id,
						title: data.title,
						source: data.sourceOrgName || '未填写',
						price: formatAchPrice(data),
						techIntro: data.techIntro || '',
						purpose: (data.applicationFields || []).join(' / ') || '未填写',
						techPath: data.techRoute || '未填写',
						patentHolder: (data.inventors || []).map((v) => v.name).join('、') || '未填写',
						patentNo: '详见成果详情',
						maturity: data.maturityDesc || data.maturityLevel || '未填写',
						contactName: data.contactName || '暂无',
						contactTitle: data.contactTitle || '',
						phone: data.contactPhone || '',
						email: data.contactEmail || '',
						wechat: data.contactWechat || '',
						isMine: false
					}
				} catch (e) {
					console.error('[dock-detail] loadResult failed:', e)
					uni.showToast({ title: (e && e.message) || '未找到对应信息', icon: 'none' })
					setTimeout(() => uni.navigateBack(), 1200)
				}
			},
			async loadFavoriteState(id) {
				if (!id) return
				try {
					const set = await getFavoriteIdSet(this.type)
					this.favorited = set.has(String(parseInt(id, 10)))
				} catch (e) {
					this.favorited = false
				}
			},
			async loadIntent(id) {
				try {
					if (this.intentId) {
						this.intention = await getCooperationDetail(this.intentId)
						this.intentId = String(this.intention.id)
						return
					}
					if (!id) return
					this.intention = await getMyActiveIntentForTarget(this.type, id)
					this.intentId = this.intention ? String(this.intention.id) : ''
				} catch (e) {
					// 无权限或网络异常时按无意向处理（发起按钮可重试）
					console.error('[dock-detail] loadIntent failed:', e)
					this.intention = null
				}
			},
			clearConfirmTimer() {
				if (this.confirmTimer) {
					clearInterval(this.confirmTimer)
					this.confirmTimer = null
				}
			},
			openConfirm(op) {
				if (!ensureLoginForDock()) return
				if (!this.intention) return
				this.clearConfirmTimer()
				this.confirmOp = op
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
			async onConfirmAction() {
				if (!this.confirmReady || !this.intention) return
				const intentId = this.intention.id
				const version = this.intention.version
				const op = this.confirmOp
				this.closeConfirm()
				try {
					let next = null
					if (op === 'accept') {
						next = await acceptCooperation(intentId, version)
					} else if (op === 'reject') {
						next = await rejectCooperation(intentId, version, '对方拒绝了该对接意向')
					} else if (op === 'confirm') {
						next = await confirmCooperation(intentId, version)
					} else if (op === 'cancel') {
						next = await cancelCooperation(intentId, version, '取消对接')
					} else if (op === 'complete') {
						next = await completeCooperation(intentId, version)
					}
					if (next) {
						this.intention = next
						uni.showToast({ title: ACTION_TIPS[next.status] || '操作成功', icon: 'none' })
					}
				} catch (e) {
					console.error('[dock-detail] onConfirmAction failed:', e)
					uni.showToast({ title: (e && e.message) || '操作失败', icon: 'none' })
					this.loadIntent(this.detail.id)
				}
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
				if (text.indexOf('*') >= 0) {
					uni.showToast({ title: '联系方式已脱敏，正式对接后可见', icon: 'none' })
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
			async onToggleFavorite() {
				if (!ensureLoginForDock()) return
				if (!this.detail) return
				const next = !this.favorited
				this.favorited = next
				try {
					if (next) {
						await addFavorite(this.type, this.detail.id)
					} else {
						await removeFavorite(this.type, this.detail.id)
					}
					uni.showToast({ title: next ? '已收藏' : '已取消收藏', icon: 'none' })
				} catch (e) {
					this.favorited = !next
					uni.showToast({ title: (e && e.message) || '操作失败', icon: 'none' })
				}
			},
			async onCancelPending() {
				if (!ensureLoginForDock()) return
				if (!this.intention) return
				try {
					await cancelCooperation(this.intention.id, this.intention.version, '发起方取消对接')
					this.intention = null
					this.intentId = ''
					uni.showToast({ title: '已取消对接', icon: 'none' })
				} catch (e) {
					console.error('[dock-detail] onCancelPending failed:', e)
					uni.showToast({ title: (e && e.message) || '取消失败', icon: 'none' })
					this.loadIntent(this.detail.id)
				}
			},
			/** 发起对接：先选合作意向（每次对接的角色由当次选择决定，与账号画像无关） */
			onProposeDock() {
				if (!ensureLoginForDock()) return
				if (!this.detail) return
				if (!canProposeDock(this.type, this.detail)) {
					uni.showToast({
						title: getDockBlockMessage(this.type, this.detail) || '无法对接',
						icon: 'none'
					})
					return
				}
				this.selectedIntentType = ''
				this.intentMessage = ''
				this.intentDialogVisible = true
			},
			closeIntentDialog() {
				this.intentDialogVisible = false
			},
			onIntentMsgInput(e) {
				this.intentMessage = (e.detail.value || '').slice(0, 200)
			},
			async onSubmitIntent() {
				if (!this.selectedIntentType || !this.detail || this.submitting) return
				this.submitting = true
				const message = (this.intentMessage || '').trim()
				try {
					const intention = await createCooperation({
						type: this.type,
						id: this.detail.id,
						intentType: this.selectedIntentType,
						message: message || '希望就「' + this.detail.title + '」与您对接，盼回复。'
					})
					this.intention = intention
					this.intentId = String(intention.id)
					this.intentDialogVisible = false
					uni.showToast({ title: '对接意向已提交', icon: 'success' })
				} catch (e) {
					console.error('[dock-detail] onSubmitIntent failed:', e)
					uni.showToast({ title: (e && e.message) || '提交失败，请稍后重试', icon: 'none' })
					this.intentDialogVisible = false
					// 已有进行中意向等场景：刷新为意向态展示
					this.loadIntent(this.detail.id)
				} finally {
					this.submitting = false
				}
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

	.intent-type-bar {
		display: flex;
		flex-direction: row;
		align-items: center;
		background: #ffffff;
		border: 1rpx solid #e8ecf2;
		border-radius: 12rpx;
		padding: 20rpx 28rpx;
		margin-bottom: 16rpx;
	}

	.intent-type-label {
		font-size: 24rpx;
		color: #999999;
		margin-right: 16rpx;
	}

	.intent-type-value {
		font-size: 26rpx;
		color: #2b73f8;
		font-weight: 600;
	}

	/* 合作意向选择弹层（底部弹出） */
	.sheet {
		position: absolute;
		left: 0;
		right: 0;
		bottom: 0;
		background: #ffffff;
		border-radius: 24rpx 24rpx 0 0;
		padding: 32rpx 32rpx calc(24rpx + env(safe-area-inset-bottom));
		box-sizing: border-box;
	}

	.sheet-title {
		display: block;
		font-size: 32rpx;
		font-weight: 600;
		color: #1a1a1a;
		margin-bottom: 8rpx;
	}

	.sheet-sub {
		display: block;
		font-size: 24rpx;
		color: #999999;
		margin-bottom: 24rpx;
		overflow: hidden;
		white-space: nowrap;
		text-overflow: ellipsis;
	}

	.sheet-scroll {
		max-height: 420rpx;
	}

	.sheet-option {
		display: flex;
		flex-direction: row;
		align-items: center;
		justify-content: space-between;
		height: 88rpx;
		padding: 0 24rpx;
		background: #f7f9fc;
		border-radius: 12rpx;
		margin-bottom: 12rpx;
	}

	.sheet-option.active {
		background: rgba(43, 115, 248, 0.12);
	}

	.sheet-option-text {
		font-size: 28rpx;
		color: #333333;
	}

	.sheet-option.active .sheet-option-text {
		color: #2b73f8;
		font-weight: 600;
	}

	.sheet-option-check {
		font-size: 30rpx;
		color: #2b73f8;
		font-weight: 600;
	}

	.sheet-msg {
		margin-top: 8rpx;
		margin-bottom: 24rpx;
	}

	.sheet-msg-label {
		display: block;
		font-size: 24rpx;
		color: #999999;
		margin-bottom: 10rpx;
	}

	.sheet-textarea {
		width: 100%;
		height: 120rpx;
		background: #f7f9fc;
		border-radius: 12rpx;
		padding: 16rpx 20rpx;
		font-size: 26rpx;
		box-sizing: border-box;
	}

	.sheet-btn {
		background: #c8c8c8 !important;
		color: #ffffff !important;
		border-radius: 12rpx;
		font-size: 30rpx;
		margin-bottom: 12rpx;
	}

	.sheet-btn.ready {
		background: #2b73f8 !important;
	}

	.sheet-cancel {
		background: transparent !important;
		color: #888888 !important;
		font-size: 28rpx;
	}
</style>
