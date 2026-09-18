import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

test('achievement editor preserves omitted maturity and pricing as null semantics', async () => {
  const source = await readFile(new URL('../views/admin/AchievementView.vue', import.meta.url), 'utf8')

  assert.doesNotMatch(source, /maturityLevel:\s*'02_lab'/)
  assert.doesNotMatch(source, /pricingMode:\s*'negotiable'/)
  assert.match(source, /if \(achievementForm\.maturityLevel\) body\.maturityLevel = achievementForm\.maturityLevel/)
  assert.match(source, /if \(achievementForm\.pricingMode\) body\.pricingMode = achievementForm\.pricingMode/)
  assert.match(source, /formMedia/)
  assert.match(source, /splitIntroFields/)
})
