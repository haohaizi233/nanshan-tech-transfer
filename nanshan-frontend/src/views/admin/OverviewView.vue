<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'

import { api } from '../../api/client'

const router = useRouter()

const fmtTime = (v) => (v ? String(v).replace('T', ' ').slice(0, 16) : '-')
const fmtNum = (v) => (v === null || v === undefined || v === '' ? '-' : Number(v).toLocaleString())

const TODO_KIND_COLORS = {
  achievement: 'blue',
  demand: 'orange',
  organization_application: 'green',
  organization_admin_application: 'purple',
  membership_application: 'green',
  cooperation: 'red'
}

const todoKindColor = (kind) => TODO_KIND_COLORS[kind] || 'blue'

const ACTION_LABELS = {
  'achievement.approve': '通过成果审核',
  'achievement.reject': '驳回成果',
  'achievement.submit': '提交成果',
  'achievement.create': '创建成果',
  'achievement.update': '更新成果',
  'achievement.offline': '下架成果',
  'demand.approve': '通过需求审核',
  'demand.reject': '驳回需求',
  'demand.submit': '提交需求',
  'demand.create': '创建需求',
  'demand.update': '更新需求',
  'demand.cancel': '取消需求',
  'demand.close': '关闭需求',
  'institution.create': '新增机构',
  'institution.update': '更新机构',
  'institution.online': '上架机构',
  'institution.offline': '下架机构'
}

const actionLabel = (action) => ACTION_LABELS[action] || action || '-'

const RESOURCE_DOT_COLORS = {
  achievement: '#3f8cff',
  demand: '#f7a42f',
  institution: '#2bc39f'
}

const ACHIEVEMENT_STATUS_META = [
  { key: 'draft', name: '草稿', color: '#b6bfca' },
  { key: 'pending_review', name: '待审核', color: '#3f8cff' },
  { key: 'published', name: '已发布', color: '#2bc39f' },
  { key: 'offline', name: '已下架', color: '#f7a42f' },
  { key: 'rejected', name: '已驳回', color: '#f0565f' }
]

const DEMAND_STATUS_META = [
  { key: 'draft', name: '草稿', color: '#b6bfca' },
  { key: 'pending_review', name: '待审核', color: '#3f8cff' },
  { key: 'published', name: '已发布', color: '#2bc39f' },
  { key: 'matched', name: '对接中', color: '#8d68ed' },
  { key: 'closed', name: '已关闭', color: '#98a3b3' },
  { key: 'cancelled', name: '已取消', color: '#f7a42f' },
  { key: 'rejected', name: '已驳回', color: '#f0565f' }
]

const summary = ref(null)
const summaryLoading = ref(false)
const summaryError = ref('')

const loadSummary = async () => {
  summaryLoading.value = true
  summaryError.value = ''

  try {
    summary.value = await api('/admin/dashboard/summary')
  } catch (error) {
    summary.value = null
    summaryError.value = error.message || '数据概览加载失败'
  } finally {
    summaryLoading.value = false
  }
}

const pendingQueueRoute = (s) => {
  if (!s) return '/admin/achievements'
  const pendingAchievements = Number(s.pendingAchievements ?? 0)
  const pendingDemands = Number(s.pendingDemands ?? 0)
  const content = pendingAchievements + pendingDemands
  const membership = Number(s.pendingOrganizationApplications ?? 0)
    + Number(s.pendingOrganizationAdminApplications ?? 0)
    + Number(s.pendingMembershipApplications ?? 0)
  const coop = Number(s.pendingCooperations ?? 0)
  if (membership >= content && membership >= coop && membership > 0) return '/admin/membership-review'
  if (coop >= content && coop > 0) return '/admin/cooperation'
  if (pendingDemands > pendingAchievements) return '/admin/requirements'
  return '/admin/achievements'
}

