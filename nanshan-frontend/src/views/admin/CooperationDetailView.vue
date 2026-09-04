<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api } from '../../api/client'

const route = useRoute()
const router = useRouter()

const STATUS_META = {
  pending: { label: '待处理', cls: 'pending' },
  accepted: { label: '已受理', cls: 'accepted' },
  confirmed: { label: '已确认', cls: 'confirmed' },
  completed: { label: '已完成', cls: 'completed' },
  rejected: { label: '已拒绝', cls: 'rejected' },
  cancelled: { label: '已取消', cls: 'cancelled' }
}

const EVENT_LABELS = {
  create: '发起意向',
  accept: '受理',
  reject: '拒绝',
  cancel: '取消',
  confirm: '确认合作',
  complete: '标记完成'
}

const ROLE_LABELS = {
  initiator: '发起方',
  target_owner: '目标方',
  admin: '管理员'
}

const TYPE_META = {
  achievement: '成果',
  demand: '需求'
}

const loading = ref(false)
const loadError = ref('')
const detail = ref(null)

const fmtTime = v => (v ? String(v).replace('T', ' ').slice(0, 16) : '-')

const statusLabel = status => STATUS_META[status]?.label || status || '-'
const statusClass = status => STATUS_META[status]?.cls || 'unknown'
const typeLabel = type => TYPE_META[type] || type || '-'
const typeClass = type => (type === 'achievement' ? 'blue' : type === 'demand' ? 'orange' : '')

const fetchDetail = async () => {
  loading.value = true
  loadError.value = ''
  try {
    detail.value = await api('/admin/cooperations/' + route.params.id)
  } catch (err) {
    loadError.value = err.message || '加载失败'
    detail.value = null
  } finally {
    loading.value = false
  }
}

onMounted(fetchDetail)

const goBack = () => {
  router.push('/admin/cooperation')
}

const initiatorText = computed(() => {
  const d = detail.value || {}
  if (d.initiatorName && d.initiatorUserNo) {
    return `${d.initiatorName}（${d.initiatorUserNo}）`
  }
  return d.initiatorName || d.initiatorUserNo || '-'
})

const targetOwnerText = computed(() => {
  const d = detail.value || {}
  if (d.targetOwnerName && d.targetOwnerUserNo) {
    return `${d.targetOwnerName}（${d.targetOwnerUserNo}）`
  }
  return d.targetOwnerName || d.targetOwnerUserNo || '-'
})

const milestones = computed(() => {
  const d = detail.value || {}
  return [
    { label: '受理时间', value: d.acceptedAt },
    { label: '确认时间', value: d.confirmedAt },
    { label: '完成时间', value: d.completedAt },
    { label: '关闭时间', value: d.closedAt }
  ].filter(item => item.value)
})

const events = computed(() => {
  const list = detail.value?.events || []
  return [...list].sort((a, b) =>
    String(a.createdAt || '').localeCompare(String(b.createdAt || ''))
  )
})

const eventLabel = type => EVENT_LABELS[type] || type || '-'

const isTerminalEvent = type => type === 'reject' || type === 'cancel'

const transitionText = event => {
  if (!event.fromStatus) return statusLabel(event.toStatus)
  return `${statusLabel(event.fromStatus)} → ${statusLabel(event.toStatus)}`
}

const operatorText = event => {
  const role = ROLE_LABELS[event.operatorRole] || event.operatorRole || '-'
  return event.operatorUserId ? `${role} · ${event.operatorUserId}` : role
}
</script>

