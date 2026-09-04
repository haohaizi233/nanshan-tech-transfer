<script setup>
import {
  computed,
  onMounted,
  ref
} from 'vue'

import {
  useRoute,
  useRouter
} from 'vue-router'

import {
  useCooperationStore
} from '../../stores/cooperation'

const route =
  useRoute()

const router =
  useRouter()

const store =
  useCooperationStore()

const cooperation =
  computed(() => {
    return store.getById(
      route.params.id
    )
  })

const communicationVisible =
  ref(false)

const communicationText =
  ref('')

const showAllRecords =
  ref(false)

onMounted(() => {
  if (
    route.query.action ===
    'process'
  ) {
    setTimeout(() => {
      document
        .querySelector(
          '.bottom-actions'
        )
        ?.scrollIntoView({
          behavior: 'smooth'
        })
    }, 150)
  }
})

const goBack = () => {
  router.push(
    '/admin/cooperation'
  )
}

const accept =
  () => {
    if (
      cooperation.value.status !==
      '待处理'
    ) return

    const result =
      window.confirm(
        '确定接受该合作意向吗？'
      )

    if (!result) return

    store.accept(
      cooperation.value.id
    )
  }

const reject =
  () => {
    if (
      cooperation.value.status ===
      '已归档'
    ) return

    const result =
      window.confirm(
        '确定拒绝该合作意向吗？'
      )

    if (!result) return

    store.reject(
      cooperation.value.id
    )
  }

const confirmDocking =
  () => {
    if (
      cooperation.value.status !==
      '已接受'
    ) {
      window.alert(
        '请先接受合作意向'
      )

      return
    }

    store.confirm(
      cooperation.value.id
    )
  }

const complete =
  () => {
    if (
      cooperation.value.status !==
      '已确认'
    ) {
      window.alert(
        '请先完成对接确认'
      )

      return
    }

    store.complete(
      cooperation.value.id
    )
  }

const archive =
  () => {
    if (
      cooperation.value.status !==
      '已完成'
    ) {
      window.alert(
        '完成对接后才能归档'
      )

      return
    }

    store.archive(
      cooperation.value.id
    )
  }

const openCommunication =
  () => {
    communicationText.value =
      ''

    communicationVisible.value =
      true
  }

const submitCommunication =
  () => {
    const text =
      communicationText.value.trim()

    if (!text) {
      window.alert(
        '请输入沟通内容'
      )

      return
    }

    store.addCommunication(
      cooperation.value.id,
      text
    )

    communicationVisible.value =
      false
  }

const visibleCommunications =
  computed(() => {
    if (
      showAllRecords.value
    ) {
      return cooperation.value
        .communications
    }

    return cooperation.value
      .communications
      .slice(0, 3)
  })

const timeline =
  computed(() => {
    const status =
      cooperation.value.status

    const order = [
      '待处理',
      '已接受',
      '已确认',
      '已完成',
      '已归档',
    ]

    if (
      status === '已拒绝'
    ) {
      return [
        {
          name: '待处理',
          state: 'done'
        },

        {
          name: '已拒绝',
          state: 'rejected'
        },
      ]
    }

    const currentIndex =
      order.indexOf(status)

    return order.map(
      (
        name,
        index
      ) => {
        const history =
          cooperation.value
            .history
            .find(
              item =>
                item.status ===
                name
            )

        let state =
          'waiting'

        if (
          index <
          currentIndex
        ) {
          state =
            'done'
        }

        if (
          index ===
          currentIndex
        ) {
          state =
            name ===
            '已归档'
              ? 'done'
              : 'current'
        }

        return {
          name,

          state,

          time:
            history?.time ||
            (
              index === 0
                ? cooperation
                    .value
                    .submittedAt
                : ''
            ),

          operator:
            history?.operator ||
            ''
        }
      }
    )
  })
</script>

