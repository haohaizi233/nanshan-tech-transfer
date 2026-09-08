<script setup>
import {
  computed,
  onMounted,
  reactive,
  ref,
} from 'vue'

import { api, getSavedUser } from '../../api/client'

const achievements = ref([])

const categories = ref([])
const ownerUsers = ref([])
const organizations = ref([])
const currentUser = ref(getSavedUser() || {})
const isPlatformAdmin = computed(() => (currentUser.value.roles || []).includes('admin'))

const statusOptions = [
  { value: 'draft', label: '草稿' },
  { value: 'pending_review', label: '待审核' },
  { value: 'published', label: '已发布' },
  { value: 'offline', label: '已下架' },
  { value: 'rejected', label: '已驳回' },
]

const filters = reactive({
  keyword: '',
  categoryCode: '',
  status: '',
})

const appliedFilters = reactive({
  keyword: '',
  categoryCode: '',
  status: '',
})

const currentPage = ref(1)
const pageSize = ref(10)
const total = ref(0)
const totalPages = ref(1)

const loading = ref(false)
const loadError = ref('')

const exporting = ref(false)

const modalVisible = ref(false)
const modalMode = ref('view')

const viewId = ref('')
const viewDetail = ref(null)
const viewLoading = ref(false)
const viewError = ref('')

const auditItem = ref(null)
const rejectReason = ref('')
const auditError = ref('')
const auditSubmitting = ref(false)

const formVisible = ref(false)
const formMode = ref('create')
const formLoading = ref(false)
const formSaving = ref(false)
const formError = ref('')
const editingId = ref(null)
const achievementForm = reactive({
  title: '', categoryId: '', orgId: '', ownerUserId: '', sourceOrgName: '', techIntro: '', techRoute: '',
  maturityLevel: '02_lab', maturityDesc: '', pricingMode: 'negotiable',
  priceMinWan: '', priceMaxWan: '', contactName: '', contactPhone: '', contactEmail: '',
  applicationFieldsText: '', inventorNamesText: '', version: null,
})

const fmtTime = v =>
  v ? String(v).replace('T', ' ').slice(0, 16) : '-'

const fmtCount = v =>
  v === null || v === undefined
    ? '-'
    : Number(v).toLocaleString()

const getStatusClass = status =>
  ({
    published: 'published',
    pending_review: 'reviewing',
    offline: 'offline',
    rejected: 'rejected',
    draft: 'draft',
  }[status] || '')

const fetchList = async () => {
  loading.value = true
  loadError.value = ''

  try {
    const data = await api('/admin/achievements', {
      params: {
        page: currentPage.value,
        pageSize: pageSize.value,
        keyword: appliedFilters.keyword.trim(),
        categoryCode: appliedFilters.categoryCode,
        status: appliedFilters.status,
      },
    })

    const list = (data && data.list) || []
    const pages = (data && data.totalPages) || 1

    if (list.length === 0 && currentPage.value > pages) {
      currentPage.value = pages
      return fetchList()
    }

    achievements.value = list
    total.value = (data && data.total) || 0
    totalPages.value = pages
  } catch (err) {
    achievements.value = []
    total.value = 0
    totalPages.value = 1
    loadError.value = err.message || '加载失败，请稍后重试'
  } finally {
    loading.value = false
  }
}

const fetchCategories = async () => {
  try {
    const data = await api('/achievements/categories')

    categories.value = (Array.isArray(data) ? data : [])
      .slice()
      .sort((a, b) => (a.sortOrder || 0) - (b.sortOrder || 0))
  } catch {
    categories.value = []
  }
}

const handleSearch = () => {
  Object.assign(appliedFilters, filters)

  currentPage.value = 1

  fetchList()
}

const handleReset = () => {
  Object.assign(filters, {
    keyword: '',
    categoryCode: '',
    status: '',
  })

  Object.assign(appliedFilters, {
    keyword: '',
    categoryCode: '',
    status: '',
  })

  currentPage.value = 1

  fetchList()
}

const changePage = page => {
  if (page === '...') return

  if (
    page < 1 ||
    page > totalPages.value ||
    page === currentPage.value
  ) {
    return
  }

  currentPage.value = page

  fetchList()
}

const handlePageSizeChange = () => {
  currentPage.value = 1

  fetchList()
}

const visiblePages = computed(() => {
  const count = totalPages.value

  if (count <= 7) {
    return Array.from(
      { length: count },
      (_, index) => index + 1
    )
  }

  if (currentPage.value <= 4) {
    return [1, 2, 3, 4, 5, '...', count]
  }

  if (currentPage.value >= count - 3) {
    return [
      1,
      '...',
      count - 4,
      count - 3,
      count - 2,
      count - 1,
      count,
    ]
  }

  return [
    1,
    '...',
    currentPage.value - 1,
    currentPage.value,
    currentPage.value + 1,
    '...',
    count,
  ]
})

