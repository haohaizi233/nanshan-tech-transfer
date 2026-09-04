<script setup>
import {
  computed,
  onMounted,
  reactive,
  ref
} from 'vue'

import {
  useRoute,
  useRouter
} from 'vue-router'

import {
  useRequirementStore
} from '../../stores/requirement'

const route =
  useRoute()

const router =
  useRouter()

const store =
  useRequirementStore()

const activeTab =
  ref('attachment')

const editVisible =
  ref(false)

const requirement =
  computed(() => {
    return store.getById(
      route.params.id
    )
  })

const editForm =
  reactive({
    title: '',
    budget: '',
    cooperation: '',
    summary: ''
  })

onMounted(() => {
  if (
    route.query.action ===
    'audit'
  ) {
    setTimeout(() => {
      document
        .querySelector(
          '.action-bar'
        )
        ?.scrollIntoView({
          behavior: 'smooth'
        })
    }, 100)
  }
})

const goBack = () => {
  router.push(
    '/admin/requirements'
  )
}

const toggleFavorite =
  () => {
    store.toggleFavorite(
      requirement.value.id
    )
  }

const share =
  async () => {
    const url =
      window.location.href

    try {
      await navigator
        .clipboard
        .writeText(url)

      window.alert(
        '详情链接已复制'
      )
    } catch {
      window.alert(
        url
      )
    }
  }

const printPage = () => {
  window.print()
}

const approve = () => {
  const result =
    window.confirm(
      '确定审核通过该需求吗？'
    )

  if (!result) return

  store.approve(
    requirement.value.id
  )

  window.alert(
    '审核通过'
  )
}

const reject = () => {
  const result =
    window.confirm(
      '确定驳回该需求吗？'
    )

  if (!result) return

  store.reject(
    requirement.value.id
  )

  window.alert(
    '需求已驳回'
  )
}

const openEdit =
  () => {
    Object.assign(
      editForm,
      {
        title:
          requirement.value.title,

        budget:
          requirement.value.budget,

        cooperation:
          requirement.value.cooperation,

        summary:
          requirement.value.summary
      }
    )

    editVisible.value =
      true
  }

const saveEdit =
  () => {
    if (
      !editForm.title.trim()
    ) {
      window.alert(
        '请输入需求标题'
      )

      return
    }

    store.updateRequirement(
      requirement.value.id,
      {
        title:
          editForm.title,

        budget:
          editForm.budget,

        cooperation:
          editForm.cooperation,

        summary:
          editForm.summary
      }
    )

    editVisible.value =
      false
  }

const downloadAttachment =
  attachment => {
    const text = `
附件名称：${attachment.name}
需求编号：${requirement.value.id}
需求名称：${requirement.value.title}

当前为前端演示附件。
后续接入后端文件服务后，
这里可以直接下载真实 PDF 文件。
`

    const blob =
      new Blob(
        [text],
        {
          type:
            'text/plain;charset=utf-8'
        }
      )

    const url =
      URL.createObjectURL(
        blob
      )

    const link =
      document.createElement(
        'a'
      )

    link.href = url

    link.download =
      attachment.name
        .replace(
          '.pdf',
          '.txt'
        )

    link.click()

    URL.revokeObjectURL(
      url
    )
  }

const timeline =
  computed(() => {
    const approved =
      requirement.value
        .auditStatus ===
      '已通过'

    const rejected =
      requirement.value
        .auditStatus ===
      '已驳回'

    return [
      {
        name: '草稿',
        status: 'done',
        time:
          '2025-05-20 16:20',
        operator:
          '张伟 创建'
      },

      {
        name: '已提交',
        status: 'done',
        time:
          '2025-05-21 10:30',
        operator:
          '张伟 提交'
      },

      {
        name:
          rejected
            ? '已驳回'
            : approved
              ? '审核完成'
              : '审核中',

        status:
          approved ||
          rejected
            ? 'done'
            : 'current',

        time:
          approved ||
          rejected
            ? '刚刚'
            : '2025-05-21 11:05',

        operator:
          '管理员 受理'
      },

      {
        name: '已通过',

        status:
          approved
            ? 'done'
            : 'waiting',

        time:
          approved
            ? '刚刚'
            : '待审核',

        operator: ''
      },

      {
        name: '已发布',

        status:
          approved
            ? 'done'
            : 'waiting',

        time:
          approved
            ? '刚刚'
            : '待发布',

        operator: ''
      }
    ]
  })
</script>

