<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api } from '../../api/client'
import { confirmDialog } from '../../utils/appDialog.js'
import { useAbortable } from '../../api/useAbortable'

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

// 后台审核接口使用 accepted/rejected；保留既有小程序事件名的兼容映射。
EVENT_LABELS.accepted = EVENT_LABELS.accept
EVENT_LABELS.rejected = EVENT_LABELS.reject
EVENT_LABELS.auto_rejected = '自动驳回'

const ROLE_LABELS = {
  initiator: '发起方',
  target_owner: '目标方',
  admin: '管理员'
}

ROLE_LABELS.org_admin = '机构管理员'

const TYPE_META = {
  achievement: '成果',
  demand: '需求'
}

const loading = ref(false)
const loadError = ref('')
const detail = ref(null)
const reviewing = ref(false)
const reviewError = ref('')
const rejectVisible = ref(false)
const rejectReason = ref('')

const { run: runApi } = useAbortable()

const fmtTime = v => (v ? String(v).replace('T', ' ').slice(0, 16) : '-')

const statusLabel = status => STATUS_META[status]?.label || status || '-'
const statusClass = status => STATUS_META[status]?.cls || 'unknown'
const typeLabel = type => TYPE_META[type] || type || '-'
const typeClass = type => (type === 'achievement' ? 'blue' : type === 'demand' ? 'orange' : '')

const fetchDetail = async () => {
  loading.value = true
  loadError.value = ''
  try {
    const data = await runApi('/admin/cooperations/' + route.params.id)
    if (data === null) return // 被取消（导航到其他记录或卸载）
    detail.value = data
  } catch (err) {
    loadError.value = err.message || '加载失败'
    detail.value = null
  } finally {
    loading.value = false
  }
}

onMounted(fetchDetail)
// 详情路由复用组件时，:id 变化须重新加载，否则显示旧记录
watch(() => route.params.id, fetchDetail)

const goBack = () => {
  router.push('/admin/cooperation')
}

const acceptCooperation = async () => {
  if (!detail.value || reviewing.value) return
  const ok = await confirmDialog({
    title: '接受对接',
    message: '确认接受该对接申请吗？',
    confirmText: '接受对接',
    tone: 'primary',
  })
  if (!ok) return

  reviewing.value = true
  reviewError.value = ''
  try {
    detail.value = await api(`/admin/cooperations/${detail.value.id}/accept`, {
      method: 'POST',
      body: { version: detail.value.version }
    })
  } catch (err) {
    reviewError.value = err.message || '接受对接失败'
  } finally {
    reviewing.value = false
  }
}

const openReject = () => {
  rejectReason.value = ''
  reviewError.value = ''
  rejectVisible.value = true
}

const closeReject = () => {
  if (!reviewing.value) rejectVisible.value = false
}

const rejectCooperation = async () => {
  if (!detail.value || reviewing.value) return
  if (!rejectReason.value.trim()) {
    reviewError.value = '请填写驳回原因'
    return
  }

  reviewing.value = true
  reviewError.value = ''
  try {
    detail.value = await api(`/admin/cooperations/${detail.value.id}/reject`, {
      method: 'POST',
      body: {
        version: detail.value.version,
        reason: rejectReason.value.trim()
      }
    })
    rejectVisible.value = false
  } catch (err) {
    reviewError.value = err.message || '驳回对接失败'
  } finally {
    reviewing.value = false
  }
}

const canReview = computed(() => (
  Boolean(detail.value?.canReview) && detail.value?.status === 'pending'
))
const isAssisted = computed(() => (detail.value?.handlingMode || 'direct') === 'assisted')
const canAccept = computed(() => canReview.value && !isAssisted.value)
const canReject = computed(() => canReview.value)

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
          v-if="canAccept"
          class="accept-btn"
          :disabled="reviewing"
          @click="acceptCooperation"
        >
          {{ reviewing ? '处理中…' : '接受对接' }}
        </button>

        <button
          v-if="canReject"
          class="reject-btn"
          :disabled="reviewing"
          @click="openReject"
        >
          驳回对接
        </button>

        <button
          class="back-btn"
          @click="goBack"
        >
          返回列表
        </button>

      </section>

      <p
        v-if="reviewError && !rejectVisible"
        class="review-error"
      >
        {{ reviewError }}
      </p>

      <div
        v-if="rejectVisible"
        class="modal-mask"
        @click.self="closeReject"
      >
        <section class="reject-modal">
          <header class="reject-modal-header">
            <h2>驳回对接申请</h2>
            <button
              type="button"
              :disabled="reviewing"
              @click="closeReject"
            >
              ×
            </button>
          </header>

          <div class="reject-modal-body">
            <p>请填写驳回原因，系统会将它记录到对接进度中。</p>
            <textarea
              v-model="rejectReason"
              maxlength="500"
              rows="4"
              placeholder="请输入驳回原因"
            ></textarea>
            <p
              v-if="reviewError"
              class="review-error"
            >
              {{ reviewError }}
            </p>
          </div>

          <footer class="reject-modal-footer">
            <button
              class="back-btn"
              type="button"
              :disabled="reviewing"
              @click="closeReject"
            >
              取消
            </button>
            <button
              class="reject-btn"
              type="button"
              :disabled="reviewing"
              @click="rejectCooperation"
            >
              {{ reviewing ? '处理中…' : '确认驳回' }}
            </button>
          </footer>
        </section>
      </div>

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

.accept-btn,
.reject-btn {
  border: 1px solid transparent;
  color: #fff;
}

.accept-btn {
  background: #1677ff;
}

.reject-btn {
  background: #ef5360;
}

.bottom-actions button:disabled,
.reject-modal button:disabled {
  cursor: not-allowed;
  opacity: 0.6;
}

.review-error {
  margin: 0 0 14px;
  color: #ef5360;
  font-size: 13px;
  text-align: center;
}

.modal-mask {
  position: fixed;
  z-index: 1000;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 20px;
  background: rgba(20, 34, 52, 0.42);
}

.reject-modal {
  width: min(460px, 100%);
  overflow: hidden;
  border-radius: 10px;
  background: #fff;
  box-shadow: 0 12px 36px rgba(20, 34, 52, 0.2);
}

.reject-modal-header,
.reject-modal-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 20px;
}

.reject-modal-header {
  border-bottom: 1px solid #edf1f5;
}

.reject-modal-header h2 {
  margin: 0;
  color: #253347;
  font-size: 17px;
}

.reject-modal-header button {
  border: 0;
  background: transparent;
  color: #7c8797;
  font-size: 24px;
  line-height: 1;
}

.reject-modal-body {
  padding: 20px;
}

.reject-modal-body > p:first-child {
  margin: 0 0 10px;
  color: #697586;
  font-size: 13px;
}

.reject-modal textarea {
  box-sizing: border-box;
  width: 100%;
  resize: vertical;
  padding: 10px 12px;
  border: 1px solid #cfd7e1;
  border-radius: 6px;
  color: #253347;
  font: inherit;
  line-height: 1.6;
}

.reject-modal textarea:focus {
  border-color: #1677ff;
  outline: none;
}

.reject-modal-footer {
  justify-content: flex-end;
  gap: 12px;
  border-top: 1px solid #edf1f5;
}

.reject-modal-footer button {
  min-width: 88px;
  height: 36px;
  border-radius: 5px;
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
