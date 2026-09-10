<script setup>
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '../../api/client'
import { validateEmail, validatePhone } from '../../utils/contactValidation.js'

const router = useRouter()
const mode = ref('user')
const submitting = ref(false)
const errorMessage = ref('')
const successMessage = ref('')

const userForm = reactive({ displayName: '', username: '', phone: '', email: '', password: '', confirmPassword: '' })
const institutionForm = reactive({
  kind: 'enterprise', name: '', region: '', creditCode: '', intro: '',
  contactName: '', contactPhone: '', email: '', username: '', password: '', confirmPassword: '',
})

const switchMode = value => {
  mode.value = value
  errorMessage.value = ''
  successMessage.value = ''
}

const validatePassword = form => {
  if (!form.username.trim() || !form.password) return '请填写登录账号和密码。'
  if (form.password.length < 8) return '密码至少需要 8 位。'
  if (form.password !== form.confirmPassword) return '两次输入的密码不一致。'
  return ''
}

const submitUserRegistration = async () => {
  const error = validatePassword(userForm)
  if (error) throw new Error(error)
  const body = { username: userForm.username.trim(), password: userForm.password }
  if (userForm.displayName.trim()) body.displayName = userForm.displayName.trim()
  if (userForm.phone.trim()) {
    const phoneCheck = validatePhone(userForm.phone, { required: false })
    if (!phoneCheck.ok) throw new Error(phoneCheck.message)
    body.phone = phoneCheck.value
  }
  if (userForm.email.trim()) {
    const emailCheck = validateEmail(userForm.email, { required: false })
    if (!emailCheck.ok) throw new Error(emailCheck.message)
    body.email = emailCheck.value
  }
  await api('/auth/register', { method: 'POST', body })
  successMessage.value = '普通用户注册成功，请从小程序或用户端登录；后台管理端仅供平台管理员和机构管理员使用。'
}

const submitInstitutionRegistration = async () => {
  if (!institutionForm.name.trim() || !institutionForm.contactName.trim() || !institutionForm.contactPhone.trim()) {
    throw new Error('请填写机构名称、联系人和联系电话。')
  }
  const phoneCheck = validatePhone(institutionForm.contactPhone, { required: true, label: '联系电话' })
  if (!phoneCheck.ok) throw new Error(phoneCheck.message)
  const error = validatePassword(institutionForm)
  if (error) throw new Error(error)
  const body = {
    kind: institutionForm.kind, name: institutionForm.name.trim(),
    contactName: institutionForm.contactName.trim(), contactPhone: phoneCheck.value,
    username: institutionForm.username.trim(), password: institutionForm.password,
  }
  if (institutionForm.region.trim()) body.region = institutionForm.region.trim()
  if (institutionForm.creditCode.trim()) body.creditCode = institutionForm.creditCode.trim()
  if (institutionForm.intro.trim()) body.intro = institutionForm.intro.trim()
  if (institutionForm.email.trim()) {
    const emailCheck = validateEmail(institutionForm.email, { required: false })
    if (!emailCheck.ok) throw new Error(emailCheck.message)
    body.email = emailCheck.value
  }
  await api('/institution-registrations', { method: 'POST', body })
  successMessage.value = '机构申请已提交，请等待平台审核；审核通过后可使用该管理员账号登录后台。'
}

