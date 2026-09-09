<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api, getSavedUser } from '../../api/client'

const router = useRouter()

const statusOptions = [
  { value: 'draft', label: '草稿' },
  { value: 'pending_review', label: '待审核' },
  { value: 'published', label: '已发布' },
  { value: 'matched', label: '对接中' },
  { value: 'closed', label: '已关闭' },
  { value: 'cancelled', label: '已取消' },
  { value: 'rejected', label: '已驳回' }
]

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
const getBudget = item => item.budget || (item.budgetNegotiable ? '面议' : '-')
const getSubmitter = item => item.submitterName || item.submitterUserNo || '-'

const filters = reactive({ keyword: '', status: '', categoryCode: '' })
const appliedFilters = reactive({ keyword: '', status: '', categoryCode: '' })
const categoryOptions = ref([])
const formCategories = ref([])
const ownerUsers = ref([])
const organizations = ref([])
const currentUser = ref(getSavedUser() || {})
const isPlatformAdmin = computed(() => (currentUser.value.roles || []).includes('admin'))

const loading = ref(false)
const loadError = ref('')
const tableData = ref([])
const total = ref(0)
const currentPage = ref(1)
const pageSize = ref(10)

const fetchList = async () => {
  loading.value = true
  loadError.value = ''
  try {
    const data = await api('/admin/demands', {
      params: {
        page: currentPage.value,
        pageSize: pageSize.value,
        keyword: appliedFilters.keyword.trim(),
        status: appliedFilters.status,
        categoryCode: appliedFilters.categoryCode
      }
    })
    tableData.value = data.list || []
    total.value = data.total || 0
  } catch (err) {
    tableData.value = []
    total.value = 0
    loadError.value = err.message || '加载失败'
  } finally {
    loading.value = false
  }
}

const loadCategoryOptions = async () => {
  try {
    // 后端暂未提供需求分类字典接口，因此从后台需求列表提取真实已使用分类。
    const data = await api('/admin/demands', { params: { page: 1, pageSize: 50 } })
    const unique = new Map()
    ;(data.list || []).forEach(item => {
      if (item.categoryCode && item.categoryName) unique.set(item.categoryCode, item.categoryName)
    })
    categoryOptions.value = [...unique].map(([code, name]) => ({ code, name }))
  } catch {
    // 分类加载失败不影响需求列表和其他筛选项。
    categoryOptions.value = []
  }
}

onMounted(() => {
  fetchList()
  loadCategoryOptions()
  api('/admin/demand-categories').then(data => { formCategories.value = data || [] }).catch(() => { formCategories.value = [] })
  api('/admin/users', { params: { page: 1, pageSize: 50, status: 'active' } }).then(data => { ownerUsers.value = data.list || [] }).catch(() => { ownerUsers.value = [] })
  api('/admin/content-organizations').then(data => { organizations.value = data || [] }).catch(() => { organizations.value = [] })
})

const handleSearch = () => {
  Object.assign(appliedFilters, filters)
  currentPage.value = 1
  fetchList()
}

const handleReset = () => {
  Object.assign(filters, { keyword: '', status: '', categoryCode: '' })
  Object.assign(appliedFilters, { keyword: '', status: '', categoryCode: '' })
  currentPage.value = 1
  fetchList()
}

const totalPages = computed(() => Math.max(1, Math.ceil(total.value / pageSize.value)))

const visiblePages = computed(() => {
  const pages = totalPages.value
  if (pages <= 7) {
    return Array.from({ length: pages }, (_, index) => index + 1)
  }
  if (currentPage.value <= 4) {
    return [1, 2, 3, 4, 5, '...', pages]
  }
  return [1, '...', currentPage.value - 1, currentPage.value, currentPage.value + 1, '...', pages]
})

const changePage = page => {
  if (page === '...' || page < 1 || page > totalPages.value || page === currentPage.value) return
  currentPage.value = page
  fetchList()
}

const handlePageSizeChange = () => {
  currentPage.value = 1
  fetchList()
}

const detailVisible = ref(false)
const detailId = ref('')
const detailLoading = ref(false)
const detailError = ref('')
const detail = ref(null)

