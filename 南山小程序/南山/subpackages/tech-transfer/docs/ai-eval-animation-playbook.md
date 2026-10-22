# AI 评估前端动画最佳实践 Playbook（uni-app H5 适配）

> 目标页面：`subpackages/tech-transfer/pages/ai-eval-detail/ai-eval-detail.vue`（SSE 流式打字机 + 轮询回退）
> 配套可运行 demo：`docs/ai-eval-animation-demo.html`（浏览器直接打开，全部动画可交互预览）

---

## 0. 设计原则与 uni-app H5 约束（先读这个）

### 性能铁律
1. **只动 `transform` / `opacity`**（走 GPU 合成层）。禁止动画 `width/height/top/left/margin/padding`（触发 layout/reflow）。进度条用 `transform: scaleX()`，不要动 `width`。
2. **`box-shadow` / `filter: blur()` / `border-radius` 的动画开销大**，尤其移动端。要阴影变化就过渡 `opacity`（阴影写在伪元素上）。
3. **动画时长分级**：微反馈 80–150ms；元素进入 200–350ms；数据增长（count-up / 条形）600–1200ms；装饰性循环（shimmer、呼吸灯）1.2–1.8s。**超过 400ms 的转场会让用户觉得"慢"**。
4. **缓动函数**（统一这套，视觉一致）：
   - 进入/生长：`cubic-bezier(0.22, 1, 0.36, 1)`（easeOutQuart，快出缓收）
   - 离开/消失：`cubic-bezier(0.4, 0, 1, 1)`（easeIn）
   - 弹性/回弹（chips、徽章、数字到达）：`cubic-bezier(0.34, 1.56, 0.64, 1)`（overshoot）
5. **流式渲染是高频更新**（content_delta 每秒可 10+ 次）：每帧 DOM 更新尽量只增不改（append 块，不重排已有块），不要在 delta 回调里跑 JS 动画 —— 动画全部交给 CSS（增量节点自带 enter 动画），JS 只 push 数据。

### uni-app 特有注意事项
- 本页 `<style>` **无 scoped**，且 H5 下所有页面 CSS 都会注入同一文档 → **keyframes 和关键类名必须加前缀**（本项目已有 `aiSpin`、`patent-spin`），统一用 `aie-` 前缀（ai-eval）。
- **rpx 动画没问题**：rpx 编译为 px，`translateY(24rpx)` 正常。但 `@media (prefers-reduced-motion)` 块里也用 rpx 即可。
- **`<transition>`（Vue3）在 H5 可用**；小程序端支持有限。SSE 打字机本身 H5-only，但轮询回退路径会走到小程序 → **enter 动画的初始状态默认 opacity: 1**（动画只在 `animation` 应用时生效），过渡不生效时内容直接可见，不会白屏。
- **`uni.createCanvasContext`（旧 canvas API）逐帧 `draw()` 在 H5 是真 canvas 绘制，30fps 没问题**；小程序端每帧 draw 开销大 → 雷达动画帧数压到 30 帧 / 800ms，并提供"无动画直接终态"的降级（见 §3）。
- **移动端没有 hover** → 触感反馈用 `:active`；桌面预览加 `@media (hover: hover)` 补 hover。
- **数字抖动**：计时器/分数变化会引起字宽跳动 → `font-variant-numeric: tabular-nums`（H5 生效）。
- **uni-button 默认样式**：`button::after { border: none; }`，`margin: 0`、显式 `height`（已有先例，见技能）。
- **可访问性**：统一在样式尾部放一个 `@media (prefers-reduced-motion: reduce)` 降级块，把循环动画换成静止/纯淡入。

---

## 1. 流式文字动画（打字机升级）

### 1.1 词级渐现（推荐，ChatGPT 式）

**原理**：不对整个 `<text>` 反复做过渡（每次 delta 全量更新会不断重触发动画，闪烁）。而是**增量块渲染**：每次 `content_delta` 把新文本 push 成一个"块"，`v-for` 渲染，**新块自带一次性 enter 动画**（fade + 上移 6rpx），旧块不再动。块多了（> 80）把最老的合并成纯文本段，控制 DOM 数量。

