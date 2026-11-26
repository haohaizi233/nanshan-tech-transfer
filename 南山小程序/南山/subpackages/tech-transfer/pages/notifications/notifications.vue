<template>
  <view class="notifications">
    <view class="inbox-toolbar">
      <text class="inbox-count">{{ unread > 0 ? unread + ' 条未读' : '暂无未读' }}</text>
      <button v-if="unread > 0" class="text-action" :disabled="busy || loading" @click="markRead()">全部已读</button>
    </view>

    <view v-if="error" class="inbox-state" role="alert">
      <text>{{ error }}</text>
      <button v-if="owner" class="text-action" :disabled="busy || loading" @click="load(!items.length)">重试</button>
    </view>
    <view v-else-if="!items.length" class="inbox-state">
      <text>{{ loading ? '正在加载通知…' : '暂无通知' }}</text>
    </view>

    <view v-if="items.length" class="inbox-list">
      <button
        v-for="item in items"
        :key="item.id"
        class="notice-card"
        :class="{ 'notice-unread': !item.readAt }"
        :disabled="busy || loading || !owner"
        :aria-label="(item.readAt ? '已读，' : '未读，') + item.title + '，查看详情'"
        @click="openNotification(item)"
      >
        <view class="notice-content">
          <view class="notice-meta">
            <text class="notice-category" :class="'category-' + item.category">{{ categories[item.category] || '通知' }}</text>
            <text class="notice-date">{{ item.occurredAt }}</text>
          </view>
          <text class="notice-title">{{ item.title }}</text>
          <text v-if="item.body" class="notice-preview">{{ item.body }}</text>
        </view>
        <view class="notice-trailing" aria-hidden="true">
          <view v-if="!item.readAt" class="unread-dot" />
          <view class="notice-chevron" />
        </view>
      </button>
    </view>

    <button v-if="items.length < total && !error" class="load-more text-action" :disabled="loading || busy" @click="load(false)">
      {{ loading ? '正在加载…' : '加载更多' }}
    </button>

    <view v-if="selectedNotification" class="detail-backdrop" @click="closeNotification">
      <view class="detail-sheet" role="dialog" aria-modal="true" aria-labelledby="notice-detail-title" @click.stop @keydown.esc.stop="closeNotification">
        <view class="detail-top">
          <text class="notice-category" :class="'category-' + selectedNotification.category">{{ categories[selectedNotification.category] || '通知' }}</text>
          <button ref="closeDetailButton" class="detail-close" aria-label="关闭通知详情" @click="closeNotification">×</button>
        </view>
        <text id="notice-detail-title" class="detail-title">{{ selectedNotification.title }}</text>
        <text class="detail-date">{{ selectedNotification.occurredAt }}</text>
        <scroll-view v-if="selectedNotification.body" scroll-y class="detail-text">
          <text class="detail-body">{{ selectedNotification.body }}</text>
        </scroll-view>
        <view v-if="readError" class="read-error" role="alert">
          <text>{{ readError }}</text>
          <button class="text-action" :disabled="busy" @click="markRead(selectedNotification)">重试标记已读</button>
        </view>
      </view>
    </view>
  </view>
</template>

<script>
import { apiRequest, getCurrentUser } from '../../api/client.js'
import { refreshNotificationBadge, subscribeNotificationBadge, notificationReadSucceeded } from '../../../../utils/notification-poller.js'

export default {
  data: () => ({
    items: [],
    total: 0,
    page: 1,
    unread: 0,
    busy: false,
    loading: false,
    error: '',
    readError: '',
    selectedNotification: null,
    owner: '',
    generation: 0,
    unsubscribe: null,
    categories: { review: '审核', cooperation: '合作', organization: '机构', membership: '成员申请' }
  }),
  onShow() {
    this.resetInbox()
    this.owner = String(getCurrentUser()?.userId || '')
    if (!this.owner) {
      this.error = '请先登录'
      return
    }
    if (!this.unsubscribe) this.unsubscribe = subscribeNotificationBadge(count => { this.unread = count })
    this.load(true)
    refreshNotificationBadge()
  },
  onHide() {
    this.resetInbox()
  },
  onUnload() {
    this.resetInbox()
  },
  methods: {
    resetInbox() {
      this.generation += 1
      this.closeNotification()
      this.loading = false
      this.busy = false
      this.items = []
      this.page = 1
      this.total = 0
      this.unread = 0
      this.error = ''
      if (this.unsubscribe) {
        this.unsubscribe()
        this.unsubscribe = null
      }
    },
    valid(generation) {
      return generation === this.generation && String(getCurrentUser()?.userId || '') === this.owner
    },
    async load(reset) {
      if (this.loading || this.busy || !this.owner) return
      const generation = this.generation
      const page = reset ? 1 : this.page + 1
      this.loading = true
      this.error = ''
      try {
        const data = await apiRequest('GET', '/me/notifications', { page, pageSize: 20 })
        if (!this.valid(generation)) return
        this.items = reset ? data.list : [...this.items, ...data.list]
        this.total = data.total
        this.page = page
      } catch (error) {
        if (this.valid(generation)) this.error = error.message || '通知加载失败'
      } finally {
        if (this.valid(generation)) this.loading = false
      }
    },
    openNotification(item) {
      if (!this.owner || this.busy || this.loading) return
      this.selectedNotification = item
      this.readError = ''
      // #ifdef H5
      this.$nextTick?.(() => this.$refs.closeDetailButton?.$el?.focus())
      // #endif
      if (!item.readAt) return this.markRead(item)
    },
    closeNotification() {
      this.selectedNotification = null
      this.readError = ''
    },
    async markRead(item) {
      if (this.busy || this.loading || !this.owner || item?.readAt) return
      const generation = this.generation
      this.busy = true
      this.readError = ''
      if (!item) this.error = ''
      let result
      try {
        const path = item ? '/me/notifications/' + item.id + '/read' : '/me/notifications/read-all'
        result = await apiRequest('POST', path)
        if (!this.valid(generation)) return
        const timestamp = new Date().toISOString()
        this.items.forEach(notice => {
          if (!notice.readAt && (!item || notice.id === item.id)) notice.readAt = timestamp
        })
      } catch {
        if (!this.valid(generation)) return
        if (item) {
          if (this.selectedNotification?.id === item.id) this.readError = '未能标记已读，请重试。'
        } else {
          this.error = '未能标记全部已读，请重试。'
        }
      } finally {
        if (this.valid(generation)) this.busy = false
      }
      if (result) await notificationReadSucceeded(result.updated)
    }
  }
}
</script>