const openDetail = async item => {
  detailId.value = item.id
  detailVisible.value = true
  detailLoading.value = true
  detailError.value = ''
  detail.value = null
  try {
    detail.value = await api('/admin/demands/' + item.id)
  } catch (err) {
    detailError.value = err.message || '加载失败'
  } finally {
    detailLoading.value = false
  }
}

const goDetailPage = id => {
  router.push('/admin/requirements/' + id)
}

const auditVisible = ref(false)
const auditItem = ref(null)
const auditReason = ref('')
const auditSubmitting = ref(false)
const auditError = ref('')

const formVisible = ref(false)
const formMode = ref('create')
const formLoading = ref(false)
const formSaving = ref(false)
const formError = ref('')
const editingId = ref(null)
const demandForm = reactive({ title: '', description: '', region: '', orgId: '', ownerUserId: '', categoryId: '', orgName: '', categoryName: '', coopModeText: '', budgetMinWan: '', budgetMaxWan: '', budgetNegotiable: false, contactName: '', contactPhone: '', tagsText: '', version: null })
const belongsToOrg = (user, orgId) => {
  const id = Number(orgId)
  if ((user.organizationMemberships || []).some(m => Number(m.orgId) === id && m.status === 'active')) return true
  return Number(user.orgId) === id
}
const primaryAdminOrgId = () => {
  const memberships = currentUser.value.organizationMemberships || []
  const admin = memberships.find(m => m.role === 'admin' && m.status === 'active')
  return admin?.orgId || currentUser.value.orgId || ''
}
const usersForSelectedOrg = computed(() => ownerUsers.value.filter(user => belongsToOrg(user, demandForm.orgId)))
const adminOrgLabel = computed(() => {
  const memberships = currentUser.value.organizationMemberships || []
  const matched = memberships.find(m => Number(m.orgId) === Number(demandForm.orgId))
  const admin = matched || memberships.find(m => m.role === 'admin' && m.status === 'active')
  return admin?.orgName || currentUser.value.orgName || '当前登录机构'
})

