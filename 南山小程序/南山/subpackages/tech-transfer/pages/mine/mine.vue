<template>
  <view class="mine-page">
    <!-- 未加载 -->
    <view v-if="loading" class="loading-box">
      <text>正在加载...</text>
    </view>

    <!-- 已加载 -->
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
        <text class="label">身份类型</text>
        <text class="value">{{ userTypeLabel }}</text>
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
        <text class="form-label">身份类型</text>
        <picker :value="userTypeIndex" :range="userTypeOptions" range-key="label" @change="onTypeChange">
          <view class="form-picker">{{ userTypeOptions[userTypeIndex].label }}</view>
        </picker>
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
    <view v-else class="login-box">
      <text class="login-tip">本地开发环境，点击下方按钮自动登录</text>
      <button class="btn-primary" @tap="handleLogin">进入科转通</button>
    </view>
  </view>
</template>

<script>
import { getCachedUser, getCurrentUser, updateMyProfile, logout } from '../../api/me.js'
import { TT_COMMON_40902 } from '../../constants/error-codes.js'

const USER_TYPE_OPTIONS = [
  { label: '请选择', value: '' },
  { label: '企业人员', value: 'enterprise_staff' },
  { label: '科研人员', value: 'researcher' },
  { label: '投资人', value: 'investor' },
  { label: '服务机构', value: 'service_org' },
  { label: '其他', value: 'other' },
]

export default {
  data() {
    return {
      loading: true,
      user: null,
      editMode: false,
      saving: false,
      form: {
        displayName: '',
        userType: '',
        phone: '',
        email: '',
        orgTitle: '',
      },
      userTypeOptions: USER_TYPE_OPTIONS,
    }
  },
  computed: {
    userTypeLabel() {
      const t = this.user?.userType
      const found = USER_TYPE_OPTIONS.find((o) => o.value === t)
      return found ? found.label : '未填写'
    },
    userTypeIndex() {
      const t = this.form.userType
      return USER_TYPE_OPTIONS.findIndex((o) => o.value === t)
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
        userType: this.user.userType || '',
        phone: this.user.phone || '',
        email: this.user.email || '',
        orgTitle: this.user.orgTitle || '',
      }
    },
    onTypeChange(e) {
      const idx = e.detail.value
      this.form.userType = USER_TYPE_OPTIONS[idx].value
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
        if (e.code === TT_COMMON_40902) {
          uni.showToast({ title: '数据已变更，请刷新后重试', icon: 'none' })
          await this.loadUser()
        } else {
          uni.showToast({ title: '保存失败: ' + (e.message || ''), icon: 'none' })
        }
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
}
.value {
  font-size: 28rpx;
  color: #333;
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
