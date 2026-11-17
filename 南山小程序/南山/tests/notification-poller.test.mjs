import assert from 'node:assert/strict'
import { existsSync, readFileSync } from 'node:fs'
import test from 'node:test'

test('notification poller stays in the main package and only refreshes the summary', () => {
  const source = readFileSync(new URL('../utils/notification-poller.js', import.meta.url), 'utf8')
  const app = readFileSync(new URL('../App.vue', import.meta.url), 'utf8')
  assert.match(source, /getNotificationSummary/)
  assert.doesNotMatch(source, /subpackages\/tech-transfer/)
  assert.match(source, /HostBridge\.request/)
  assert.match(source, /NOTIFICATION_POLL_INTERVAL_MS = 30_000/)
  assert.match(source, /inFlight/)
  assert.match(source, /99\+/)
  assert.match(app, /startNotificationPolling\(\)/)
  assert.match(app, /stopNotificationPolling\(\)/)
})

test('main-package notification polling leaves no orphan subpackage API module', () => {
  assert.equal(existsSync(new URL('../subpackages/tech-transfer/api/notifications.js', import.meta.url)), false)
})

test('notification polling is not started for a visitor session and stops after 401', () => {
  const source = readFileSync(new URL('../utils/notification-poller.js', import.meta.url), 'utf8')
  assert.match(source, /function hasNotificationSession\(\)/)
  assert.match(source, /if \(!hasNotificationSession\(\)\)\s*\{[\s\S]*?return/)
  assert.match(source, /clearNotificationSession\(/)
})

test('root host redirects to the business home during load instead of rendering an empty page', () => {
  const source = readFileSync(new URL('../pages/dev-home/dev-home.vue', import.meta.url), 'utf8')
  assert.match(source, /onLoad\(\)\s*\{[\s\S]*?uni\.reLaunch/)
  assert.match(source, /v-else class="dev-redirecting"/)
})

import vm from 'node:vm'
function harness() {
  const storage = new Map(), jobs = new Map(), events = new Map(), calls = []
  let now = 100000, sequence = 0
  const bridge = { getStorage: k => storage.get(k), setStorage: (k,v) => storage.set(k,v),
    request: async o => { calls.push(o); return responder(o) } }
  let responder = () => ({code:0,data:{total:16}})
  const context = vm.createContext({ HostBridge:bridge, console:{warn(){}}, Date:{now:()=>now},
    setTimeout:(fn,ms)=>{jobs.set(++sequence,{fn,ms});return sequence}, clearTimeout:id=>jobs.delete(id),
    setInterval:(fn,ms)=>{jobs.set(++sequence,{fn,ms});return sequence}, clearInterval:id=>jobs.delete(id),
    uni:{getStorageSync:k=>storage.get(k),setStorageSync:(k,v)=>storage.set(k,v),
      $emit:(k,v)=>events.get(k)?.forEach(f=>f(v)), $on:(k,f)=>events.set(k,[...(events.get(k)||[]),f]),
      $off:(k,f)=>events.set(k,(events.get(k)||[]).filter(x=>x!==f))} })
  let source = readFileSync(new URL('../utils/notification-poller.js',import.meta.url),'utf8')
  source = source.replace(/^import .*$/mg,'').replace(/export /g,'')
  vm.runInContext(source+';globalThis.api={startNotificationPolling,stopNotificationPolling,refreshNotificationBadge,subscribeNotificationBadge,formatNotificationBadge,syncNotificationSession,notificationReadSucceeded}',context)
  const login = (id='A',expired=false) => { storage.set('tt_auth_mode','account');storage.set('tt_current_user',{userId:id});storage.set('tt_access_token',id);storage.set('tt_refresh_token','r'+id);storage.set('tt_token_expires_at',expired?0:now+999999) }
  return { ...context.api, storage,jobs,calls,login, respond:f=>responder=f,
    advance:ms=>now+=ms, tick:async()=>{const [id,j]=jobs.entries().next().value;jobs.delete(id);await j.fn()},
    flush:async()=>{for(let i=0;i<30;i++)await Promise.resolve()} }
}
test('singleton 30 second polling, fresh resume, background stop',async()=>{
 const h=harness();h.login();h.startNotificationPolling();h.startNotificationPolling();h.startNotificationPolling();await h.flush()
 assert.equal(h.calls.length,1);assert.equal(h.jobs.size,1);assert.equal([...h.jobs.values()][0].ms,30000)
 h.stopNotificationPolling();assert.equal(h.jobs.size,0);h.startNotificationPolling();await h.flush();assert.equal(h.calls.length,1)
 h.advance(30000);await h.tick();await h.flush();assert.equal(h.calls.length,2)
})
test('refresh lock includes token renewal',async()=>{
 const h=harness();h.login('A',true);let finish
 h.respond(o=>o.path==='/auth/refresh'?new Promise(r=>finish=r):{code:0,data:{total:16}})
 const a=h.refreshNotificationBadge(),b=h.refreshNotificationBadge();await h.flush()
 assert.equal(h.calls.length,1);finish({code:0,data:{accessToken:'new',expiresIn:3600}});await Promise.all([a,b]);assert.equal(h.calls.length,2)
})
test('account switch rejects late summary and old global cache',async()=>{
 const h=harness();h.storage.set('nanshan_notification_badge_count',16);h.login('B');let count
 h.subscribeNotificationBadge(v=>count=v);assert.equal(count,0)
 h.login('A');let finish;h.respond(()=>new Promise(r=>finish=r));const a=h.refreshNotificationBadge();await h.flush()
 h.login('B');h.respond(()=>({code:0,data:{total:2}}));await h.refreshNotificationBadge();assert.equal(count,2)
 finish({code:0,data:{total:16}});await a;assert.equal(count,2)
})
test('network failure preserves badge and backs off; visitor does not request',async()=>{
 const h=harness();h.startNotificationPolling();assert.equal(h.calls.length,0);h.login();let count;h.subscribeNotificationBadge(v=>count=v)
 h.startNotificationPolling();await h.flush();assert.equal(count,16)
 h.respond(()=>{throw new Error('timeout')});h.advance(30000);await h.tick();await h.flush();assert.equal(count,16)
 assert.equal([...h.jobs.values()][0].ms,60000);assert.equal(h.storage.get('tt_auth_mode'),'account')
})
test('global badge belongs only to mine and formats counts',()=>{
 const h=harness();assert.equal(h.formatNotificationBadge(100),'99+');assert.equal(h.formatNotificationBadge(0),'0')
 const s=readFileSync(new URL('../subpackages/tech-transfer/components/app-tabbar.vue',import.meta.url),'utf8')
 assert.match(s,/item.key === 'mine' && notificationBadge > 0/);assert.doesNotMatch(s,/item.key === 'ai' && notificationBadge/)
})

test('logout clears badge immediately and late renewal cannot overwrite next account',async()=>{
 const h=harness();h.login();let count;h.subscribeNotificationBadge(v=>count=v);await h.refreshNotificationBadge();assert.equal(count,16)
 h.storage.set('tt_auth_mode','');h.syncNotificationSession();assert.equal(count,0);assert.equal(h.jobs.size,0)
 h.login('A',true);let finish;h.respond(()=>new Promise(r=>finish=r));const a=h.refreshNotificationBadge();await h.flush()
 h.login('B');h.syncNotificationSession();finish({code:0,data:{accessToken:'stale',expiresIn:3600}});await a
 assert.equal(h.storage.get('tt_access_token'),'B')
})
test('401 renewal denied clears session; transient renewal timeout preserves it',async()=>{
 const h=harness();h.login('A',true);h.respond(()=>{throw new Error('timeout')});await h.refreshNotificationBadge();assert.equal(h.storage.get('tt_auth_mode'),'account')
 h.advance(60000);h.respond(()=>({code:401}));await h.refreshNotificationBadge();assert.equal(h.storage.get('tt_auth_mode'),'')
})

test('successful read immediately publishes 16 to 15 and reconciles once',async()=>{
 const h=harness();h.login();let count;h.subscribeNotificationBadge(n=>count=n);await h.refreshNotificationBadge()
 h.respond(()=>({code:0,data:{total:15}}));const pending=h.notificationReadSucceeded(1)
 assert.equal(count,15);await pending;assert.equal(count,15);assert.equal(h.calls.length,2)
})
test('a queued old-account task cannot refresh the new account token', async () => {
 const h=harness();h.login('A',true)
 const old=h.refreshNotificationBadge()
 h.login('B',true)
 await old
 assert.equal(h.calls.length,0)
 assert.equal(h.storage.get('tt_access_token'),'B')
})