const splitText = value => String(value || '').split(/[，,\n]/).map(x => x.trim()).filter(Boolean)
const resetDemandForm = () => Object.assign(demandForm, { title: '', description: '', region: '', orgId: '', ownerUserId: '', categoryId: '', orgName: '', categoryName: '', coopModeText: '', budgetMinWan: '', budgetMaxWan: '', budgetNegotiable: false, contactName: '', contactPhone: '', tagsText: '', version: null })
const openCreate = () => {
  formMode.value = 'create'; editingId.value = null; formError.value = ''; resetDemandForm()
  if (!isPlatformAdmin.value) {
    demandForm.orgId = primaryAdminOrgId()
    demandForm.ownerUserId = currentUser.value.userId || ''
  }
  formVisible.value = true
}
const openEdit = async item => {
  resetDemandForm(); formMode.value = 'edit'; editingId.value = item.id; formError.value = ''; formLoading.value = true; formVisible.value = true
  try { const data = await api(`/admin/demands/${item.id}`); Object.assign(demandForm, { title: data.title || '', description: data.description || '', region: data.region || '', orgId: data.orgId || '', ownerUserId: data.ownerUserId || '', categoryId: data.categoryId || '', orgName: data.orgName || '', categoryName: data.categoryName || '', coopModeText: (data.coopMode || []).join('，'), budgetMinWan: data.budgetMinWan ?? '', budgetMaxWan: data.budgetMaxWan ?? '', budgetNegotiable: Boolean(data.budgetNegotiable), contactName: data.contactName || '', contactPhone: data.contactPhone || '', tagsText: (data.tags || []).join('，'), version: data.version }) } catch (err) { formError.value = err.message || '加载需求详情失败' } finally { formLoading.value = false }
}
const claimOrganization = async item => {
  if (!window.confirm('确认将该历史需求归属到当前机构？归属后将由本机构统一管理。')) return
  try {
    await api(`/admin/demands/${item.id}/claim-organization`, { method: 'POST', body: { version: item.version } })
    fetchList()
  } catch (err) { loadError.value = err.message || '归属机构失败' }
}
const saveDemand = async (saveAction = 'draft') => {
  if (formMode.value === 'create' && !demandForm.categoryId) { formError.value = '请选择需求分类'; return }
  if (formMode.value === 'create' && isPlatformAdmin.value && (!demandForm.orgId || !demandForm.ownerUserId)) { formError.value = '请依次选择分类、所属机构和归属用户'; return }
  if (formMode.value === 'create' && !isPlatformAdmin.value && !demandForm.orgId) { formError.value = '未绑定可管理的机构'; return }
  if (!demandForm.title.trim() || !demandForm.description.trim()) { formError.value = '请填写需求标题和需求描述'; return }
  formSaving.value = true; formError.value = ''
  try {
    const body = { title: demandForm.title.trim(), description: demandForm.description.trim(), budgetNegotiable: demandForm.budgetNegotiable, saveAction }
    if (demandForm.categoryId) body.categoryId = Number(demandForm.categoryId)
    if (demandForm.orgId) body.orgId = Number(demandForm.orgId)
    if (isPlatformAdmin.value && demandForm.ownerUserId) body.ownerUserId = Number(demandForm.ownerUserId)
    const optionalTextFields = { region: demandForm.region, categoryName: demandForm.categoryName, contactName: demandForm.contactName, contactPhone: demandForm.contactPhone }
    if (isPlatformAdmin.value) optionalTextFields.orgName = demandForm.orgName
    Object.entries(optionalTextFields).forEach(([key, value]) => { if (value.trim()) body[key] = value.trim() })
    if (demandForm.coopModeText.trim()) body.coopMode = splitText(demandForm.coopModeText)
    if (demandForm.tagsText.trim()) body.tags = splitText(demandForm.tagsText)
    if (demandForm.budgetMinWan !== '') body.budgetMinWan = Number(demandForm.budgetMinWan)
    if (demandForm.budgetMaxWan !== '') body.budgetMaxWan = Number(demandForm.budgetMaxWan)
    if (formMode.value === 'create') { await api('/admin/demands', { method: 'POST', body }); currentPage.value = 1 } else { body.version = demandForm.version; await api(`/admin/demands/${editingId.value}`, { method: 'PATCH', body }) }
    formVisible.value = false; fetchList()
  } catch (err) { formError.value = err.message || '保存需求失败' } finally { formSaving.value = false }
}

const openAudit = item => {
  auditItem.value = item
  auditReason.value = ''
  auditError.value = ''
  auditVisible.value = true
}

const closeAudit = () => {
  if (auditSubmitting.value) return
  auditVisible.value = false
}

const submitApprove = async () => {
  if (!auditItem.value || auditSubmitting.value) return
  auditSubmitting.value = true
  auditError.value = ''
  try {
    await api(`/admin/demands/${auditItem.value.id}/approve`, {
      method: 'POST',
      body: { version: auditItem.value.version }
    })
    auditVisible.value = false
    fetchList()
  } catch (err) {
    auditError.value = err.message || '操作失败'
  } finally {
    auditSubmitting.value = false
  }
}

const submitReject = async () => {
  if (!auditItem.value || auditSubmitting.value) return
  if (!auditReason.value.trim()) {
    auditError.value = '请填写驳回原因'
    return
  }
  auditSubmitting.value = true
  auditError.value = ''
  try {
    await api(`/admin/demands/${auditItem.value.id}/reject`, {
      method: 'POST',
      body: { version: auditItem.value.version, reason: auditReason.value.trim() }
    })
    auditVisible.value = false
    fetchList()
  } catch (err) {
    auditError.value = err.message || '操作失败'
  } finally {
    auditSubmitting.value = false
  }
}
</script>

