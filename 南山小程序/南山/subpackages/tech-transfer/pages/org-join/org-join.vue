<template>
	<view class="page">
		<view class="card">
			<text class="card-title">搜索并选择您的机构</text>
			<text class="card-desc">认证机构由平台机构目录统一管理，请搜索后选择所在机构提交申请，通过机构管理员审核后完成认证</text>

			<view class="search-row">
				<input
					class="search-input"
					:value="keyword"
					placeholder="输入机构名称搜索"
					confirm-type="search"
					@input="onKeywordInput"
					@confirm="doSearch"
				/>
				<button class="search-btn" type="primary" size="mini" @click="doSearch">搜索</button>
			</view>

			<view v-if="searched && !loading && candidates.length === 0" class="empty-box">
				<text class="empty-text">没有找到我的机构？</text>
				<text class="empty-link" @click="goApplyNew">申请新增机构</text>
			</view>

			<view v-if="loading" class="loading-text">搜索中...</view>

			<view v-if="candidates.length" class="org-list">
				<view
					v-for="org in candidates"
					:key="org.id"
					:class="selectedOrg && selectedOrg.id === org.id ? 'org-item active' : 'org-item'"
					@click="selectOrg(org)"
				>
					<text class="org-name">{{ org.name }}</text>
					<text class="org-kind">{{ kindLabel(org.kind) }}</text>
				</view>
			</view>
			<view v-if="selectedOrg" class="selected-tip">已选择：{{ selectedOrg.name }}</view>
		</view>

		<view v-if="selectedOrg" class="card">
			<text class="card-title">申请信息</text>
			<view class="form-item">
				<text class="label">真实姓名 <text class="required">*</text></text>
				<input class="input" :value="form.realName" placeholder="请输入真实姓名" @input="onFieldInput('realName', $event)" />
			</view>
			<view class="form-item">
				<text class="label">部门</text>
				<input class="input" :value="form.department" placeholder="请输入所在部门" @input="onFieldInput('department', $event)" />
			</view>
			<view class="form-item">
				<text class="label">职务</text>
				<input class="input" :value="form.title" placeholder="请输入职务" @input="onFieldInput('title', $event)" />
			</view>
			<view class="form-item">
				<text class="label">工作邮箱</text>
				<input class="input" :value="form.workEmail" placeholder="请输入工作邮箱" @input="onFieldInput('workEmail', $event)" />
			</view>
			<view class="form-item">
				<text class="label">证明材料说明</text>
				<textarea class="textarea" :value="form.proofMaterial" placeholder="如工牌、在职证明、企业邮箱等说明（文字描述）" @input="onFieldInput('proofMaterial', $event)" />
			</view>
			<view class="form-item">
				<text class="label">申请说明</text>
				<textarea class="textarea" :value="form.applyNote" placeholder="补充说明（选填）" @input="onFieldInput('applyNote', $event)" />
			</view>

			<button class="submit-btn" type="primary" :disabled="submitting" @click="onSubmit">
				{{ submitting ? '提交中...' : '提交申请' }}
			</button>
		</view>
	</view>
</template>