const statCards = computed(() => {
  const s = summary.value

  return [
    {
      key: 'users',
      label: '用户总数',
      value: s?.users,
      icon: 'user',
      color: 'blue',
      route: '/admin/users',
      sub: ''
    },
    {
      key: 'achievements',
      label: '成果总数',
      value: s?.achievements,
      icon: 'achievement',
      color: 'green',
      route: '/admin/achievements',
      sub: ''
    },
    {
      key: 'demands',
      label: '需求总数',
      value: s?.demands,
      icon: 'requirement',
      color: 'orange',
      route: '/admin/requirements',
      sub: ''
    },
    {
      key: 'cooperations',
      label: '合作意向',
      value: s?.cooperations,
      icon: 'cooperation',
      color: 'purple',
      route: '/admin/cooperation',
      sub: ''
    },
    {
      key: 'pending',
      label: '待审核',
      value: s?.pendingTotal,
      icon: 'pending',
      color: 'yellow',
      route: pendingQueueRoute(s),
      sub: s
        ? `内容 ${(s.pendingAchievements ?? 0) + (s.pendingDemands ?? 0)} · 机构认证 ${(s.pendingOrganizationApplications ?? 0) + (s.pendingOrganizationAdminApplications ?? 0) + (s.pendingMembershipApplications ?? 0)} · 对接 ${s.pendingCooperations ?? 0}`
        : ''
    }
  ]
})

const pendingCount = computed(() => summary.value?.pendingTotal ?? 0)

const buildStatusView = (counts, meta, summaryTotal) => {
  const list = meta
    .map((item) => ({ ...item, value: Number(counts?.[item.key] ?? 0) }))
    .filter((item) => item.value > 0)

  const countsSum = list.reduce((sum, item) => sum + item.value, 0)
  const total = countsSum === summaryTotal ? countsSum : summaryTotal

  return { list, total, countsSum }
}

const achievementStatusView = computed(() =>
  buildStatusView(
    summary.value?.achievementStatusCounts,
    ACHIEVEMENT_STATUS_META,
    Number(summary.value?.achievements ?? 0)
  )
)

const demandStatusView = computed(() =>
  buildStatusView(
    summary.value?.demandStatusCounts,
    DEMAND_STATUS_META,
    Number(summary.value?.demands ?? 0)
  )
)

const percentOf = (count, total) => (total ? `${((count / total) * 100).toFixed(1)}%` : '0%')

const buildDonut = (list, countsSum) => {
  if (!list.length || !countsSum) {
    return '#e8edf4'
  }

  let current = 0

  const parts = list.map((item) => {
    const start = (current / countsSum) * 100
    current += item.value
    const end = (current / countsSum) * 100

    return `${item.color} ${start}% ${end}%`
  })

  return `conic-gradient(${parts.join(',')})`
}

const achievementDonut = computed(() =>
  buildDonut(achievementStatusView.value.list, achievementStatusView.value.countsSum)
)

const requirementDonut = computed(() =>
  buildDonut(demandStatusView.value.list, demandStatusView.value.countsSum)
)

const trendDays = ref(7)
const trend = ref(null)
const trendLoading = ref(false)
const trendError = ref('')

const loadTrend = async () => {
  trendLoading.value = true
  trendError.value = ''

  try {
    trend.value = await api('/admin/dashboard/trend', {
      params: { days: trendDays.value }
    })
  } catch (error) {
    trend.value = null
    trendError.value = error.message || '趋势数据加载失败'
  } finally {
    trendLoading.value = false
  }
}

watch(trendDays, () => {
  loadTrend()
})

const trendLabels = computed(() => trend.value?.labels ?? [])

const trendMax = computed(() => {
  const values = [
    ...(trend.value?.users ?? []),
    ...(trend.value?.achievements ?? []),
    ...(trend.value?.demands ?? [])
  ]

  return Math.ceil(Math.max(10, ...values) / 10) * 10
})

const yLabels = computed(() =>
  [1, 0.75, 0.5, 0.25, 0].map((rate) => Math.round(trendMax.value * rate))
)

const labelGap = computed(() => Math.max(1, Math.ceil(trendLabels.value.length / 12)))