<template>
  <div class="requirement-page">

    <section class="filter-card">

      <div class="filters">

        <div class="filter-item keyword">
          <label>关键词</label>
          <input
            v-model="filters.keyword"
            placeholder="请输入需求标题、编号或机构"
            @keyup.enter="handleSearch"
          />
        </div>

        <div class="filter-item">
          <label>状态</label>
          <select v-model="filters.status">
            <option value="">全部</option>
            <option v-for="item in statusOptions" :key="item.value" :value="item.value">
              {{ item.label }}
            </option>
          </select>
        </div>

        <div class="filter-item">
          <label>分类</label>
          <select v-model="filters.categoryCode">
            <option value="">全部分类</option>
            <option v-for="item in categoryOptions" :key="item.code" :value="item.code">
              {{ item.name }}
            </option>
          </select>
        </div>

        <div class="actions">
          <button class="primary-btn" @click="openCreate">新增需求</button>
          <button class="primary-btn" @click="handleSearch">查询</button>
          <button class="default-btn" @click="handleReset">重置</button>
        </div>

      </div>

    </section>


    <section class="table-card">

      <table>

        <thead>
          <tr>
            <th>ID</th>
            <th>需求标题</th>
            <th>分类</th>
            <th>所属机构</th>
            <th>地区</th>
            <th>预算</th>
            <th>状态</th>
            <th>提交人</th>
            <th>创建时间</th>
            <th>操作</th>
          </tr>
        </thead>

        <tbody>

          <tr v-if="loading">
            <td colspan="10" class="empty">加载中…</td>
          </tr>

          <tr v-else-if="loadError">
            <td colspan="10" class="error-cell">
              <span>{{ loadError }}</span>
              <button class="retry-btn" @click="fetchList">重试</button>
            </td>
          </tr>

          <template v-else>

            <tr v-for="item in tableData" :key="item.id">
              <td class="ellipsis-cell" :title="item.id">{{ item.id }}</td>
              <td class="title-cell" :title="item.title">{{ item.title }}</td>
              <td>{{ item.categoryName || '-' }}</td>
              <td class="ellipsis-cell" :title="item.orgName">{{ item.orgName || '-' }}</td>
              <td>{{ item.region || '-' }}</td>
              <td>{{ getBudget(item) }}</td>
              <td>
                <span class="status" :class="getStatusClass(item.status)">
                  <i></i>
                  {{ item.statusLabel || item.status }}
                </span>
              </td>
              <td>{{ getSubmitter(item) }}</td>
              <td>{{ fmtTime(item.createdAt) }}</td>
              <td>
                <div class="operation">
                  <button @click="openEdit(item)">编辑</button>
                  <span>|</span>
                  <template v-if="item.pendingOrgAssignment">
                    <button @click="claimOrganization(item)">归属本机构</button>
                    <span>|</span>
                  </template>
                  <button @click="openDetail(item)">查看</button>
                  <template v-if="isPlatformAdmin && item.status === 'pending_review'">
                    <span>|</span>
                    <button @click="openAudit(item)">审核</button>
                  </template>
                </div>
              </td>
            </tr>

            <tr v-if="tableData.length === 0">
              <td colspan="10" class="empty">暂无符合条件的需求</td>
            </tr>

          </template>

        </tbody>

      </table>


      <div class="pagination">

        <span>共 {{ total }} 条</span>

        <select v-model="pageSize" @change="handlePageSizeChange">
          <option :value="10">10条/页</option>
          <option :value="20">20条/页</option>
        </select>

        <button :disabled="currentPage === 1" @click="changePage(currentPage - 1)">‹</button>

        <template v-for="(page, index) in visiblePages" :key="`${page}-${index}`">
          <span v-if="page === '...'">...</span>
          <button v-else :class="{ active: currentPage === page }" @click="changePage(page)">
            {{ page }}
          </button>
        </template>

        <button :disabled="currentPage === totalPages" @click="changePage(currentPage + 1)">›</button>

      </div>

    </section>


    <div v-if="detailVisible" class="modal-mask" @click.self="detailVisible = false">

      <div class="modal detail-modal">

        <div class="modal-header">
          <h3>需求详情</h3>
          <button @click="detailVisible = false">×</button>
        </div>

        <div class="modal-body">

          <div v-if="detailLoading" class="modal-tip">加载中…</div>

          <div v-else-if="detailError" class="modal-error">
            <span>{{ detailError }}</span>
            <button @click="openDetail({ id: detailId })">重试</button>
          </div>

          <template v-else-if="detail">

            <div class="detail-head">
              <h4>{{ detail.title }}</h4>
              <span class="status" :class="getStatusClass(detail.status)">
                <i></i>
                {{ detail.statusLabel || detail.status }}
              </span>
            </div>

            <div class="info-grid">
              <div class="info-item">
                <label>需求编号</label>
                <span>{{ detail.id }}</span>
              </div>
              <div class="info-item">
                <label>分类</label>
                <span>{{ detail.categoryName || '-' }}</span>
              </div>
              <div class="info-item">
                <label>所属机构</label>
                <span>{{ detail.orgName || '-' }}</span>
              </div>
              <div class="info-item">
                <label>地区</label>
                <span>{{ detail.region || '-' }}</span>
              </div>
              <div class="info-item">
                <label>预算</label>
                <span>{{ getBudget(detail) }}</span>
              </div>
              <div class="info-item">
                <label>合作方式</label>
                <span>{{ detail.coopMode || '-' }}</span>
              </div>
              <div class="info-item">
                <label>提交人</label>
                <span>{{ getSubmitter(detail) }}</span>
              </div>
              <div class="info-item">
                <label>创建时间</label>
                <span>{{ fmtTime(detail.createdAt) }}</span>
              </div>
            </div>

            <div class="detail-block">
              <h4>需求描述</h4>
              <p class="pre-line">{{ detail.description || '-' }}</p>
            </div>

            <div class="detail-block">
              <h4>标签</h4>
              <div v-if="detail.tags && detail.tags.length" class="tag-list">
                <span v-for="tag in detail.tags" :key="tag" class="tag">{{ tag }}</span>
              </div>
              <p v-else class="pre-line">-</p>
            </div>

            <div class="detail-block">
              <h4>联系方式</h4>
              <div class="info-grid">
                <div class="info-item">
                  <label>联系人</label>
                  <span>{{ detail.contactName || '-' }}</span>
                </div>
                <div class="info-item">
                  <label>职务</label>
                  <span>{{ detail.contactTitle || '-' }}</span>
                </div>
                <div class="info-item">
                  <label>联系电话</label>
                  <span>{{ detail.contactPhone || '-' }}</span>
                </div>
                <div class="info-item">
                  <label>邮箱</label>
                  <span>{{ detail.contactEmail || '-' }}</span>
                </div>
              </div>
            </div>

            <div class="detail-block">
              <h4>机构简介</h4>
              <p class="pre-line">{{ detail.orgIntro || '-' }}</p>
            </div>

            <div v-if="detail.rejectReason" class="reject-reason">
              驳回原因：{{ detail.rejectReason }}
            </div>

          </template>

        </div>

        <div class="modal-footer">
          <button class="plain-btn" @click="detailVisible = false">关闭</button>
          <button v-if="detail" class="link-btn" @click="goDetailPage(detailId)">进入详情页 →</button>
        </div>

      </div>

    </div>


    <div v-if="formVisible" class="modal-mask" @click.self="formVisible = false">
      <div class="modal form-modal">
        <div class="modal-header"><h3>{{ formMode === 'create' ? '新增需求' : '编辑需求' }}</h3><button type="button" @click="formVisible = false">×</button></div>
        <div class="modal-body form-content" :class="{ 'org-admin-form': !isPlatformAdmin }">
          <p v-if="formLoading" class="modal-tip">加载中…</p>
          <template v-else>
            <template v-if="!isPlatformAdmin">
              <label>所属机构</label>
              <select v-if="organizations.length > 1" v-model="demandForm.orgId">
                <option v-for="item in organizations" :key="item.id" :value="item.id">{{ item.name }}</option>
              </select>
              <input v-else :value="adminOrgLabel" disabled />
              <label>归属用户</label><input :value="currentUser.displayName || currentUser.userNo || '当前登录账号'" disabled />
            </template>
            <label>需求标题 *</label><input v-model="demandForm.title" />
            <label>需求描述 *</label><textarea v-model="demandForm.description" rows="4"></textarea>
            <div class="form-grid">
              <div><label>所属机构 *</label><select v-model="demandForm.orgId" @change="demandForm.ownerUserId = ''"><option value="">请选择机构</option><option v-for="item in organizations" :key="item.id" :value="item.id">{{ item.name }}</option></select></div>
              <div><label>地区</label><input v-model="demandForm.region" /></div>
              <div><label>分类 *</label><select v-model="demandForm.categoryId"><option value="">请选择分类</option><option v-for="item in formCategories" :key="item.id" :value="item.id">{{ item.name }}</option></select></div>
              <div><label>归属用户 *</label><select v-model="demandForm.ownerUserId" :disabled="!demandForm.orgId"><option value="">请先选择机构</option><option v-for="item in usersForSelectedOrg" :key="item.userId" :value="item.userId">{{ item.displayName || item.userNo }}</option></select></div>
              <div><label>合作方式（逗号分隔）</label><input v-model="demandForm.coopModeText" placeholder="技术合作，成果转让" /></div>
              <div><label>预算下限（万元）</label><input v-model.number="demandForm.budgetMinWan" type="number" min="0" /></div>
              <div><label>预算上限（万元）</label><input v-model.number="demandForm.budgetMaxWan" type="number" min="0" /></div>
              <div><label>联系人</label><input v-model="demandForm.contactName" /></div>
              <div><label>联系电话</label><input v-model="demandForm.contactPhone" /></div>
            </div>
            <label>标签（逗号分隔）</label><input v-model="demandForm.tagsText" placeholder="AI，智能制造" />
            <label class="checkbox-label"><input v-model="demandForm.budgetNegotiable" type="checkbox" /> 预算可议</label>
            <p v-if="formError" class="error-text">{{ formError }}</p>
          </template>
        </div>
        <div class="modal-footer">
          <button class="plain-btn" :disabled="formSaving" @click="formVisible = false">取消</button>
          <button class="plain-btn" :disabled="formLoading || formSaving" @click="saveDemand('draft')">{{ formSaving ? '保存中…' : '保存草稿' }}</button>
          <button v-if="isPlatformAdmin" class="approve-btn" :disabled="formLoading || formSaving" @click="saveDemand('publish')">{{ formSaving ? '保存中…' : '直接发布' }}</button>
          <button v-else class="approve-btn" :disabled="formLoading || formSaving" @click="saveDemand('submit')">{{ formSaving ? '保存中…' : '提交审核' }}</button>
        </div>
      </div>
    </div>

    <div v-if="auditVisible" class="modal-mask" @click.self="closeAudit">

      <div class="modal audit-modal">

        <div class="modal-header">
          <h3>需求审核</h3>
          <button @click="closeAudit">×</button>
        </div>

        <div class="modal-body">

          <div v-if="auditItem" class="audit-target">
            <label>需求标题</label>
            <span :title="auditItem.title">{{ auditItem.title }}</span>
          </div>

          <label class="audit-reason-label">驳回原因</label>
          <textarea
            v-model="auditReason"
            rows="4"
            placeholder="驳回时必填，将反馈给需求提交人"
          ></textarea>

          <p v-if="auditError" class="error-text">{{ auditError }}</p>

        </div>

        <div class="modal-footer">
          <button class="plain-btn" :disabled="auditSubmitting" @click="closeAudit">取消</button>
          <button class="reject-btn" :disabled="auditSubmitting" @click="submitReject">
            {{ auditSubmitting ? '提交中…' : '审核驳回' }}
          </button>
          <button class="approve-btn" :disabled="auditSubmitting" @click="submitApprove">
            {{ auditSubmitting ? '提交中…' : '审核通过' }}
          </button>
        </div>

      </div>

    </div>

  </div>