const fetchDetail = async id => {
  viewLoading.value = true
  viewError.value = ''

  try {
    viewDetail.value = await api(
      '/admin/achievements/' + id
    )
  } catch (err) {
    viewError.value = err.message || '加载失败，请稍后重试'
  } finally {
    viewLoading.value = false
  }
}

const openView = item => {
  modalMode.value = 'view'
  modalVisible.value = true

  viewId.value = item.id
  viewDetail.value = null
  viewError.value = ''

  fetchDetail(item.id)
}

const fetchOwnerUsers = async () => {
  if (!isPlatformAdmin.value) {
    ownerUsers.value = []
    return
  }
  try {
    const data = await api('/admin/users', { params: { page: 1, pageSize: 50, status: 'active' } })
    ownerUsers.value = data.list || []
  } catch { ownerUsers.value = [] }
}

const usersForSelectedOrg = computed(() => ownerUsers.value.filter(user => Number(user.orgId) === Number(achievementForm.orgId)))

const resetAchievementForm = () => {
  Object.assign(achievementForm, {
    title: '', categoryId: '', orgId: '', ownerUserId: '', sourceOrgName: '', techIntro: '', techRoute: '',
    maturityLevel: '02_lab', maturityDesc: '', pricingMode: 'negotiable',
    priceMinWan: '', priceMaxWan: '', contactName: '', contactPhone: '', contactEmail: '',
    applicationFieldsText: '', inventorNamesText: '', version: null,
  })
}

const splitText = value => String(value || '').split(/[，,\n]/).map(x => x.trim()).filter(Boolean)

const openCreate = () => {
  formMode.value = 'create'
  editingId.value = null
  formError.value = ''
  resetAchievementForm()
  if (!isPlatformAdmin.value) {
    achievementForm.orgId = currentUser.value.orgId || ''
    achievementForm.ownerUserId = currentUser.value.userId || ''
  }
  formVisible.value = true
}

const openEdit = async item => {
  resetAchievementForm()
  formMode.value = 'edit'
  editingId.value = item.id
  formError.value = ''
  formLoading.value = true
  formVisible.value = true
  try {
    const data = await api(`/admin/achievements/${item.id}`)
    Object.assign(achievementForm, {
      title: data.title || '', sourceOrgName: data.orgName || '', techIntro: data.techIntro || '',
      techRoute: data.techRoute || '', maturityLevel: data.maturityLevel || '02_lab',
      maturityDesc: data.maturityDesc || '', pricingMode: data.pricingMode || 'negotiable',
      priceMinWan: data.priceMinWan ?? '', priceMaxWan: data.priceMaxWan ?? '',
      contactName: data.contactName || '', contactPhone: data.contactPhone || '',
      contactEmail: data.contactEmail || '',
      applicationFieldsText: (data.applicationFields || []).join('，'),
      inventorNamesText: (data.inventors || []).map(x => x.name).filter(Boolean).join('，'),
      version: data.version,
    })
  } catch (err) {
    formError.value = err.message || '加载成果详情失败'
  } finally {
    formLoading.value = false
  }
}

const saveAchievement = async (saveAction = 'draft') => {
  if (formMode.value === 'create' && (!achievementForm.categoryId || !achievementForm.orgId || !achievementForm.ownerUserId)) {
    formError.value = '请依次选择分类、所属机构和归属用户'
    return
  }
  if (!achievementForm.title.trim()) {
    formError.value = '请输入成果名称'
    return
  }
  formSaving.value = true
  formError.value = ''
  try {
    const body = { title: achievementForm.title.trim(), maturityLevel: achievementForm.maturityLevel, pricingMode: achievementForm.pricingMode, saveAction }
    const optionalTextFields = {
      sourceOrgName: achievementForm.sourceOrgName, techIntro: achievementForm.techIntro,
      techRoute: achievementForm.techRoute, maturityDesc: achievementForm.maturityDesc,
      contactName: achievementForm.contactName, contactPhone: achievementForm.contactPhone,
      contactEmail: achievementForm.contactEmail,
    }
    Object.entries(optionalTextFields).forEach(([key, value]) => { if (value.trim()) body[key] = value.trim() })
    if (formMode.value === 'create' || achievementForm.applicationFieldsText.trim()) body.applicationFields = splitText(achievementForm.applicationFieldsText)
    if (achievementForm.categoryId) body.categoryId = Number(achievementForm.categoryId)
    if (isPlatformAdmin.value && achievementForm.orgId) body.orgId = Number(achievementForm.orgId)
    if (isPlatformAdmin.value && achievementForm.ownerUserId) body.ownerUserId = Number(achievementForm.ownerUserId)
    if (achievementForm.priceMinWan !== '') body.priceMinWan = Number(achievementForm.priceMinWan)
    if (achievementForm.priceMaxWan !== '') body.priceMaxWan = Number(achievementForm.priceMaxWan)
    const inventors = splitText(achievementForm.inventorNamesText)
    if (inventors.length) body.inventorRefs = inventors.map((name, index) => ({ name, sortOrder: index }))
    if (formMode.value === 'create') {
      await api('/admin/achievements', { method: 'POST', body })
      currentPage.value = 1
    } else {
      body.version = achievementForm.version
      await api(`/admin/achievements/${editingId.value}`, { method: 'PATCH', body })
    }
    formVisible.value = false
    fetchList()
  } catch (err) {
    formError.value = err.message || '保存成果失败'
  } finally {
    formSaving.value = false
  }
}

