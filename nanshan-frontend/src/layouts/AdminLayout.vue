<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import { api } from '../api/client'

import AdminSidebar from '../components/layout/AdminSidebar.vue'
import AdminHeader from '../components/layout/AdminHeader.vue'

const collapsed = ref(false)
const notification = ref({ total: 0, categories: {} })
let notificationTimer = null
let notificationInFlight = false
const refreshNotification = async () => {
  if (notificationInFlight) return
  notificationInFlight = true
  try { notification.value = await api('/admin/notifications/summary') } catch (e) { console.warn('[admin notification]', e) }
  finally { notificationInFlight = false }
}
onMounted(() => { refreshNotification(); notificationTimer = setInterval(refreshNotification, 200) })
onUnmounted(() => { clearInterval(notificationTimer); notificationTimer = null })

const toggleSidebar = () => {
  collapsed.value = !collapsed.value
}
</script>

<template>
  <div class="admin-layout">
    <AdminSidebar
      :collapsed="collapsed"
      :notification="notification"
      @toggle="toggleSidebar"
    />

    <div
      class="admin-main"
      :class="{ collapsed: collapsed }"
    >
      <AdminHeader
        :collapsed="collapsed"
        :notification="notification"
        @toggle="toggleSidebar"
      />

      <main class="admin-content">
        <RouterView />
      </main>
    </div>
  </div>
</template>

<style scoped>
.admin-layout {
  width: 100%;
  min-height: 100vh;
  background: #f5f7fb;
}

.admin-main {
  min-height: 100vh;
  margin-left: 244px;
  transition: margin-left 0.25s ease;
}

.admin-main.collapsed {
  margin-left: 78px;
}

.admin-content {
  min-height: calc(100vh - 74px);
  padding: 20px 22px 28px;
}
</style>
