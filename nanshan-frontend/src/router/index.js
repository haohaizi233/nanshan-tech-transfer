import {
  createRouter,
  createWebHistory
} from 'vue-router'

import { getToken } from '../api/client'
import LoginView from '../views/auth/LoginView.vue'
import RegisterView from '../views/auth/RegisterView.vue'

import AdminLayout from '../layouts/AdminLayout.vue'

import OverviewView from '../views/admin/OverviewView.vue'
import AchievementView from '../views/admin/AchievementView.vue'
import InstitutionView from '../views/admin/InstitutionView.vue'
import MembershipReviewView from '../views/admin/MembershipReviewView.vue'
import UserView from '../views/admin/UserView.vue'
import ContentView from '../views/admin/ContentView.vue'
import SystemView from '../views/admin/SystemView.vue'
import LogView from '../views/admin/LogView.vue'
import RequirementView from '../views/admin/RequirementView.vue'

import RequirementDetailView from '../views/admin/RequirementDetailView.vue'

import CooperationView from '../views/admin/CooperationView.vue'

import CooperationDetailView from '../views/admin/CooperationDetailView.vue'

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
        redirect: '/admin/overview'
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
        component: ContentView
      },

      {
        path: 'content',
        name: 'content',
        component: ContentView
      },

      {
        path: 'system',
        name: 'system',
        component: SystemView
      },

      {
        path: 'logs',
        name: 'logs',
        component: LogView
      }
    ]
  },

  {
    path: '/:pathMatch(.*)*',
    redirect: '/login'
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
    return { path: '/admin/overview' }
  }
})

export default router