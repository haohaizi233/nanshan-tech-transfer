<script setup>
import { computed, nextTick, onBeforeUnmount, watch } from 'vue'

import {
  cancelDialog,
  dialogState,
  submitDialog,
} from '../utils/appDialog.js'

const isPrompt = computed(() => dialogState.type === 'prompt')
const isAlert = computed(() => dialogState.type === 'alert')
const confirmClass = computed(() => (
  dialogState.tone === 'danger' ? 'app-dialog-confirm danger' : 'app-dialog-confirm'
))

watch(() => dialogState.visible, (visible) => {
  if (visible) {
    window.addEventListener('keydown', onKeydown)
    nextTick(() => {
      const root = document.querySelector('.app-dialog')
      const target = root?.querySelector('textarea, .app-dialog-confirm')
      target?.focus()
    })
    return
  }
  window.removeEventListener('keydown', onKeydown)
})

onBeforeUnmount(() => {
  window.removeEventListener('keydown', onKeydown)
})

const onKeydown = (event) => {
  if (event.key === 'Escape') {
    event.preventDefault()
    cancelDialog()
  }
}
</script>

<template>
  <Teleport to="body">
    <div
      v-if="dialogState.visible"
      class="app-dialog-mask"
      @click.self="cancelDialog"
    >
      <section
        class="app-dialog"
        role="dialog"
        aria-modal="true"
        :aria-labelledby="'app-dialog-title'"
      >
        <header class="app-dialog-header">
          <h2 id="app-dialog-title">{{ dialogState.title }}</h2>
          <button
            type="button"
            class="app-dialog-close"
            aria-label="关闭"
            @click="cancelDialog"
          >
            ×
          </button>
        </header>

        <div class="app-dialog-body">
          <p v-if="dialogState.message">{{ dialogState.message }}</p>
          <textarea
            v-if="isPrompt"
            v-model="dialogState.inputValue"
            :placeholder="dialogState.inputPlaceholder"
            rows="4"
            @keydown.enter.ctrl="submitDialog"
          />
          <p
            v-if="dialogState.error"
            class="app-dialog-error"
          >
            {{ dialogState.error }}
          </p>
        </div>

        <footer class="app-dialog-footer">
          <button
            v-if="!isAlert"
            type="button"
            class="app-dialog-cancel"
            @click="cancelDialog"
          >
            {{ dialogState.cancelText }}
          </button>
          <button
            type="button"
            :class="confirmClass"
            @click="submitDialog"
          >
            {{ dialogState.confirmText }}
          </button>
        </footer>
      </section>
    </div>
  </Teleport>
</template>

<style scoped>
.app-dialog-mask {
  position: fixed;
  z-index: 2400;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 20px;
  background: rgba(20, 34, 52, 0.42);
}

.app-dialog {
  width: min(460px, 100%);
  overflow: hidden;
  border-radius: 10px;
  background: #fff;
  box-shadow: 0 12px 36px rgba(20, 34, 52, 0.2);
}

.app-dialog-header,
.app-dialog-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 20px;
}

.app-dialog-header {
  border-bottom: 1px solid #edf1f5;
}

.app-dialog-header h2 {
  margin: 0;
  color: #253347;
  font-size: 17px;
  font-weight: 600;
}

.app-dialog-close {
  border: 0;
  background: transparent;
  color: #7c8797;
  font-size: 24px;
  line-height: 1;
}

.app-dialog-body {
  padding: 20px;
}

.app-dialog-body > p:first-child {
  margin: 0;
  color: #3c495c;
  font-size: 14px;
  line-height: 1.7;
  white-space: pre-wrap;
}

.app-dialog-body textarea {
  box-sizing: border-box;
  width: 100%;
  min-height: 96px;
  margin-top: 12px;
  padding: 10px 12px;
  resize: vertical;
  border: 1px solid #d9e1ea;
  border-radius: 6px;
  color: #253347;
  outline: none;
}

.app-dialog-body textarea:focus {
  border-color: #1677ff;
}

.app-dialog-error {
  margin: 10px 0 0;
  color: #ef5360;
  font-size: 13px;
}

.app-dialog-footer {
  justify-content: flex-end;
  gap: 12px;
  border-top: 1px solid #edf1f5;
}

.app-dialog-footer button {
  min-width: 88px;
  height: 36px;
  border-radius: 5px;
}

.app-dialog-cancel {
  border: 1px solid #d9e1ea;
  background: #fff;
  color: #4b5b70;
}

.app-dialog-confirm {
  border: 0;
  background: #1677ff;
  color: #fff;
}

.app-dialog-confirm.danger {
  background: #ef5360;
}
</style>
