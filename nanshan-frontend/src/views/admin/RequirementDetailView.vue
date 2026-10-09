<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api } from '../../api/client'
import { useAbortable } from '../../api/useAbortable'
import { useAuthStore } from '../../stores/auth.js'

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()

const loading = ref(false)
const loadError = ref('')
const detail = ref(null)
const isPlatformAdmin = computed(() => (authStore.user?.roles || []).includes('admin'))

const submitting = ref(false)
const actionError = ref('')
const rejectVisible = ref(false)
const rejectReason = ref('')

const { run: runApi } = useAbortable()

const statusClassMap = {
  draft: 'draft',
  pending_review: 'pending',
  published: 'published',
  matched: 'matched',
  closed: 'closed',
  cancelled: 'cancelled',
  rejected: 'rejected'
}

const getStatusClass = status => statusClassMap[status] || 'draft'
const fmtTime = v => (v ? String(v).replace('T', ' ').slice(0, 16) : '-')

const budgetText = computed(() => {
  if (!detail.value) return '-'
  return detail.value.budget || (detail.value.budgetNegotiable ? '面议' : '-')
})

const submitterText = computed(() => {
  if (!detail.value) return '-'
  return detail.value.submitterName || detail.value.submitterUserNo || '-'
})

const fetchDetail = async () => {
  loading.value = true
  loadError.value = ''
  try {
    const data = await runApi('/admin/demands/' + route.params.id)
    if (data === null) return // 被取消（导航到其他记录或卸载）
    detail.value = data
  } catch (err) {
    detail.value = null
    loadError.value = err.message || '加载失败'
  } finally {
    loading.value = false
  }
}

onMounted(fetchDetail)
// 详情路由复用组件时，:id 变化须重新加载，否则显示旧记录
watch(() => route.params.id, fetchDetail)

const goBack = () => {
  router.push('/admin/requirements')
}

const approve = async () => {
  if (!detail.value || submitting.value) return
  submitting.value = true
  actionError.value = ''
  try {
    await api(`/admin/demands/${detail.value.id}/approve`, {
      method: 'POST',
      body: { version: detail.value.version }
    })
    fetchDetail()
  } catch (err) {
    actionError.value = err.message || '操作失败'
  } finally {
    submitting.value = false
  }
}

const openReject = () => {
  rejectReason.value = ''
  actionError.value = ''
  rejectVisible.value = true
}

const closeReject = () => {
  if (submitting.value) return
  rejectVisible.value = false
}