<template>
  <div class="cooperation-detail">

    <div class="page-title">

      <button
        class="back-title"
        @click="goBack"
      >
        ←
      </button>

      <h1>
        合作意向详情
      </h1>

      <div
        v-if="detail"
        class="title-meta"
      >

        <span class="header-id">
          {{ detail.id }}
        </span>

        <span
          class="status-tag"
          :class="statusClass(detail.status)"
        >
          <i></i>

          {{ statusLabel(detail.status) }}
        </span>

        <span class="header-time">
          {{ fmtTime(detail.createdAt) }}
        </span>

      </div>

    </div>


    <div
      v-if="loading"
      class="state-tip"
    >
      加载中…
    </div>


    <div
      v-else-if="loadError"
      class="error-card"
    >

      <p>
        {{ loadError }}
      </p>

      <div class="error-actions">

        <button
          class="retry-btn"
          @click="fetchDetail"
        >
          重试
        </button>

        <button
          class="back-btn"
          @click="goBack"
        >
          返回列表
        </button>

      </div>

    </div>


    <template v-else-if="detail">

      <div class="top-grid">

        <section class="info-card">

          <div class="info-row">

            <label>
              发起人
            </label>

            <div>
              <strong>
                {{ initiatorText }}
              </strong>
            </div>

          </div>


          <div class="info-row">

            <label>
              目标持有方
            </label>

            <div>
              <strong>
                {{ targetOwnerText }}
              </strong>
            </div>

          </div>


          <div class="info-row">

            <label>
              发起时间
            </label>

            <span>
              {{ fmtTime(detail.createdAt) }}
            </span>

          </div>


          <div
            v-for="item in milestones"
            :key="item.label"
            class="info-row"
          >

            <label>
              {{ item.label }}
            </label>

            <span>
              {{ fmtTime(item.value) }}
            </span>

          </div>

        </section>


        <section class="progress-card">

          <h2>
            状态流转
          </h2>


          <div class="progress-list">

            <div
              v-for="item in events"
              :key="item.id"
              class="progress-item"
              :class="
                isTerminalEvent(item.eventType)
                  ? 'rejected'
                  : 'done'
              "
            >

              <div class="progress-marker">

                <span class="point">
                  {{
                    isTerminalEvent(
                      item.eventType
                    )
                      ? '×'
                      : '✓'
                  }}
                </span>

                <span class="line"></span>

              </div>


              <div class="progress-main">

                <div class="progress-name">
                  {{ eventLabel(item.eventType) }}
                </div>

                <div class="progress-desc">
                  {{ transitionText(item) }}
                </div>

                <div
                  v-if="item.remark"
                  class="progress-desc"
                >
                  备注：{{ item.remark }}
                </div>

              </div>


              <div class="progress-operator">

                <div>
                  {{ operatorText(item) }}
                </div>

                <div class="progress-time">
                  {{ fmtTime(item.createdAt) }}
                </div>

              </div>

            </div>


            <div
              v-if="!events.length"
              class="empty"
            >
              暂无流转记录
            </div>

          </div>

        </section>

      </div>


      <section class="description-card">

        <div class="description-row">

          <label>
            目标类型
          </label>

          <div>
            <span
              class="type-badge"
              :class="typeClass(detail.targetType)"
            >
              {{ typeLabel(detail.targetType) }}
            </span>
          </div>

        </div>


        <div class="description-row">

          <label>
            目标标题
          </label>

          <p>
            {{ detail.targetTitle || '-' }}
          </p>

        </div>


        <div class="description-row">

          <label>
            目标 ID
          </label>

          <p>
            {{ detail.targetId || '-' }}
          </p>

        </div>


        <div class="description-row">

          <label>
            留言
          </label>

          <p>
            {{ detail.message || '-' }}
          </p>

        </div>

      </section>


      <section class="bottom-actions">

        <button
          class="back-btn"
          @click="goBack"
        >
          返回列表
        </button>

      </section>

    </template>


    <div
      v-else
      class="not-found"
    >
      未找到该合作意向
    </div>

  </div>
</template>

<style scoped>
.cooperation-detail {
  width: 100%;
}

.page-title {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 14px;
}

.page-title h1 {
  margin: 0;
  color: #1d2939;
  font-size: 22px;
}

.back-title {
  padding: 0;
  border: 0;
  background: transparent;
  color: #314055;
  font-size: 28px;
}

.title-meta {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-left: auto;
}

.header-id {
  color: #374459;
  font-size: 14px;
  font-weight: 600;
}

.header-time {
  color: #8995a5;
  font-size: 13px;
}

.top-grid {
  display: grid;
  grid-template-columns:
    minmax(0, 1.65fr)
    minmax(350px, 0.95fr);
  gap: 18px;
}

.info-card,
.progress-card,
.description-card,
.bottom-actions {
  border: 1px solid #e8edf4;
  border-radius: 10px;
  background: white;
  box-shadow:
    0 2px 14px
    rgba(40, 72, 110, 0.06);
}

.info-card {
  padding: 20px 27px;
}

.info-row {
  display: grid;
  grid-template-columns:
    135px 1fr;
  align-items: center;
  min-height: 48px;
}

.info-row label {
  color: #647084;
  font-size: 14px;
}

.info-row strong,
.info-row div,
.info-row span {
  color: #374459;
  font-size: 14px;
}

.status-tag {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 5px 8px;
  border-radius: 4px;
}

.status-tag i {
  width: 7px;
  height: 7px;
  border-radius: 50%;
}

