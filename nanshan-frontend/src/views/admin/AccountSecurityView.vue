<script setup>
import { onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '../../api/client'
import { alertDialog, confirmDialog } from '../../utils/appDialog.js'
import { useAuthStore } from '../../stores/auth'

const router = useRouter()
const authStore = useAuthStore()

const loading = ref(true)
const securityData = ref({
  passwordConfigured: true,
  wechatBound: false,
  phone: null,
  email: null,
  recentLogs: [],
})

// 弹窗状态
const bindModalVisible = ref(false)
const bindType = ref('phone') // 'phone' | 'email'
const bindLoading = ref(false)
const bindError = ref('')
const countdown = ref(0)
let timer = null

const bindForm = reactive({
  contactValue: '',
  challengeId: '',
  code: '',
})

const loadSecurity = async () => {
  loading.value = true
  try {
    const data = await api('/me/security')
    securityData.value = data
  } catch (err) {
    console.error('加载安全中心数据失败', err)
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  loadSecurity()
})

const openBindModal = (type) => {
  bindType.value = type
  bindError.value = ''
  bindForm.contactValue = ''
  bindForm.challengeId = ''
  bindForm.code = ''
  bindModalVisible.value = true
  if (timer) clearInterval(timer)
  countdown.value = 0
}

const handleSendBindCode = async () => {
  if (!bindForm.contactValue.trim()) {
    bindError.value = bindType.value === 'phone' ? '请输入11位手机号' : '请输入邮箱地址'
    return
  }
  bindLoading.value = true
  bindError.value = ''
  try {
    const res = await api('/me/security/contact/challenge', {
      method: 'POST',
      body: {
        contactType: bindType.value,
        contactValue: bindForm.contactValue.trim(),
      },
    })
    bindForm.challengeId = res.challengeId
    countdown.value = 60
    if (timer) clearInterval(timer)
    timer = setInterval(() => {
      if (countdown.value > 0) {
        countdown.value--
      } else {
        clearInterval(timer)
        timer = null
      }
    }, 1000)
  } catch (err) {
    bindError.value = err.message || '发送验证码失败'
  } finally {
    bindLoading.value = false
  }
}

const handleConfirmBind = async () => {
  if (!bindForm.code.trim()) {
    bindError.value = '请输入收到的验证码'
    return
  }
  bindLoading.value = true
  bindError.value = ''
  try {
    await api('/me/security/contact/verify', {
      method: 'POST',
      body: {
        challengeId: bindForm.challengeId,
        code: bindForm.code.trim(),
        contactValue: bindForm.contactValue.trim(),
      },
    })
    bindModalVisible.value = false
    await alertDialog({ title: '绑定成功', message: `安全${bindType.value === 'phone' ? '手机号' : '邮箱'}已成功确权绑定` })
    loadSecurity()
  } catch (err) {
    bindError.value = err.message || '核验绑定失败'
  } finally {
    bindLoading.value = false
  }
}

const handleRevokeAllSessions = async () => {
  const ok = await confirmDialog({
    title: '强制注销其他会话',
    message: '该操作将立即失效所有设备上的登录状态（包括当前会话），您需要使用密码重新登录。是否继续？',
  })
  if (!ok) return

  try {
    await api('/me/security/revoke-sessions', { method: 'POST' })
    await alertDialog({ title: '已安全下线', message: '所有会话已注销，请重新登录' })
    await authStore.logout()
    router.push('/login')
  } catch (err) {
    await alertDialog({ title: '操作失败', message: err.message || '注销失败' })
  }
}
</script>

<template>
  <div class="security-view">
    <div class="page-header">
      <h2>账号安全中心</h2>
      <p class="subtitle">管理您的登录密码、已确权安全联系方式及活跃登录会话</p>
    </div>

    <div v-if="loading" class="loading-box">正在加载安全配置…</div>

    <div v-else class="security-content">
      <!-- 密码与微信绑定状态卡片 -->
      <div class="card security-card">
        <h3 class="card-title">基本认证凭证</h3>
        <div class="item-row">
          <div class="item-info">
            <span class="item-label">登录密码</span>
            <span class="item-desc">用于后台管理系统及移动端密码登录</span>
          </div>
          <div class="item-status">
            <span class="status-badge active">{{ securityData.passwordConfigured ? '已设置' : '未设置（微信快捷）' }}</span>
          </div>
        </div>

        <div class="item-row">
          <div class="item-info">
            <span class="item-label">微信账号绑定</span>
            <span class="item-desc">绑定微信后可在移动端及 PC 扫码快捷登录</span>
          </div>
          <div class="item-status">
            <span class="status-badge" :class="securityData.wechatBound ? 'active' : 'inactive'">
              {{ securityData.wechatBound ? '已绑定' : '未绑定' }}
            </span>
          </div>
        </div>
      </div>

      <!-- 安全联系方式（确权用于找回密码）卡片 -->
      <div class="card security-card">
        <div class="card-head-row">
          <div>
            <h3 class="card-title">安全联系方式（用于密码恢复与二次验证）</h3>
            <p class="card-sub">仅完成双向验证的已确权联系方式才可用于找回密码</p>
          </div>
        </div>

        <div class="item-row">
          <div class="item-info">
            <span class="item-label">安全手机号</span>
            <span class="item-val">{{ securityData.phone ? securityData.phone.value : '尚未绑定已确权手机号' }}</span>
          </div>
          <div class="item-action">
            <button class="action-btn" @click="openBindModal('phone')">
              {{ securityData.phone ? '更换手机号' : '立即绑定' }}
            </button>
          </div>
        </div>

        <div class="item-row">
          <div class="item-info">
            <span class="item-label">安全邮箱</span>
            <span class="item-val">{{ securityData.email ? securityData.email.value : '尚未绑定已确权邮箱' }}</span>
          </div>
          <div class="item-action">
            <button class="action-btn" @click="openBindModal('email')">
              {{ securityData.email ? '更换邮箱' : '立即绑定' }}
            </button>
          </div>
        </div>
      </div>

      <!-- 会话安全管理卡片 -->
      <div class="card security-card">
        <h3 class="card-title">会话管理与安全保护</h3>
        <div class="item-row">
          <div class="item-info">
            <span class="item-label">登出所有设备</span>
            <span class="item-desc">若怀疑账号凭据泄露，可一键递增会话版本，立即失效全部旧 Token 与 Refresh 会话</span>
          </div>
          <div class="item-action">
            <button class="action-btn danger-btn" @click="handleRevokeAllSessions">退出全部会话</button>
          </div>
        </div>
      </div>

      <!-- 最近安全日志卡片 -->
      <div class="card security-card">
        <h3 class="card-title">最近安全审计日志</h3>
        <div v-if="!securityData.recentLogs || !securityData.recentLogs.length" class="empty-logs">
          暂无安全操作记录
        </div>
        <div v-else class="logs-list">
          <div v-for="(log, idx) in securityData.recentLogs" :key="idx" class="log-item">
            <span class="log-action">{{ log.action }}</span>
            <span class="log-resource">{{ log.resourceType }}</span>
            <span class="log-time">{{ log.createdAt ? log.createdAt.replace('T', ' ').slice(0, 19) : '' }}</span>
          </div>
        </div>
      </div>
    </div>

    <!-- 绑定联系方式弹窗 -->
    <div v-if="bindModalVisible" class="modal-mask" @click.self="bindModalVisible = false">
      <div class="modal-box">
        <h3>{{ bindType === 'phone' ? '绑定安全手机号' : '绑定安全邮箱' }}</h3>
        <p class="modal-tip">系统将发送一次性 6 位验证码以确权归属，完成验证后方可作为安全凭证使用。</p>

        <div class="form-item">
          <label>{{ bindType === 'phone' ? '手机号' : '邮箱地址' }}</label>
          <input
            v-model="bindForm.contactValue"
            type="text"
            class="input-control"
            :placeholder="bindType === 'phone' ? '请输入11位大陆手机号' : '请输入常用邮箱地址'"
            :disabled="bindLoading || countdown > 0"
          />
        </div>

        <div class="form-item">
          <label>验证码</label>
          <div class="code-row">
            <input
              v-model="bindForm.code"
              type="text"
              maxlength="6"
              class="input-control"
              placeholder="请输入6位验证码"
              :disabled="bindLoading"
            />
            <button
              type="button"
              class="code-btn"
              :disabled="countdown > 0 || bindLoading"
              @click="handleSendBindCode"
            >
              {{ countdown > 0 ? `${countdown}秒` : '获取验证码' }}
            </button>
          </div>
        </div>

        <p v-if="bindError" class="modal-error">{{ bindError }}</p>

        <div class="modal-btns">
          <button class="cancel-btn" :disabled="bindLoading" @click="bindModalVisible = false">取消</button>
          <button class="confirm-btn" :disabled="bindLoading" @click="handleConfirmBind">
            {{ bindLoading ? '处理中…' : '确认确权绑定' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.security-view {
  max-width: 980px;
  margin: 0 auto;
}
.page-header {
  margin-bottom: 24px;
}
.page-header h2 {
  font-size: 20px;
  color: #1e293b;
  margin-bottom: 6px;
}
.subtitle {
  font-size: 13px;
  color: #64748b;
}
.loading-box {
  padding: 40px;
  text-align: center;
  color: #64748b;
}
.security-card {
  background: #fff;
  border-radius: 8px;
  padding: 24px;
  margin-bottom: 20px;
  border: 1px solid #eef1f6;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.02);
}
.card-title {
  font-size: 16px;
  color: #1e293b;
  margin-bottom: 6px;
}
.card-sub {
  font-size: 12px;
  color: #94a3b8;
  margin-bottom: 16px;
}
.item-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 0;
  border-bottom: 1px solid #f1f5f9;
}
.item-row:last-child {
  border-bottom: none;
}
.item-info {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.item-label {
  font-size: 14px;
  font-weight: 500;
  color: #334155;
}
.item-desc, .item-val {
  font-size: 13px;
  color: #64748b;
}
.status-badge {
  display: inline-block;
  padding: 4px 10px;
  border-radius: 4px;
  font-size: 12px;
  font-weight: 500;
}
.status-badge.active {
  background: #ecfdf5;
  color: #10b981;
}
.status-badge.inactive {
  background: #f1f5f9;
  color: #94a3b8;
}
.action-btn {
  padding: 6px 14px;
  border: 1px solid #cbd5e1;
  background: #fff;
  color: #334155;
  border-radius: 4px;
  font-size: 13px;
  cursor: pointer;
  transition: all 0.2s;
}
.action-btn:hover {
  border-color: #0256ff;
  color: #0256ff;
}
.danger-btn {
  border-color: #fecaca;
  color: #ef4444;
}
.danger-btn:hover {
  background: #fef2f2;
  border-color: #ef4444;
}
.empty-logs {
  font-size: 13px;
  color: #94a3b8;
  padding: 12px 0;
}
.logs-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.log-item {
  display: flex;
  justify-content: space-between;
  font-size: 13px;
  padding: 8px 12px;
  background: #f8fafc;
  border-radius: 4px;
}
.log-action {
  font-weight: 500;
  color: #334155;
}
.log-resource {
  color: #64748b;
}
.log-time {
  color: #94a3b8;
}
.modal-mask {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.45);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}
.modal-box {
  width: 440px;
  background: #fff;
  border-radius: 8px;
  padding: 28px;
  box-shadow: 0 10px 25px rgba(0, 0, 0, 0.1);
}
.modal-box h3 {
  font-size: 18px;
  color: #1e293b;
  margin-bottom: 8px;
}
.modal-tip {
  font-size: 13px;
  color: #64748b;
  line-height: 1.5;
  margin-bottom: 20px;
}
.form-item {
  margin-bottom: 16px;
}
.form-item label {
  display: block;
  font-size: 13px;
  color: #334155;
  margin-bottom: 6px;
}
.input-control {
  width: 100%;
  padding: 10px 12px;
  border: 1px solid #cbd5e1;
  border-radius: 4px;
  font-size: 14px;
  box-sizing: border-box;
}
.code-row {
  display: flex;
  gap: 8px;
}
.code-btn {
  white-space: nowrap;
  padding: 0 14px;
  background: #f1f5f9;
  border: 1px solid #cbd5e1;
  border-radius: 4px;
  font-size: 13px;
  color: #475569;
  cursor: pointer;
}
.code-btn:disabled {
  color: #94a3b8;
  cursor: not-allowed;
}
.modal-error {
  color: #ef4444;
  font-size: 12px;
  margin-bottom: 12px;
}
.modal-btns {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  margin-top: 24px;
}
.cancel-btn {
  padding: 8px 18px;
  border: 1px solid #cbd5e1;
  background: #fff;
  border-radius: 4px;
  color: #475569;
  cursor: pointer;
}
.confirm-btn {
  padding: 8px 18px;
  border: none;
  background: #0256ff;
  border-radius: 4px;
  color: #fff;
  cursor: pointer;
  font-weight: 500;
}
</style>
