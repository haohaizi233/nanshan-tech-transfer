import assert from 'node:assert/strict'
import test from 'node:test'

import {
  getPatentDetailNavigationTarget,
  PATENT_DETAIL_NAV_ITEMS,
  resolvePatentDetailSection,
} from '../subpackages/tech-transfer/utils/patent-detail-navigation.mjs'

test('patent detail navigation keeps the three reader sections in display order', () => {
  assert.deepEqual(
    PATENT_DETAIL_NAV_ITEMS.map(item => ({ key: item.key, label: item.label })),
    [
      { key: 'abstract', label: '摘要' },
      { key: 'claims', label: '权利要求' },
      { key: 'description', label: '说明书' },
    ],
  )
})

test('patent detail navigation resolves the selected reader section', () => {
  assert.equal(resolvePatentDetailSection('claims'), 'claims')
  assert.equal(resolvePatentDetailSection('unknown'), 'abstract')
  assert.equal(resolvePatentDetailSection(''), 'abstract')
})

test('description navigation requests expansion before scrolling to its section', () => {
  assert.deepEqual(getPatentDetailNavigationTarget('description'), {
    section: 'description',
    expandDescription: true,
  })
  assert.deepEqual(getPatentDetailNavigationTarget('claims'), {
    section: 'claims',
    expandDescription: false,
  })
})