const inventorNames = computed(() => {
  const list =
    (viewDetail.value && viewDetail.value.inventors) || []

  const names = list
    .map(inventor => inventor && inventor.name)
    .filter(Boolean)

  return names.length ? names.join('、') : '-'
})

const innovationPoints = computed(() => {
  const list =
    viewDetail.value && viewDetail.value.innovationPoints

  return Array.isArray(list) ? list.filter(Boolean) : []
})

const contactText = computed(() => {
  const detail = viewDetail.value

  if (!detail) return '-'

  const parts = [
    detail.contactName,
    detail.contactPhone,
    detail.contactEmail,
  ].filter(Boolean)

  return parts.length ? parts.join(' / ') : '-'
})

const openAudit = item => {
  modalMode.value = 'audit'
  auditItem.value = item
  rejectReason.value = ''
  auditError.value = ''

  modalVisible.value = true
}

const closeModal = () => {
  if (modalMode.value === 'audit' && auditSubmitting.value) {
    return
  }

  modalVisible.value = false
}

const handleApprove = async () => {
  if (!auditItem.value || auditSubmitting.value) return

  auditSubmitting.value = true
  auditError.value = ''

  try {
    await api(
      `/admin/achievements/${auditItem.value.id}/approve`,
      {
        method: 'POST',
        body: {
          version: auditItem.value.version,
        },
      }
    )

    modalVisible.value = false

    fetchList()
  } catch (err) {
    auditError.value = err.message || '操作失败，请稍后重试'
  } finally {
    auditSubmitting.value = false
  }
}

const handleReject = async () => {
  if (!auditItem.value || auditSubmitting.value) return

  if (!rejectReason.value.trim()) {
    auditError.value = '请填写驳回原因'
    return
  }

  auditSubmitting.value = true
  auditError.value = ''

  try {
    await api(
      `/admin/achievements/${auditItem.value.id}/reject`,
      {
        method: 'POST',
        body: {
          version: auditItem.value.version,
          reason: rejectReason.value.trim(),
        },
      }
    )

    modalVisible.value = false

    fetchList()
  } catch (err) {
    auditError.value = err.message || '操作失败，请稍后重试'
  } finally {
    auditSubmitting.value = false
  }
}

const downloadAchievement = item => {
  const content = [
    `成果编号：${item.id}`,
    `成果名称：${item.title}`,
    `所属分类：${item.categoryName || '-'}`,
    `发布单位：${item.orgName || '-'}`,
    `状态：${item.statusLabel || '-'}`,
    `成果简介：${item.techIntro || ''}`,
  ].join('\n')

  const blob = new Blob(
    [content],
    {
      type: 'text/plain;charset=utf-8',
    }
  )

  const url = URL.createObjectURL(blob)

  const link = document.createElement('a')

  link.href = url
  link.download = `${item.title}.txt`

  link.click()

  URL.revokeObjectURL(url)
}

