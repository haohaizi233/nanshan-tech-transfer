<script setup>
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'

import {
  statistics,
  trendMap,
  achievementStatus,
  requirementStatus,
  todoList,
  activityList
} from '../../mock/dashboard'

const router = useRouter()

const trendDays = ref(7)

const currentTrend = computed(() => {
  return trendMap[trendDays.value]
})

const statRouteMap = {
  users: '/admin/users',
  achievements: '/admin/achievements',
  requirements: '/admin/requirements',
  cooperation: '/admin/cooperation',
  pending: '/admin/achievements'
}

const handleStatClick = (item) => {
  const path = statRouteMap[item.key]

  if (path) {
    router.push(path)
  }
}

const goPage = (path) => {
  router.push(path)
}

const createPolylinePoints = (values) => {
  const width = 450
  const startX = 52
  const startY = 188
  const maxValue = 500

  const step = width / (values.length - 1)

  return values
    .map((value, index) => {
      const x = startX + step * index
      const y = startY - (value / maxValue) * 168

      return `${x},${y}`
    })
    .join(' ')
}

const createPointList = (values) => {
  const width = 450
  const startX = 52
  const startY = 188
  const maxValue = 500

  const step = width / (values.length - 1)

  return values.map((value, index) => {
    return {
      x: startX + step * index,
      y: startY - (value / maxValue) * 168,
      value
    }
  })
}

const userPoints = computed(() => {
  return createPolylinePoints(currentTrend.value.users)
})

const achievementPoints = computed(() => {
  return createPolylinePoints(
    currentTrend.value.achievements
  )
})

const requirementPoints = computed(() => {
  return createPolylinePoints(
    currentTrend.value.requirements
  )
})

const userCircles = computed(() => {
  return createPointList(currentTrend.value.users)
})

const achievementCircles = computed(() => {
  return createPointList(
    currentTrend.value.achievements
  )
})

const requirementCircles = computed(() => {
  return createPointList(
    currentTrend.value.requirements
  )
})

const achievementDonut = computed(() => {
  let current = 0

  const parts = achievementStatus.map((item) => {
    const start = current
    current += Number(item.percent.replace('%', ''))

    return `${item.color} ${start}% ${current}%`
  })

  return `conic-gradient(${parts.join(',')})`
})

const requirementDonut = computed(() => {
  let current = 0

  const parts = requirementStatus.map((item) => {
    const start = current
    current += Number(item.percent.replace('%', ''))

    return `${item.color} ${start}% ${current}%`
  })

  return `conic-gradient(${parts.join(',')})`
})
</script>

<template>
  <div class="overview-page">
    <section class="statistics-grid">
      <button
        v-for="item in statistics"
        :key="item.key"
        type="button"
        class="stat-card"
        @click="handleStatClick(item)"
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
            {{ item.value }}
          </div>

          <div class="stat-change">
            较上周

            <span
              :class="
                item.trend === 'up'
                  ? 'trend-up'
                  : 'trend-down'
              "
            >
              {{ item.trend === 'up' ? '↑' : '↓' }}
              {{ item.change }}
            </span>
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
              500
            </text>

            <text x="15" y="66">
              400
            </text>

            <text x="15" y="108">
              300
            </text>

            <text x="15" y="150">
              200
            </text>

            <text x="15" y="192">
              100
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
            <text
              v-for="(label, index) in currentTrend.labels"
              :key="label"
              :x="
                52 +
                (450 /
                  (currentTrend.labels.length - 1)) *
                  index
              "
              y="217"
              text-anchor="middle"
              font-size="10"
            >
              {{ label }}
            </text>
          </g>
        </svg>
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

        <div class="distribution-content">
          <div
            class="donut-chart"
            :style="{
              background: achievementDonut
            }"
          >
            <div class="donut-hole"></div>
          </div>

          <div class="distribution-list">
            <div
              v-for="item in achievementStatus"
              :key="item.name"
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
                （{{ item.percent }}）
              </span>
            </div>
          </div>
        </div>

        <div class="distribution-total">
          总计：3,256
        </div>
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

        <div class="distribution-content">
          <div
            class="donut-chart"
            :style="{
              background: requirementDonut
            }"
          >
            <div class="donut-hole"></div>
          </div>

          <div class="distribution-list">
            <div
              v-for="item in requirementStatus"
              :key="item.name"
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
                （{{ item.percent }}）
              </span>
            </div>
          </div>
        </div>

        <div class="distribution-total">
          总计：2,187
        </div>
      </div>
    </section>

    <section class="bottom-grid">
      <div class="panel list-panel">
        <div class="panel-header">
          <div class="panel-title">
            待办事项

            <span class="todo-count">
              6
            </span>
          </div>

          <button
            type="button"
            class="more-button"
            @click="goPage('/admin/achievements')"
          >
            查看全部 ›
          </button>
        </div>

        <div class="todo-list">
          <div
            v-for="item in todoList"
            :key="item.id"
            class="todo-item"
          >
            <div
              class="todo-icon"
              :class="item.iconClass"
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
              :title="item.text"
            >
              {{ item.text }}
            </div>

            <span
              class="todo-tag"
              :class="item.tagClass"
            >
              {{ item.tag }}
            </span>

            <span class="todo-time">
              {{ item.time }}
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

        <div class="activity-list">
          <div
            v-for="item in activityList"
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

.trend-up {
  margin-left: 5px;
  color: #ff4c56;
}

.trend-down {
  margin-left: 5px;
  color: #20b875;
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

  border-radius: 50%;

  background: #ffffff;
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
    70px
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
    72px;

  align-items: center;
  gap: 7px;

  height: 48px;

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