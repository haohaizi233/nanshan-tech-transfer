<script setup>
import { onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { useAuthStore } from '../../stores/auth'

const router = useRouter()
const route = useRoute()
const authStore = useAuthStore()

const REMEMBER_KEY = 'nanshan_admin_remember_user'

const form = reactive({
  username: '',
  password: '',
  remember: false
})

const loading = ref(false)
const errorMsg = ref('')

onMounted(() => {
  const savedUsername = localStorage.getItem(REMEMBER_KEY)
  if (savedUsername) {
    form.username = savedUsername
    form.remember = true
  }
})

const handleLogin = async () => {
  if (!form.username || !form.password) {
    errorMsg.value = '请输入账号和密码'
    return
  }

  loading.value = true
  errorMsg.value = ''

  try {
    const user = await authStore.login(form.username.trim(), form.password)
    if (form.remember) {
      localStorage.setItem(REMEMBER_KEY, form.username.trim())
    } else {
      localStorage.removeItem(REMEMBER_KEY)
    }
    const roles = user.roles || []
    const defaultPath = roles.includes('org_admin') && !roles.includes('admin')
      ? '/admin/achievements'
      : '/admin/overview'
    router.push(route.query.redirect || defaultPath)
  } catch (err) {
    errorMsg.value = err.message || '登录失败，请稍后再试'
  } finally {
    loading.value = false
  }
}

const goRegister = () => {
  router.push('/register')
}
</script>

<template>
  <div class="login-page">
    <div class="background-decoration decoration-one"></div>
    <div class="background-decoration decoration-two"></div>

    <div class="login-container">
      <section class="brand-section">
        <div class="brand-content">
          <div class="logo-row">
            <div class="logo">
              <div class="logo-shape logo-left"></div>
              <div class="logo-shape logo-right"></div>
            </div>

            <div>
              <div class="brand-name">南山科转通</div>
              <div class="brand-subtitle">科技成果转化服务平台</div>
            </div>
          </div>

          <div class="welcome">
            <h1>科技创新<br />连接未来</h1>

            <p>
              汇聚科技成果与产业需求，促进创新资源高效对接，
              助力科技成果转化与产业升级。
            </p>
          </div>

          <div class="feature-list">
            <div class="feature-item">
              <span class="feature-icon">✓</span>
              <span>科技成果智能管理</span>
            </div>

            <div class="feature-item">
              <span class="feature-icon">✓</span>
              <span>企业需求精准匹配</span>
            </div>

            <div class="feature-item">
              <span class="feature-icon">✓</span>
              <span>产学研合作高效对接</span>
            </div>
          </div>
        </div>
      </section>

      <section class="form-section">
        <div class="login-card">
          <div class="card-header">
            <h2>欢迎登录</h2>
            <p>南山科转通后台管理系统</p>
          </div>

          <form @submit.prevent="handleLogin">
            <div class="form-item">
              <label>账号</label>

              <div class="input-wrapper">
                <span class="input-icon">
                  <svg
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    stroke-width="1.8"
                  >
                    <circle cx="12" cy="8" r="4" />
                    <path d="M4 21a8 8 0 0 1 16 0" />
                  </svg>
                </span>

                <input
                  v-model="form.username"
                  type="text"
                  placeholder="请输入用户名"
                />
              </div>
            </div>

            <div class="form-item">
              <label>密码</label>

              <div class="input-wrapper">
                <span class="input-icon">
                  <svg
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    stroke-width="1.8"
                  >
                    <rect x="5" y="10" width="14" height="10" rx="2" />
                    <path d="M8 10V7a4 4 0 0 1 8 0v3" />
                  </svg>
                </span>

                <input
                  v-model="form.password"
                  type="password"
                  placeholder="请输入密码"
                />
              </div>
            </div>

            <div class="form-options">
              <label class="remember">
                <input
                  v-model="form.remember"
                  type="checkbox"
                />
                <span>记住密码</span>
              </label>

              <button
                type="button"
                class="text-button"
              >
                忘记密码？
              </button>
            </div>

            <button
              class="login-button"
              type="submit"
              :disabled="loading"
            >
              {{ loading ? '登录中…' : '登录' }}
            </button>

            <p v-if="errorMsg" class="login-error">
              {{ errorMsg }}
            </p>
          </form>

          <div class="register-row">
            <span>还没有账号？</span>

            <button
              type="button"
              class="register-button"
              @click="goRegister"
            >
              立即注册
            </button>
          </div>
        </div>

        <div class="copyright">
          © 2026 南山科转通 · 后台管理系统
        </div>
      </section>
    </div>
  </div>
</template>

<style scoped>
.login-page {
  position: relative;
  width: 100%;
  height: 100vh;
  min-height: 720px;
  overflow: hidden;
  background:
    radial-gradient(
      circle at 18% 20%,
      rgba(28, 129, 255, 0.18),
      transparent 30%
    ),
    linear-gradient(
      135deg,
      #032a56 0%,
      #063a74 46%,
      #eef6ff 46%,
      #f8fbff 100%
    );
}

.login-container {
  position: relative;
  z-index: 2;
  display: flex;
  width: 100%;
  height: 100%;
}

.brand-section {
  display: flex;
  width: 48%;
  padding: 70px 7%;
  color: #ffffff;
}

.brand-content {
  display: flex;
  flex-direction: column;
  width: 100%;
}

.logo-row {
  display: flex;
  align-items: center;
  gap: 16px;
}

.logo {
  position: relative;
  width: 58px;
  height: 58px;
}

.logo-shape {
  position: absolute;
}

.logo-left {
  left: 1px;
  top: 3px;
  width: 31px;
  height: 53px;
  clip-path: polygon(50% 0, 100% 55%, 54% 100%, 0 55%);
  background: linear-gradient(
    160deg,
    #34c8ff,
    #0879ff
  );
}

.logo-right {
  right: 1px;
  top: 17px;
  width: 35px;
  height: 39px;
  clip-path: polygon(0 0, 100% 100%, 20% 100%);
  background: linear-gradient(
    135deg,
    #2f8fff,
    #0754d9
  );
}

.brand-name {
  font-size: 27px;
  font-weight: 700;
  letter-spacing: 1px;
}

.brand-subtitle {
  margin-top: 6px;
  font-size: 15px;
  color: rgba(255, 255, 255, 0.72);
}

.welcome {
  margin-top: 150px;
}

.welcome h1 {
  margin: 0;
  font-size: 52px;
  line-height: 1.28;
  letter-spacing: 3px;
}

.welcome p {
  max-width: 500px;
  margin-top: 28px;
  font-size: 17px;
  line-height: 2;
  color: rgba(255, 255, 255, 0.7);
}

.feature-list {
  display: flex;
  flex-direction: column;
  gap: 20px;
  margin-top: 44px;
}

.feature-item {
  display: flex;
  align-items: center;
  gap: 13px;
  font-size: 15px;
  color: rgba(255, 255, 255, 0.85);
}

.feature-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  border-radius: 50%;
  background: rgba(65, 170, 255, 0.2);
  border: 1px solid rgba(106, 192, 255, 0.6);
}

