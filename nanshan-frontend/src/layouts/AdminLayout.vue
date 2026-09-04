<script setup>
import { ref } from 'vue'

import AdminSidebar from '../components/layout/AdminSidebar.vue'
import AdminHeader from '../components/layout/AdminHeader.vue'

const collapsed = ref(false)

const toggleSidebar = () => {
  collapsed.value = !collapsed.value
}
</script>

<template>
  <div class="admin-layout">
    <AdminSidebar
      :collapsed="collapsed"
      @toggle="toggleSidebar"
    />

    <div
      class="admin-main"
      :class="{ collapsed: collapsed }"
    >
      <AdminHeader
        :collapsed="collapsed"
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