const submit = async () => {
  errorMessage.value = ''
  successMessage.value = ''
  submitting.value = true
  try {
    if (mode.value === 'user') await submitUserRegistration()
    else await submitInstitutionRegistration()
  } catch (err) {
    errorMessage.value = err.message || '提交失败，请稍后重试。'
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <main class="register-page">
    <section class="register-card">
      <header class="heading">
        <p class="brand">南山科技成果转化服务平台</p>
        <h1>创建账号</h1>
        <p>个人用户可立即使用平台；机构注册需平台审核通过后开通机构管理员权限。</p>
      </header>

      <div class="mode-tabs" role="tablist">
        <button type="button" :class="{ active: mode === 'user' }" @click="switchMode('user')">普通用户注册</button>
        <button type="button" :class="{ active: mode === 'institution' }" @click="switchMode('institution')">机构注册申请</button>
      </div>

      <form @submit.prevent="submit">
        <template v-if="mode === 'user'">
          <div class="form-grid">
            <label>姓名或昵称<input v-model="userForm.displayName" maxlength="64" placeholder="选填" /></label>
            <label>手机号码<input v-model="userForm.phone" maxlength="32" placeholder="选填" /></label>
            <label>登录账号 <em>*</em><input v-model="userForm.username" maxlength="64" placeholder="4-64 位：字母、数字、._-" /></label>
            <label>电子邮箱<input v-model="userForm.email" type="email" maxlength="128" placeholder="选填" /></label>
            <label>登录密码 <em>*</em><input v-model="userForm.password" type="password" maxlength="128" placeholder="至少 8 位" /></label>
            <label>确认密码 <em>*</em><input v-model="userForm.confirmPassword" type="password" maxlength="128" /></label>
          </div>
        </template>

        <template v-else>
          <h2>机构资料</h2>
          <div class="form-grid">
            <label>机构类型 <em>*</em><select v-model="institutionForm.kind"><option value="university">高校</option><option value="institute">科研院所</option><option value="enterprise">企业</option><option value="invest">投资机构</option><option value="service">服务机构</option><option value="other">其他</option></select></label>
            <label>机构名称 <em>*</em><input v-model="institutionForm.name" maxlength="255" /></label>
            <label>所在地区<input v-model="institutionForm.region" maxlength="64" placeholder="例如：深圳市南山区" /></label>
            <label>统一社会信用代码<input v-model="institutionForm.creditCode" maxlength="64" placeholder="选填" /></label>
          </div>
          <label class="full-width">机构简介<textarea v-model="institutionForm.intro" rows="3" maxlength="5000" placeholder="选填"></textarea></label>
          <h2>首位机构管理员</h2>
          <div class="form-grid">
            <label>联系人姓名 <em>*</em><input v-model="institutionForm.contactName" maxlength="64" /></label>
            <label>联系电话 <em>*</em><input v-model="institutionForm.contactPhone" maxlength="32" /></label>
            <label>电子邮箱<input v-model="institutionForm.email" type="email" maxlength="128" placeholder="选填" /></label>
            <label>登录账号 <em>*</em><input v-model="institutionForm.username" maxlength="64" placeholder="4-64 位：字母、数字、._-" /></label>
            <label>登录密码 <em>*</em><input v-model="institutionForm.password" type="password" maxlength="128" placeholder="至少 8 位" /></label>
            <label>确认密码 <em>*</em><input v-model="institutionForm.confirmPassword" type="password" maxlength="128" /></label>
          </div>
        </template>

        <p v-if="errorMessage" class="message error">{{ errorMessage }}</p>
        <p v-if="successMessage" class="message success">{{ successMessage }}</p>
        <footer class="actions"><button type="button" class="secondary" @click="router.push('/login')">返回登录</button><button type="submit" class="primary" :disabled="submitting || Boolean(successMessage)">{{ submitting ? '提交中…' : mode === 'user' ? '完成注册' : '提交注册申请' }}</button></footer>
      </form>
    </section>
  </main>
</template>

<style scoped>
.register-page { min-height: 100vh; padding: 48px 20px; background: radial-gradient(circle at 12% 6%, #dceeff 0, transparent 30%), #f5f7fb; }.register-card { box-sizing: border-box; max-width: 840px; margin: 0 auto; padding: 38px 44px; border: 1px solid #e4eaf2; border-radius: 18px; background: #fff; box-shadow: 0 20px 50px rgba(34, 62, 100, .12); }.heading { margin-bottom: 26px; }.brand { margin: 0; color: #1677ff; font-size: 13px; font-weight: 700; letter-spacing: .04em; }.heading h1 { margin: 8px 0; color: #1f2d3d; font-size: 28px; }.heading p:last-child { margin: 0; color: #718096; line-height: 1.7; }.mode-tabs { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-bottom: 28px; padding: 5px; border-radius: 10px; background: #f1f5f9; }.mode-tabs button { padding: 11px; border: 0; border-radius: 7px; background: transparent; color: #64748b; font: inherit; font-weight: 650; cursor: pointer; }.mode-tabs button.active { background: #fff; color: #1677ff; box-shadow: 0 2px 8px rgba(22, 119, 255, .13); }h2 { margin: 28px 0 16px; padding-top: 24px; border-top: 1px solid #edf1f5; color: #25364a; font-size: 18px; }.form-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 18px; }label { display: block; color: #344154; font-size: 14px; font-weight: 650; }em { color: #ef4444; font-style: normal; }input, select, textarea { box-sizing: border-box; width: 100%; margin-top: 7px; padding: 10px 11px; border: 1px solid #d7e0eb; border-radius: 7px; color: #243447; font: inherit; font-weight: 400; outline: none; }input:focus, select:focus, textarea:focus { border-color: #1677ff; box-shadow: 0 0 0 3px rgba(22,119,255,.1); }textarea { resize: vertical; }.full-width { margin-top: 18px; }.message { margin: 18px 0 0; padding: 11px 13px; border-radius: 7px; font-size: 14px; }.error { color: #c53030; background: #fff1f1; }.success { color: #177245; background: #edf9f0; }.actions { display: flex; justify-content: flex-end; gap: 12px; margin-top: 30px; }button { padding: 10px 19px; border: 0; border-radius: 7px; font: inherit; font-weight: 650; cursor: pointer; }.primary { color: #fff; background: #1677ff; }.primary:disabled { cursor: not-allowed; opacity: .65; }.secondary { color: #475569; background: #edf2f7; }@media (max-width: 640px) { .register-card { padding: 28px 22px; }.form-grid { grid-template-columns: 1fr; }.register-page { padding: 22px 12px; } }
</style>