</template>

<style scoped>
.requirement-page {
  width: 100%;
}

.filter-card,
.table-card {
  border: 1px solid #e8edf4;
  border-radius: 11px;
  background: #fff;
  box-shadow: 0 2px 14px rgba(40, 72, 110, 0.07);
}

.filter-card {
  padding: 25px 27px;
}

.filters {
  display: grid;
  grid-template-columns: minmax(260px, 1fr) 220px 170px auto;
  align-items: end;
  gap: 16px;
}

.filter-item label {
  display: block;
  margin-bottom: 9px;
  color: #283447;
  font-size: 14px;
  font-weight: 600;
}

.filter-item input,
.filter-item select {
  width: 100%;
  height: 42px;
  padding: 0 13px;
  border: 1px solid #dce4ee;
  border-radius: 5px;
  outline: none;
  background: white;
}

.filter-item input:focus,
.filter-item select:focus {
  border-color: #1677ff;
}

.actions {
  display: flex;
  gap: 12px;
  white-space: nowrap;
}

.primary-btn,
.default-btn {
  height: 42px;
  padding: 0 28px;
  border-radius: 5px;
}

.primary-btn {
  border: 1px solid #1677ff;
  background: #1677ff;
  color: white;
}

.default-btn {
  border: 1px solid #dce4ee;
  background: white;
  color: #4d596a;
}

