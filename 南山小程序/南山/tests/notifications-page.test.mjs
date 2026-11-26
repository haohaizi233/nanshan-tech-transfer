import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
const source=readFileSync(new URL('../subpackages/tech-transfer/pages/notifications/notifications.vue',import.meta.url),'utf8')
function harness(request = () => Promise.resolve({list:[],total:0,updated:1})) {
 let calls=[]
 let badgeUpdates=[]
 const script=source.match(/<script>([\s\S]*?)<\/script>/)[1].replace(/^import .*$/mg,'').replace('export default','return')
 const page=new Function('apiRequest','getCurrentUser','subscribeNotificationBadge','refreshNotificationBadge','notificationReadSucceeded',script)(
  (...args)=>{calls.push(args);return request(...args)},()=>({userId:1}),()=>()=>{},()=>{},count=>{badgeUpdates.push(count);return Promise.resolve()})
 const ctx={...page.data(),...page.methods,owner:'1'}
 return {page,ctx,calls,badgeUpdates}
}
test('read actions wait until list loading is finished',async()=>{
 const {ctx,calls}=harness();ctx.loading=true
 await ctx.markRead()
 assert.equal(calls.length,0)
})
test('pagination waits until read actions finish',async()=>{
 const {ctx,calls}=harness();ctx.busy=true
 await ctx.load(false)
 assert.equal(calls.length,0)
})
test('show starts a fresh load even if an old generation was loading',async()=>{
 const {ctx,page,calls}=harness();ctx.loading=true;ctx.busy=true
 page.onShow.call(ctx)
 await Promise.resolve()
 assert.equal(calls.length,1)
 assert.equal(ctx.busy,false)
})

test('opening a notification displays its details and marks only that item read', async () => {
 const {ctx, calls, badgeUpdates} = harness()
 const first = {id: 79, readAt: null, body: '完整审核内容'}
 const second = {id: 80, readAt: null}
 ctx.items = [first, second]

 await ctx.openNotification(first)

 assert.equal(ctx.selectedNotification, first)
 assert.ok(first.readAt)
 assert.equal(second.readAt, null)
 assert.deepEqual(calls, [['POST', '/me/notifications/79/read']])
 assert.deepEqual(badgeUpdates, [1])

 ctx.closeNotification()
 await ctx.openNotification(first)
 assert.equal(ctx.selectedNotification, first)
 assert.equal(calls.length, 1)
})

test('a failed read leaves details visible and allows retry', async () => {
 let attempts = 0
 const {ctx, calls} = harness(async () => {
  if (++attempts === 1) throw new Error('网络断开')
  return {updated: 1}
 })
 const item = {id: 79, readAt: null}
 ctx.items = [item]

 await ctx.openNotification(item)
 assert.equal(ctx.selectedNotification, item)
 assert.equal(item.readAt, null)
 assert.ok(ctx.readError)

 await ctx.markRead(item)
 assert.deepEqual(calls[1], ['POST', '/me/notifications/79/read'])
 assert.ok(item.readAt)
 assert.equal(ctx.readError, '')
})
