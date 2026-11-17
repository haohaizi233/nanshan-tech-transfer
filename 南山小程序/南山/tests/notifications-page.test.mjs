import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
const source=readFileSync(new URL('../subpackages/tech-transfer/pages/notifications/notifications.vue',import.meta.url),'utf8')
function harness() {
 let calls=[]
 const script=source.match(/<script>([\s\S]*?)<\/script>/)[1].replace(/^import .*$/mg,'').replace('export default','return')
 const page=new Function('apiRequest','getCurrentUser','subscribeNotificationBadge','refreshNotificationBadge','notificationReadSucceeded',script)(
  (...args)=>{calls.push(args);return Promise.resolve({list:[],total:0,updated:1})},()=>({userId:1}),()=>()=>{},()=>{},()=>Promise.resolve())
 const ctx={...page.data(),...page.methods,owner:'1'}
 return {page,ctx,calls}
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