.form-section {
  display: flex;
  flex: 1;
  flex-direction: column;
  align-items: center;
  justify-content: center;
}

.login-card {
  width: 470px;
  padding: 46px 48px 42px;
  border: 1px solid rgba(221, 230, 241, 0.9);
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.96);
  box-shadow:
    0 24px 70px rgba(42, 77, 117, 0.14);
}

.card-header h2 {
  margin: 0;
  font-size: 28px;
  color: #17243a;
}

.card-header p {
  margin: 12px 0 34px;
  font-size: 14px;
  color: #98a2b2;
}

.form-item {
  margin-bottom: 22px;
}

.form-item label {
  display: block;
  margin-bottom: 9px;
  font-size: 14px;
  font-weight: 600;
  color: #3d495a;
}

.input-wrapper {
  position: relative;
}

.input-wrapper input {
  width: 100%;
  height: 48px;
  padding: 0 15px 0 47px;
  outline: none;
  border: 1px solid #dce4ee;
  border-radius: 6px;
  background: #ffffff;
  color: #273448;
  transition: 0.2s;
}

.input-wrapper input:focus {
  border-color: #1677ff;
  box-shadow: 0 0 0 3px rgba(22, 119, 255, 0.08);
}

.input-wrapper input::placeholder {
  color: #b5bdc9;
}

.input-icon {
  position: absolute;
  z-index: 2;
  left: 15px;
  top: 50%;
  width: 20px;
  height: 20px;
  color: #9aa6b6;
  transform: translateY(-50%);
}

.input-icon svg {
  width: 20px;
  height: 20px;
}

.form-options {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 3px;
}

.remember {
  display: flex;
  align-items: center;
  gap: 7px;
  font-size: 13px;
  color: #657184;
}

.remember input {
  width: 15px;
  height: 15px;
}

.text-button {
  padding: 0;
  border: none;
  background: transparent;
  font-size: 13px;
  color: #1677ff;
}

.login-button {
  width: 100%;
  height: 50px;
  margin-top: 26px;
  border: none;
  border-radius: 6px;
  background: linear-gradient(
    90deg,
    #0877ff,
    #1267ed
  );
  color: white;
  font-size: 16px;
  font-weight: 600;
  box-shadow:
    0 8px 18px rgba(22, 119, 255, 0.22);
  transition: 0.2s;
}

.login-button:hover {
  transform: translateY(-1px);
  box-shadow:
    0 10px 22px rgba(22, 119, 255, 0.3);
}

.login-button:active {
  transform: translateY(0);
}

.register-row {
  display: flex;
  justify-content: center;
  gap: 7px;
  margin-top: 25px;
  font-size: 13px;
  color: #8a95a5;
}

.register-button {
  padding: 0;
  border: none;
  background: transparent;
  color: #1677ff;
}

.copyright {
  margin-top: 30px;
  color: #a0a9b8;
  font-size: 12px;
}

.login-error {
  margin: 14px 0 0;
  color: #e5484d;
  font-size: 13px;
  text-align: center;
}

.background-decoration {
  position: absolute;
  border-radius: 50%;
  filter: blur(1px);
}

.decoration-one {
  left: -200px;
  bottom: -280px;
  width: 650px;
  height: 650px;
  border: 1px solid rgba(79, 160, 255, 0.16);
}

.decoration-two {
  left: 180px;
  bottom: -360px;
  width: 700px;
  height: 700px;
  border: 1px solid rgba(79, 160, 255, 0.1);
}
</style>