const exportData = async () => {
  if (exporting.value) return

  exporting.value = true

  try {
    const size = 50
    const rows = []

    for (let page = 1; page <= 20; page += 1) {
      const data = await api('/admin/achievements', {
        params: {
          page,
          pageSize: size,
          keyword: appliedFilters.keyword.trim(),
          categoryCode: appliedFilters.categoryCode,
          status: appliedFilters.status,
        },
      })

      const list = (data && data.list) || []

      rows.push(...list)

      if (list.length < size) break

      if (data.total && rows.length >= data.total) break
    }

    const header = [
      'ID',
      '成果名称',
      '所属分类',
      '发布单位',
      '提交人',
      '状态',
      '浏览量',
      '创建时间',
    ]

    const body = rows.map(item => [
      item.id,
      item.title,
      item.categoryName || '-',
      item.orgName || '-',
      item.submitterName || item.submitterUserNo || '-',
      item.statusLabel || '-',
      item.viewCount ?? 0,
      fmtTime(item.createdAt),
    ])

    const escapeCsv = value => {
      const text = String(value ?? '')
        .replaceAll('"', '""')

      return `"${text}"`
    }

    const csv = [header, ...body]
      .map(row => row.map(escapeCsv).join(','))
      .join('\n')

    const blob = new Blob(
      ['\uFEFF' + csv],
      {
        type: 'text/csv;charset=utf-8',
      }
    )

    const url = URL.createObjectURL(blob)

    const link = document.createElement('a')

    link.href = url
    link.download = '成果列表.csv'

    link.click()

    URL.revokeObjectURL(url)
  } catch (err) {
    window.alert(`导出失败：${err.message || '请稍后重试'}`)
  } finally {
    exporting.value = false
  }
}

onMounted(() => {
  fetchList()
  fetchCategories()
  fetchOwnerUsers()
  if (isPlatformAdmin.value) {
    api('/admin/content-organizations').then(data => { organizations.value = data || [] }).catch(() => { organizations.value = [] })
  }
})
</script>

