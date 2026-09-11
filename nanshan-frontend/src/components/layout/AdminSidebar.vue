<script setup>
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { getSavedUser } from '../../api/client'

import iconOverview from '../../assets/admin-icons/overview.png'
import iconAchievement from '../../assets/admin-icons/achievement.png'
import iconRequirement from '../../assets/admin-icons/requirement.png'
import iconCooperation from '../../assets/admin-icons/cooperation.png'
import iconCapital from '../../assets/admin-icons/capital.png'
import iconInstitution from '../../assets/admin-icons/institution.png'
import iconReview from '../../assets/admin-icons/review.png'
import iconUser from '../../assets/admin-icons/user.png'
import iconAi from '../../assets/admin-icons/ai.png'
import iconContent from '../../assets/admin-icons/content.png'
import iconSystem from '../../assets/admin-icons/system.png'
import iconLog from '../../assets/admin-icons/log.png'

const MENU_ICONS = {
  overview: iconOverview,
  achievement: iconAchievement,
  requirement: iconRequirement,
  cooperation: iconCooperation,
  capital: iconCapital,
  institution: iconInstitution,
  review: iconReview,
  user: iconUser,
  ai: iconAi,
  content: iconContent,
  system: iconSystem,
  log: iconLog,
}

defineProps({
  collapsed: {
    type: Boolean,
    default: false
  }
})

const emit = defineEmits(['toggle'])

const route = useRoute()
const router = useRouter()
const isOrgAdminOnly = computed(() => {
  const roles = getSavedUser()?.roles || []
  return roles.includes('org_admin') && !roles.includes('admin')
})
const orgAdminPaths = new Set([
  '/admin/achievements',
  '/admin/requirements',
  '/admin/cooperation',
  '/admin/users',
])

const menuList = [
  {
    name: '数据概览',
    path: '/admin/overview',
    icon: 'overview'
  },
  {
    name: '成果管理',
    path: '/admin/achievements',
    icon: 'achievement'
  },
  {
    name: '需求管理',
    path: '/admin/requirements',
    icon: 'requirement'
  },
  {
    name: '合作对接管理',
    path: '/admin/cooperation',
    icon: 'cooperation'
  },
  {
    name: '资本对接管理',
    path: '/admin/capital',
    icon: 'capital'
  },
  {
    name: '机构管理',
    path: '/admin/institutions',
    icon: 'institution'
  },
  {
    name: '机构认证审核',
    path: '/admin/membership-review',
    icon: 'review'
  },
  {
    name: '用户管理',
    path: '/admin/users',
    icon: 'user'
  },
  {
    name: 'AI推荐管理',
    path: '/admin/ai',
    icon: 'ai'
  },
  {
    name: '内容管理',
    path: '/admin/content',
    icon: 'content'
  },
  {
    name: '系统管理',
    path: '/admin/system',
    icon: 'system'
  },
  {
    name: '操作日志',
    path: '/admin/logs',
    icon: 'log'
  }
]

const visibleMenuList = computed(() => (
  isOrgAdminOnly.value
    ? menuList.filter(item => orgAdminPaths.has(item.path))
    : menuList
))

const goPage = (path) => {
  router.push(path)
}

const isActive = (path) => {
  return route.path.startsWith(path)
}
</script>

<template>
  <aside
    class="sidebar"
    :class="{ collapsed }"
  >
    <div class="brand">
      <div class="brand-logo">
        <div class="logo-piece logo-piece-left"></div>
        <div class="logo-piece logo-piece-right"></div>
      </div>

      <div
        v-if="!collapsed"
        class="brand-text"
      >
        <div class="brand-title">
          南山科转通
        </div>

        <div class="brand-subtitle">
          | 后台管理系统
        </div>
      </div>
    </div>

    <nav class="menu">
      <button
        v-for="item in visibleMenuList"
        :key="item.path"
        type="button"
        class="menu-item"
        :class="{ active: isActive(item.path) }"
        :title="collapsed ? item.name : ''"
        @click="goPage(item.path)"
      >
        <span class="menu-icon">
          <img
            class="menu-icon-img"
            :src="MENU_ICONS[item.icon]"
            :alt="item.name"
          >
        </span>

        <span
          v-if="!collapsed"
          class="menu-text"
        >
          {{ item.name }}
        </span>
      </button>
    </nav>

    <button
      type="button"
      class="collapse-button"
      @click="emit('toggle')"
    >
      <span class="collapse-icon">
        {{ collapsed ? '»' : '«' }}
      </span>

      <span v-if="!collapsed">
        收起菜单
      </span>
    </button>
  </aside>
