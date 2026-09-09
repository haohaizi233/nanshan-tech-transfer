import assert from 'node:assert/strict'
import test from 'node:test'

import {
  getPublicationTabCount,
  getPublishedCount,
  filterPublicationsByTab,
} from '../subpackages/tech-transfer/constants/review-status.js'

const publications = [
  { id: 1, status: 'draft' },
  { id: 2, status: 'pending_review' },
  { id: 3, status: 'rejected' },
  { id: 4, status: 'published' },
  { id: 5, status: 'matched' },
  { id: 6, status: 'cancelled' },
  { id: 7, status: 'closed' },
  { id: 8, status: 'offline' },
]

test('personal-center summary counts only published publications', () => {
  assert.equal(getPublishedCount(publications), 1)
})

test('publication tabs keep drafts in all while grouping terminal states', () => {
  assert.deepEqual(filterPublicationsByTab(publications, 'all').map(item => item.id), [1, 2, 3, 4, 5, 6, 7, 8])
  assert.deepEqual(filterPublicationsByTab(publications, 'pending_review').map(item => item.id), [2])
  assert.deepEqual(filterPublicationsByTab(publications, 'matched').map(item => item.id), [5])
  assert.deepEqual(filterPublicationsByTab(publications, 'offline').map(item => item.id), [7, 8])
  assert.equal(getPublicationTabCount(publications, 'draft'), 0)
})