.table-card {
  margin-top: 14px;
  overflow-x: auto;
}

table {
  width: 100%;
  min-width: 1400px;
  border-collapse: collapse;
  table-layout: fixed;
}

th,
td {
  height: 64px;
  padding: 0 14px;
  border-bottom: 1px solid #edf1f5;
  color: #4d596a;
  font-size: 13px;
  text-align: left;
}

th {
  color: #273346;
  font-weight: 600;
}

th:nth-child(1) {
  width: 130px;
}

th:nth-child(2) {
  width: 220px;
}

th:nth-child(3) {
  width: 110px;
}

th:nth-child(4) {
  width: 150px;
}

th:nth-child(5) {
  width: 100px;
}

th:nth-child(6) {
  width: 120px;
}

th:nth-child(7) {
  width: 95px;
}

th:nth-child(8) {
  width: 90px;
}

th:nth-child(9) {
  width: 140px;
}

th:nth-child(10) {
  width: 110px;
}

tbody tr:hover {
  background: #fafcff;
}

.title-cell,
.ellipsis-cell {
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
}

.status {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 8px;
  border-radius: 4px;
}

.status i {
  width: 7px;
  height: 7px;
  border-radius: 50%;
}

.status.pending {
  background: #edf4ff;
  color: #317dea;
}

