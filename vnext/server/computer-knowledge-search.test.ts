import assert from 'node:assert/strict'
import test from 'node:test'

import {
  buildSearchPlan,
  extractRelevantExcerpt,
  rankSearchSources,
} from './computer-knowledge-search.ts'
import type { SearchSource } from '../src/tooling.ts'
import { ensureSearchCitations } from '../src/tutor.ts'

function source(overrides: Partial<SearchSource>): SearchSource {
  return {
    title: 'Source',
    url: 'https://example.com/source',
    snippet: 'virtual memory definition mechanism example page table address translation',
    source: 'Example',
    quality: 'community',
    role: 'discussion',
    reason: 'test',
    ...overrides,
  }
}

test('explanation planning preserves the concept and asks for teaching evidence', () => {
  const plan = buildSearchPlan('跟我讲讲什么是虚拟内存')
  assert.equal(plan.intent, 'explanation')
  assert.equal(plan.topic, '虚拟内存')
  assert.match(plan.query, /virtual memory/)
  assert.deepEqual(plan.facets, ['准确定义', '核心机制', '最小例子', '边界与常见误区'])
  assert.ok(plan.trustedDomains.includes('pages.cs.wisc.edu'))
})

test('explanation planning removes formatting instructions from the topic', () => {
  const plan = buildSearchPlan('请联网搜索并讲解什么是虚拟内存：先给定义，再解释机制')
  assert.equal(plan.topic, '虚拟内存')
  assert.match(plan.query, /^virtual memory /)
})

test('canonical concepts add mechanism terms for source-page extraction', () => {
  assert.match(buildSearchPlan('解释 TCP 拥塞控制').query, /slow start/)
  assert.match(buildSearchPlan('什么是虚拟内存').query, /page table/)
  assert.match(buildSearchPlan('什么是 LoRA').query, /frozen weights/)
})

test('unknown Chinese and mixed technical terms are not discarded', () => {
  const plan = buildSearchPlan('解释一下 LoRA 低秩适配为什么有效')
  assert.match(plan.topic, /LoRA/)
  assert.match(plan.query, /lora/i)
  assert.match(plan.query, /low rank adaptation/i)
  assert.match(plan.query, /为什么有效/)
  assert.ok(plan.trustedDomains.includes('huggingface.co'))
})

test('query intent changes retrieval facets', () => {
  assert.equal(buildSearchPlan('Python asyncio 为什么报 event loop is closed').intent, 'troubleshooting')
  assert.equal(buildSearchPlan('B+树和红黑树有什么区别').intent, 'comparison')
  assert.equal(buildSearchPlan('找最新的 transformer 推理研究论文').intent, 'current')
  assert.equal(buildSearchPlan('用 Rust 实现一个线程池').intent, 'implementation')
})

test('ranking prefers standards and textbooks over community discussions', () => {
  const plan = buildSearchPlan('什么是 TCP 拥塞控制')
  const ranked = rankSearchSources(plan, [
    source({ title: 'A discussion', url: 'https://stackoverflow.com/questions/1/a', source: 'Stack Overflow' }),
    source({ title: 'RFC congestion control', url: 'https://www.rfc-editor.org/rfc/rfc5681', quality: 'official', role: 'standard', source: 'RFC Editor' }),
    source({ title: 'Networking textbook', url: 'https://www.computer-networking.info/congestion', quality: 'official', role: 'textbook', source: 'Open textbook' }),
  ])
  assert.equal(ranked[0].url, 'https://www.rfc-editor.org/rfc/rfc5681')
  assert.equal(ranked.at(-1)?.source, 'Stack Overflow')
})

test('ranking canonicalizes duplicates and limits one domain from flooding results', () => {
  const plan = buildSearchPlan('解释一下哈希表')
  const ranked = rankSearchSources(plan, [
    source({ title: 'A', url: 'https://example.com/a?utm_source=test' }),
    source({ title: 'A duplicate', url: 'https://example.com/a/' }),
    source({ title: 'B', url: 'https://example.com/b' }),
    source({ title: 'C', url: 'https://example.com/c' }),
    source({ title: 'D', url: 'https://another.example/d' }),
  ], 8)
  assert.equal(ranked.filter(item => new URL(item.url).hostname === 'example.com').length, 2)
  assert.equal(ranked.filter(item => new URL(item.url).pathname === '/a').length, 1)
  assert.equal(ranked.length, 3)
})

test('a searched answer deterministically receives exact source links when the model omits them', () => {
  const answer = ensureSearchCitations('虚拟内存通过页表进行地址转换。', [{
    id: 'tool-1', kind: 'search', status: 'completed', title: '计算机知识搜索', detail: '', durationMs: 1,
    sources: [source({
      title: 'OSTEP: Address Spaces',
      url: 'https://pages.cs.wisc.edu/~remzi/OSTEP/vm-intro.pdf',
      quality: 'official', role: 'textbook', source: 'OSTEP',
    })],
  }])
  assert.match(answer, /\[OSTEP: Address Spaces\]\(https:\/\/pages\.cs\.wisc\.edu\/~remzi\/OSTEP\/vm-intro\.pdf\)/)
  assert.equal(ensureSearchCitations(answer, []), answer)
})

test('authority-page extraction prefers explanatory prose over a table of contents', () => {
  const plan = buildSearchPlan('什么是 TCP 拥塞控制')
  const excerpt = extractRelevantExcerpt(`
    <p>3. Congestion Control Algorithms ................................... 4</p>
    <p>TCP congestion control uses a congestion window to govern the amount of outstanding data in the network.</p>
    <p>When congestion is detected, the sender reduces that window instead of continuing to inject packets at the same rate.</p>
  `, plan)
  assert.doesNotMatch(excerpt, /\.{4,}/)
  assert.match(excerpt, /congestion window/)
  assert.match(excerpt, /reduces that window/)
})