<template>
  <div
    v-if="cooperation"
    class="cooperation-detail"
  >

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

    </div>


    <div class="top-grid">

      <section class="info-card">

        <div class="info-row">

          <label>
            意向编号
          </label>

          <strong>
            {{ cooperation.id }}
          </strong>

        </div>


        <div class="info-row">

          <label>
            发起人
          </label>

          <div>
            <strong>
              {{
                cooperation.initiator
              }}
            </strong>

            <span class="type-tag blue">
              {{
                cooperation.initiatorType
              }}
            </span>
          </div>

        </div>


        <div class="info-row">

          <label>
            联系方式
          </label>

          <div>
            ☎
            {{
              cooperation.contactName
            }}

            {{
              cooperation.phone
            }}

            <span class="separator">
              |
            </span>

            {{
              cooperation.email
            }}
          </div>

        </div>


        <div class="info-row">

          <label>
            对接对象
          </label>

          <div>
            <strong>
              {{
                cooperation.target
              }}
            </strong>

            <span class="type-tag green">
              {{
                cooperation.targetType
              }}
            </span>
          </div>

        </div>


        <div class="info-row">

          <label>
            对接类型
          </label>

          <strong>
            ◇
            {{ cooperation.type }}
          </strong>

        </div>


        <div class="info-row">

          <label>
            提交时间
          </label>

          <span>
            ◷
            {{
              cooperation.submittedAt
            }}
          </span>

        </div>


        <div class="info-row">

          <label>
            当前状态
          </label>

          <span
            class="current-status"
            :class="
              cooperation.status
            "
          >
            ●
            {{ cooperation.status }}
          </span>

        </div>

      </section>


      <section class="progress-card">

        <h2>
          对接进度
        </h2>


        <div class="progress-list">

          <div
            v-for="
              item
              in timeline
            "
            :key="item.name"
            class="progress-item"
            :class="
              item.state
            "
          >

            <div class="progress-marker">

              <span class="point">
                {{
                  item.state ===
                  'done'
                    ? '✓'
                    : item.state ===
                        'rejected'
                      ? '×'
                      : ''
                }}
              </span>

              <span class="line"></span>

            </div>


            <div class="progress-main">

              <div class="progress-name">
                {{ item.name }}
              </div>

              <div
                v-if="item.time"
                class="progress-desc"
              >
                {{ item.time }}
              </div>

            </div>


            <div
              class="progress-operator"
            >
              {{ item.operator }}
            </div>

          </div>

        </div>

      </section>

    </div>


    <section class="description-card">

      <div class="description-row">

        <label>
          合作诉求
        </label>

        <p>
          {{ cooperation.request }}
        </p>

      </div>


      <div class="description-row">

        <label>
          留言
        </label>

        <p>
          {{ cooperation.message }}
        </p>

      </div>

    </section>


    <section class="communication-card">

      <div class="communication-header">

        <h2>
          沟通记录 / 处理记录
        </h2>


        <div class="record-actions">

          <button
            class="add-record"
            @click="
              openCommunication
            "
          >
            ＋ 新增沟通记录
          </button>

          <button
            @click="
              showAllRecords =
                !showAllRecords
            "
          >
            {{
              showAllRecords
                ? '收起记录'
                : '查看更多记录'
            }}
          </button>

        </div>

      </div>


      <div class="communication-list">

        <div
          v-for="
            item
            in visibleCommunications
          "
          :key="item.id"
          class="communication-item"
        >

          <div
            class="record-avatar"
            :class="
              item.role === '系统'
                ? 'orange'
                : item.role ===
                    '对接专员'
                  ? 'green'
                  : 'blue'
            "
          >
            ●
          </div>


          <div class="record-content">

            <div class="record-user">

              <strong>
                {{ item.user }}
              </strong>

              <span>
                （{{
                  item.organization
                }}）
              </span>

              <em>
                {{ item.role }}
              </em>

            </div>


            <div class="record-text">
              {{ item.content }}
            </div>


            <div
              v-if="
                item.attachments.length
              "
              class="attachments"
            >

              📎 附件
              （{{
                item.attachments.length
              }}）

            </div>

          </div>


          <div class="record-time">
            {{ item.time }}
          </div>

        </div>


        <div
          v-if="
            !visibleCommunications.length
          "
          class="empty"
        >
          暂无沟通记录
        </div>

      </div>

    </section>


    <section class="bottom-actions">

      <button
        class="accept-btn"
        :disabled="
          cooperation.status !==
          '待处理'
        "
        @click="accept"
      >
        接受意向
      </button>


      <button
        class="reject-btn"
        :disabled="
          cooperation.status ===
          '已归档'
        "
        @click="reject"
      >
        拒绝意向
      </button>


      <button
        class="confirm-btn"
        :disabled="
          cooperation.status !==
          '已接受'
        "
        @click="
          confirmDocking
        "
      >
        确认对接
      </button>


      <button
        class="complete-btn"
        :disabled="
          cooperation.status !==
          '已确认'
        "
        @click="complete"
      >
        标记完成
      </button>


      <button
        class="archive-btn"
        :disabled="
          cooperation.status !==
          '已完成'
        "
        @click="archive"
      >
        归档
      </button>


      <button
        class="back-btn"
        @click="goBack"
      >
        返回
      </button>

    </section>


    <div
      v-if="
        communicationVisible
      "
      class="modal-mask"
      @click.self="
        communicationVisible =
          false
      "
    >

      <div class="modal">

        <div class="modal-header">

          <h3>
            新增沟通记录
          </h3>

          <button
            @click="
              communicationVisible =
                false
            "
          >
            ×
          </button>

        </div>


        <div class="modal-content">

          <label>
            沟通内容
          </label>

          <textarea
            v-model="
              communicationText
            "
            rows="7"
            placeholder="请输入本次沟通情况、会议安排、双方反馈等内容"
          ></textarea>

        </div>


        <div class="modal-footer">

          <button
            class="back-btn"
            @click="
              communicationVisible =
                false
            "
          >
            取消
          </button>

          <button
            class="accept-btn"
            @click="
              submitCommunication
            "
          >
            保存记录
          </button>

        </div>

      </div>

    </div>

  </div>


  <div
    v-else
    class="not-found"
  >
    未找到该合作意向
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
.communication-card,
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