.status.pending i {
  background: #317dea;
}

.status.published {
  color: #22b779;
}

.status.published i {
  background: #22b779;
}

.status.matched {
  background: #f0edff;
  color: #7a64f6;
}

.status.matched i {
  background: #7a64f6;
}

.status.draft,
.status.closed {
  background: #f0f2f5;
  color: #8994a3;
}

.status.draft i,
.status.closed i {
  background: #8994a3;
}

.status.cancelled {
  background: #fff1e4;
  color: #ff8c25;
}

.status.cancelled i {
  background: #ff8c25;
}

.status.rejected {
  background: #fff0f2;
  color: #ed5663;
}

.status.rejected i {
  background: #ed5663;
}

.operation {
  display: flex;
  gap: 7px;
  white-space: nowrap;
}

.operation button {
  padding: 0;
  border: 0;
  background: transparent;
  color: #1677ff;
}

.operation span {
  color: #d4dbe5;
}

.empty {
  height: 180px;
  text-align: center;
  color: #99a4b2;
}

.error-cell {
  height: 140px;
  text-align: center;
  color: #ed5663;
}

.retry-btn {
  margin-left: 12px;
  padding: 6px 18px;
  border: 1px solid #ed5663;
  border-radius: 5px;
  background: white;
  color: #ed5663;
  cursor: pointer;
}

.pagination {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 7px;
  min-height: 74px;
  padding: 12px;
}

.pagination select {
  height: 38px;
  margin-left: 15px;
  padding: 0 12px;
  border: 1px solid #dce4ee;
  border-radius: 5px;
  background: white;
}

.pagination button {
  min-width: 38px;
  height: 38px;
  border: 1px solid #dfe5ed;
  border-radius: 5px;
  background: white;
}

.pagination button.active {
  border-color: #1677ff;
  background: #1677ff;
  color: white;
}

.pagination button:disabled {
  opacity: 0.4;
  cursor: not-allowed;
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
  display: flex;
  flex-direction: column;
  width: 640px;
  max-height: 82vh;
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
  color: #223044;
  font-size: 17px;
}