<template>
  <div class="achievement-page">

    <section class="filter-card">
      <div class="filter-grid">

        <div class="filter-item">
          <label>关键词</label>

          <input
            v-model="filters.keyword"
            type="text"
            placeholder="请输入成果名称/关键词"
            @keyup.enter="handleSearch"
          />
        </div>

        <div class="filter-item">
          <label>分类</label>

          <select v-model="filters.categoryCode">
            <option value="">
              请选择分类
            </option>

            <option
              v-for="item in categories"
              :key="item.code"
              :value="item.code"
            >
              {{ item.name }}
            </option>
          </select>
        </div>

        <div class="filter-item">
          <label>状态</label>

          <select v-model="filters.status">
            <option value="">
              请选择状态
            </option>

            <option
              v-for="item in statusOptions"
              :key="item.value"
              :value="item.value"
            >
              {{ item.label }}
            </option>
          </select>
        </div>

        <div class="filter-actions">
          <button
            type="button"
            class="primary-button"
            @click="handleSearch"
          >
            查询
          </button>

          <button
            type="button"
            class="default-button"
            @click="handleReset"
          >
            重置
          </button>
        </div>

        <div class="right-actions">
          <button type="button" class="primary-button" @click="openCreate">新增成果</button>
          <button
            type="button"
            class="default-button"
            :disabled="exporting"
            @click="exportData"
          >
            {{ exporting ? '导出中…' : '⇩ 导出' }}
          </button>
        </div>

      </div>
    </section>


    <section class="table-card">

      <div class="table-wrapper">

        <table>
          <thead>
            <tr>
              <th>ID</th>
              <th class="name-column">
                成果名称
              </th>
              <th>所属分类</th>
              <th>发布单位/团队</th>
              <th>提交人</th>
              <th>状态</th>
              <th>浏览量</th>
              <th>创建时间</th>
              <th class="operation-column">
                操作
              </th>
            </tr>
          </thead>

          <tbody>

            <tr v-if="loading">
              <td colspan="9" class="empty">
                加载中…
              </td>
            </tr>

            <tr v-else-if="loadError">
              <td colspan="9" class="error-cell">
                <div class="table-error">
                  <p>{{ loadError }}</p>

                  <button
                    type="button"
                    class="retry-button"
                    @click="fetchList"
                  >
                    重试
                  </button>
                </div>
              </td>
            </tr>

            <template v-else>

              <tr
                v-for="item in achievements"
                :key="item.id"
              >
                <td>
                  {{ item.id }}
                </td>

                <td
                  class="achievement-name"
                  :title="item.title"
                >
                  {{ item.title }}
                </td>

                <td>
                  {{ item.categoryName || '-' }}
                </td>

                <td
                  class="organization"
                  :title="item.orgName"
                >
                  {{ item.orgName || '-' }}
                </td>

                <td>
                  {{
                    item.submitterName ||
                      item.submitterUserNo ||
                      '-'
                  }}
                </td>

                <td>
                  <span
                    class="status"
                    :class="
                      getStatusClass(item.status)
                    "
                  >
                    <i></i>

                    {{ item.statusLabel }}
                  </span>
                </td>

                <td>
                  {{ fmtCount(item.viewCount) }}
                </td>

                <td class="created-time">
                  {{ fmtTime(item.createdAt) }}
                </td>

                <td>
                  <div class="operation-buttons">
                    <button type="button" @click="openEdit(item)">编辑</button>
                    <span>|</span>

                    <button
                      type="button"
                      @click="openView(item)"
                    >
                      查看
                    </button>

                    <span>|</span>

                    <button
                      v-if="
                        isPlatformAdmin && item.status === 'pending_review'
                      "
                      type="button"
                      @click="openAudit(item)"
                    >
                      审核
                    </button>

                    <span
                      v-if="
                        isPlatformAdmin && item.status === 'pending_review'
                      "
                    >
                      |
                    </span>

                    <button
                      type="button"
                      @click="
                        downloadAchievement(item)
                      "
                    >
                      下载
                    </button>

                  </div>
                </td>
              </tr>

              <tr v-if="achievements.length === 0">
                <td colspan="9" class="empty">
                  暂无符合条件的成果
                </td>
              </tr>

            </template>

          </tbody>
        </table>

      </div>


      <div class="pagination">

        <div class="total">
          共 {{ total }} 条
        </div>

        <select
          v-model="pageSize"
          @change="handlePageSizeChange"
        >
          <option :value="10">
            10条/页
          </option>

          <option :value="20">
            20条/页
          </option>

          <option :value="50">
            50条/页
          </option>
        </select>

        <button
          type="button"
          class="page-button"
          :disabled="currentPage === 1"
          @click="
            changePage(currentPage - 1)
          "
        >
          ‹
        </button>

        <template
          v-for="(page, index) in visiblePages"
          :key="`${page}-${index}`"
        >

          <span
            v-if="page === '...'"
            class="ellipsis"
          >
            ...
          </span>

          <button
            v-else
            type="button"
            class="page-button"
            :class="{
              active:
                page === currentPage
            }"
            @click="changePage(page)"
          >
            {{ page }}
          </button>

        </template>

        <button
          type="button"
          class="page-button"
          :disabled="
            currentPage === totalPages
          "
          @click="
            changePage(currentPage + 1)
          "
        >
          ›
        </button>

      </div>

    </section>


    <div v-if="formVisible" class="modal-mask" @click.self="!formSaving && (formVisible = false)">
      <div class="modal form-modal">
        <div class="modal-header"><h3>{{ formMode === 'create' ? '新增成果' : '编辑成果' }}</h3><button type="button" class="close-button" @click="formVisible = false">×</button></div>
        <div class="form-content" :class="{ 'org-admin-form': !isPlatformAdmin }">
          <p v-if="formLoading" class="modal-state">加载中…</p>
          <template v-else>
            <template v-if="!isPlatformAdmin">
              <label>所属机构</label><input :value="currentUser.orgName || '当前登录机构'" disabled />
              <label>归属用户</label><input :value="currentUser.displayName || currentUser.userNo || '当前登录账号'" disabled />
            </template>
            <label>成果名称 *</label><input v-model="achievementForm.title" />
            <label>分类 *</label><select v-model="achievementForm.categoryId"><option value="">请选择分类</option><option v-for="item in categories" :key="item.id" :value="item.id">{{ item.name }}</option></select>
            <label>所属机构 *</label><select v-model="achievementForm.orgId" @change="achievementForm.ownerUserId = ''"><option value="">请选择机构</option><option v-for="item in organizations" :key="item.id" :value="item.id">{{ item.name }}</option></select>
            <label>归属用户 *</label><select v-model="achievementForm.ownerUserId" :disabled="!achievementForm.orgId"><option value="">请先选择机构</option><option v-for="item in usersForSelectedOrg" :key="item.userId" :value="item.userId">{{ item.displayName || item.userNo }}</option></select>
            <label>技术简介</label><textarea v-model="achievementForm.techIntro" rows="4"></textarea>
            <div class="form-grid"><div><label>成熟度 *</label><select v-model="achievementForm.maturityLevel"><option value="01_idea">概念阶段</option><option value="02_lab">实验室验证</option><option value="03_pilot_ready">可中试</option><option value="04_pilot_done">中试完成</option><option value="05_mass_ready">量产准备</option></select></div><div><label>定价方式 *</label><select v-model="achievementForm.pricingMode"><option value="negotiable">面议</option><option value="license">许可</option><option value="transfer">转让</option><option value="cooperation">合作</option><option value="other">其他</option></select></div></div>
            <div class="form-grid"><div><label>最低报价（万元）</label><input v-model="achievementForm.priceMinWan" type="number" min="0" /></div><div><label>最高报价（万元）</label><input v-model="achievementForm.priceMaxWan" type="number" min="0" /></div></div>
            <label>应用领域（逗号分隔）</label><input v-model="achievementForm.applicationFieldsText" />
            <label>发明人（逗号分隔）</label><input v-model="achievementForm.inventorNamesText" />
            <div class="form-grid"><div><label>联系人</label><input v-model="achievementForm.contactName" /></div><div><label>联系电话</label><input v-model="achievementForm.contactPhone" /></div></div>
            <label>联系邮箱</label><input v-model="achievementForm.contactEmail" />
            <p v-if="formError" class="audit-error">{{ formError }}</p>
          </template>
        </div>
        <div class="modal-footer">
          <button type="button" class="default-button" :disabled="formSaving" @click="formVisible = false">取消</button>
          <button type="button" class="default-button" :disabled="formLoading || formSaving" @click="saveAchievement('draft')">{{ formSaving ? '保存中…' : '保存草稿' }}</button>
          <button v-if="isPlatformAdmin" type="button" class="primary-button" :disabled="formLoading || formSaving" @click="saveAchievement('publish')">{{ formSaving ? '保存中…' : '直接发布' }}</button>
          <button v-else type="button" class="primary-button" :disabled="formLoading || formSaving" @click="saveAchievement('submit')">{{ formSaving ? '保存中…' : '提交审核' }}</button>
        </div>
      </div>
    </div>

    <div
      v-if="modalVisible"
      class="modal-mask"
      @click.self="closeModal"
    >

      <div class="modal">

        <div class="modal-header">
          <h3>
            {{
              modalMode === 'view'
                ? '成果详情'
                : '成果审核'
            }}
          </h3>

          <button
            type="button"
            class="close-button"
            @click="closeModal"
          >
            ×
          </button>
        </div>


        <div
          v-if="modalMode === 'view'"
          class="detail-content"
        >
          <div v-if="viewLoading" class="modal-state">
            加载中…
          </div>

          <div
            v-else-if="viewError"
            class="modal-state error"
          >
            <p>{{ viewError }}</p>

            <button
              type="button"
              class="retry-button"
              @click="fetchDetail(viewId)"
            >
              重试
            </button>
          </div>

          <template v-else-if="viewDetail">

            <div>
              <label>成果编号</label>
              <p>
                {{ viewDetail.id }}
              </p>
            </div>

            <div>
              <label>成果名称</label>
              <p>
                {{ viewDetail.title }}
              </p>
            </div>

            <div>
              <label>所属分类</label>
              <p>
                {{ viewDetail.categoryName || '-' }}
              </p>
            </div>

            <div>
              <label>发布单位</label>
              <p>
                {{ viewDetail.orgName || '-' }}
              </p>
            </div>

            <div>
              <label>提交人</label>
              <p>
                {{
                  viewDetail.submitterName ||
                    viewDetail.submitterUserNo ||
                    '-'
                }}
              </p>
            </div>

            <div>
              <label>状态</label>
              <p>
                {{ viewDetail.statusLabel || '-' }}
              </p>
            </div>

            <div>
              <label>成熟度</label>
              <p>
                {{ viewDetail.maturityLevel || '-' }}
              </p>
            </div>

            <div>
              <label>浏览量</label>
              <p>
                {{ fmtCount(viewDetail.viewCount) }}
              </p>
            </div>

            <div>
              <label>发明人</label>
              <p>
                {{ inventorNames }}
              </p>
            </div>

            <div>
              <label>联系方式</label>
              <p>
                {{ contactText }}
              </p>
            </div>

            <div class="full">
              <label>创新点</label>

              <ul
                v-if="innovationPoints.length"
                class="point-list"
              >
                <li
                  v-for="(point, index) in innovationPoints"
                  :key="index"
                >
                  {{ point }}
                </li>
              </ul>

              <p v-else>-</p>
            </div>

            <div class="full">
              <label>成果简介</label>
              <p>
                {{ viewDetail.techIntro || '-' }}
              </p>
            </div>

          </template>
        </div>


        <div
          v-else
          class="audit-content"
        >
          <div class="audit-name">
            {{ auditItem.title }}
          </div>

          <p>
            当前状态：
            <strong>
              {{ auditItem.statusLabel }}
            </strong>
          </p>

          <p class="audit-tip">
            请确认该成果内容是否符合平台发布要求，驳回时需填写原因。
          </p>

          <div class="modal-form-item">
            <label>驳回原因 *</label>

            <textarea
              v-model="rejectReason"
              rows="4"
              placeholder="请填写驳回原因"
            ></textarea>
          </div>

          <p
            v-if="auditError"
            class="audit-error"
          >
            {{ auditError }}
          </p>
        </div>


        <div class="modal-footer">

          <button
            type="button"
            class="default-button"
            :disabled="
              modalMode === 'audit' && auditSubmitting
            "
            @click="closeModal"
          >
            取消
          </button>

          <template
            v-if="modalMode === 'audit'"
          >
            <button
              type="button"
              class="reject-button"
              :disabled="auditSubmitting"
              @click="handleReject"
            >
              审核驳回
            </button>

            <button
              type="button"
              class="primary-button"
              :disabled="auditSubmitting"
              @click="handleApprove"
            >
              审核通过
            </button>
          </template>

        </div>

      </div>

    </div>

  </div>