```html
<!-- 流式区：块级渲染，每块自带渐现 -->
<view v-if="showStreamPreview" class="section stream-section">
  <view class="section-head">
    <text class="section-title">AI 评价报告</text>
    <AiGeneratedMark mode="badge" />
  </view>
  <!-- 段标题：出现时蓝色竖条从 0 拉伸 + 文字渐现 -->
  <view v-for="(sec, sIndex) in streamPreview.sections" :key="'stream-' + sIndex" class="report-sec">
    <text v-if="sec.heading" class="report-sec__heading aie-fade-up">{{ sec.heading }}</text>
    <!-- 内容按增量块渲染 -->
    <view class="report-sec__content">
      <text v-for="(b, bi) in blocksFor(sIndex)" :key="b.id" :class="b.stable ? '' : 'aie-word-in'">{{ b.text }}</text>
      <text v-if="sIndex === streamPreview.sections.length - 1" class="aie-caret">▍</text>
    </view>
  </view>
</view>
```

```js
// data() 增加：
streamBlocks: [],       // [{ id, text, stable }]，按段落顺序 append
_seqId: 0,

methods: {
  // onContentDelta / onSnapshot 里改为喂给 appendStreamText
  appendStreamText(delta) {
    if (!delta) return
    // 按「句读 + 长度」切块：每 6~14 字一块，块太碎动画会晕、太整没效果
    const chunks = String(delta).match(/[\s\S]{1,12}/g) || []
    for (const text of chunks) {
      this.streamBlocks.push({ id: ++this._seqId, text, stable: false })
    }
    // 80 块以上把最老的 40 块合并为一个稳定块，防止 DOM 爆炸
    if (this.streamBlocks.length > 80) {
      const merged = this.streamBlocks.slice(0, 40).map((b) => b.text).join('')
      this.streamBlocks.splice(0, 40, { id: ++this._seqId, text: merged, stable: true })
    }
  },
  // streamText 仍维护（供 extractStreamData 解析结构），streamBlocks 只管视觉
}
```

```css
/* 词级渐现：fade + 微上移 + 轻微模糊消散（blur 只在一次 220ms 动画里，可接受） */
@keyframes aieWordIn {
  from { opacity: 0; transform: translateY(6rpx); }
  to   { opacity: 1; transform: translateY(0); }
}
.aie-word-in {
  animation: aieWordIn 220ms cubic-bezier(0.22, 1, 0.36, 1) both;
}

/* 段落标题渐现 + 竖条拉伸 */
@keyframes aieFadeUp {
  from { opacity: 0; transform: translateY(10rpx); }
  to   { opacity: 1; transform: translateY(0); }
}
.aie-fade-up { animation: aieFadeUp 280ms cubic-bezier(0.22, 1, 0.36, 1) both; }

.report-sec__heading {
  display: flex; align-items: center;
}
.report-sec__heading::before {
  content: ''; width: 6rpx; height: 28rpx; background: #2b73f8;
  border-radius: 3rpx; margin-right: 12rpx; flex-shrink: 0;
  transform-origin: top center;
  animation: aieBarGrow 320ms cubic-bezier(0.22, 1, 0.36, 1) both;
}
@keyframes aieBarGrow {
  from { transform: scaleY(0); }
  to   { transform: scaleY(1); }
}
```

### 1.2 光标升级（静态 ▍ → 呼吸光标）

```css
.aie-caret {
  display: inline-block;
  margin-left: 2rpx;
  color: #2b73f8;
  animation: aieCaret 900ms step-end infinite;
}
@keyframes aieCaret {
  0%, 100% { opacity: 1; }
  50%      { opacity: 0; }
}
/* done 后停止闪烁：把 class 换成 aie-caret--stop { animation: none; opacity: 0.35; } */
```

### 1.3 备选：逐字打字机（适合短文本如 stage 文案 / 结论首句）