const labelStepX = computed(() =>
  trendLabels.value.length > 1 ? 450 / (trendLabels.value.length - 1) : 0
)

const createPolylinePoints = (values) => {
  if (!values.length) {
    return ''
  }

  const step = values.length > 1 ? 450 / (values.length - 1) : 0

  return values
    .map((value, index) => {
      const x = 52 + step * index
      const y = 188 - (value / trendMax.value) * 168

      return `${x},${y}`
    })
    .join(' ')
}

const createPointList = (values) => {
  if (!values.length) {
    return []
  }

  const step = values.length > 1 ? 450 / (values.length - 1) : 0

  return values.map((value, index) => ({
    x: 52 + step * index,
    y: 188 - (value / trendMax.value) * 168,
    value
  }))
}

const userPoints = computed(() => createPolylinePoints(trend.value?.users ?? []))
const achievementPoints = computed(() => createPolylinePoints(trend.value?.achievements ?? []))
const requirementPoints = computed(() => createPolylinePoints(trend.value?.demands ?? []))
const userCircles = computed(() => createPointList(trend.value?.users ?? []))
const achievementCircles = computed(() => createPointList(trend.value?.achievements ?? []))
const requirementCircles = computed(() => createPointList(trend.value?.demands ?? []))

const todoItems = ref([])
const todoLoading = ref(false)
const todoError = ref('')

const loadTodo = async () => {
  todoLoading.value = true
  todoError.value = ''

  try {
    const data = await api('/admin/dashboard/todos', { params: { limit: 5 } })
    todoItems.value = data?.list ?? []
  } catch (error) {
    todoItems.value = []
    todoError.value = error.message || '待办数据加载失败'
  } finally {
    todoLoading.value = false
  }
}

const activityLogs = ref([])
const activityLoading = ref(false)
const activityError = ref('')

const loadActivity = async () => {
  activityLoading.value = true
  activityError.value = ''

  try {
    const data = await api('/admin/audit-logs', { params: { page: 1, pageSize: 8 } })

    activityLogs.value = data?.list ?? []
  } catch (error) {
    activityLogs.value = []
    activityError.value = error.message || '动态数据加载失败'
  } finally {
    activityLoading.value = false
  }
}

const activityItems = computed(() =>
  activityLogs.value.slice(0, 8).map((item) => ({
    id: item.id,
    color: RESOURCE_DOT_COLORS[item.resourceType] || '#98a3b3',
    text: `${item.actorUserNo || '系统'} ${actionLabel(item.action)}`,
    time: fmtTime(item.createdAt)
  }))
)

const goPage = (path) => {
  router.push(path)
}

onMounted(() => {
  loadSummary()
  loadTrend()
  loadTodo()
  loadActivity()
})
</script>

