import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'
import { splitHttpLinkText } from '../subpackages/tech-transfer/utils/http-link-text.mjs'

test('正文链接提供独立复制按钮并复制完整网址', () => {
  const component = readFileSync(new URL('../subpackages/tech-transfer/components/http-link-text.vue', import.meta.url), 'utf8')
  assert.match(component, /<button[^>]+@click\.stop="copyLink\(segment.url\)"[^>]*>复制<\/button>/)
  assert.match(component, /navigator\.clipboard\.writeText\(url\)/)
  assert.match(component, /uni\.setClipboardData\(\{\s*data: url/)
})

test('成果正文识别个人网站和行内链接，保留原文标点与网址参数', () => {
  const website = 'https://cmse.szu.edu.cn/szdw1/jsml/gfzclygc/j_s/csg.htm'
  const resource = 'https://example.org/wiki/Topic_(science)?x=a%26b&y=2#intro'
  assert.deepEqual(splitHttpLinkText(`个人网站：${website}。资料 (${resource})，邮箱 csg@szu.edu.cn`), [
    { text: '个人网站：' },
    { text: website, url: website },
    { text: '。资料 (' },
    { text: resource, url: resource },
    { text: ')，邮箱 csg@szu.edu.cn' },
  ])
  assert.deepEqual(splitHttpLinkText('https:// 及 javascript:alert(1)'), [
    { text: 'https:// 及 javascript:alert(1)' },
  ])
})