```js
// rAF 逐字，中文按字符；30ms/字；返回 stop()
typewrite(target, text, done) {
  let i = 0
  let raf = 0
  let last = 0
  const step = (ts) => {
    if (!last) last = ts
    if (ts - last >= 30) {          // 30ms 出 1 字
      last = ts
      i += 1
      this[target] = text.slice(0, i)
    }
    if (i < text.length) raf = requestAnimationFrame(step)
    else if (done) done()
  }
  raf = requestAnimationFrame(step)
  return () => cancelAnimationFrame(raf)
}
```

> 注意：**流式报告正文不要用逐字**（delta 到达节奏本身就是打字机，再逐字会拖慢 2 倍）。逐字只用于 `stageText` 这类短文案。

### 1.4 阶段文案切换（streamStage 变化时）

```html
<transition name="aie-stage" mode="out-in">
  <text :key="stageText" class="stage-line">{{ stageText }}</text>
</transition>
```
```css
.aie-stage-enter-active { transition: opacity 240ms ease, transform 240ms cubic-bezier(0.22, 1, 0.36, 1); }
.aie-stage-leave-active { transition: opacity 120ms ease; position: absolute; }
.aie-stage-enter-from { opacity: 0; transform: translateY(8rpx); }
.aie-stage-leave-to   { opacity: 0; }
.stage-line { display: block; }
```
> `mode="out-in"` + `leave` 时 `position: absolute` 防止高度跳动（父容器需 `position: relative`）。

---

## 2. 评分出现动画（count-up + 进度条 + 卡片弹入）

### 2.1 数字滚动 Count-up（easeOutExpo，rAF）

H5/小程序通用，纯 options API，可直接加到页面 `methods`：

```js
// 用法：this.countUp('totalDisplay', 0, targetScore, 1000)；data 里 totalDisplay: 0
countUp(field, from, to, duration = 900, decimals = 0) {
  if (this._countRafs && this._countRafs[field]) cancelAnimationFrame(this._countRafs[field])
  this._countRafs = this._countRafs || {}
  const start = performance ? performance.now() : Date.now()
  const tick = (now) => {
    const t = Math.min(1, (now - start) / duration)
    const eased = 1 - Math.pow(2, -10 * t)          // easeOutExpo
    const v = from + (to - from) * (t === 1 ? 1 : eased)
    this[field] = decimals ? v.toFixed(decimals) : Math.round(v)
    if (t < 1) this._countRafs[field] = requestAnimationFrame(tick)
    else this[field] = decimals ? Number(to).toFixed(decimals) : to
  }
  this._countRafs[field] = requestAnimationFrame(tick)
}
```

模板：`<text class="total-num">{{ totalDisplay }}</text>`，data 初始 `totalDisplay: 0`。

**到达回弹**（分数落定后 scale 1.05 → 1，260ms）：

```css
@keyframes aieNumPop {
  0%   { transform: scale(1); }
  40%  { transform: scale(1.06); }
  100% { transform: scale(1); }
}
.total-num--pop { animation: aieNumPop 320ms cubic-bezier(0.34, 1.56, 0.64, 1); }
```

### 2.2 进度条填充（scaleX，不动 width）

模板把现有 `:style="{ width: dim.score + '%' }"` 换成：

```html
<view class="bar-track">
  <view class="bar-fill" :class="{ 'bar-fill--go': barsRevealed }"
        :style="{ '--p': dim.score / 100 }"></view>
</view>
```

```css
.bar-fill {
  height: 100%;
  background: #2b73f8;
  border-radius: 12rpx;
  transform: scaleX(0);                    /* 初始 0 */
  transform-origin: left center;
  /* 自定义属性 --p 不能直接进 scaleX() 的老浏览器？→ 用 width 退化见下 */
}
.bar-fill--go {
  transform: scaleX(var(--p, 0));
  transition: transform 800ms cubic-bezier(0.22, 1, 0.36, 1);
}
```

> **兼容性备注**：`scaleX(var(--p))` 需要 CSS 自定义属性支持（H5 全绿）。若要兼容极老 WebView，用 JS 逐卡写 `style.transform = 'scaleX(' + p + ')'`，或直接保留 `width` 写法 + `transition: width 800ms`（动画期间有 layout 开销，但只有一次性入场，可接受——**权衡结论：一次性入场可以退回 width 过渡，别用于循环/高频**）。