</template>

<style scoped>
.sidebar {
  position: fixed;
  z-index: 100;
  left: 0;
  top: 0;
  bottom: 0;

  display: flex;
  flex-direction: column;

  width: 244px;

  padding: 20px 10px 18px;

  background:
    linear-gradient(
      180deg,
      #062f60 0%,
      #052550 100%
    );

  color: #ffffff;

  transition: width 0.25s ease;

  box-shadow:
    2px 0 8px rgba(0, 20, 50, 0.08);
}

.sidebar.collapsed {
  width: 78px;
}

.brand {
  display: flex;
  align-items: center;

  height: 72px;

  padding: 0 11px 15px;
}

.brand-logo {
  position: relative;

  flex-shrink: 0;

  width: 48px;
  height: 48px;

  margin-right: 12px;
}

.logo-piece {
  position: absolute;
}

.logo-piece-left {
  left: 2px;
  top: 1px;

  width: 28px;
  height: 46px;

  clip-path:
    polygon(
      50% 0,
      100% 58%,
      55% 100%,
      0 58%
    );

  background:
    linear-gradient(
      155deg,
      #32c3ff,
      #0872f9
    );
}

.logo-piece-right {
  right: 0;
  bottom: 2px;

  width: 31px;
  height: 33px;

  clip-path:
    polygon(
      0 0,
      100% 100%,
      19% 100%
    );

  background:
    linear-gradient(
      140deg,
      #2c88ff,
      #0754d7
    );
}

.brand-text {
  white-space: nowrap;
}

.brand-title {
  font-size: 20px;
  font-weight: 700;
}

.brand-subtitle {
  margin-top: 4px;
  font-size: 15px;
}

.menu {
  flex: 1;
  margin-top: 8px;
}

.menu-item {
  display: flex;
  align-items: center;

  width: 100%;
  height: 52px;

  margin: 6px 0;
  padding: 0 16px;

  border: 0;
  border-radius: 7px;

  background: transparent;

  color: #e8f1fb;

  font-size: 16px;
  text-align: left;

  transition:
    background 0.2s,
    transform 0.2s;
}

.menu-item:hover {
  background:
    rgba(255, 255, 255, 0.08);
}

.menu-item.active {
  background:
    linear-gradient(
      180deg,
      #1a7fff,
      #0d6cea
    );

  box-shadow:
    0 6px 16px rgba(0, 107, 255, 0.26);
}

.menu-icon {
  display: flex;
  align-items: center;
  justify-content: center;

  flex-shrink: 0;

  width: 24px;
  height: 24px;
}

.menu-icon-img {
  width: 22px;
  height: 22px;
  object-fit: contain;
  display: block;
}

.menu-text {
  margin-left: 14px;
  white-space: nowrap;
}

.sidebar.collapsed .menu-item {
  justify-content: center;
  padding: 0;
}

.collapse-button {
  display: flex;
  align-items: center;

  height: 58px;

  padding: 18px 10px 0;

  border: 0;
  border-top:
    1px solid rgba(255, 255, 255, 0.18);

  background: transparent;

  color: #d8e6f5;

  font-size: 15px;
}

.sidebar.collapsed .collapse-button {
  justify-content: center;
}

.collapse-icon {
  margin-right: 13px;
  font-size: 22px;
}

.sidebar.collapsed .collapse-icon {
  margin-right: 0;
}
</style>
