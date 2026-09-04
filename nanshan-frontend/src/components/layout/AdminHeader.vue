<script setup>
import { ref, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'

defineProps({
  collapsed: {
    type: Boolean,
    default: false
  }
})

const emit = defineEmits(['toggle'])

const route = useRoute()
const router = useRouter()

const showUserMenu = ref(false)

const pageMap = {
  '/admin/overview': {
    parent: '首页',
    name: '数据概览'
  },

  '/admin/achievements': {
    parent: '成果管理',
    name: '成果列表'
  },

  '/admin/requirements': {
    parent: '需求管理',
    name: '需求列表'
  },

  '/admin/cooperation': {
    parent: '合作对接管理',
    name: '对接列表'
  },

  '/admin/institutions': {
    parent: '机构管理',
    name: '机构列表'
  },

  '/admin/users': {
    parent: '用户管理',
    name: '用户列表'
  },

  '/admin/ai': {
    parent: 'AI推荐管理',
    name: '推荐列表'
  },

  '/admin/content': {
    parent: '内容管理',
    name: '轮播图管理'
  },

  '/admin/system': {
    parent: '系统管理',
    name: '系统设置'
  },

  '/admin/logs': {
    parent: '操作日志',
    name: '日志列表'
  }
}

const breadcrumb = computed(() => {
  return {
    parent:
      route.meta.parent ||
      '首页',

    name:
      route.meta.title ||
      '数据概览'
  }
})

const toggleUserMenu = () => {
  showUserMenu.value = !showUserMenu.value
}

const logout = () => {
  showUserMenu.value = false
  router.push('/login')
}
</script>

<template>
  <header class="admin-header">
    <div class="header-left">
      <button
        class="hamburger-button"
        type="button"
        @click="emit('toggle')"
      >
        <span></span>
        <span></span>
        <span></span>
      </button>

      <div class="breadcrumb">
        <span class="breadcrumb-main">
          {{ breadcrumb.parent }}
        </span>

        <span class="separator">
          /
        </span>

        <span class="breadcrumb-sub">
          {{ breadcrumb.name }}
        </span>
      </div>
    </div>

    <div class="header-right">
      <button
        type="button"
        class="notification-button"
      >
        <svg
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
        >
          <path
            d="M18 8a6 6 0 1 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9"
          />

          <path d="M10 21h4" />
        </svg>

        <span class="notification-count">
          12
        </span>
      </button>

      <div class="vertical-line"></div>

      <div class="user-area">
        <button
          type="button"
          class="user-button"
          @click="toggleUserMenu"
        >
          <div class="avatar">
            <div class="avatar-head"></div>
            <div class="avatar-body"></div>
          </div>

          <span class="username">
            管理员
          </span>

          <span
            class="arrow"
            :class="{ open: showUserMenu }"
          ></span>
        </button>

        <div
          v-if="showUserMenu"
          class="user-dropdown"
        >
          <button
            type="button"
            @click="showUserMenu = false"
          >
            个人信息
          </button>

          <button
            type="button"
            @click="showUserMenu = false"
          >
            修改密码
          </button>

          <div class="dropdown-line"></div>

          <button
            type="button"
            class="logout-button"
            @click="logout"
          >
            退出登录
          </button>
        </div>
      </div>
    </div>
  </header>
</template>

<style scoped>
.admin-header {
  position: sticky;
  z-index: 50;
  top: 0;

  display: flex;
  align-items: center;
  justify-content: space-between;

  height: 74px;

  padding: 0 34px;

  border-bottom: 1px solid #edf1f6;

  background: #ffffff;
}

.header-left {
  display: flex;
  align-items: center;
}

.hamburger-button {
  display: flex;
  flex-direction: column;
  justify-content: space-between;

  width: 25px;
  height: 21px;

  margin-right: 28px;
  padding: 1px 0;

  border: 0;
  background: transparent;
}

.hamburger-button span {
  display: block;

  width: 21px;
  height: 2px;

  border-radius: 2px;

  background: #26384e;
}

.breadcrumb {
  display: flex;
  align-items: center;
  gap: 15px;

  font-size: 17px;
}

.breadcrumb-main {
  color: #1f2938;
  font-weight: 700;
}

.separator {
  color: #bdc5d0;
}

.breadcrumb-sub {
  color: #98a3b3;
}

.header-right {
  display: flex;
  align-items: center;
}

.notification-button {
  position: relative;

  width: 36px;
  height: 36px;

  padding: 6px;

  border: 0;

  background: transparent;

  color: #27394e;
}

.notification-button svg {
  width: 24px;
  height: 24px;

  stroke-width: 1.8;
}

.notification-count {
  position: absolute;
  right: -3px;
  top: -4px;

  display: flex;
  align-items: center;
  justify-content: center;

  min-width: 20px;
  height: 20px;

  padding: 0 5px;

  border: 2px solid white;
  border-radius: 12px;

  background: #ff3f4b;

  color: white;

  font-size: 10px;
  font-weight: 700;
}

.vertical-line {
  width: 1px;
  height: 28px;

  margin: 0 19px;

  background: #e6ebf1;
}

.user-area {
  position: relative;
}

.user-button {
  display: flex;
  align-items: center;

  border: 0;
  background: transparent;
}

.avatar {
  position: relative;

  width: 38px;
  height: 38px;

  overflow: hidden;

  border: 2px solid #ddecf8;
  border-radius: 50%;

  background:
    linear-gradient(
      180deg,
      #cbeeff,
      #79bddf
    );
}

.avatar-head {
  position: absolute;

  left: 12px;
  top: 6px;

  width: 11px;
  height: 12px;

  border-radius: 50%;

  background: #33485a;
}

.avatar-body {
  position: absolute;

  left: 8px;
  bottom: 2px;

  width: 19px;
  height: 17px;

  border-radius: 12px 12px 4px 4px;

  background: #26394b;
}

.username {
  margin-left: 12px;

  color: #273345;

  font-size: 15px;
  font-weight: 600;
}

.arrow {
  width: 7px;
  height: 7px;

  margin-left: 10px;
  margin-top: -4px;

  border-right: 1.5px solid #6f7a89;
  border-bottom: 1.5px solid #6f7a89;

  transform: rotate(45deg);

  transition: transform 0.2s;
}

.arrow.open {
  margin-top: 4px;
  transform: rotate(225deg);
}

.user-dropdown {
  position: absolute;

  right: 0;
  top: 50px;

  width: 140px;

  padding: 7px;

  border: 1px solid #e5eaf1;
  border-radius: 7px;

  background: white;

  box-shadow:
    0 10px 30px rgba(43, 63, 86, 0.12);
}

.user-dropdown button {
  width: 100%;
  height: 38px;

  padding: 0 12px;

  border: 0;
  border-radius: 5px;

  background: transparent;

  color: #4a5667;

  text-align: left;
}

.user-dropdown button:hover {
  background: #f4f7fb;
}

.dropdown-line {
  height: 1px;

  margin: 5px 0;

  background: #edf0f4;
}

.user-dropdown .logout-button {
  color: #f0525d;
}
</style>