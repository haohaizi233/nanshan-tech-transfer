<script setup>
import { reactive } from 'vue'
import { useRouter } from 'vue-router'

const router = useRouter()

const form = reactive({
  username: '',
  phone: '',
  password: '',
  confirmPassword: ''
})

const handleRegister = () => {
  console.log('注册信息：', form)

  // 暂时模拟注册成功
  router.push('/login')
}

const goLogin = () => {
  router.push('/login')
}
</script>

<template>
  <div class="register-page">
    <div class="register-card">
      <div class="header">
        <div class="brand">
          <div class="logo">A</div>

          <div>
            <div class="brand-title">南山科转通</div>
            <div class="brand-subtitle">后台管理系统</div>
          </div>
        </div>

        <h1>创建账号</h1>
        <p>填写以下信息完成注册</p>
      </div>

      <form @submit.prevent="handleRegister">
        <div class="form-item">
          <label>用户名</label>

          <input
            v-model="form.username"
            type="text"
            placeholder="请输入用户名"
          />
        </div>

        <div class="form-item">
          <label>手机号</label>

          <input
            v-model="form.phone"
            type="text"
            placeholder="请输入手机号"
          />
        </div>

        <div class="form-item">
          <label>密码</label>

          <input
            v-model="form.password"
            type="password"
            placeholder="请输入密码"
          />
        </div>

        <div class="form-item">
          <label>确认密码</label>

          <input
            v-model="form.confirmPassword"
            type="password"
            placeholder="请再次输入密码"
          />
        </div>

        <button
          class="submit-button"
          type="submit"
        >
          注册
        </button>
      </form>

      <div class="login-link">
        <span>已有账号？</span>

        <button
          type="button"
          @click="goLogin"
        >
          返回登录
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.register-page {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 100%;
  min-height: 100vh;
  padding: 40px;
  background:
    radial-gradient(
      circle at 15% 20%,
      rgba(25, 122, 255, 0.14),
      transparent 28%
    ),
    linear-gradient(
      135deg,
      #eef6ff,
      #f8fbff
    );
}

.register-card {
  width: 500px;
  padding: 42px 50px;
  border: 1px solid #e5ebf3;
  border-radius: 14px;
  background: white;
  box-shadow:
    0 22px 70px rgba(43, 76, 116, 0.12);
}

.brand {
  display: flex;
  align-items: center;
  gap: 13px;
  margin-bottom: 35px;
}

.logo {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 48px;
  height: 48px;
  border-radius: 12px;
  background:
    linear-gradient(
      135deg,
      #26b8ff,
      #0d62ee
    );
  color: white;
  font-size: 24px;
  font-weight: bold;
}

.brand-title {
  font-size: 19px;
  font-weight: 700;
  color: #152a45;
}

.brand-subtitle {
  margin-top: 3px;
  color: #9aa5b4;
  font-size: 12px;
}

.header h1 {
  margin: 0;
  font-size: 27px;
}

.header > p {
  margin: 10px 0 30px;
  color: #9aa5b3;
  font-size: 14px;
}

.form-item {
  margin-bottom: 19px;
}

.form-item label {
  display: block;
  margin-bottom: 8px;
  color: #404b5c;
  font-size: 14px;
  font-weight: 600;
}

.form-item input {
  width: 100%;
  height: 46px;
  padding: 0 14px;
  outline: none;
  border: 1px solid #dce4ee;
  border-radius: 6px;
  transition: 0.2s;
}

.form-item input:focus {
  border-color: #1677ff;
  box-shadow:
    0 0 0 3px rgba(22, 119, 255, 0.08);
}

.form-item input::placeholder {
  color: #b6bec9;
}

.submit-button {
  width: 100%;
  height: 48px;
  margin-top: 11px;
  border: none;
  border-radius: 6px;
  background: #1677ff;
  color: white;
  font-size: 16px;
  font-weight: 600;
}

.submit-button:hover {
  background: #0969e8;
}

.login-link {
  display: flex;
  justify-content: center;
  gap: 7px;
  margin-top: 24px;
  color: #8c97a7;
  font-size: 13px;
}

.login-link button {
  padding: 0;
  border: none;
  background: transparent;
  color: #1677ff;
}
</style>