**卡片 stagger（每卡错峰 80ms）**：

```css
@keyframes aieCardIn {
  from { opacity: 0; transform: translateY(20rpx) scale(0.97); }
  to   { opacity: 1; transform: translateY(0) scale(1); }
}
.dim-card {
  animation: aieCardIn 360ms cubic-bezier(0.22, 1, 0.36, 1) both;
  animation-delay: calc(var(--i, 0) * 80ms);
}
```
模板：`<view v-for="(dim, i) in dims" :key="dim.key" class="dim-card" :style="{ '--i': i }">`

### 2.3 结果入场时间线（done 事件后统一编排）

done 后一次性调度：分数 count-up（0ms）→ 条形展开（120ms 置 `barsRevealed=true`）→ 卡片 stagger（CSS delay 自动）→ 雷达生长（250ms 启动）→ 徽章 pop（900ms）。

```js
// applyStreamDone / fetchTask 拿到 evaluation 后调用
playResultEntrance() {
  clearTimeout(this._entranceT1); clearTimeout(this._entranceT2)
  this.barsRevealed = false
  this.resultReady = false                       // 控制卡片 pop 动画 class
  this.$nextTick(() => {
    this.countUp('totalDisplay', 0, Number(this.evaluation.totalScore) || 0, 1000)
    this._entranceT1 = setTimeout(() => { this.barsRevealed = true }, 120)
    this._entranceT2 = setTimeout(() => { this.scheduleRadarDraw(true /* animated */) }, 250)
    this.resultReady = true
  })
}
```

---

## 3. 雷达图生长动画（canvas 逐帧，从中心扩展）

改造 `drawRadar()`：把「评分多边形 + 顶点 + 标签」参数化为 `t ∈ [0,1]`，网格静态画一次，数据层每帧按 `easeOutCubic(t)` 缩放比例重绘。30 帧 / 800ms。

```js
drawRadar(animated = false) {
  const dims = this.dims
  if (!this.aiEnabled || dims.length < 3) return
  uni.createSelectorQuery().select('#evalRadar').boundingClientRect((rect) => {
    if (!rect || !rect.width || !rect.height) return
    const ctx = uni.createCanvasContext('evalRadar', this)
    const w = rect.width, h = rect.height
    const cx = w / 2, cy = h / 2, R = Math.min(w, h) / 2 - 28
    const n = dims.length
    const angleAt = (i) => -Math.PI / 2 + (i * 2 * Math.PI) / n
    const pointAt = (i, ratio) => [
      cx + R * ratio * Math.cos(angleAt(i)),
      cy + R * ratio * Math.sin(angleAt(i))
    ]
    const ratioOf = (d) => Math.max(0, Math.min(1, d.value / 100))

    // —— 静态层：网格 + 轴线（每次重绘都要画，canvas 无分层）——
    const drawGrid = () => {
      ctx.setLineWidth(1); ctx.setStrokeStyle('#e3e9f2')
      ;[0.25, 0.5, 0.75, 1].forEach((lv) => {
        ctx.beginPath()
        for (let i = 0; i < n; i++) {
          const p = pointAt(i, lv)
          i === 0 ? ctx.moveTo(p[0], p[1]) : ctx.lineTo(p[0], p[1])
        }
        ctx.closePath(); ctx.stroke()
      })
      for (let i = 0; i < n; i++) {
        const p = pointAt(i, 1)
        ctx.beginPath(); ctx.moveTo(cx, cy); ctx.lineTo(p[0], p[1]); ctx.stroke()
      }
    }

    // —— 数据层：按进度 k（0→1）生长，alpha 同步渐入 ——
    const drawData = (k) => {
      ctx.beginPath()
      dims.forEach((d, i) => {
        const p = pointAt(i, ratioOf(d) * k)   // ★ 从中心向外扩展
        i === 0 ? ctx.moveTo(p[0], p[1]) : ctx.lineTo(p[0], p[1])
      })
      ctx.closePath()
      ctx.setFillStyle('rgba(43, 115, 248, ' + (0.22 * k).toFixed(3) + ')')
      ctx.fill()
      ctx.setStrokeStyle('#2b73f8'); ctx.setLineWidth(2); ctx.stroke()
      if (k > 0.55) {                            // 顶点圆点后段出现
        ctx.setFillStyle('#2b73f8')
        dims.forEach((d, i) => {
          const p = pointAt(i, ratioOf(d) * k)
          ctx.beginPath(); ctx.arc(p[0], p[1], 2.5, 0, 2 * Math.PI); ctx.fill()
        })
      }
      if (k > 0.75) {                            // 标签最后淡入（canvas 无 alpha 动画，用出现时机模拟）
        ctx.setFillStyle('#666666'); ctx.setFontSize(11)
        ctx.setTextAlign('center'); ctx.setTextBaseline('middle')
        dims.forEach((d, i) => {
          const x = cx + (R + 18) * Math.cos(angleAt(i))
          const y = cy + (R + 18) * Math.sin(angleAt(i))
          ctx.fillText(d.label, x, y)
        })
      }
      ctx.draw()
    }

    if (!animated) { drawGrid(); drawData(1); return }

    const FRAMES = 30, DUR = 800
    let f = 0
    if (this._radarTimer) clearInterval(this._radarTimer)
    this._radarTimer = setInterval(() => {
      f += 1
      const t = f / FRAMES
      const k = 1 - Math.pow(1 - t, 3)          // easeOutCubic
      drawGrid(); drawData(k)
      if (f >= FRAMES) { clearInterval(this._radarTimer); this._radarTimer = null }
    }, DUR / FRAMES)
  }).exec()
}
```

