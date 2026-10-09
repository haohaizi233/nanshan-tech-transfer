import {
  createRouter,
  createWebHistory
} from 'vue-router'

import { getSavedUser, getToken } from '../api/client'
import LoginView from '../views/auth/LoginView.vue'
import RegisterView from '../views/auth/RegisterView.vue'

import AdminLayout from '../layouts/AdminLayout.vue'

// 管理页懒加载：减小首屏 bundle，按需加载各功能模块
const OverviewView = () => import('../views/admin/OverviewView.vue')
const AchievementView = () => import('../views/admin/AchievementView.vue')
const AchievementImportView = () => import('../views/admin/AchievementImportView.vue')
const InstitutionView = () => import('../views/admin/InstitutionView.vue')
const MembershipReviewView = () => import('../views/admin/MembershipReviewView.vue')
const UserView = () => import('../views/admin/UserView.vue')
const ContentView = () => import('../views/admin/ContentView.vue')
const SystemView = () => import('../views/admin/SystemView.vue')
const LogView = () => import('../views/admin/LogView.vue')
const RequirementView = () => import('../views/admin/RequirementView.vue')

const RequirementDetailView = () => import('../views/admin/RequirementDetailView.vue')

const CooperationView = () => import('../views/admin/CooperationView.vue')

const CooperationDetailView = () => import('../views/admin/CooperationDetailView.vue')
const CapitalView = () => import('../views/admin/CapitalView.vue')

const isOrgAdminOnly = () => {
  const roles = getSavedUser()?.roles || []
  return roles.includes('org_admin') && !roles.includes('admin')
}

const orgAdminAllowedPaths = [
  '/admin/achievements',
  '/admin/requirements',
  '/admin/cooperation',
  '/admin/users'
]

const routes = [
  {
    path: '/',
    redirect: '/login'
  },

  {
    path: '/login',
    name: 'login',
    component: LoginView
  },

  {
    path: '/register',
    name: 'register',
    component: RegisterView
  },

  {
    path: '/admin',
    component: AdminLayout,

    children: [
      {
        path: '',
        redirect: () => (isOrgAdminOnly() ? '/admin/achievements' : '/admin/overview')
      },

      {
        path: 'overview',
        name: 'overview',
        component: OverviewView,

        meta: {
          parent: '首页',
          title: '数据概览'
        }
      },

      {
        path: 'achievements',
        name: 'achievements',
        component: AchievementView,

        meta: {
          parent: '成果管理',
          title: '成果列表'
        }
      },

      {
        path: 'achievement-imports',
        name: 'achievement-imports',
        component: AchievementImportView,
        meta: {
          parent: '成果管理',
          title: '成果导入暂存'
        }
      },

      {
        path: 'requirements',
        name: 'requirements',
        component: RequirementView,

        meta: {
          parent: '需求管理',
          title: '需求列表'
        }
      },

      {
        path: 'requirements/:id',
        name: 'requirement-detail',
        component: RequirementDetailView,

        meta: {
          parent: '需求管理',
          title: '需求详情'
        }
      },

      {
        path: 'cooperation',

        name: 'cooperation',

        component:
          CooperationView,

        meta: {
          parent:
            '合作对接管理',

          title:
            '对接列表'
        }
      },

      {
        path:
          'cooperation/:id',

        name:
          'cooperation-detail',

        component:
          CooperationDetailView,

        meta: {
          parent:
            '合作对接管理',

          title:
            '对接详情'
        }
      },

      {
        path: 'capital',
        name: 'capital',
        component: CapitalView,
        meta: {
          parent: '资本对接管理',
          title: '资源列表'
        }
      },

      {
        path: 'institutions',
        name: 'institutions',
        component: InstitutionView,

        meta: {
          parent: '机构管理',
          title: '机构列表'
        }
      },

      {
        path: 'membership-review',
        name: 'membership-review',
        component: MembershipReviewView,

        meta: {
          parent: '机构管理',
          title: '机构认证审核'
        }
      },

      {
        path: 'users',
        name: 'users',
        component: UserView,

        meta: {
          parent: '用户管理',
          title: '用户列表'
        }
      },

      {
        path: 'ai',
        name: 'ai',
        component: ContentView,
        meta: { parent: 'AI 管理', title: 'AI 配置' }
      },

      {
        path: 'content',
        name: 'content',
        component: ContentView,
        meta: { parent: '内容管理', title: '内容配置' }
      },

      {
        path: 'system',
        name: 'system',
        component: SystemView,
        meta: { parent: '系统管理', title: '系统配置' }
      },

      {
        path: 'logs',
        name: 'logs',
        component: LogView,
        meta: { parent: '系统管理', title: '操作日志' }
      }
    ]
  },

  {
    path: '/:pathMatch(.*)*',
    name: 'not-found',
    redirect: () => (getToken() ? '/admin' : '/login')
  }
]

const router = createRouter({
  history: createWebHistory(),
  routes
})

router.beforeEach(to => {
  if (to.path.startsWith('/admin') && !getToken()) {
    return { path: '/login', query: { redirect: to.fullPath } }
  }
  if (to.path === '/login' && getToken()) {
    return { path: isOrgAdminOnly() ? '/admin/achievements' : '/admin/overview' }
  }
  // 已认证用户不应停留在注册页
  if (to.path === '/register' && getToken()) {
    return { path: isOrgAdminOnly() ? '/admin/achievements' : '/admin/overview' }
  }
  if (
    isOrgAdminOnly() &&
    to.path.startsWith('/admin') &&
    !orgAdminAllowedPaths.some(path => to.path === path || to.path.startsWith(path + '/'))
  ) {
    return { path: '/admin/achievements' }
  }
})

export default router
