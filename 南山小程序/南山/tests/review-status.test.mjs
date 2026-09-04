import assert from 'node:assert/strict'
import test from 'node:test'

import { getPublicationStatus, getPendingReviewCount } from '../common/review-status.js'

test('labels a rejected publication with the administrator reason', () => {
  assert.deepEqual(
    getPublicationStatus({ status: 'rejected', rejectReason: '请补充技术指标' }),
    {
      label: '已驳回',
      cls: 'rejected',
      hint: '管理员已驳回：请补充技术指标',
    },
  )
})

test('labels a pending publication as being reviewed by an administrator', () => {
  assert.deepEqual(
    getPublicationStatus({ status: 'pending_review' }),
    {
      label: '待审核',
      cls: 'pending',
      hint: '管理员审核中，请耐心等待',
    },
  )
})

test('counts only pending publications for the personal-center summary', () => {
  assert.equal(
    getPendingReviewCount([
      { status: 'pending_review' },
      { status: 'published' },
      { status: 'rejected' },
      { status: 'pending_review' },
    ]),
    2,
  )
})