<script>
	import { searchInstitutions, applyMembership } from '../../api/membership.js'
	import { isLoggedIn } from '../../api/user.js'
	import HostBridge from '../../../../host/host-bridge.js'

	const KIND_LABELS = {
		platform: '平台载体',
		university: '高校院所',
		institute: '科研院所',
		enterprise: '企业',
		service: '服务机构',
		invest: '投资机构'
	}

	export default {
		data() {
			return {
				keyword: '',
				searched: false,
				loading: false,
				candidates: [],
				selectedOrg: null,
				submitting: false,
				form: {
					realName: '',
					department: '',
					title: '',
					workEmail: '',
					proofMaterial: '',
					applyNote: ''
				}
			}
		},
		onShow() {
			if (!isLoggedIn()) {
				uni.showToast({ title: '请先登录', icon: 'none' })
				setTimeout(() => uni.navigateBack(), 800)
			}
		},
		methods: {
			kindLabel(kind) {
				return KIND_LABELS[kind] || '机构'
			},
			onKeywordInput(e) {
				this.keyword = e.detail.value
			},
			onFieldInput(key, e) {
				this.form[key] = e.detail.value
			},
			async doSearch() {
				const kw = (this.keyword || '').trim()
				if (!kw) {
					uni.showToast({ title: '请输入机构名称', icon: 'none' })
					return
				}
				this.loading = true
				this.searched = true
				try {
					const data = await searchInstitutions(kw, 1, 20)
					this.candidates = data.list || []
				} catch (e) {
					this.candidates = []
					uni.showToast({ title: (e && e.message) || '搜索失败', icon: 'none' })
				} finally {
					this.loading = false
				}
			},
			selectOrg(org) {
				this.selectedOrg = this.selectedOrg && this.selectedOrg.id === org.id ? null : org
			},
			goApplyNew() {
				HostBridge.navigate('pages/org-apply/org-apply')
			},
			async onSubmit() {
				if (!this.selectedOrg) {
					uni.showToast({ title: '请先选择机构', icon: 'none' })
					return
				}
				const realName = (this.form.realName || '').trim()
				if (!realName) {
					uni.showToast({ title: '请填写真实姓名', icon: 'none' })
					return
				}
				this.submitting = true
				uni.showLoading({ title: '提交中', mask: true })
				try {
					await applyMembership({
						orgId: this.selectedOrg.id,
						realName,
						department: (this.form.department || '').trim() || undefined,
						title: (this.form.title || '').trim() || undefined,
						workEmail: (this.form.workEmail || '').trim() || undefined,
						proofMaterial: (this.form.proofMaterial || '').trim() || undefined,
						applyNote: (this.form.applyNote || '').trim() || undefined
					})
					uni.hideLoading()
					uni.showToast({ title: '已提交，等待机构管理员审核', icon: 'none', duration: 2000 })
					setTimeout(() => uni.navigateBack(), 1200)
				} catch (e) {
					uni.hideLoading()
					uni.showToast({ title: (e && e.message) || '提交失败，请稍后重试', icon: 'none', duration: 2500 })
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
		background: #f5f6f8;
		padding: 24rpx;
		padding-bottom: calc(40rpx + env(safe-area-inset-bottom));
		box-sizing: border-box;
	}

	.card {
		background: #ffffff;
		border-radius: 16rpx;
		padding: 32rpx;
		border: 1rpx solid #e8ecf2;
		margin-bottom: 24rpx;
	}

	.card-title {
		display: block;
		font-size: 32rpx;
		font-weight: 600;
		color: #1a1a1a;
		margin-bottom: 10rpx;
	}

	.card-desc {
		display: block;
		font-size: 24rpx;
		color: #999999;
		line-height: 1.6;
		margin-bottom: 24rpx;
	}

	.search-row {
		display: flex;
		flex-direction: row;
		align-items: center;
		margin-bottom: 20rpx;
	}

	.search-input {
		flex: 1;
		height: 76rpx;
		background: #f7f9fc;
		border-radius: 12rpx;
		padding: 0 24rpx;
		font-size: 28rpx;
		margin-right: 16rpx;
	}

	.search-btn {
		margin: 0;
		background: #2b73f8;
		color: #ffffff;
		border-radius: 12rpx;
		font-size: 26rpx;
		height: 76rpx;
		line-height: 76rpx;
		padding: 0 28rpx;
	}

	.loading-text {
		text-align: center;
		font-size: 24rpx;
		color: #999999;
		padding: 20rpx 0;
	}

	.empty-box {
		text-align: center;
		padding: 32rpx 0;
	}

	.empty-text {
		display: block;
		font-size: 26rpx;
		color: #666666;
		margin-bottom: 12rpx;
	}

	.empty-link {
		font-size: 28rpx;
		color: #2b73f8;
		font-weight: 600;
	}

	.org-list {
		display: flex;
		flex-direction: column;
	}

	.org-item {
		display: flex;
		flex-direction: row;
		align-items: center;
		justify-content: space-between;
		background: #f7f9fc;
		border: 1rpx solid #e8ecf2;
		border-radius: 12rpx;
		padding: 22rpx 24rpx;
		margin-bottom: 14rpx;
	}

	.org-item.active {
		border-color: #2b73f8;
		background: rgba(43, 115, 248, 0.08);
	}

	.org-name {
		flex: 1;
		font-size: 28rpx;
		color: #222222;
	}

	.org-kind {
		font-size: 22rpx;
		color: #666666;
		background: #eef2f8;
		padding: 4rpx 12rpx;
		border-radius: 8rpx;
		margin-left: 16rpx;
	}

	.selected-tip {
		margin-top: 8rpx;
		font-size: 24rpx;
		color: #2b73f8;
	}

	.form-item {
		margin-bottom: 22rpx;
	}

	.label {
		display: block;
		font-size: 28rpx;
		color: #333333;
		margin-bottom: 10rpx;
	}

	.required {
		color: #e74c3c;
	}

	.input {
		height: 80rpx;
		background: #f7f9fc;
		border-radius: 12rpx;
		padding: 0 24rpx;
		font-size: 28rpx;
	}

	.textarea {
		width: 100%;
		min-height: 140rpx;
		background: #f7f9fc;
		border-radius: 12rpx;
		padding: 20rpx 24rpx;
		font-size: 28rpx;
		box-sizing: border-box;
	}

	.submit-btn {
		margin-top: 12rpx;
		background: #2b73f8;
		color: #ffffff;
		border-radius: 12rpx;
	}
</style>
