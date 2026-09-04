<template>
  <view class="mine-page">
    <!-- 未加载 -->
    <view v-if="loading" class="loading-box">
      <text>正在加载...</text>
    </view>

    <!-- 已加载：个人资料 -->
    <view v-else-if="user" class="profile-box">
      <view class="avatar-box">
        <image class="avatar" src="/static/logo.png" mode="aspectFill" />
      </view>
      <view class="info-row">
        <text class="label">姓名</text>
        <text class="value">{{ user.displayName || '未填写' }}</text>
      </view>
      <view class="info-row">
        <text class="label">用户编号</text>
        <text class="value">{{ user.userNo }}</text>
      </view>
      <view class="info-row">
        <text class="label">主体类型</text>
        <text class="value">{{ subjectTypeLabel || '未填写' }}</text>
      </view>
      <view class="info-row">
        <text class="label">合作方向</text>
        <view class="cap-tags">
          <text v-if="!capabilityLabels.length" class="value">未填写</text>
          <text v-for="label in capabilityLabels" :key="label" class="cap-tag">{{ label }}</text>
        </view>
      </view>
      <view class="info-row">
        <text class="label">手机号</text>
        <text class="value">{{ user.phone || '未填写' }}</text>
      </view>
      <view class="info-row">
        <text class="label">邮箱</text>
        <text class="value">{{ user.email || '未填写' }}</text>
      </view>
      <view class="info-row">
        <text class="label">职务</text>
        <text class="value">{{ user.orgTitle || '未填写' }}</text>
      </view>
      <view class="info-row">
        <text class="label">角色</text>
        <text class="value">{{ user.roles && user.roles.join(', ') }}</text>
      </view>

      <button class="btn-primary" @tap="editMode = !editMode">
        {{ editMode ? '取消编辑' : '编辑资料' }}
      </button>
      <button class="btn-secondary" @tap="handleLogout">退出登录</button>
    </view>

    <!-- 编辑模式 -->
    <view v-if="editMode && user" class="edit-box">
      <view class="edit-title">编辑个人资料</view>
      <view class="form-row">
        <text class="form-label">姓名</text>
        <input class="form-input" v-model="form.displayName" placeholder="请输入姓名" />
      </view>
      <view class="form-row">
        <text class="form-label">主体类型</text>
        <picker :value="subjectTypeIndex" :range="subjectPickerOptions" range-key="label" @change="onSubjectTypeChange">
          <view class="form-picker">{{ subjectTypeText || '请选择主体类型' }}</view>
        </picker>
      </view>
      <view class="form-row">
        <text class="form-label">合作方向（可多选，用于内容推荐）</text>
        <view class="cap-row">
          <view
            v-for="opt in capabilityOptions"
            :key="opt.value"
            :class="form.businessCapabilities.indexOf(opt.value) >= 0 ? 'cap-btn active' : 'cap-btn'"
            @tap="toggleCapability(opt.value)"
          >{{ opt.label }}</view>
        </view>
      </view>
      <view class="form-row">
        <text class="form-label">手机号</text>
        <input class="form-input" v-model="form.phone" placeholder="请输入手机号" />
      </view>
      <view class="form-row">
        <text class="form-label">邮箱</text>
        <input class="form-input" v-model="form.email" placeholder="请输入邮箱" />
      </view>
      <view class="form-row">
        <text class="form-label">职务</text>
        <input class="form-input" v-model="form.orgTitle" placeholder="请输入职务" />
      </view>
      <button class="btn-primary" @tap="handleSave" :disabled="saving">
        {{ saving ? '保存中...' : '保存' }}
      </button>
    </view>

    <!-- 未登录 -->
    <view v-if="!loading && !user" class="login-box">
      <text class="login-tip">本地开发环境，点击下方按钮自动登录</text>
      <button class="btn-primary" @tap="handleLogin">进入科转通</button>
    </view>
  </view>
</template>

<script>
import { getCachedUser, getCurrentUser, updateMyProfile, logout } from '../../../../common/me-api.js'
import {
  SUBJECT_TYPE_OPTIONS,
  CAPABILITY_OPTIONS,
  getSubjectTypeLabel,
  getCapabilityLabels,
  normalizeCapabilities,
} from '../../../../common/user.js'