- `onUnload/onHide` 里 `clearInterval(this._radarTimer)`。
- `watch.evaluation` → `this.drawRadar(true)`；页面缓存恢复（onShow）→ `drawRadar(false)` 直接终态，不重播。
- **顶点脉冲（可选彩蛋）**：生长完成后在每个顶点画一圈 `r: 3→8, alpha: 0.5→0` 的扩散圈，一次性 400ms，用同一 interval 的第二个时间线即可。

---

## 4. 加载骨架屏（Skeleton）

替换当前「加载中…」纯文本。骨架 = 头部条 + 综合评分块 + 2×2 维度卡 + 2 段报告条，尺寸贴近真实内容避免跳动。

```html
<!-- v-if="loading && !task"（有缓存 task 时不闪骨架，走 stale-while-revalidate） -->
<view v-if="showSkeleton" class="aie-skel">
  <view class="aie-skel__bar aie-skel__bar--title"></view>
  <view class="aie-skel__card">
    <view class="aie-skel__bar aie-skel__bar--score"></view>
    <view class="aie-skel__bar aie-skel__bar--short"></view>
  </view>
  <view class="aie-skel__grid">
    <view v-for="i in 4" :key="i" class="aie-skel__card aie-skel__card--dim">
      <view class="aie-skel__bar aie-skel__bar--short"></view>
      <view class="aie-skel__bar aie-skel__bar--mid"></view>
    </view>
  </view>
  <view class="aie-skel__card">
    <view v-for="i in 3" :key="i" class="aie-skel__bar aie-skel__bar--line"></view>
  </view>
</view>
```

```css
.aie-skel__card {
  background: #ffffff; border: 1rpx solid #e8ecf2; border-radius: 20rpx;
  padding: 32rpx; margin-bottom: 28rpx;
}
.aie-skel__grid { display: flex; flex-wrap: wrap; justify-content: space-between; }
.aie-skel__card--dim { width: calc(50% - 10rpx); box-sizing: border-box; padding: 20rpx; }
.aie-skel__bar {
  height: 28rpx; border-radius: 8rpx; margin-bottom: 16rpx;
  background: #eef1f6;
  position: relative; overflow: hidden;
}
.aie-skel__bar--title { height: 36rpx; width: 70%; }
.aie-skel__bar--score { height: 64rpx; width: 45%; margin: 0 auto 16rpx; }
.aie-skel__bar--short { width: 40%; }
.aie-skel__bar--mid   { width: 75%; }
.aie-skel__bar--line  { width: 100%; height: 24rpx; }

/* 流光：伪元素光带 translateX（只动 transform，不伤 layout） */
.aie-skel__bar::after {
  content: ''; position: absolute; inset: 0;
  background: linear-gradient(90deg, transparent, rgba(255,255,255,0.85), transparent);
  transform: translateX(-100%);
  animation: aieShimmer 1.4s ease infinite;
}
@keyframes aieShimmer {
  to { transform: translateX(100%); }
}
```

