<template>
	<view class="page">
		<view v-if="!loadingOrgs && adminOrgs.length === 0" class="empty-card">
			<text class="empty-title">您还不是机构管理员</text>
			<text class="empty-desc">机构管理员由平台授予，可管理本机构成员认证。普通成员认证请在「我的-机构认证」中申请</text>
		</view>

		<view v-if="adminOrgs.length" class="org-bar">
			<view
				v-for="org in adminOrgs"
				:key="org.orgId"
				:class="currentOrgId === org.orgId ? 'org-chip active' : 'org-chip'"
				@click="switchOrg(org.orgId)"
			>{{ org.orgName }}</view>
		</view>

		<view v-if="currentOrgId" class="card">
			<view class="tab-row">
				<view :class="tab === 'members' ? 'tab active' : 'tab'" @click="switchTab('members')">成员管理</view>
				<view :class="tab === 'applications' ? 'tab active' : 'tab'" @click="switchTab('applications')">
					申请审核<text v-if="pendingCount" class="tab-badge">{{ pendingCount }}</text>
				</view>
			</view>

			<view v-if="tab === 'members'" class="list-wrap">
				<view v-if="!members.length && !loadingList" class="list-empty">暂无成员</view>
				<view v-for="m in members" :key="m.id" class="member-item">
					<view class="member-info">
						<text class="member-name">{{ m.userNo || ('成员 #' + m.id) }}</text>
						<text class="member-meta">
							<text :class="m.role === 'admin' ? 'role-tag admin' : 'role-tag'">{{ m.role === 'admin' ? '管理员' : '成员' }}</text>
							<text v-if="m.department" class="member-dept">{{ m.department }}</text>
						</text>
					</view>
					<button
						v-if="m.role === 'member'"
						class="mini-btn danger"
						size="mini"
						@click="openRevoke(m)"
					>撤销</button>
				</view>
			</view>

			<view v-if="tab === 'applications'" class="list-wrap">
				<view v-if="!applications.length && !loadingList" class="list-empty">暂无待审核申请</view>
				<view v-for="a in applications" :key="a.id" class="member-item">
					<view class="member-info">
						<text class="member-name">{{ a.realName || a.userNo || ('申请 #' + a.id) }}</text>
						<text class="member-meta">
							<text v-if="a.department" class="member-dept">{{ a.department }}</text>
							<text v-if="a.title" class="member-dept">{{ a.title }}</text>
						</text>
						<text v-if="a.proofMaterial" class="proof-text">证明：{{ a.proofMaterial }}</text>
						<text v-if="a.applyNote" class="proof-text">说明：{{ a.applyNote }}</text>
					</view>
					<view class="action-row">
						<button class="mini-btn primary" size="mini" @click="approve(a)">通过</button>
						<button class="mini-btn danger" size="mini" @click="openReject(a)">驳回</button>
					</view>
				</view>
			</view>
		</view>

		<view v-if="dialogVisible" class="dialog-mask" @click="closeDialog">
			<view class="dialog-panel" @click.stop>
				<text class="dialog-title">{{ dialogTitle }}</text>
				<textarea class="dialog-textarea" :value="dialogReason" placeholder="请填写原因（必填）" @input="onReasonInput" />
				<view class="dialog-actions">
					<button class="dialog-btn cancel" @click="closeDialog">取消</button>
					<button class="dialog-btn confirm" :disabled="dialogSubmitting" @click="confirmDialog">
						{{ dialogSubmitting ? '提交中...' : '确认' }}
					</button>
				</view>
			</view>
		</view>
	</view>
</template>

