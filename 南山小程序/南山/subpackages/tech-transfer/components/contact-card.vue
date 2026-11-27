<template>
  <view v-if="rows.length" :class="variant === 'card' ? 'cc-section-card' : 'section cc-section'">
    <view class="cc-head">
      <text :class="variant === 'card' ? 'cc-title-card' : 'cc-title'">{{ title }}</text>
    </view>
    <view :class="variant === 'card' ? 'cc-list-card' : 'cc-list'">
      <view
        v-for="row in rows"
        :key="row.key"
        :class="variant === 'card' ? 'cc-row-card' : 'cc-row'"
        @click="onRowClick(row)"
      >
        <text :class="variant === 'card' ? 'cc-label-card' : 'cc-label'">{{ row.label }}</text>
        <text
          :class="[
            variant === 'card' ? 'cc-value-card' : 'cc-value',
            { 'cc-link': interactive && row.action },
          ]"
        >{{ row.value }}</text>
      </view>
    </view>
    <text v-if="normalizedTip" class="cc-tip">{{ normalizedTip }}</text>
  </view>
</template>

<script>
import { buildContactRows } from '../utils/contact-card.mjs'

export default {
  name: 'ContactCard',
  emits: ['call', 'copy'],
  options: {
    virtualHost: true,
    styleIsolation: 'shared',
  },
  props: {
    title: {
      type: String,
      default: '联系方式',
    },
    counterpartName: {
      type: String,
      default: '',
    },
    contact: {
      type: Object,
      default: () => ({}),
    },
    tip: {
      type: String,
      default: '',
    },
    interactive: {
      type: Boolean,
      default: false,
    },
    separateTitle: {
      type: Boolean,
      default: false,
    },
    variant: {
      type: String,
      default: 'section',
    },
  },
  computed: {
    rows() {
      return buildContactRows(this.contact, {
        counterpartName: this.counterpartName,
        separateTitle: this.separateTitle,
      })
    },
    normalizedTip() {
      return this.tip == null ? '' : String(this.tip).trim()
    },
  },
  methods: {
    onRowClick(row) {
      if (!this.interactive || !row || !row.action) return
      if (row.action === 'call') {
        this.$emit('call', row.value)
        return
      }
      if (row.action === 'copy') {
        this.$emit('copy', { value: row.value, label: row.copyLabel })
      }
    },
  },
}
</script>

<style scoped>
.cc-head {
  display: flex;
  flex-direction: row;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 20rpx;
}

.cc-title {
  font-size: 36rpx;
  color: #1a1a1a;
  font-weight: 600;
}

.cc-list {
  background-color: #f7f9fc;
  border-radius: 12rpx;
  padding: 8rpx 20rpx;
}

.cc-row {
  display: flex;
  flex-direction: row;
  align-items: center;
  padding: 22rpx 0;
  border-bottom: 1rpx solid #e8ecf2;
}

.cc-row:last-child {
  border-bottom: none;
}

.cc-label {
  width: 120rpx;
  font-size: 28rpx;
  color: #555555;
  flex-shrink: 0;
}

.cc-value {
  flex: 1;
  font-size: 28rpx;
  color: #222222;
}

.cc-link {
  color: #2b73f8;
}

.cc-tip {
  display: block;
  margin-top: 20rpx;
  font-size: 24rpx;
  color: #999999;
  line-height: 1.5;
}

.cc-section-card {
  background: #fff;
  border-radius: 16rpx;
  padding: 32rpx;
  margin-bottom: 24rpx;
}

.cc-title-card {
  display: block;
  font-size: 30rpx;
  font-weight: 600;
  color: #1a1a1a;
}

.cc-row-card {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16rpx 0;
  border-bottom: 1rpx solid #f0f0f0;
}

.cc-row-card:last-child {
  border-bottom: none;
}

.cc-label-card {
  font-size: 28rpx;
  color: #999;
}

.cc-value-card {
  font-size: 28rpx;
  color: #333;
}
</style>