.status-tag.pending {
  background: #eaf3ff;
  color: #1677ff;
}

.status-tag.pending i {
  background: #1677ff;
}

.status-tag.accepted {
  background: #e9faf1;
  color: #20b875;
}

.status-tag.accepted i {
  background: #20b875;
}

.status-tag.confirmed {
  background: #f3edff;
  color: #7b5cd6;
}

.status-tag.confirmed i {
  background: #7b5cd6;
}

.status-tag.completed {
  background: #e3f6ec;
  color: #0e8f63;
}

.status-tag.completed i {
  background: #0e8f63;
}

.status-tag.rejected {
  background: #ffecef;
  color: #ef5260;
}

.status-tag.rejected i {
  background: #ef5260;
}

.status-tag.cancelled,
.status-tag.unknown {
  background: #eff1f4;
  color: #768294;
}

.status-tag.cancelled i,
.status-tag.unknown i {
  background: #768294;
}

.type-badge {
  display: inline-flex;
  padding: 3px 8px;
  border-radius: 4px;
  font-size: 11px;
}

.type-badge.blue {
  background: #eaf3ff;
  color: #1677ff;
}

.type-badge.orange {
  background: #fff5e6;
  color: #ec961d;
}

.progress-card {
  padding: 21px 25px;
}

.progress-card h2 {
  margin: 0;
  color: #253347;
  font-size: 16px;
}

.progress-list {
  margin-top: 19px;
}

.progress-item {
  display: grid;
  grid-template-columns:
    30px 1fr 155px;
  min-height: 72px;
}

.progress-marker {
  position: relative;
}

.point {
  position: relative;
  z-index: 2;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 21px;
  height: 21px;
  border: 2px solid #cfd6df;
  border-radius: 50%;
  background: #fff;
  color: white;
  font-size: 11px;
}

.line {
  position: absolute;
  top: 21px;
  bottom: 0;
  left: 10px;
  width: 1px;
  background: #dce3eb;
}

.progress-item:last-child .line {
  display: none;
}

.progress-item.done .point {
  border-color: #1677ff;
  background: #1677ff;
}

.progress-item.rejected .point {
  border-color: #ef5360;
  background: #ef5360;
}

.progress-name {
  color: #3d4a5e;
  font-size: 15px;
  font-weight: 600;
}

.progress-item.done .progress-name {
  color: #1677ff;
}

.progress-item.rejected .progress-name {
  color: #ef5360;
}

.progress-desc {
  margin-top: 7px;
  color: #8995a5;
  font-size: 12px;
}

.progress-operator {
  color: #7c8797;
  font-size: 12px;
  text-align: right;
  word-break: break-all;
}

.progress-time {
  margin-top: 5px;
}

.description-card {
  margin-top: 14px;
  padding: 14px 27px;
}

.description-row {
  display: grid;
  grid-template-columns:
    135px 1fr;
  padding: 14px 0;
}

.description-row + .description-row {
  border-top: 1px solid #edf1f5;
}

.description-row label {
  color: #314055;
  font-weight: 600;
}

.description-row p {
  margin: 0;
  color: #515e70;
  font-size: 13px;
  line-height: 1.9;
}

.description-row div {
  color: #515e70;
}

.empty {
  padding: 35px;
  color: #9ca6b4;
  text-align: center;
}

.bottom-actions {
  display: flex;
  justify-content: center;
  gap: 24px;
  margin-top: 14px;
  padding: 20px;
}

.bottom-actions button {
  min-width: 145px;
  height: 46px;
  border-radius: 5px;
  font-size: 14px;
}

.back-btn {
  border: 1px solid #cfd7e1;
  background: white;
  color: #596577;
}

.state-tip {
  padding: 100px;
  color: #8793a3;
  text-align: center;
}

.error-card {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 14px;
  padding: 60px 20px;
  border: 1px solid #e8edf4;
  border-radius: 10px;
  background: white;
  box-shadow:
    0 2px 14px
    rgba(40, 72, 110, 0.06);
}

.error-card p {
  margin: 0;
  color: #ef5260;
}

.error-actions {
  display: flex;
  gap: 12px;
}

.error-actions button {
  height: 38px;
  padding: 0 22px;
  border-radius: 5px;
}

.error-actions .retry-btn {
  border: 1px solid #1677ff;
  background: #1677ff;
  color: white;
}

.error-actions .back-btn {
  border: 1px solid #cfd7e1;
  background: white;
  color: #596577;
}

.not-found {
  padding: 100px;
  color: #8793a3;
  text-align: center;
}
</style>