<template>
  <div
    v-if="requirement"
    class="detail-page"
  >

    <div class="back-row">
      <button
        @click="goBack"
      >
        ‹ 返回
      </button>
    </div>


    <div class="title-row">

      <div>
        <h1>
          {{ requirement.title }}
        </h1>

        <div class="title-meta">

          <span
            class="review-status"
          >
            {{
              requirement.status
            }}
          </span>

          <span>
            发布时间：
            {{
              requirement.publishedAt
            }}
          </span>

          <span>
            浏览量：
            {{ requirement.views }}
          </span>

        </div>
      </div>


      <div class="top-actions">

        <button
          @click="
            toggleFavorite
          "
        >
          ☆
          {{
            requirement.favorite
              ? '已收藏'
              : '收藏'
          }}
        </button>

        <button
          @click="share"
        >
          ⤴ 分享
        </button>

        <button
          @click="
            printPage
          "
        >
          ▣ 打印
        </button>

      </div>

    </div>


    <section class="summary-card">

      <div class="summary-item">
        <div class="summary-icon blue">
          ▤
        </div>

        <div>
          <label>
            需求编号
          </label>

          <strong>
            {{
              requirement.id
            }}
          </strong>
        </div>
      </div>


      <div class="summary-item">
        <div class="summary-icon green">
          ▦
        </div>

        <div>
          <label>
            发布单位
          </label>

          <strong>
            {{
              requirement.organization
            }}
          </strong>

          <small
            v-if="
              requirement.certified
            "
          >
            已认证
          </small>
        </div>
      </div>


      <div class="summary-item">
        <div class="summary-icon purple">
          ⚙
        </div>

        <div>
          <label>
            所属行业
          </label>

          <strong>
            {{
              requirement.industry
            }}
          </strong>
        </div>
      </div>


      <div class="summary-item">
        <div class="summary-icon orange">
          ◷
        </div>

        <div>
          <label>
            发布时间
          </label>

          <strong>
            {{
              requirement.publishedAt
            }}
          </strong>
        </div>
      </div>


      <div class="summary-item">
        <div class="summary-icon yellow">
          ◫
        </div>

        <div>
          <label>
            预算范围
          </label>

          <strong>
            {{
              requirement.budget
            }}
          </strong>
        </div>
      </div>


      <div class="summary-item">
        <div class="summary-icon blue">
          ◆
        </div>

        <div>
          <label>
            合作方式
          </label>

          <strong>
            {{
              requirement.cooperation
            }}
          </strong>
        </div>
      </div>

    </section>


    <div class="main-grid">

      <section class="detail-card">

        <h2>
          需求详情
        </h2>

        <div class="detail-section">

          <h3>
            <i></i>
            需求概述
          </h3>

          <p>
            {{
              requirement.summary
            }}
          </p>

        </div>


        <div class="detail-section">

          <h3>
            <i></i>
            具体需求
          </h3>

          <ol>
            <li
              v-for="
                item
                in requirement.requirements
              "
              :key="item"
            >
              {{ item }}
            </li>
          </ol>

        </div>


        <div class="detail-section">

          <h3>
            <i></i>
            技术指标
          </h3>

          <ul>
            <li
              v-for="
                item
                in requirement.indicators
              "
              :key="item"
            >
              {{ item }}
            </li>
          </ul>

        </div>


        <div class="detail-section">

          <h3>
            <i></i>
            联系方式
          </h3>

          <div class="contact-grid">

            <span>
              联系人：
              {{
                requirement.contact.name
              }}
            </span>

            <span>
              联系电话：
              {{
                requirement.contact.phone
              }}
            </span>

            <span>
              邮箱：
              {{
                requirement.contact.email
              }}
            </span>

            <span class="full">
              地址：
              {{
                requirement.contact.address
              }}
            </span>

          </div>

        </div>

      </section>


      <section class="timeline-card">

        <h2>
          需求状态
        </h2>

        <div class="timeline">

          <div
            v-for="
              item in timeline
            "
            :key="item.name"
            class="timeline-item"
            :class="
              item.status
            "
          >

            <div class="timeline-left">

              <span
                class="timeline-dot"
              >
                {{
                  item.status ===
                  'done'
                    ? '✓'
                    : ''
                }}
              </span>

              <span
                class="timeline-line"
              ></span>

            </div>


            <div
              class="timeline-content"
            >

              <strong>
                {{ item.name }}
              </strong>

              <div>
                {{ item.time }}
              </div>

              <small>
                {{ item.operator }}
              </small>

            </div>

          </div>

        </div>

      </section>

    </div>


    <section class="records-card">

      <div class="tabs">

        <button
          :class="{
            active:
              activeTab ===
              'attachment'
          }"
          @click="
            activeTab =
              'attachment'
          "
        >
          附件信息
        </button>

        <button
          :class="{
            active:
              activeTab ===
              'audit'
          }"
          @click="
            activeTab =
              'audit'
          "
        >
          审核记录
          （{{
            requirement
              .auditRecords
              .length
          }}）
        </button>

        <button
          :class="{
            active:
              activeTab ===
              'docking'
          }"
          @click="
            activeTab =
              'docking'
          "
        >
          对接记录
          （{{
            requirement
              .dockingRecords
              .length
          }}）
        </button>

      </div>


      <div
        v-if="
          activeTab ===
          'attachment'
        "
        class="tab-content"
      >

        <div
          v-for="
            item
            in requirement.attachments
          "
          :key="item.id"
          class="attachment-row"
        >

          <span
            class="pdf-icon"
          >
            PDF
          </span>

          <strong>
            {{ item.name }}
          </strong>

          <span>
            {{ item.size }}
          </span>

          <span>
            {{ item.uploadedAt }}
          </span>

          <span>
            {{ item.uploader }}
          </span>

          <button
            @click="
              downloadAttachment(
                item
              )
            "
          >
            ⇩ 下载
          </button>

        </div>

        <div
          v-if="
            !requirement
              .attachments.length
          "
          class="empty-record"
        >
          暂无附件
        </div>

      </div>


      <div
        v-else-if="
          activeTab ===
          'audit'
        "
        class="tab-content"
      >

        <div
          v-for="
            record
            in requirement.auditRecords
          "
          :key="record.id"
          class="record-row"
        >

          <strong>
            {{ record.action }}
          </strong>

          <span>
            {{ record.operator }}
          </span>

          <span>
            {{ record.time }}
          </span>

          <span>
            {{ record.remark }}
          </span>

        </div>

      </div>


      <div
        v-else
        class="tab-content"
      >

        <div
          v-if="
            !requirement
              .dockingRecords
              .length
          "
          class="empty-record"
        >
          暂无对接记录
        </div>

      </div>

    </section>


    <section class="action-bar">

      <button
        class="approve-btn"
        @click="approve"
      >
        ✓ 审核通过
      </button>

      <button
        class="reject-btn"
        @click="reject"
      >
        × 审核驳回
      </button>

      <button
        class="edit-btn"
        @click="
          openEdit
        "
      >
        ✎ 编辑
      </button>

      <button
        class="back-btn"
        @click="goBack"
      >
        ↶ 返回
      </button>

    </section>


    <div
      v-if="editVisible"
      class="modal-mask"
      @click.self="
        editVisible = false
      "
    >

      <div class="modal">

        <div class="modal-header">

          <h3>
            编辑需求
          </h3>

          <button
            @click="
              editVisible = false
            "
          >
            ×
          </button>

        </div>


        <div class="edit-form">

          <label>
            需求标题

            <input
              v-model="
                editForm.title
              "
            />
          </label>

          <label>
            预算范围

            <input
              v-model="
                editForm.budget
              "
            />
          </label>

          <label>
            合作方式

            <input
              v-model="
                editForm.cooperation
              "
            />
          </label>

          <label class="full">
            需求概述

            <textarea
              v-model="
                editForm.summary
              "
              rows="6"
            ></textarea>
          </label>

        </div>


        <div class="modal-footer">

          <button
            class="back-btn"
            @click="
              editVisible = false
            "
          >
            取消
          </button>

          <button
            class="approve-btn"
            @click="
              saveEdit
            "
          >
            保存
          </button>

        </div>

      </div>

    </div>

  </div>


  <div
    v-else
    class="not-found"
  >
    <h2>
      未找到该需求
    </h2>

    <button
      @click="goBack"
    >
      返回需求列表
    </button>
  </div>