<script>
	import {
		fetchCurrentUser,
		getOrgMembers,
		getOrgMembershipApplications,
		approveMembershipApplication,
		rejectMembershipApplication,
		revokeOrgMember
	} from '../../common/membership-api.js'
	import { isLoggedIn } from '../../common/user.js'

	export default {
		data() {
			return {
				loadingOrgs: true,
				adminOrgs: [],
				currentOrgId: 0,
				tab: 'members',
				members: [],
				applications: [],
				pendingCount: 0,
				loadingList: false,
				dialogVisible: false,
				dialogTitle: '',
				dialogReason: '',
				dialogSubmitting: false,
				dialogAction: null
			}
		},
		onShow() {
			if (!isLoggedIn()) {
				uni.showToast({ title: '请先登录', icon: 'none' })
				setTimeout(() => uni.navigateBack(), 800)
				return
			}
			this.loadAdminOrgs()
		},
		methods: {
			async loadAdminOrgs() {
				this.loadingOrgs = true
				try {
					const user = await fetchCurrentUser()
					const adminOrgs = ((user && user.organizationMemberships) || []).filter(
						(m) => m.role === 'admin' && m.status === 'active'
					)
					this.adminOrgs = adminOrgs
					if (!this.currentOrgId && adminOrgs.length) {
						this.currentOrgId = adminOrgs[0].orgId
						this.loadList()
					}
				} catch (e) {
					uni.showToast({ title: (e && e.message) || '加载失败', icon: 'none' })
				} finally {
					this.loadingOrgs = false
				}
			},
			switchOrg(orgId) {
				if (this.currentOrgId === orgId) return
				this.currentOrgId = orgId
				this.loadList()
			},
			switchTab(tab) {
				if (this.tab === tab) return
				this.tab = tab
				this.loadList()
			},
			async loadList() {
				if (!this.currentOrgId) return
				this.loadingList = true
				try {
					if (this.tab === 'members') {
						const data = await getOrgMembers(this.currentOrgId, { status: 'active', page: 1, pageSize: 50 })
						this.members = data.list || []
					} else {
						const data = await getOrgMembershipApplications(this.currentOrgId, { status: 'pending', page: 1, pageSize: 50 })
						this.applications = data.list || []
						this.pendingCount = data.total || 0
					}
				} catch (e) {
					uni.showToast({ title: (e && e.message) || '加载失败', icon: 'none', duration: 2500 })
					if (e && (e.code === 'TT_ADMIN_40301' || e.message === '非机构管理员')) {
						this.adminOrgs = []
						this.currentOrgId = 0
					}
				} finally {
					this.loadingList = false
				}
			},
			approve(a) {
				uni.showModal({
					title: '通过申请',
					content: `确认为该用户开通本机构成员身份？`,
					success: async (res) => {
						if (!res.confirm) return
						uni.showLoading({ title: '审核中', mask: true })
						try {
							await approveMembershipApplication(a.id, a.version)
							uni.hideLoading()
							uni.showToast({ title: '已通过', icon: 'success' })
							this.loadList()
						} catch (e) {
							uni.hideLoading()
							uni.showToast({ title: (e && e.message) || '操作失败', icon: 'none', duration: 2500 })
							this.loadList()
						}
					}
				})
			},
			openReject(a) {
				this.dialogAction = { type: 'reject', id: a.id, version: a.version }
				this.dialogTitle = '驳回申请'
				this.dialogReason = ''
				this.dialogVisible = true
			},
			openRevoke(m) {
				this.dialogAction = { type: 'revoke', id: m.id, version: m.version }
				this.dialogTitle = '撤销成员'
				this.dialogReason = ''
				this.dialogVisible = true
			},
			onReasonInput(e) {
				this.dialogReason = e.detail.value
			},
			closeDialog() {
				if (this.dialogSubmitting) return
				this.dialogVisible = false
				this.dialogAction = null
			},
			async confirmDialog() {
				const reason = (this.dialogReason || '').trim()
				if (!reason) {
					uni.showToast({ title: '请填写原因', icon: 'none' })
					return
				}
				const action = this.dialogAction
				if (!action) return
				this.dialogSubmitting = true
				uni.showLoading({ title: '提交中', mask: true })
				try {
					if (action.type === 'reject') {
						await rejectMembershipApplication(action.id, action.version, reason)
					} else {
						await revokeOrgMember(action.id, action.version, reason)
					}
					uni.hideLoading()
					uni.showToast({ title: '操作成功', icon: 'success' })
					this.dialogVisible = false
					this.dialogAction = null
					this.loadList()
				} catch (e) {
					uni.hideLoading()
					uni.showToast({ title: (e && e.message) || '操作失败', icon: 'none', duration: 2500 })
					this.dialogVisible = false
					this.dialogAction = null
					this.loadList()
				} finally {
					this.dialogSubmitting = false
				}
			}
		}
	}
</script>