const submitReject = async () => {
  if (!detail.value || submitting.value) return
  if (!rejectReason.value.trim()) {
    actionError.value = '请填写驳回原因'
    return
  }
  submitting.value = true
  actionError.value = ''
  try {
    await api(`/admin/demands/${detail.value.id}/reject`, {
      method: 'POST',
      body: { version: detail.value.version, reason: rejectReason.value.trim() }
    })
    rejectVisible.value = false
    fetchDetail()
  } catch (err) {
    actionError.value = err.message || '操作失败'
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <div class="detail-page">

    <div v-if="loading" class="state-block">加载中…</div>

    <div v-else-if="loadError" class="state-block">
      <p class="state-error">{{ loadError }}</p>
      <div class="state-actions">
        <button type="button" class="primary-btn" @click="fetchDetail">重试</button>
        <button type="button" class="back-btn" @click="goBack">返回列表</button>
      </div>
    </div>

    <template v-else-if="detail">

      <div class="back-row">
        <button type="button" @click="goBack">‹ 返回</button>
      </div>


      <div class="title-row">

        <div>
          <h1>{{ detail.title }}</h1>

          <div class="title-meta">
            <span class="status-badge" :class="getStatusClass(detail.status)">
              {{ detail.statusLabel || detail.status }}
            </span>

            <span>提交时间：{{ fmtTime(detail.createdAt) }}</span>

            <span v-if="detail.publishedAt">发布时间：{{ fmtTime(detail.publishedAt) }}</span>
          </div>
        </div>

      </div>


      <section class="summary-card">

        <div class="summary-item">
          <div class="summary-icon blue">▤</div>
          <div>
            <label>分类</label>
            <strong>{{ detail.categoryName || '-' }}</strong>
          </div>
        </div>

        <div class="summary-item">
          <div class="summary-icon green">▦</div>
          <div>
            <label>所属机构</label>
            <strong :title="detail.orgName">{{ detail.orgName || '-' }}</strong>
          </div>
        </div>

        <div class="summary-item">
          <div class="summary-icon purple">⌖</div>
          <div>
            <label>地区</label>
            <strong>{{ detail.region || '-' }}</strong>
          </div>
        </div>

        <div class="summary-item">
          <div class="summary-icon yellow">◫</div>
          <div>
            <label>预算</label>
            <strong>{{ budgetText }}</strong>
          </div>
        </div>

        <div class="summary-item">
          <div class="summary-icon blue">◆</div>
          <div>
            <label>合作方式</label>
            <strong>{{ detail.coopMode || '-' }}</strong>
          </div>
        </div>

        <div class="summary-item">
          <div class="summary-icon orange">◷</div>
          <div>
            <label>提交人</label>
            <strong>{{ submitterText }}</strong>
          </div>
        </div>

      </section>


      <div class="main-grid">

        <section class="detail-card">

          <h2>需求详情</h2>

          <div class="detail-section">
            <h3><i></i>需求描述</h3>
            <p class="pre-line">{{ detail.description || '-' }}</p>
          </div>

          <div class="detail-section">
            <h3><i></i>标签</h3>
            <div v-if="detail.tags && detail.tags.length" class="tag-list">
              <span v-for="tag in detail.tags" :key="tag" class="tag">{{ tag }}</span>
            </div>
            <p v-else>-</p>
          </div>

          <div class="detail-section">
            <h3><i></i>联系方式</h3>
            <div class="contact-grid">
              <span>联系人：{{ detail.contactName || '-' }}</span>
              <span>职务：{{ detail.contactTitle || '-' }}</span>
              <span>联系电话：{{ detail.contactPhone || '-' }}</span>
              <span>邮箱：{{ detail.contactEmail || '-' }}</span>
            </div>
          </div>

          <div class="detail-section">
            <h3><i></i>机构简介</h3>
            <p class="pre-line">{{ detail.orgIntro || '-' }}</p>
          </div>

        </section>

        <section class="side-card">

          <h2>状态信息</h2>

          <div class="info-rows">
            <div class="info-row">
              <label>需求编号</label>
              <span>{{ detail.id }}</span>
            </div>
            <div class="info-row">
              <label>状态</label>
              <span>{{ detail.statusLabel || detail.status }}</span>
            </div>
            <div class="info-row">
              <label>提交时间</label>
              <span>{{ fmtTime(detail.createdAt) }}</span>
            </div>
            <div class="info-row">
              <label>更新时间</label>
              <span>{{ fmtTime(detail.updatedAt) }}</span>
            </div>
            <div v-if="detail.publishedAt" class="info-row">
              <label>发布时间</label>
              <span>{{ fmtTime(detail.publishedAt) }}</span>
            </div>
          </div>

          <div v-if="detail.status === 'rejected'" class="reject-reason">
            <label>驳回原因</label>
            <p>{{ detail.rejectReason || '-' }}</p>
          </div>

        </section>

      </div>


      <section class="action-bar">

        <div class="action-buttons">
          <template v-if="isPlatformAdmin && detail.status === 'pending_review'">
            <button type="button" class="approve-btn" :disabled="submitting" @click="approve">
              {{ submitting ? '提交中…' : '✓ 审核通过' }}
            </button>

            <button type="button" class="reject-btn" :disabled="submitting" @click="openReject">
              × 审核驳回
            </button>
          </template>

          <button type="button" class="back-btn" @click="goBack">↶ 返回列表</button>
        </div>

        <p v-if="actionError && !rejectVisible" class="action-error">{{ actionError }}</p>

      </section>


      <div v-if="rejectVisible" class="modal-mask" @click.self="closeReject">

        <div class="modal">

          <div class="modal-header">
            <h3>审核驳回</h3>
            <button type="button" @click="closeReject">×</button>
          </div>

          <div class="modal-body">
            <label class="reject-label">驳回原因（必填）</label>
            <textarea
              v-model="rejectReason"
              rows="5"
              placeholder="请填写驳回原因，将反馈给需求提交人"
            ></textarea>
            <p v-if="actionError" class="error-text">{{ actionError }}</p>
          </div>

          <div class="modal-footer">
            <button type="button" class="back-btn" :disabled="submitting" @click="closeReject">取消</button>
            <button type="button" class="reject-btn" :disabled="submitting" @click="submitReject">
              {{ submitting ? '提交中…' : '确认驳回' }}
            </button>
          </div>

        </div>

      </div>

    </template>

  </div>
</template>

<style scoped>
.detail-page {
  width: 100%;
}

button {
  cursor: pointer;
}

button:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.state-block {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 18px;
  min-height: 320px;
  border: 1px solid #e8edf4;
  border-radius: 10px;
  background: white;
  box-shadow: 0 2px 14px rgba(40, 72, 110, 0.06);
  color: #8b96a5;
  font-size: 14px;
}

.state-error {
  margin: 0;
  color: #ed5663;
}

.state-actions {
  display: flex;
  gap: 12px;
}

.state-actions button {
  height: 40px;
  padding: 0 26px;
  border-radius: 5px;
}

.primary-btn {
  border: 1px solid #1677ff;
  background: #1677ff;
  color: white;
}

.back-row {
  margin-bottom: 12px;
}

.back-row button {
  border: 0;
  background: transparent;
  color: #536174;
  font-size: 14px;
}

.title-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 16px;
}

.title-row h1 {
  margin: 0 0 9px;
  color: #1b2738;
  font-size: 22px;
}

.title-meta {
  display: flex;
  align-items: center;
  gap: 20px;
  color: #8994a4;
  font-size: 12px;
}

.status-badge {
  display: inline-flex;
  align-items: center;
  padding: 4px 9px;
  border-radius: 4px;
  font-size: 12px;
}

.status-badge.pending {
  background: #edf4ff;
  color: #317dea;
}

.status-badge.published {
  background: #e9faf1;
  color: #27b878;
}

.status-badge.matched {
  background: #f0edff;
  color: #7a64f6;
}

.status-badge.draft,
.status-badge.closed {
  background: #f0f2f5;
  color: #8994a3;
}

.status-badge.cancelled {
  background: #fff1e4;
  color: #ff8c25;
}

.status-badge.rejected {
  background: #fff0f2;
  color: #ed5663;
}

.summary-card {
  display: grid;
  grid-template-columns: repeat(6, 1fr);
  padding: 20px;
  border: 1px solid #e8edf4;
  border-radius: 10px;
  background: white;
  box-shadow: 0 2px 14px rgba(40, 72, 110, 0.06);
}

.summary-item {
  display: flex;
  align-items: center;
  gap: 13px;
  min-width: 0;
  min-height: 64px;
  padding: 0 17px;
  border-right: 1px solid #edf1f5;
}

.summary-item:last-child {
  border-right: 0;
}

.summary-icon {
  display: flex;
  flex: 0 0 44px;
  align-items: center;
  justify-content: center;
  width: 44px;
  height: 44px;
  border-radius: 50%;
  font-size: 20px;
}

.summary-icon.blue {
  background: #eaf3ff;
  color: #1677ff;
}

.summary-icon.green {
  background: #e9faef;
  color: #20b878;
}

.summary-icon.purple {
  background: #f0edff;
  color: #7a64f6;
}

.summary-icon.orange {
  background: #fff1e4;
  color: #ff8c25;
}

.summary-icon.yellow {
  background: #fff7dc;
  color: #efa91b;
}

.summary-item label {
  display: block;
  margin-bottom: 5px;
  color: #7d8897;
  font-size: 12px;
}

.summary-item strong {
  display: block;
  overflow: hidden;
  color: #344154;
  font-size: 13px;
  font-weight: 500;
  white-space: nowrap;
  text-overflow: ellipsis;
}

.main-grid {
  display: grid;
  grid-template-columns: minmax(0, 2.2fr) minmax(310px, 0.8fr);
  gap: 14px;
  margin-top: 14px;
}

.detail-card,
.side-card,
.action-bar {
  border: 1px solid #e8edf4;
  border-radius: 10px;
  background: white;
  box-shadow: 0 2px 14px rgba(40, 72, 110, 0.06);
}

.detail-card,
.side-card {
  min-height: 420px;
  padding: 20px 23px;
}

.detail-card h2,
.side-card h2 {
  margin: 0 0 17px;
  color: #223044;
  font-size: 17px;
}

.detail-section {
  padding: 10px 0 13px;
  border-bottom: 1px solid #edf1f5;
}

.detail-section:last-child {
  border-bottom: 0;
}

.detail-section h3 {
  display: flex;
  align-items: center;
  gap: 9px;
  margin: 0 0 8px;
  color: #314054;
  font-size: 14px;
}

.detail-section h3 i {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #1677ff;
}

.detail-section p,
.detail-section li {
  color: #515e70;
  font-size: 13px;
  line-height: 1.9;
}

.pre-line {
  white-space: pre-line;
}

.tag-list {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.tag {
  padding: 3px 10px;
  border-radius: 3px;
  background: #edf4ff;
  color: #2f7de1;
  font-size: 12px;
}

.contact-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 11px 25px;
  color: #515e70;
  font-size: 13px;
}

.info-rows {
  padding: 4px 0 10px;
}

.info-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 11px 0;
  border-bottom: 1px dashed #edf1f5;
  font-size: 13px;
}