</template>

<style scoped>
.detail-page {
  width: 100%;
}

button {
  cursor: pointer;
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

.review-status {
  padding: 4px 9px;
  border-radius: 4px;
  background: #e9faf1;
  color: #27b878;
}

.top-actions {
  display: flex;
  gap: 12px;
}

.top-actions button {
  height: 38px;
  padding: 0 18px;
  border: 1px solid #dce4ee;
  border-radius: 5px;
  background: white;
  color: #3f4c60;
}

.summary-card {
  display: grid;
  grid-template-columns: repeat(6, 1fr);
  padding: 20px;
  border: 1px solid #e8edf4;
  border-radius: 10px;
  background: white;
  box-shadow:
    0 2px 14px rgba(40, 72, 110, 0.06);
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

.summary-item small {
  display: inline-block;
  margin-top: 3px;
  padding: 2px 6px;
  border-radius: 3px;
  background: #e9f3ff;
  color: #287bea;
}

.main-grid {
  display: grid;
  grid-template-columns: minmax(0, 2.2fr) minmax(310px, 0.8fr);
  gap: 14px;
  margin-top: 14px;
}

.detail-card,
.timeline-card,
.records-card,
.action-bar {
  border: 1px solid #e8edf4;
  border-radius: 10px;
  background: white;
  box-shadow:
    0 2px 14px rgba(40, 72, 110, 0.06);
}

.detail-card,
.timeline-card {
  min-height: 420px;
  padding: 20px 23px;
}

.detail-card h2,
.timeline-card h2 {
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

.detail-section ol,
.detail-section ul {
  margin: 0;
  padding-left: 21px;
}

.contact-grid {
  display: grid;
  grid-template-columns: 1fr 1fr 1fr;
  gap: 11px 25px;
  color: #515e70;
  font-size: 13px;
}

.contact-grid .full {
  grid-column: 1 / -1;
}

.timeline {
  padding: 10px 0 10px 7px;
}

.timeline-item {
  display: grid;
  grid-template-columns: 25px 1fr;
  min-height: 74px;
}

.timeline-left {
  position: relative;
}

.timeline-dot {
  position: relative;
  z-index: 2;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 17px;
  height: 17px;
  border: 2px solid #cfd6df;
  border-radius: 50%;
  background: white;
  color: white;
  font-size: 10px;
}

.timeline-line {
  position: absolute;
  left: 8px;
  top: 17px;
  bottom: 0;
  width: 1px;
  background: #dce3eb;
}

.timeline-item:last-child .timeline-line {
  display: none;
}

.timeline-item.done .timeline-dot {
  border-color: #20b875;
  background: #20b875;
}

.timeline-item.current .timeline-dot {
  border: 5px solid #1677ff;
  box-shadow: 0 0 0 3px #e5f0ff;
}

.timeline-content strong {
  color: #3b485b;
  font-size: 14px;
}

.timeline-item.current .timeline-content strong {
  color: #1677ff;
}

.timeline-content div {
  margin-top: 7px;
  color: #8995a5;
  font-size: 12px;
}

.timeline-content small {
  display: block;
  margin-top: 4px;
  color: #8995a5;
}

.timeline-item.waiting {
  opacity: 0.55;
}

.records-card {
  margin-top: 14px;
}

.tabs {
  display: flex;
  height: 47px;
  padding-left: 18px;
  border-bottom: 1px solid #e8edf4;
}

.tabs button {
  position: relative;
  padding: 0 19px;
  border: 0;
  background: transparent;
  color: #556174;
}

.tabs button.active {
  color: #1677ff;
  font-weight: 600;
}

.tabs button.active::after {
  position: absolute;
  right: 10px;
  bottom: 0;
  left: 10px;
  height: 2px;
  background: #1677ff;
  content: "";
}

.tab-content {
  min-height: 58px;
}

.attachment-row {
  display: grid;
  grid-template-columns: 45px 1.6fr 110px 170px 100px 80px;
  align-items: center;
  min-height: 58px;
  padding: 0 20px;
  color: #596577;
  font-size: 12px;
}

.pdf-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 31px;
  height: 34px;
  border-radius: 3px;
  background: #ef4652;
  color: white;
  font-size: 9px;
  font-weight: 700;
}

.attachment-row button {
  border: 1px solid #7bb5ff;
  border-radius: 4px;
  background: white;
  color: #1677ff;
}

.record-row {
  display: grid;
  grid-template-columns: 130px 120px 180px 1fr;
  gap: 15px;
  min-height: 54px;
  padding: 16px 22px;
  border-bottom: 1px solid #edf1f5;
  color: #647083;
  font-size: 12px;
}

.empty-record {
  padding: 24px;
  color: #9ba5b3;
  text-align: center;
}

.action-bar {
  display: flex;
  justify-content: center;
  gap: 22px;
  margin-top: 14px;
  padding: 20px;
}

.action-bar button {
  width: 195px;
  height: 48px;
  border-radius: 5px;
  font-size: 15px;
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

.edit-btn {
  border: 1px solid #68a8ff;
  background: white;
  color: #1677ff;
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
  box-shadow:
    0 20px 70px rgba(20, 40, 70, 0.2);
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

.edit-form {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 20px;
  padding: 25px;
}

.edit-form label {
  color: #5e6979;
  font-size: 13px;
}

.edit-form input,
.edit-form textarea {
  width: 100%;
  margin-top: 8px;
  padding: 0 12px;
  outline: none;
  border: 1px solid #dce4ee;
  border-radius: 5px;
}

.edit-form input {
  height: 42px;
}

.edit-form textarea {
  padding-top: 10px;
  resize: vertical;
}

.edit-form input:focus,
.edit-form textarea:focus {
  border-color: #1677ff;
}

.edit-form .full {
  grid-column: 1 / -1;
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

.not-found {
  padding: 100px;
  text-align: center;
}

@media print {
  .back-row,
  .top-actions,
  .action-bar,
  .admin-header,
  .sidebar {
    display: none !important;
  }
}
</style>