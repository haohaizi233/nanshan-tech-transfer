<template>
  <view class="notifications">
    <text class="heading">消息通知 · 未读 {{ unread }}</text>
    <button :disabled="busy || loading" @click="markRead()">全部标记已读</button>
    <text v-if="error">{{ error }}</text>
    <view v-for="item in items" :key="item.id" class="notice" :class="{unread: !item.readAt}">
      <text class="title">{{ item.readAt ? '' : '● ' }}{{ item.title }}</text>
      <text class="meta">{{ categories[item.category] || item.category }} · {{ item.occurredAt }}</text>
      <text v-if="item.body" class="notice-body">{{ item.body }}</text>
      <button v-if="!item.readAt" class="btn-read" :disabled="busy || loading" @click="markRead(item)">标记已读</button>
    </view>
    <text v-if="!items.length && !loading">暂无通知</text>
    <button v-if="items.length < total" :disabled="loading || busy" @click="load(false)">加载更多</button>
  </view>
</template>
<script>
import { apiRequest, getCurrentUser } from '../../api/client.js'
import { refreshNotificationBadge, subscribeNotificationBadge, notificationReadSucceeded } from '../../../../utils/notification-poller.js'
export default {
  data: () => ({ items: [], total: 0, page: 1, unread: 0, busy: false, loading: false, error: '', owner: '', generation: 0,
    categories: {review:'审核',cooperation:'合作',organization:'机构',membership:'会员'} }),
  onShow() {
    this.owner = String(getCurrentUser()?.userId || '')
    this.generation++
    this.loading = false
    this.busy = false
    this.items = []
    if (!this.owner) { this.error='请先登录'; return }
    if (!this.unsubscribe) this.unsubscribe = subscribeNotificationBadge(n => { this.unread=n })
    this.load(true)
    refreshNotificationBadge()
  },
  onHide() { this.generation++; this.loading=false; this.busy=false; this.items=[] },
  onUnload() { this.generation++; if(this.unsubscribe) this.unsubscribe() },
  methods: {
    valid(g) { return g===this.generation && String(getCurrentUser()?.userId || '')===this.owner },
    async load(reset) {
      if(this.loading || this.busy) return
      const g=this.generation, page=reset?1:this.page+1
      this.loading=true;this.error=''
      try {
        const d=await apiRequest('GET','/me/notifications',{page,pageSize:20})
        if(!this.valid(g)) return
        this.items=reset?d.list:[...this.items,...d.list];this.total=d.total;this.page=page
      } catch(e) { if(this.valid(g)) this.error=e.message }
      finally { if(this.valid(g)) this.loading=false }
    },
    async markRead(item) {
      if(this.busy || this.loading) return
      const g=this.generation;this.busy=true;this.error=''
      try {
        const result = await apiRequest('POST',item?'/me/notifications/'+item.id+'/read':'/me/notifications/read-all')
        if(!this.valid(g)) return
        this.items.forEach(n=>{if(!item || n.id===item.id)n.readAt=new Date().toISOString()})
        await notificationReadSucceeded(result.updated)
      } catch(e) {if(this.valid(g))this.error=e.message}
      finally {if(this.valid(g))this.busy=false}
    }
  }
}
</script>
<style scoped>
.notifications { padding: 24rpx; background: #f8fafc; min-height: 100vh; }
.heading { display: block; font-size: 32rpx; font-weight: 600; color: #1e293b; margin-bottom: 24rpx; }
.notice {
  padding: 28rpx;
  margin-top: 20rpx;
  background: #ffffff;
  border-radius: 20rpx;
  border: 1rpx solid #edf1f7;
  border-left: 8rpx solid #cbd5e1;
  box-shadow: 0 6rpx 20rpx rgba(15, 34, 67, 0.04);
}
.notice.unread { border-left-color: #2b73f8; }
.notice text { display: block; margin-bottom: 12rpx; font-size: 24rpx; color: #64748b; }
.notice .title { font-size: 28rpx; font-weight: 600; color: #1e293b; line-height: 1.4; }
.notice .meta { font-size: 22rpx; color: #94a3b8; }
.notice .notice-body {
  font-size: 26rpx;
  color: #4a5568;
  line-height: 1.75;
  text-align: justify;
  text-indent: 2em;
  word-break: break-word;
}
.btn-read {
  display: inline-block;
  margin-top: 8rpx;
  font-size: 24rpx;
  color: #2b73f8;
  background: rgba(43, 115, 248, 0.08);
  border: none;
  border-radius: 24rpx;
  padding: 4rpx 20rpx;
  line-height: 1.6;
}
.btn-read::after { border: none; }
</style>