.type-tag {
  display: inline-flex;
  margin-left: 10px;
  padding: 3px 8px;
  border-radius: 4px;
  font-size: 11px;
}

.type-tag.blue {
  background: #eaf3ff;
  color: #1677ff;
}

.type-tag.green {
  background: #e9faf1;
  color: #20b875;
}

.separator {
  margin: 0 10px;
  color: #c6cdd7 !important;
}

.current-status {
  width: max-content;
}

.current-status.待处理 {
  color: #ee991e;
}

.current-status.已接受,
.current-status.已确认 {
  color: #1677ff;
}

.current-status.已完成 {
  color: #20b875;
}

.current-status.已归档 {
  color: #778395;
}

.current-status.已拒绝 {
  color: #ef5360;
}

.progress-card {
  padding: 21px 25px;
}

.progress-card h2,
.communication-card h2 {
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

.progress-item.current .point {
  border: 5px solid #f5a623;
  box-shadow:
    0 0 0 3px #fff0d4;
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

.progress-item.current .progress-name {
  color: #f09712;
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
}

.progress-item.waiting {
  opacity: 0.5;
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

.communication-card {
  margin-top: 14px;
  padding: 0 22px;
}

.communication-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  min-height: 55px;
}

.record-actions {
  display: flex;
  gap: 10px;
}

.record-actions button {
  height: 32px;
  padding: 0 12px;
  border: 1px solid #9ac6ff;
  border-radius: 4px;
  background: white;
  color: #1677ff;
}

.record-actions .add-record {
  background: #1677ff;
  color: white;
}

.communication-item {
  display: grid;
  grid-template-columns:
    45px
    minmax(0, 1fr)
    170px;
  align-items: start;
  min-height: 68px;
  padding: 13px 10px;
  border-top: 1px solid #edf1f5;
}

.record-avatar {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 35px;
  height: 35px;
  border-radius: 50%;
}

.record-avatar.blue {
  background: #eaf3ff;
  color: #1677ff;
}

.record-avatar.orange {
  background: #fff2de;
  color: #f3a11e;
}

.record-avatar.green {
  background: #e9faf1;
  color: #20b875;
}

.record-user {
  display: flex;
  align-items: center;
  gap: 5px;
  color: #536074;
  font-size: 12px;
}

.record-user strong {
  color: #344154;
  font-size: 13px;
}

.record-user em {
  padding: 2px 6px;
  border-radius: 3px;
  background: #edf4ff;
  color: #1677ff;
  font-size: 10px;
  font-style: normal;
}

.record-text {
  margin-top: 7px;
  color: #697587;
  font-size: 12px;
}

.attachments {
  margin-top: 7px;
  color: #1677ff;
  font-size: 12px;
}

.record-time {
  color: #8995a5;
  font-size: 12px;
  text-align: right;
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

.accept-btn {
  border: 1px solid #1677ff;
  background: #1677ff;
  color: white;
}

.reject-btn {
  border: 1px solid #ef5360;
  background: white;
  color: #ef5360;
}

.confirm-btn {
  border: 1px solid #73acff;
  background: white;
  color: #1677ff;
}

.complete-btn {
  border: 1px solid #55c995;
  background: white;
  color: #20aa70;
}

.archive-btn {
  border: 1px solid #aab4c1;
  background: white;
  color: #687486;
}

.back-btn {
  border: 1px solid #cfd7e1;
  background: white;
  color: #596577;
}

.bottom-actions button:disabled {
  cursor: not-allowed;
  opacity: 0.38;
}

.modal-mask {
  position: fixed;
  z-index: 800;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  background:
    rgba(15, 28, 48, 0.38);
}

.modal {
  width: 580px;
  border-radius: 10px;
  background: white;
  box-shadow:
    0 25px 80px
    rgba(20, 40, 70, 0.2);
}

.modal-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: 62px;
  padding: 0 23px;
  border-bottom: 1px solid #edf1f5;
}

.modal-header h3 {
  margin: 0;
  font-size: 17px;
}

.modal-header button {
  border: 0;
  background: transparent;
  color: #8793a3;
  font-size: 24px;
}

.modal-content {
  padding: 24px;
}

.modal-content label {
  display: block;
  margin-bottom: 9px;
  color: #465366;
  font-size: 13px;
  font-weight: 600;
}

.modal-content textarea {
  width: 100%;
  padding: 12px;
  outline: none;
  border: 1px solid #dce4ee;
  border-radius: 5px;
  resize: vertical;
}

.modal-content textarea:focus {
  border-color: #1677ff;
}

.modal-footer {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
  padding: 17px 24px;
  border-top: 1px solid #edf1f5;
}

.modal-footer button {
  min-width: 95px;
  height: 39px;
  border-radius: 5px;
}

.not-found {
  padding: 100px;
  color: #8793a3;
  text-align: center;
}
</style>