.modal-header button {
  border: 0;
  background: transparent;
  color: #8d98a7;
  font-size: 24px;
  cursor: pointer;
}

.modal-body {
  flex: 1;
  overflow-y: auto;
  padding: 22px 24px;
}

.modal-footer {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 12px;
  padding: 15px 24px;
  border-top: 1px solid #edf1f5;
}

.modal-footer button {
  min-width: 90px;
  height: 39px;
  border-radius: 5px;
  cursor: pointer;
}

.modal-footer button:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.modal-footer .approve-btn {
  border: 1px solid #1677ff;
  background: #1677ff;
  color: white;
}

.modal-footer .reject-btn {
  border: 1px solid #f04451;
  background: #f04451;
  color: white;
}

.modal-footer .plain-btn {
  border: 1px solid #cfd7e1;
  background: white;
  color: #596577;
}

.modal-footer .link-btn {
  min-width: auto;
  margin-right: auto;
  border: 0;
  background: transparent;
  color: #1677ff;
}

.modal-tip {
  padding: 40px 0;
  color: #99a4b2;
  text-align: center;
}

.modal-error {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 14px;
  padding: 40px 0;
  color: #ed5663;
}

.modal-error button {
  padding: 6px 18px;
  border: 1px solid #ed5663;
  border-radius: 5px;
  background: white;
  color: #ed5663;
  cursor: pointer;
}

.detail-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 16px;
}

.detail-head h4 {
  margin: 0;
  color: #1b2738;
  font-size: 17px;
  line-height: 1.5;
}

.info-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 12px 24px;
  margin-bottom: 16px;
  padding: 14px 16px;
  border: 1px solid #edf1f5;
  border-radius: 8px;
  background: #fafcff;
}

.info-item label {
  display: block;
  margin-bottom: 4px;
  color: #7d8897;
  font-size: 12px;
}

.info-item span {
  color: #344154;
  font-size: 13px;
  word-break: break-all;
}

.detail-block {
  margin-bottom: 16px;
}

.detail-block h4 {
  margin: 0 0 8px;
  color: #314054;
  font-size: 14px;
}

.detail-block p {
  margin: 0;
  color: #515e70;
  font-size: 13px;
  line-height: 1.8;
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

.reject-reason {
  padding: 10px 14px;
  border-radius: 6px;
  background: #fff0f2;
  color: #ed5663;
  font-size: 13px;
  line-height: 1.7;
}

.audit-target {
  margin-bottom: 14px;
}

.audit-target label {
  display: block;
  margin-bottom: 5px;
  color: #7d8897;
  font-size: 12px;
}

.audit-target span {
  color: #1b2738;
  font-size: 14px;
  font-weight: 600;
}

.audit-reason-label {
  display: block;
  margin-bottom: 8px;
  color: #283447;
  font-size: 14px;
  font-weight: 600;
}

.audit-modal textarea {
  width: 100%;
  padding: 10px 12px;
  border: 1px solid #dce4ee;
  border-radius: 5px;
  outline: none;
  resize: vertical;
  font-size: 13px;
  font-family: inherit;
}

.audit-modal textarea:focus {
  border-color: #1677ff;
}

.error-text {
  margin: 10px 0 0;
  color: #ed5663;
  font-size: 13px;
}

.form-modal {
  width: 720px;
}

.form-content label {
  display: block;
  margin: 0 0 6px;
  color: #344154;
  font-size: 13px;
}

.form-content input,
.form-content select,
.form-content textarea {
  box-sizing: border-box;
  width: 100%;
  margin: 0 0 14px;
  padding: 9px 10px;
  border: 1px solid #dce4ee;
  border-radius: 5px;
  font: inherit;
}

.form-content textarea {
  resize: vertical;
}

.form-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0 14px;
}

.checkbox-label {
  display: flex !important;
  align-items: center;
  gap: 7px;
}

.checkbox-label input {
  width: auto;
  margin: 0;
}

.org-admin-form .form-grid > div:nth-child(1),
.org-admin-form .form-grid > div:nth-child(4) {
  display: none;
}
</style>