<template>
  <div class="overview-page">
    <div v-if="summaryError" class="error-banner">
      <span>数据概览加载失败：{{ summaryError }}</span>

      <button
        type="button"
        @click="loadSummary"
      >
        重试
      </button>
    </div>

    <section class="statistics-grid">
      <button
        v-for="item in statCards"
        :key="item.key"
        type="button"
        class="stat-card"
        @click="goPage(item.route)"
      >
        <div
          class="stat-icon"
          :class="item.color"
        >
          <svg
            v-if="item.icon === 'user'"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
          >
            <circle cx="9" cy="8" r="4" />

            <path
              d="M3 21v-2a6 6 0 0 1 12 0v2"
            />

            <path
              d="M16 4a4 4 0 0 1 0 8"
            />

            <path
              d="M18 14a6 6 0 0 1 3 5v2"
            />
          </svg>

          <svg
            v-else-if="item.icon === 'achievement'"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
          >
            <path
              d="m12 3 9 4-9 4-9-4 9-4Z"
            />

            <path
              d="m3 12 9 4 9-4"
            />

            <path
              d="m3 17 9 4 9-4"
            />
          </svg>

          <svg
            v-else-if="item.icon === 'requirement'"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
          >
            <rect
              x="4"
              y="3"
              width="16"
              height="18"
              rx="2"
            />

            <path d="M8 7h8M8 11h8M8 15h6" />
          </svg>

          <svg
            v-else-if="item.icon === 'cooperation'"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
          >
            <path d="m8 12 3 3 5-5" />
            <path d="M2 12 7 7l4 4 4-4 7 7-10 8Z" />
          </svg>

          <svg
            v-else
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
          >
            <path
              d="M6 3h12v4a6 6 0 0 1-12 0V3Z"
            />

            <path d="M8 21h8M12 13v8" />
          </svg>
        </div>

        <div class="stat-content">
          <div class="stat-label">
            {{ item.label }}

            <span class="info">
              i
            </span>
          </div>

          <div class="stat-value">
            {{ fmtNum(item.value) }}
          </div>

          <div
            v-if="item.sub"
            class="stat-change"
          >
            {{ item.sub }}
          </div>
        </div>
      </button>
    </section>

    <section class="charts-grid">
      <div class="panel trend-panel">
        <div class="panel-header">
          <div class="panel-title">
            近{{ trendDays }}日数据趋势

            <span class="info">
              i
            </span>
          </div>

          <select v-model="trendDays">
            <option :value="7">
              近7日
            </option>

            <option :value="30">
              近30日
            </option>

            <option :value="90">
              近90日
            </option>
          </select>
        </div>

        <div
          v-if="trendLoading"
          class="panel-state"
        >
          加载中…
        </div>

        <div
          v-else-if="trendError"
          class="panel-state error"
        >
          <span>{{ trendError }}</span>

          <button
            type="button"
            @click="loadTrend"
          >
            重试
          </button>
        </div>

        <template v-else>
          <div class="chart-legend">
            <span>
              <i class="legend-dot blue"></i>
              新增用户
            </span>

            <span>
              <i class="legend-dot green"></i>
              新增成果
            </span>

            <span>
              <i class="legend-dot orange"></i>
              新增需求
            </span>
          </div>

          <svg
            class="trend-chart"
            viewBox="0 0 540 230"
            preserveAspectRatio="none"
          >
            <g
              stroke="#edf1f5"
              stroke-width="1"
            >
              <line
                x1="52"
                y1="20"
                x2="502"
                y2="20"
              />

              <line
                x1="52"
                y1="62"
                x2="502"
                y2="62"
              />

              <line
                x1="52"
                y1="104"
                x2="502"
                y2="104"
              />

              <line
                x1="52"
                y1="146"
                x2="502"
                y2="146"
              />

              <line
                x1="52"
                y1="188"
                x2="502"
                y2="188"
              />
            </g>

            <g
              class="chart-axis"
              font-size="11"
            >
              <text x="15" y="24">
                {{ yLabels[0] }}
              </text>

              <text x="15" y="66">
                {{ yLabels[1] }}
              </text>

              <text x="15" y="108">
                {{ yLabels[2] }}
              </text>

              <text x="15" y="150">
                {{ yLabels[3] }}
              </text>

              <text x="15" y="192">
                {{ yLabels[4] }}
              </text>
            </g>

            <polyline
              :points="userPoints"
              fill="none"
              stroke="#2f80f7"
              stroke-width="2"
            />

            <polyline
              :points="achievementPoints"
              fill="none"
              stroke="#2bc39f"
              stroke-width="2"
            />

            <polyline
              :points="requirementPoints"
              fill="none"
              stroke="#f7a42f"
              stroke-width="2"
            />

            <g
              fill="#ffffff"
              stroke="#2f80f7"
              stroke-width="2"
            >
              <circle
                v-for="point in userCircles"
                :key="`user-${point.x}`"
                :cx="point.x"
                :cy="point.y"
                r="3"
              />
            </g>

            <g
              fill="#ffffff"
              stroke="#2bc39f"
              stroke-width="2"
            >
              <circle
                v-for="point in achievementCircles"
                :key="`achievement-${point.x}`"
                :cx="point.x"
                :cy="point.y"
                r="3"
              />
            </g>

            <g
              fill="#ffffff"
              stroke="#f7a42f"
              stroke-width="2"
            >
              <circle
                v-for="point in requirementCircles"
                :key="`requirement-${point.x}`"
                :cx="point.x"
                :cy="point.y"
                r="3"
              />
            </g>

            <g class="chart-axis">
              <template
                v-for="(label, index) in trendLabels"
                :key="`label-${index}`"
              >
                <text
                  v-if="index % labelGap === 0"
                  :x="52 + labelStepX * index"
                  y="217"
                  text-anchor="middle"
                  font-size="10"
                >
                  {{ label }}
                </text>
              </template>
            </g>
          </svg>
        </template>
      </div>

      <div class="panel distribution-panel">
        <div class="panel-header">
          <div class="panel-title">
            成果状态分布

            <span class="info">
              i
            </span>
          </div>

          <button
            type="button"
            class="more-button"
            @click="goPage('/admin/achievements')"
          >
            更多 ›
          </button>
        </div>

        <div
          v-if="summaryLoading"
          class="panel-state"
        >
          加载中…
        </div>

        <template v-else>
          <div class="distribution-content">
            <div
              class="donut-chart"
              :style="{
                background: achievementDonut
              }"
            >
              <div class="donut-hole">
                <span
                  v-if="!achievementStatusView.list.length"
                  class="donut-empty"
                >
                  暂无数据
                </span>
              </div>
            </div>

            <div class="distribution-list">
              <div
                v-for="item in achievementStatusView.list"
                :key="item.key"
                class="distribution-item"
              >
                <div class="distribution-name">
                  <span
                    class="distribution-dot"
                    :style="{
                      background: item.color
                    }"
                  ></span>

                  {{ item.name }}
                </div>

                <span>
                  {{ item.value.toLocaleString() }}
                  （{{ percentOf(item.value, achievementStatusView.total) }}）
                </span>
              </div>
            </div>
          </div>

          <div class="distribution-total">
            总计：{{ achievementStatusView.total.toLocaleString() }}
          </div>
        </template>
      </div>

      <div class="panel distribution-panel">
        <div class="panel-header">
          <div class="panel-title">
            需求状态分布

            <span class="info">
              i
            </span>
          </div>

          <button
            type="button"
            class="more-button"
            @click="goPage('/admin/requirements')"
          >
            更多 ›
          </button>
        </div>

        <div
          v-if="summaryLoading"
          class="panel-state"
        >
          加载中…
        </div>

        <template v-else>
          <div class="distribution-content">
            <div
              class="donut-chart"
              :style="{
                background: requirementDonut
              }"
            >
              <div class="donut-hole">
                <span
                  v-if="!demandStatusView.list.length"
                  class="donut-empty"
                >
                  暂无数据
                </span>
              </div>
            </div>

            <div class="distribution-list">
              <div
                v-for="item in demandStatusView.list"
                :key="item.key"
                class="distribution-item"
              >
                <div class="distribution-name">
                  <span
                    class="distribution-dot"
                    :style="{
                      background: item.color
                    }"
                  ></span>

                  {{ item.name }}
                </div>

                <span>
                  {{ item.value.toLocaleString() }}
                  （{{ percentOf(item.value, demandStatusView.total) }}）
                </span>
              </div>
            </div>
          </div>

          <div class="distribution-total">
            总计：{{ demandStatusView.total.toLocaleString() }}
          </div>
        </template>
      </div>
    </section>

    <section class="bottom-grid">
      <div class="panel list-panel">
        <div class="panel-header">
          <div class="panel-title">
            待办事项

            <span class="todo-count">
              {{ pendingCount }}
            </span>
          </div>

        </div>

        <div
          v-if="todoLoading"
          class="panel-state"
        >
          加载中…
        </div>

        <div
          v-else-if="todoError"
          class="panel-state error"
        >
          <span>{{ todoError }}</span>

          <button
            type="button"
            @click="loadTodo"
          >
            重试
          </button>
        </div>

        <div
          v-else-if="!todoItems.length"
          class="panel-state"
        >
          暂无待办事项
        </div>

        <div
          v-else
          class="todo-list"
        >
          <div
            v-for="item in todoItems"
            :key="item.id"
            class="todo-item"
          >
            <div
              class="todo-icon"
              :class="todoKindColor(item.kind)"
            >
              <svg
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
              >
                <circle
                  cx="12"
                  cy="8"
                  r="4"
                />

                <path
                  d="M5 21v-2a7 7 0 0 1 14 0v2"
                />
              </svg>
            </div>

            <div
              class="todo-text"
              :title="item.title"
            >
              {{ item.title }}
            </div>

            <span
              class="todo-tag"
              :class="todoKindColor(item.kind)"
            >
              {{ item.label }}
            </span>

            <span class="todo-time">
              {{ fmtTime(item.createdAt) }}
            </span>

            <button
              type="button"
              class="process-button"
              @click="goPage(item.route)"
            >
              去处理
            </button>
          </div>
        </div>
      </div>

      <div class="panel list-panel">
        <div class="panel-header">
          <div class="panel-title">
            最新动态
          </div>

          <button
            type="button"
            class="more-button"
            @click="goPage('/admin/logs')"
          >
            查看全部 ›
          </button>
        </div>

        <div
          v-if="activityLoading"
          class="panel-state"
        >
          加载中…
        </div>

        <div
          v-else-if="activityError"
          class="panel-state error"
        >
          <span>{{ activityError }}</span>

          <button
            type="button"
            @click="loadActivity"
          >
            重试
          </button>
        </div>

        <div
          v-else-if="!activityItems.length"
          class="panel-state"
        >
          暂无动态
        </div>

        <div
          v-else
          class="activity-list"
        >
          <div
            v-for="item in activityItems"
            :key="item.id"
            class="activity-item"
          >
            <span
              class="activity-dot"
              :style="{
                background: item.color
              }"
            ></span>

            <div
              class="activity-text"
              :title="item.text"
            >
              {{ item.text }}
            </div>

            <span class="activity-time">
              {{ item.time }}
            </span>
          </div>
        </div>
      </div>
    </section>
  </div>