<style>
	.page {
		min-height: 100vh;
		background: #f5f6f8;
		padding: 24rpx;
		padding-bottom: calc(40rpx + env(safe-area-inset-bottom));
		box-sizing: border-box;
	}

	.empty-card {
		background: #ffffff;
		border-radius: 16rpx;
		border: 1rpx solid #e8ecf2;
		padding: 48rpx 32rpx;
		text-align: center;
	}

	.empty-title {
		display: block;
		font-size: 30rpx;
		font-weight: 600;
		color: #333333;
		margin-bottom: 12rpx;
	}

	.empty-desc {
		display: block;
		font-size: 24rpx;
		color: #999999;
		line-height: 1.6;
	}

	.org-bar {
		display: flex;
		flex-direction: row;
		flex-wrap: wrap;
		margin-bottom: 20rpx;
	}

	.org-chip {
		height: 60rpx;
		line-height: 60rpx;
		padding: 0 26rpx;
		border-radius: 30rpx;
		background: #ffffff;
		border: 1rpx solid #e8ecf2;
		font-size: 26rpx;
		color: #666666;
		margin: 0 14rpx 14rpx 0;
	}

	.org-chip.active {
		background: rgba(43, 115, 248, 0.12);
		border-color: #2b73f8;
		color: #2b73f8;
		font-weight: 600;
	}

	.card {
		background: #ffffff;
		border-radius: 16rpx;
		padding: 24rpx;
		border: 1rpx solid #e8ecf2;
	}

	.tab-row {
		display: flex;
		flex-direction: row;
		border-bottom: 1rpx solid #eef0f4;
		margin-bottom: 20rpx;
	}

	.tab {
		position: relative;
		height: 76rpx;
		line-height: 76rpx;
		font-size: 28rpx;
		color: #666666;
		margin-right: 48rpx;
	}

	.tab.active {
		color: #2b73f8;
		font-weight: 600;
		border-bottom: 4rpx solid #2b73f8;
	}

	.tab-badge {
		position: absolute;
		top: 12rpx;
		right: -34rpx;
		min-width: 30rpx;
		height: 30rpx;
		line-height: 30rpx;
		padding: 0 8rpx;
		border-radius: 15rpx;
		background: #e74c3c;
		color: #ffffff;
		font-size: 20rpx;
		text-align: center;
	}

	.list-wrap {
		display: flex;
		flex-direction: column;
	}

	.list-empty {
		text-align: center;
		font-size: 24rpx;
		color: #999999;
		padding: 40rpx 0;
	}

	.member-item {
		display: flex;
		flex-direction: row;
		align-items: center;
		justify-content: space-between;
		background: #f7f9fc;
		border-radius: 12rpx;
		padding: 22rpx 24rpx;
		margin-bottom: 14rpx;
	}

	.member-info {
		flex: 1;
		min-width: 0;
		display: flex;
		flex-direction: column;
	}

	.member-name {
		font-size: 28rpx;
		color: #222222;
		font-weight: 600;
	}

	.member-meta {
		display: flex;
		flex-direction: row;
		align-items: center;
		margin-top: 8rpx;
	}

	.role-tag {
		font-size: 22rpx;
		color: #666666;
		background: #eef2f8;
		padding: 2rpx 12rpx;
		border-radius: 8rpx;
		margin-right: 12rpx;
	}

	.role-tag.admin {
		color: #2b73f8;
		background: rgba(43, 115, 248, 0.12);
	}

	.member-dept {
		font-size: 22rpx;
		color: #999999;
		margin-right: 12rpx;
	}

	.proof-text {
		margin-top: 8rpx;
		font-size: 22rpx;
		color: #666666;
		line-height: 1.5;
		word-break: break-all;
	}

	.action-row {
		display: flex;
		flex-direction: column;
		margin-left: 16rpx;
	}

	.mini-btn {
		margin: 4rpx 0;
		font-size: 24rpx;
		border-radius: 10rpx;
	}

	.mini-btn.primary {
		background: #2b73f8;
		color: #ffffff;
	}

	.mini-btn.danger {
		background: #ffffff;
		color: #e74c3c;
		border: 1rpx solid #e74c3c;
	}

	.dialog-mask {
		position: fixed;
		left: 0;
		right: 0;
		top: 0;
		bottom: 0;
		background: rgba(0, 0, 0, 0.45);
		z-index: 1000;
		display: flex;
		align-items: center;
		justify-content: center;
		padding: 48rpx;
	}

	.dialog-panel {
		width: 100%;
		background: #ffffff;
		border-radius: 16rpx;
		padding: 32rpx;
		box-sizing: border-box;
	}

	.dialog-title {
		display: block;
		font-size: 30rpx;
		font-weight: 600;
		color: #1a1a1a;
		margin-bottom: 20rpx;
	}

	.dialog-textarea {
		width: 100%;
		min-height: 140rpx;
		background: #f7f9fc;
		border-radius: 12rpx;
		padding: 20rpx 24rpx;
		font-size: 26rpx;
		box-sizing: border-box;
		margin-bottom: 24rpx;
	}

	.dialog-actions {
		display: flex;
		flex-direction: row;
	}

	.dialog-btn {
		flex: 1;
		margin: 0 8rpx;
		font-size: 28rpx;
		border-radius: 12rpx;
	}

	.dialog-btn.cancel {
		background: #ffffff;
		color: #666666;
		border: 1rpx solid #dddddd;
	}

	.dialog-btn.confirm {
		background: #2b73f8;
		color: #ffffff;
	}
</style>
