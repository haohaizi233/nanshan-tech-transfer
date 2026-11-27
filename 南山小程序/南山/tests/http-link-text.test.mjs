import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'
import {
  hasHttpLink,
  parseStandaloneHttpLink,
  splitHttpLinkText,
} from '../subpackages/tech-transfer/utils/http-link-text.mjs'

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

test('parseStandaloneHttpLink extracts labeled and bare link lines without stretching prose', () => {
  assert.deepEqual(
    parseStandaloneHttpLink('个人网站：https://ias.szu.edu.cn/info/1108/3197.htm'),
    {
      label: '个人网站',
      url: 'https://ias.szu.edu.cn/info/1108/3197.htm',
      text: 'https://ias.szu.edu.cn/info/1108/3197.htm',
    },
  )
  assert.deepEqual(
    parseStandaloneHttpLink('https://example.org/demo'),
    {
      label: '',
      url: 'https://example.org/demo',
      text: 'https://example.org/demo',
    },
  )
  assert.equal(parseStandaloneHttpLink('详见 https://example.org/demo，欢迎联系'), null)
  assert.equal(parseStandaloneHttpLink('个人网站：https://a.example.com 与 https://b.example.com'), null)
  assert.equal(hasHttpLink('个人网站：https://ias.szu.edu.cn/info/1108/3197.htm'), true)
  assert.equal(hasHttpLink('纯文本段落'), false)
})

test('formatted-text and http-link-text render standalone link cards left-aligned without justify stretching', () => {
  const formatted = readFileSync(
    new URL('../subpackages/tech-transfer/components/formatted-text.vue', import.meta.url),
    'utf8',
  )
  const linkText = readFileSync(
    new URL('../subpackages/tech-transfer/components/http-link-text.vue', import.meta.url),
    'utf8',
  )
  assert.match(formatted, /ft-has-link/)
  assert.match(formatted, /ft-link-block/)
  assert.match(formatted, /\.ft-paragraph\.ft-has-link[\s\S]*?text-align:\s*left/)
  assert.match(linkText, /http-link-card/)
})