</template>

<style scoped>
.overview-page {
  width: 100%;
}

.panel {
  border: 1px solid #e8edf4;
  border-radius: 11px;
  background: #ffffff;
  box-shadow:
    0 2px 14px rgba(40, 72, 110, 0.07);
}

.error-banner {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;

  margin-bottom: 13px;
  padding: 11px 16px;

  border: 1px solid #ffd6d9;
  border-radius: 9px;

  background: #fff1f2;

  color: #d93a44;

  font-size: 13px;
}

.error-banner button {
  flex-shrink: 0;

  height: 30px;
  padding: 0 16px;

  border: 1px solid #d93a44;
  border-radius: 5px;

  background: #ffffff;

  color: #d93a44;

  font-size: 12px;
}

.error-banner button:hover {
  background: #d93a44;

  color: #ffffff;
}

.panel-state {
  display: flex;
  align-items: center;
  justify-content: center;

  height: 220px;

  color: #9aa5b5;

  font-size: 12px;
}

.panel-state.error {
  gap: 12px;

  color: #e5484d;
}

.panel-state.error button {
  height: 28px;
  padding: 0 14px;

  border: 1px solid #e5484d;
  border-radius: 4px;

  background: #ffffff;

  color: #e5484d;

  font-size: 12px;
}

.panel-state.error button:hover {
  background: #e5484d;

  color: #ffffff;
}