**骨架 → 真实内容 crossfade**：

```html
<transition name="aie-skel" mode="out-in">
  <view v-if="showSkeleton" key="skel" class="aie-skel">…</view>
  <block v-else key="real">…真实内容…</block>
</transition>
```
```css
.aie-skel-enter-active, .aie-skel-leave-active { transition: opacity 260ms ease; }
.aie-skel-enter-from, .aie-skel-leave-to { opacity: 0; }
```

---

## 5. 状态过渡（queued → running → succeeded/failed）

### 5.1 状态区块切换（Vue Transition + key）

把 `queued / running / failed / succeeded` 四个分支包进一个 `<transition mode="out-in">`，每分支一个带 `:key` 的根 view：

```html
<transition name="aie-state" mode="out-in">
  <view v-if="task.status === 'queued'" key="queued" class="section state-section">…</view>
  <view v-else-if="task.status === 'running'" key="running" class="section state-section">…</view>
  <view v-else-if="task.status === 'failed' || task.status === 'stale'" key="failed" class="section state-section">…</view>
  <block v-else key="done">…结果…</block>
</transition>
```
```css
.aie-state-enter-active { transition: opacity 260ms ease, transform 260ms cubic-bezier(0.22, 1, 0.36, 1); }
.aie-state-leave-active { transition: opacity 140ms ease; position: absolute; width: 100%; }
.aie-state-enter-from { opacity: 0; transform: translateY(16rpx); }
.aie-state-leave-to   { opacity: 0; transform: translateY(-8rpx); }
```

### 5.2 状态徽章颜色过渡

```css
.task-status {
  transition: background-color 300ms ease, color 300ms ease;
}
@keyframes aieBadgePop {
  0% { transform: scale(0.85); } 60% { transform: scale(1.08); } 100% { transform: scale(1); }
}
.task-status--succeeded { animation: aieBadgePop 360ms cubic-bezier(0.34, 1.56, 0.64, 1); }
```

### 5.3 排队/评估中：三呼吸灯 dots + 待机 shimmer 条

```html
<view class="aie-stage-dots">
  <view class="aie-dot"></view><view class="aie-dot"></view><view class="aie-dot"></view>
</view>
<view class="aie-progress-shimmer"></view>
```
```css
.aie-stage-dots { display: flex; gap: 12rpx; justify-content: center; margin: 20rpx 0; }
.aie-dot {
  width: 12rpx; height: 12rpx; border-radius: 50%; background: #2b73f8;
  animation: aieBreathe 1.2s ease-in-out infinite;
}
.aie-dot:nth-child(2) { animation-delay: 0.16s; }
.aie-dot:nth-child(3) { animation-delay: 0.32s; }
@keyframes aieBreathe {
  0%, 100% { transform: scale(0.7); opacity: 0.35; }
  50%      { transform: scale(1);   opacity: 1; }
}

.aie-progress-shimmer {
  width: 60%; height: 8rpx; margin: 8rpx auto 0; border-radius: 8rpx;
  background: #eef1f6; position: relative; overflow: hidden;
}
.aie-progress-shimmer::after {
  content: ''; position: absolute; inset: 0;
  background: linear-gradient(90deg, transparent, #2b73f8, transparent);
  transform: translateX(-100%);
  animation: aieShimmer 1.6s ease infinite;
}
```

### 5.4 耗时计时器防抖动

```css
.elapsed { font-variant-numeric: tabular-nums; }
```

---