</template>

<style scoped>
.achievement-page {
  width: 100%;
}

.filter-card,
.table-card {
  border: 1px solid #e8edf4;
  border-radius: 11px;
  background: #ffffff;
  box-shadow:
    0 2px 14px rgba(40, 72, 110, 0.07);
}

.filter-card {
  padding: 25px 27px;
}

.filter-grid {
  display: grid;
  grid-template-columns:
    1.35fr
    1fr
    1fr
    auto
    auto;

  align-items: end;
  gap: 20px 28px;
}

.filter-item label {
  display: block;
  margin-bottom: 9px;
  color: #273347;
  font-size: 14px;
  font-weight: 600;
}

.filter-item input,
.filter-item select,
.pagination select,
.modal input,
.modal select,
.modal textarea {
  width: 100%;
  height: 40px;
  padding: 0 13px;
  outline: none;
  border: 1px solid #dce4ee;
  border-radius: 5px;
  background: #ffffff;
  color: #4c596b;
}

.filter-item input:focus,
.filter-item select:focus,
.modal input:focus,
.modal select:focus,
.modal textarea:focus {
  border-color: #1677ff;
}

.filter-actions,
.right-actions {
  display: flex;
  gap: 12px;
}

.right-actions {
  justify-content: flex-end;
}

.primary-button,
.default-button,
.reject-button {
  height: 40px;
  padding: 0 25px;
  border-radius: 5px;
  font-size: 14px;
}