.statistics-grid {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: 12px;
}

.stat-card {
  display: flex;
  align-items: center;
  gap: 16px;

  min-width: 0;
  height: 134px;

  padding: 22px 20px;

  border: 1px solid #e8edf4;
  border-radius: 11px;

  background: #ffffff;

  color: inherit;
  text-align: left;

  box-shadow:
    0 2px 14px rgba(40, 72, 110, 0.07);

  transition:
    transform 0.18s ease,
    box-shadow 0.18s ease;
}

.stat-card:hover {
  transform: translateY(-2px);

  box-shadow:
    0 7px 22px rgba(40, 72, 110, 0.11);
}

.stat-icon {
  display: flex;
  align-items: center;
  justify-content: center;

  flex-shrink: 0;

  width: 58px;
  height: 58px;

  border-radius: 50%;
}

.stat-icon svg {
  width: 31px;
  height: 31px;

  stroke-width: 2;
}

.stat-icon.blue {
  background: #eaf3ff;
  color: #1677ff;
}

.stat-icon.green {
  background: #e7f9ee;
  color: #18b96d;
}

.stat-icon.orange {
  background: #fff1e4;
  color: #ff8b26;
}

.stat-icon.purple {
  background: #efebff;
  color: #795cef;
}

.stat-icon.yellow {
  background: #fff7dc;
  color: #ecaa1b;
}