## 6. 微交互（按钮 / 列表 / 卡片）

```css
/* 移动端按下反馈：scale + 轻微变暗（active 80ms，回弹 150ms） */
.history-item, .btn, .primary-btn, .dim-card {
  transition: transform 150ms cubic-bezier(0.22, 1, 0.36, 1), opacity 150ms ease, background-color 150ms ease;
}
.history-item:active, .dim-card:active {
  transform: scale(0.97);
  opacity: 0.88;
}
.btn:active, .primary-btn:active {
  transform: scale(0.96);
}
.btn::after, .primary-btn::after { border: none; }   /* 去 uni-button 默认描边 */

/* 桌面 hover（可选，不影响移动端） */
@media (hover: hover) {
  .history-item:hover { background: #f4f8ff; transform: translateY(-2rpx); box-shadow: 0 6rpx 20rpx rgba(43,115,248,0.10); }
  .btn:hover { filter: brightness(1.06); }
}

/* 历史列表入场 stagger */
.history-item {
  animation: aieCardIn 300ms cubic-bezier(0.22, 1, 0.36, 1) both;
  animation-delay: calc(var(--i, 0) * 60ms);
}
```

按钮加载态（提交中…）配微型 spinner，比纯文字专业：

```html
<button class="btn" :disabled="retrying" @click="onRetry">
  <view v-if="retrying" class="aie-mini-spin"></view>
  <text>{{ retrying ? '提交中…' : '重新评估' }}</text>
</button>
```
```css
.aie-mini-spin {
  width: 28rpx; height: 28rpx; margin-right: 10rpx;
  border: 3rpx solid rgba(255,255,255,0.35); border-top-color: #ffffff;
  border-radius: 50%;
  animation: aieSpin 0.8s linear infinite;
}
@keyframes aieSpin { to { transform: rotate(360deg); } }
```

---

## 7. 可访问性与降级（必加）

```css
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.01ms !important;
  }
  .aie-skel__bar::after, .aie-progress-shimmer::after { animation: none !important; opacity: 0.5; }
}
```
JS 侧：`const reduceMotion = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches`，为 true 时 `drawRadar(false)`（跳过生长动画直接终态）、`countUp` 直接落终值。

---

## 8. 落地改造清单（ai-eval-detail.vue）

| # | 改动 | 位置 | 备注 |
|---|------|------|------|
| 1 | `loading && !task` 用骨架屏替换「加载中…」 | 模板 L10-12 | §4 |
| 2 | `streamPreview` 视觉改增量块渲染 `streamBlocks` | 模板 L141-152 + `appendStreamText` | §1.1，保留 `streamText` 给解析器 |
| 3 | ▍ 光标改 `.aie-caret` 呼吸光标 | 同上 | §1.2 |
| 4 | `stageText` 换挡用 `<transition name="aie-stage">` | 模板 L41 | §1.4 |
| 5 | 四分支状态包 `<transition name="aie-state">` | 模板 L33-138 | §5.1 |
| 6 | 排队/评估中加 dots + shimmer 条 | 模板 L33-43 | §5.3 |
| 7 | `total-num`/`dim.score` 改 count-up | `playResultEntrance` | §2.1 |
| 8 | `bar-fill` 改 `scaleX(var(--p))` + `barsRevealed` | 模板 L102-104 | §2.2 |
| 9 | `dim-card` stagger `--i` + 卡片弹入 | 模板 L93 | §2.2 |
| 10 | `drawRadar(animated)` 生长动画 | methods | §3，onHide/onUnload 清 timer |
| 11 | `:active` 微交互 + `button::after{border:none}` | 样式 | §6 |
| 12 | `prefers-reduced-motion` 降级块 | 样式尾 | §7 |
| 13 | 全部 keyframes 加 `aie` 前缀 | 样式 | 无 scoped，防全局冲突 |

> 验证流程（技能红线）：改 CSS → 重新编译 → grep 编译产物确认 → 浏览器强刷 + 截图/控制台验证 → 才能说"修好了"。demo 页 `docs/ai-eval-animation-demo.html` 可先行验收动效设计。