.info-row:last-child {
  border-bottom: 0;
}

.info-row label {
  flex: none;
  color: #7d8897;
}

.info-row span {
  overflow: hidden;
  color: #344154;
  text-align: right;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.reject-reason {
  margin-top: 14px;
  padding: 12px 15px;
  border-radius: 8px;
  background: #fff0f2;
}

.reject-reason label {
  display: block;
  margin-bottom: 5px;
  color: #ed5663;
  font-size: 12px;
}

.reject-reason p {
  margin: 0;
  color: #d9455f;
  font-size: 13px;
  line-height: 1.7;
  white-space: pre-line;
}

.action-bar {
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin-top: 14px;
  padding: 20px;
}

.action-buttons {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 22px;
}

.action-buttons button {
  width: 195px;
  height: 48px;
  border-radius: 5px;
  font-size: 15px;
}

.action-error {
  margin: 0;
  color: #ed5663;
  font-size: 13px;
  text-align: center;
}

.approve-btn {
  border: 1px solid #1677ff;
  background: #1677ff;
  color: white;
}

.reject-btn {
  border: 1px solid #f04451;
  background: #f04451;
  color: white;
}

.back-btn {
  border: 1px solid #cfd7e1;
  background: white;
  color: #596577;
}

.modal-mask {
  position: fixed;
  z-index: 600;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(12, 26, 46, 0.38);
}

.modal {
  width: 620px;
  border-radius: 10px;
  background: white;
  box-shadow: 0 20px 70px rgba(20, 40, 70, 0.2);
}

.modal-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: 62px;
  padding: 0 24px;
  border-bottom: 1px solid #edf1f5;
}

.modal-header h3 {
  margin: 0;
}

.modal-header button {
  border: 0;
  background: transparent;
  color: #8d98a7;
  font-size: 24px;
}

.modal-body {
  padding: 25px 24px 10px;
}

.reject-label {
  display: block;
  margin-bottom: 8px;
  color: #283447;
  font-size: 14px;
  font-weight: 600;
}

.modal-body textarea {
  width: 100%;
  padding: 10px 12px;
  border: 1px solid #dce4ee;
  border-radius: 5px;
  outline: none;
  resize: vertical;
  font-size: 13px;
  font-family: inherit;
}

.modal-body textarea:focus {
  border-color: #1677ff;
}

.error-text {
  margin: 10px 0 0;
  color: #ed5663;
  font-size: 13px;
}

.modal-footer {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
  padding: 17px 24px;
  border-top: 1px solid #edf1f5;
}

.modal-footer button {
  min-width: 90px;
  height: 39px;
  border-radius: 5px;
}

@media print {
  .back-row,
  .action-bar,
  .admin-header,
  .sidebar {
    display: none !important;
  }
}
</style>
