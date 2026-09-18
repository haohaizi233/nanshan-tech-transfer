import assert from 'node:assert/strict'
import test from 'node:test'

import { extractAchievementFields, mergeExtractedFields } from './extractAchievementFields.js'

test('extracts contact, website and inventors from a dumped intro blob', () => {
  const extracted = extractAchievementFields(`面向工业缺陷识别。
联系邮箱
ttc@sustech.edu.cn
个人网站
https://ttc.sustech.edu.cn
联系人：李老师
电话：13900001111
发明人：张三，李四
成熟度：实验室验证`)
  assert.equal(extracted.techIntro, '面向工业缺陷识别。')
  assert.equal(extracted.contactEmail, 'ttc@sustech.edu.cn')
  assert.equal(extracted.contactName, '李老师')
  assert.equal(extracted.contactPhone, '13900001111')
  assert.equal(extracted.maturityLevel, '02_lab')
  assert.equal(extracted.inventorNames, '张三，李四')
  assert.equal(extracted.links[0].url, 'https://ttc.sustech.edu.cn')
})

test('merge keeps existing filled fields and replaces the dumped intro', () => {
  const extracted = extractAchievementFields('简介正文\n邮箱：a@b.com')
  const merged = mergeExtractedFields({
    techIntro: '简介正文\n邮箱：a@b.com',
    contactEmail: '',
    contactName: '已有联系人',
    applicationFieldsText: '',
    inventorNamesText: '',
  }, extracted)
  assert.equal(merged.techIntro, '简介正文')
  assert.equal(merged.contactEmail, 'a@b.com')
  assert.equal(merged.contactName, '已有联系人')
})
