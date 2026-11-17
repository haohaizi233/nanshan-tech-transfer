import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { formatDemandBudget, parseDemandBudget } from '../subpackages/tech-transfer/utils/demand-budget.mjs'
import { normalizeCooperationCapacity } from '../subpackages/tech-transfer/utils/cooperation-capacity.mjs'
import { formatDemandBudget as adminFormat } from '../../../nanshan-frontend/src/utils/demand-budget.mjs'

const cases = [
 [0.0000001,null,true,'0.0000001 万元以上（可议）'],
 [null,100,true,'100 万元以内（可议）'], [null,100,false,'100 万元以内'],
 [50,100,true,'50–100 万元（可议）'], [50,100,false,'50–100 万元'],
 [50,null,true,'50 万元以上（可议）'], [50,null,false,'50 万元以上'],
 [null,null,true,'面议'], [null,null,false,'未提供预算'],
 [80,80,false,'80 万元'], [80,80,true,'80 万元（可议）'],
 [0,100,false,'0–100 万元'], [0,0,false,'0 万元'], [0.5,1.25,true,'0.5–1.25 万元（可议）'],
]
for (const [min,max,negotiable,expected] of cases) {
 const data = {budgetMinWan:min,budgetMaxWan:max,budgetNegotiable:negotiable}
 test(`format and roundtrip ${expected}`, () => {
  assert.equal(formatDemandBudget(data), expected)
  assert.equal(adminFormat(data), expected)
  if (min === null && max === null && !negotiable) {
   assert.throws(() => parseDemandBudget(expected)); return
  }
  const restored = parseDemandBudget(expected)
  assert.equal(restored.budgetMinWan ?? null,min)
  assert.equal(restored.budgetMaxWan ?? null,max)
  assert.equal(restored.budgetNegotiable ?? false,negotiable)
 })
}
for (const text of ['100万以内','100 万元以内','100万元以内（可议）','100万以内，面议']) {
 test(`parse ${text}`, () => assert.deepEqual(parseDemandBudget(text), {budgetMaxWan:100,...(/[可面]议/.test(text)?{budgetNegotiable:true}:{})}))
}
for (const text of ['80-120万','80–120 万','80~120万元','80至120万元','80-120万元（可议）']) {
 test(`parse ${text}`, () => assert.deepEqual(parseDemandBudget(text), {budgetMinWan:80,budgetMaxWan:120,...(text.includes('可议')?{budgetNegotiable:true}:{})}))
}
test('lower bound and negotiation only', () => {
 assert.deepEqual(parseDemandBudget('50万元以上'),{budgetMinWan:50})
 assert.deepEqual(parseDemandBudget('50万以上（可议）'),{budgetMinWan:50,budgetNegotiable:true})
 for (const text of ['面议','可议']) assert.deepEqual(parseDemandBudget(text),{budgetNegotiable:true})
 assert.deepEqual(parseDemandBudget('  '),{})
})
test('invalid input never silently loses money', () => {
 for (const text of ['abc','100元以内','100万左右面议','120-80万','-1万','Infinity','NaN','未提供预算','，','100万以内100万','面议100foo']) assert.throws(() => parseDemandBudget(text), text)
})
test('historical invalid values are safe', () => {
 for (const value of [NaN,Infinity,-1,{},true,'abc','']) {
  assert.equal(formatDemandBudget({budgetMinWan:value,budgetMaxWan:value}),'未提供预算')
 }
 assert.equal(formatDemandBudget({budgetMaxWan:'100',budgetNegotiable:true}),'100 万元以内（可议）')
 assert.equal(formatDemandBudget({budgetMinWan:120,budgetMaxWan:80}),'预算数据异常')
})
test('all four pages use the same card adapter', async () => {
 const api = readFileSync(new URL('../subpackages/tech-transfer/api/demand.js',import.meta.url),'utf8')
 const body = api.slice(api.indexOf('export function toDemandCard')).replace('export function','function')
 // Evaluate the actual adapter with only its external dependencies supplied.
 const adapter = new Function('formatDemandBudget','getPublicationStatus',body+'; return toDemandCard')(formatDemandBudget,()=>({}))
 for (const page of ['home','search','dock-detail','my-list']) {
  const source = readFileSync(new URL(`../subpackages/tech-transfer/pages/${page}/${page}.vue`,import.meta.url),'utf8')
  assert.match(source,/toDemandCard\(/)
  assert.equal(adapter({id:837,budgetMaxWan:100,budgetNegotiable:true}).budget,'100 万元以内（可议）')
 }
})

test('form payload keeps money and validate blocks invalid text before preview/submit', () => {
 const source = readFileSync(new URL('../subpackages/tech-transfer/pages/post-demand/post-demand.vue',import.meta.url),'utf8')
 const payloadBody = source.slice(source.indexOf('function buildPayload'),source.indexOf('export default'))
 const build = new Function('parseDemandBudget','normalizeCooperationCapacity',payloadBody+';return buildPayload')(parseDemandBudget,normalizeCooperationCapacity)
 const result = build({title:'test',budget:'100万以内，面议'})
 assert.equal(result.budgetMaxWan,100)
 assert.equal(result.budgetNegotiable,true)
 const validation = source.slice(source.indexOf('validate(data) {')+'validate(data) {'.length, source.indexOf('onPreview()'))
 const fn = new Function('parseDemandBudget','validatePhone','validateEmail','normalizeCooperationCapacity','data',validation.slice(0,validation.lastIndexOf('},')))
 let error
 const context = {showPreviewError(message) {error=message;return false}}
 const data = {title:'t',company:'c',location:'l',demandDesc:'d',contactName:'n',phone:'13800138000'}
 for (const budget of ['100万左右面议','120-80万']) {
  assert.equal(fn.call(context,parseDemandBudget,()=>({ok:true}),()=>({ok:true}),normalizeCooperationCapacity,{...data,budget}),false)
  assert.ok(error)
 }
 assert.equal(fn.call(context,parseDemandBudget,()=>({ok:true}),()=>({ok:true}),normalizeCooperationCapacity,{...data,budget:'100万以内，面议'}),true)
})