.stat-content {
  min-width: 0;
}

.stat-label {
  display: flex;
  align-items: center;
  gap: 6px;

  color: #6d7786;

  font-size: 14px;
}

.info {
  display: inline-flex;
  align-items: center;
  justify-content: center;

  width: 14px;
  height: 14px;

  border: 1px solid #aab4c2;
  border-radius: 50%;

  color: #98a3b1;

  font-size: 9px;
  font-style: normal;
}

.stat-value {
  margin-top: 7px;

  color: #151e2d;

  font-size: 26px;
  font-weight: 700;
}

.stat-change {
  margin-top: 8px;

  color: #8a95a4;

  font-size: 12px;
}

.charts-grid {
  display: grid;
  grid-template-columns:
    minmax(0, 1.16fr)
    minmax(0, 0.92fr)
    minmax(0, 0.92fr);

  gap: 12px;

  margin-top: 13px;
}

.trend-panel,
.distribution-panel {
  height: 314px;
  padding: 18px;
}

.panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.panel-title {
  display: flex;
  align-items: center;
  gap: 7px;

  color: #1d2735;

  font-size: 16px;
  font-weight: 700;
}

.panel-header select {
  min-width: 104px;
  height: 34px;

  padding: 0 10px;

  outline: none;

  border: 1px solid #dce4ee;
  border-radius: 5px;

  background: white;

  color: #687487;
}

.chart-legend {
  display: flex;
  gap: 24px;

  margin-top: 16px;

  color: #657285;

  font-size: 11px;
}

.chart-legend span {
  display: flex;
  align-items: center;
  gap: 7px;
}

.legend-dot {
  display: inline-block;

  width: 7px;
  height: 7px;

  border-radius: 50%;
}

.legend-dot.blue {
  background: #2f80f7;
}

.legend-dot.green {
  background: #2bc39f;
}

.legend-dot.orange {
  background: #f7a42f;
}

.trend-chart {
  display: block;

  width: 100%;
  height: 218px;

  margin-top: 6px;
}

.chart-axis {
  fill: #7f8a98;
}

.more-button {
  padding: 5px 3px;

  border: 0;

  background: transparent;

  color: #929dac;

  font-size: 12px;
}

.more-button:hover {
  color: #1677ff;
}

.distribution-content {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 23px;

  height: 220px;
}

.donut-chart {
  position: relative;

  flex-shrink: 0;

  width: 160px;
  height: 160px;

  border-radius: 50%;
}

.donut-hole {
  position: absolute;
  inset: 35px;

  display: flex;
  align-items: center;
  justify-content: center;

  border-radius: 50%;

  background: #ffffff;
}

.donut-empty {
  color: #98a3b3;

  font-size: 11px;
}

.distribution-list {
  width: 165px;
}

.distribution-item {
  display: flex;
  align-items: center;
  justify-content: space-between;

  gap: 7px;

  margin: 11px 0;

  color: #737e8d;

  font-size: 10px;

  white-space: nowrap;
}