export default {
  data() {
    return {
      loading: true,
      user: null,
      editMode: false,
      saving: false,
      form: {
        displayName: '',
        subjectType: '',
        businessCapabilities: [],
        phone: '',
        email: '',
        orgTitle: '',
      },
      capabilityOptions: CAPABILITY_OPTIONS,
    }
  },
  computed: {
    subjectTypeLabel() {
      return getSubjectTypeLabel(this.user?.subjectType)
    },
    capabilityLabels() {
      return getCapabilityLabels(this.user?.businessCapabilities || [])
    },
    subjectPickerOptions() {
      return [{ label: '请选择主体类型', value: '' }].concat(SUBJECT_TYPE_OPTIONS)
    },
    subjectTypeIndex() {
      const idx = this.subjectPickerOptions.findIndex((o) => o.value === this.form.subjectType)
      return idx >= 0 ? idx : 0
    },
    subjectTypeText() {
      return getSubjectTypeLabel(this.form.subjectType)
    },
  },
  async onShow() {
    await this.loadUser()
  },
  methods: {
    async loadUser() {
      this.loading = true
      try {
        const cached = getCachedUser()
        if (cached) {
          this.user = cached
          this.syncForm()
        }
        const fresh = await getCurrentUser()
        this.user = fresh
        this.syncForm()
      } catch (e) {
        console.error('[mine] loadUser failed:', e)
        this.user = null
      } finally {
        this.loading = false
      }
    },
    syncForm() {
      if (!this.user) return
      this.form = {
        displayName: this.user.displayName || '',
        subjectType: this.user.subjectType || '',
        businessCapabilities: normalizeCapabilities(this.user.businessCapabilities || []),
        phone: this.user.phone || '',
        email: this.user.email || '',
        orgTitle: this.user.orgTitle || '',
      }
    },
    onSubjectTypeChange(e) {
      const opt = this.subjectPickerOptions[Number(e.detail.value)] || this.subjectPickerOptions[0]
      this.form.subjectType = opt ? opt.value : ''
    },
    toggleCapability(value) {
      const idx = this.form.businessCapabilities.indexOf(value)
      if (idx >= 0) {
        this.form.businessCapabilities.splice(idx, 1)
      } else {
        this.form.businessCapabilities.push(value)
      }
    },
    async handleLogin() {
      this.loading = true
      try {
        const user = await getCurrentUser()
        this.user = user
        this.syncForm()
      } catch (e) {
        uni.showToast({ title: '登录失败: ' + (e.message || ''), icon: 'none' })
      } finally {
        this.loading = false
      }
    },
    async handleSave() {
      if (!this.user) return
      this.saving = true
      try {
        const updated = await updateMyProfile({
          ...this.form,
          version: this.user.version,
        })
        this.user = updated
        this.editMode = false
        uni.showToast({ title: '保存成功', icon: 'success' })
      } catch (e) {
        uni.showToast({ title: '保存失败: ' + (e.message || ''), icon: 'none' })
      } finally {
        this.saving = false
      }
    },
    async handleLogout() {
      try {
        await logout()
        this.user = null
        this.editMode = false
        uni.showToast({ title: '已退出', icon: 'success' })
      } catch (e) {
        uni.showToast({ title: '退出失败', icon: 'none' })
      }
    },
  },
}
</script>

<style scoped>
.mine-page {
  min-height: 100vh;
  background: #F5F6F8;
  padding: 24rpx;
}
.loading-box, .login-box {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 120rpx 0;
}
.login-tip {
  font-size: 28rpx;
  color: #999;
  margin-bottom: 40rpx;
}
.profile-box, .edit-box {
  background: #fff;
  border-radius: 16rpx;
  padding: 32rpx;
  margin-bottom: 24rpx;
}
.avatar-box {
  display: flex;
  justify-content: center;
  margin-bottom: 32rpx;
}
.avatar {
  width: 120rpx;
  height: 120rpx;
  border-radius: 60rpx;
}
.info-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 20rpx 0;
  border-bottom: 1rpx solid #f0f0f0;
}
.label {
  font-size: 28rpx;
  color: #999;
  flex-shrink: 0;
}
.value {
  font-size: 28rpx;
  color: #333;
  text-align: right;
}
.cap-tags {
  display: flex;
  flex-direction: row;
  flex-wrap: wrap;
  justify-content: flex-end;
}
.cap-tag {
  font-size: 22rpx;
  color: #0f9d58;
  background: rgba(15, 157, 88, 0.1);
  padding: 4rpx 12rpx;
  border-radius: 8rpx;
  margin: 4rpx 0 4rpx 10rpx;
}
.edit-title {
  font-size: 32rpx;
  font-weight: bold;
  margin-bottom: 24rpx;
}
.form-row {
  margin-bottom: 24rpx;
}
.form-label {
  display: block;
  font-size: 24rpx;
  color: #999;
  margin-bottom: 8rpx;
}
.form-input {
  width: 100%;
  height: 72rpx;
  border: 1rpx solid #e0e0e0;
  border-radius: 8rpx;
  padding: 0 20rpx;
  font-size: 28rpx;
}
.form-picker {
  height: 72rpx;
  line-height: 72rpx;
  border: 1rpx solid #e0e0e0;
  border-radius: 8rpx;
  padding: 0 20rpx;
  font-size: 28rpx;
  color: #333;
}
.cap-row {
  display: flex;
  flex-direction: row;
  flex-wrap: wrap;
}
.cap-btn {
  height: 64rpx;
  line-height: 64rpx;
  padding: 0 26rpx;
  text-align: center;
  background: #f7f9fc;
  border-radius: 32rpx;
  margin: 0 16rpx 16rpx 0;
  font-size: 26rpx;
  color: #666;
}
.cap-btn.active {
  background: rgba(43, 115, 248, 0.12);
  color: #2b73f8;
  font-weight: 600;
}
.btn-primary {
  width: 100%;
  height: 88rpx;
  line-height: 88rpx;
  background: #2B73F8;
  color: #fff;
  border-radius: 8rpx;
  font-size: 32rpx;
  margin-top: 24rpx;
}
.btn-secondary {
  width: 100%;
  height: 88rpx;
  line-height: 88rpx;
  background: #fff;
  color: #f44336;
  border: 1rpx solid #f44336;
  border-radius: 8rpx;
  font-size: 32rpx;
  margin-top: 16rpx;
}
</style>