.primary-button {
  border: 1px solid #1677ff;
  background: #1677ff;
  color: white;
}

.primary-button:hover {
  background: #0869e8;
}

.default-button {
  border: 1px solid #dce4ee;
  background: #ffffff;
  color: #4c596a;
}

.default-button:hover {
  border-color: #9fc6ff;
  color: #1677ff;
}

.reject-button {
  border: 1px solid #ff5964;
  background: white;
  color: #ef4350;
}

.primary-button:disabled,
.default-button:disabled,
.reject-button:disabled {
  cursor: not-allowed;
  opacity: 0.55;
}

.table-card {
  margin-top: 14px;
  overflow: hidden;
}

.table-wrapper {
  overflow-x: auto;
}

table {
  width: 100%;
  min-width: 1150px;
  border-collapse: collapse;
  table-layout: fixed;
}

th,
td {
  height: 64px;
  padding: 0 14px;
  border-bottom: 1px solid #edf1f5;
  color: #4e5969;
  font-size: 13px;
  text-align: left;
  vertical-align: middle;
}

th {
  height: 64px;
  background: #ffffff;
  color: #273347;
  font-weight: 600;
}

th:nth-child(1) {
  width: 135px;
}

.name-column {
  width: 210px;
}

th:nth-child(3) {
  width: 95px;
}

th:nth-child(4) {
  width: 155px;
}

th:nth-child(5) {
  width: 110px;
}

th:nth-child(6) {
  width: 90px;
}

th:nth-child(7) {
  width: 70px;
}

th:nth-child(8) {
  width: 135px;
}

.operation-column {
  width: 150px;
}

tbody tr:hover {
  background: #fafcff;
}

.achievement-name,
.organization {
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
}

.status {
  display: inline-flex;
  align-items: center;
  gap: 7px;
}

.status i {
  width: 7px;
  height: 7px;
  border-radius: 50%;
}

.status.published i {
  background: #22bd7a;
}

.status.reviewing {
  padding: 5px 8px;
  border-radius: 4px;
  background: #ebf3ff;
  color: #317de9;
}

.status.reviewing i {
  background: #317de9;
}

.status.offline {
  padding: 5px 8px;
  border-radius: 4px;
  background: #fff0f2;
  color: #f25763;
}

.status.offline i {
  background: #f25763;
}

.status.rejected {
  padding: 5px 8px;
  border-radius: 4px;
  background: #fff0f2;
  color: #f25763;
}

.status.rejected i {
  background: #f25763;
}