<style scoped>
.notifications {
  min-height: 100vh;
  box-sizing: border-box;
  padding: 18rpx 24rpx calc(36rpx + env(safe-area-inset-bottom));
  background: #f4f6fa;
  color: #172033;
}
.inbox-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  min-height: 68rpx;
  margin-bottom: 10rpx;
  padding: 0 6rpx;
}
.inbox-count { color: #52617a; font-size: 26rpx; font-weight: 600; }
.text-action {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-height: 64rpx;
  margin: 0;
  padding: 0 14rpx;
  background: transparent;
  color: #205bd2;
  font-size: 25rpx;
  line-height: 1.4;
}
.notice-card::after, .text-action::after, .detail-close::after { border: 0; }
.text-action[disabled] { color: #77849a; background: transparent; }
.inbox-list { display: flex; flex-direction: column; gap: 14rpx; }
.notice-card {
  position: relative;
  display: flex;
  align-items: center;
  gap: 20rpx;
  width: 100%;
  box-sizing: border-box;
  margin: 0;
  padding: 22rpx 24rpx;
  border: 1rpx solid #e2e8f1;
  border-radius: 20rpx;
  background: #fff;
  color: #172033;
  text-align: left;
  line-height: 1.45;
}
.notice-card.notice-unread { background: #f9fbff; border-color: #cbdcff; }
.notice-card.button-hover { background: #edf4ff; }
.notice-card[disabled] { color: #172033; }
.notice-content { flex: 1; min-width: 0; }
.notice-meta { display: flex; flex-wrap: wrap; align-items: center; gap: 8rpx 14rpx; margin-bottom: 10rpx; }
.notice-category {
  display: inline-block;
  padding: 4rpx 12rpx;
  border-radius: 8rpx;
  background: #edf1f7;
  color: #475569;
  font-size: 22rpx;
  font-weight: 600;
  line-height: 1.4;
}
.category-review { background: #e8f0ff; color: #2454ac; }
.category-cooperation { background: #eeeafb; color: #6041a6; }
.category-organization { background: #e1f3ee; color: #176c58; }
.category-membership { background: #fcf0da; color: #895317; }
.notice-date, .detail-date { color: #607088; font-size: 22rpx; }
.notice-title, .notice-preview { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.notice-title { font-size: 29rpx; font-weight: 600; }
.notice-unread .notice-title { font-weight: 700; }
.notice-preview { margin-top: 8rpx; color: #52617a; font-size: 25rpx; }
.notice-trailing { display: flex; align-items: center; gap: 14rpx; }
.unread-dot { width: 12rpx; height: 12rpx; border-radius: 50%; background: #2968e8; }
.notice-chevron { width: 12rpx; height: 12rpx; border: solid #64748b; border-width: 2rpx 2rpx 0 0; transform: rotate(45deg); }
.inbox-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  min-height: 180rpx;
  margin-bottom: 14rpx;
  border: 1rpx solid #e2e8f1;
  border-radius: 20rpx;
  background: #fff;
  color: #52617a;
  font-size: 27rpx;
}
.load-more { display: flex; margin: 16rpx auto 0; }
.detail-backdrop {
  position: fixed;
  z-index: 20;
  inset: 0;
  display: flex;
  align-items: flex-end;
  justify-content: center;
  background: rgba(17, 26, 44, .45);
}
.detail-sheet {
  width: 100%;
  max-width: 650px;
  box-sizing: border-box;
  padding: 22rpx 30rpx calc(36rpx + env(safe-area-inset-bottom));
  border-radius: 30rpx 30rpx 0 0;
  background: #fff;
}
.detail-top { display: flex; align-items: center; justify-content: space-between; margin-bottom: 12rpx; }
.detail-close {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 68rpx;
  height: 68rpx;
  margin: 0;
  padding: 0;
  border-radius: 50%;
  background: #f0f3f8;
  color: #43536c;
  font-size: 40rpx;
  line-height: 1;
}
.detail-title { display: block; font-size: 36rpx; font-weight: 700; line-height: 1.4; overflow-wrap: anywhere; }
.detail-date { display: block; margin-top: 10rpx; }
.detail-text { max-height: 45vh; margin-top: 24rpx; padding-top: 20rpx; border-top: 1rpx solid #e2e8f1; }
.detail-body { color: #334155; font-size: 29rpx; line-height: 1.75; white-space: pre-wrap; overflow-wrap: anywhere; }
.read-error { display: flex; flex-wrap: wrap; align-items: center; margin-top: 20rpx; color: #a62c30; font-size: 25rpx; }
</style>