.distribution-name {
  display: flex;
  align-items: center;
  gap: 6px;

  color: #535f70;
}

.distribution-dot {
  display: inline-block;

  width: 7px;
  height: 7px;

  border-radius: 50%;
}

.distribution-total {
  margin-top: -2px;

  color: #485466;

  font-size: 12px;
  font-weight: 600;

  text-align: center;
}

.bottom-grid {
  display: grid;
  grid-template-columns:
    minmax(0, 1fr)
    minmax(0, 1.24fr);

  gap: 12px;

  margin-top: 13px;
}

.list-panel {
  height: 332px;
  padding: 18px;
}

.todo-count {
  display: inline-flex;
  align-items: center;
  justify-content: center;

  width: 20px;
  height: 20px;

  margin-left: 3px;

  border-radius: 50%;

  background: #ff424c;

  color: white;

  font-size: 11px;
}

.todo-list,
.activity-list {
  margin-top: 11px;
}

.todo-item {
  display: grid;
  grid-template-columns:
    34px
    minmax(0, 1fr)
    72px
    104px
    60px;

  align-items: center;
  gap: 8px;

  height: 48px;

  border-top: 1px solid #f0f3f7;

  font-size: 12px;
}

.todo-item:first-child {
  border-top: 0;
}

.todo-icon {
  display: flex;
  align-items: center;
  justify-content: center;

  width: 27px;
  height: 27px;

  border-radius: 5px;

  color: white;
}

.todo-icon svg {
  width: 15px;
  height: 15px;

  stroke-width: 2;
}

.todo-icon.blue {
  background: #327ee9;
}

.todo-icon.green {
  background: #34c382;
}

.todo-icon.purple {
  background: #8d68ed;
}

.todo-icon.orange {
  background: #f7b42c;
}

.todo-icon.red {
  background: #f05f67;
}

.todo-text {
  overflow: hidden;

  color: #4b5666;

  white-space: nowrap;
  text-overflow: ellipsis;
}

.todo-tag {
  display: inline-flex;
  align-items: center;
  justify-content: center;

  min-height: 25px;

  padding: 3px 7px;

  border-radius: 4px;

  font-size: 10px;
}

.todo-tag.blue {
  background: #eaf3ff;
  color: #3783e9;
}

.todo-tag.green {
  background: #e9faf1;
  color: #31b77b;
}

.todo-tag.purple {
  background: #f1edff;
  color: #8068ee;
}

.todo-tag.orange {
  background: #fff3e4;
  color: #f49a34;
}

.todo-tag.red {
  background: #ffecef;
  color: #ef5a67;
}

.todo-time {
  color: #9aa5b5;

  text-align: right;
  white-space: nowrap;
}

.process-button {
  height: 28px;

  border: 1px solid #5fa3ff;
  border-radius: 4px;

  background: #ffffff;

  color: #1677ff;

  font-size: 11px;
}

.process-button:hover {
  background: #1677ff;
  color: #ffffff;
}

.activity-item {
  display: grid;
  grid-template-columns:
    13px
    minmax(0, 1fr)
    104px;

  align-items: center;
  gap: 7px;

  height: 32px;

  border-top: 1px solid #f0f3f7;

  font-size: 12px;
}

.activity-item:first-child {
  border-top: 0;
}

.activity-dot {
  width: 7px;
  height: 7px;

  border-radius: 50%;
}

.activity-text {
  overflow: hidden;

  color: #485364;

  white-space: nowrap;
  text-overflow: ellipsis;
}

.activity-time {
  color: #9aa5b5;

  text-align: right;
  white-space: nowrap;
}

@media (max-width: 1450px) {
  .stat-card {
    padding-left: 15px;
    padding-right: 12px;
  }

  .stat-value {
    font-size: 23px;
  }

  .stat-icon {
    width: 52px;
    height: 52px;
  }

  .distribution-content {
    gap: 12px;
  }

  .donut-chart {
    width: 140px;
    height: 140px;
  }

  .donut-hole {
    inset: 31px;
  }
}
</style>