.status.draft {
  padding: 5px 8px;
  border-radius: 4px;
  background: #f1f3f7;
  color: #86909c;
}

.status.draft i {
  background: #86909c;
}

.created-time {
  white-space: nowrap;
}

.operation-buttons {
  display: flex;
  align-items: center;
  gap: 6px;
  white-space: nowrap;
}

.operation-buttons button {
  padding: 0;
  border: 0;
  background: transparent;
  color: #1677ff;
  font-size: 12px;
}

.operation-buttons button:hover {
  text-decoration: underline;
}

.operation-buttons span {
  color: #d4dbe5;
}

.empty {
  height: 180px;
  color: #a0a9b5;
  text-align: center;
}

.table-error {
  padding: 34px 0;
  color: #ef4350;
  text-align: center;
}

.table-error p {
  margin: 0 0 14px;
}

.retry-button {
  height: 34px;
  padding: 0 20px;
  border: 1px solid #dce4ee;
  border-radius: 5px;
  background: #ffffff;
  color: #4c596a;
  font-size: 13px;
}

.retry-button:hover {
  border-color: #9fc6ff;
  color: #1677ff;
}

.pagination {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 7px;
  min-height: 74px;
  padding: 12px 24px;
}

.pagination .total {
  margin-right: 14px;
}

.pagination select {
  width: 110px;
  margin-right: 8px;
}

.page-button {
  min-width: 38px;
  height: 38px;
  padding: 0 11px;
  border: 1px solid #dfe5ed;
  border-radius: 5px;
  background: white;
  color: #344154;
}

.page-button.active {
  border-color: #1677ff;
  background: #1677ff;
  color: white;
}

.page-button:disabled {
  cursor: not-allowed;
  opacity: 0.4;
}

.ellipsis {
  padding: 0 6px;
}


.modal-mask {
  position: fixed;
  z-index: 500;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(15, 28, 48, 0.36);
}

.modal {
  width: 650px;
  max-height: 82vh;
  overflow-y: auto;
  border-radius: 10px;
  background: white;
  box-shadow:
    0 25px 80px rgba(20, 40, 70, 0.2);
}

.modal-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: 64px;
  padding: 0 24px;
  border-bottom: 1px solid #edf1f5;
}

.modal-header h3 {
  margin: 0;
  font-size: 18px;
}

.close-button {
  border: 0;
  background: transparent;
  color: #8b96a5;
  font-size: 25px;
}

.detail-content {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 22px;
  padding: 26px;
}

.detail-content label,
.modal-form-item label {
  display: block;
  margin-bottom: 8px;
  color: #8590a0;
  font-size: 12px;
}

.detail-content p {
  margin: 0;
  color: #344153;
  line-height: 1.7;
}

.full {
  grid-column: 1 / -1;
}

.point-list {
  margin: 0;
  padding-left: 18px;
  color: #344153;
  line-height: 1.8;
}

.modal-state {
  grid-column: 1 / -1;
  padding: 40px 0;
  color: #8b96a5;
  font-size: 14px;
  text-align: center;
}

.modal-state.error {
  color: #ef4350;
}

.modal-state .retry-button {
  margin-top: 14px;
}

.modal textarea {
  height: auto;
  padding-top: 10px;
  resize: vertical;
}

.audit-content {
  padding: 35px 30px;
}

.audit-name {
  margin-bottom: 20px;
  color: #1e2939;
  font-size: 18px;
  font-weight: 600;
}

.audit-tip {
  color: #8b96a5;
}

.audit-content .modal-form-item {
  margin-top: 20px;
}

.audit-error {
  margin: 14px 0 0;
  color: #ef4350;
  font-size: 13px;
}

.modal-footer {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
  padding: 16px 24px;
  border-top: 1px solid #edf1f5;
}

@media (max-width: 1500px) {
  .filter-grid {
    grid-template-columns:
      1.2fr
      1fr
      1fr
      auto
      auto;

    gap: 18px 20px;
  }
}
.form-modal { width: 720px; }
.form-content { overflow-y: auto; padding: 20px 24px; }
.form-content label { display: block; margin: 12px 0 6px; color: #283447; font-size: 13px; font-weight: 600; }
.form-content input, .form-content select, .form-content textarea { box-sizing: border-box; width: 100%; padding: 9px 11px; border: 1px solid #dce4ee; border-radius: 5px; font: inherit; }
.form-content textarea { resize: vertical; }
.form-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 16px; }
.org-admin-form > label:nth-of-type(5),
.org-admin-form > label:nth-of-type(6),
.org-admin-form > select:nth-of-type(2),
.org-admin-form > select:nth-of-type(3) { display: none; }
</style>
