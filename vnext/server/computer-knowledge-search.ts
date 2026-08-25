import type { SearchSource } from '../src/tooling.ts'

export type SearchIntent = 'explanation' | 'comparison' | 'troubleshooting' | 'implementation' | 'research' | 'current'

export type SearchPlan = {
  topic: string
  query: string
  intent: SearchIntent
  intentLabel: string
  facets: string[]
  trustedDomains: string[]
}

export type SearchProviderConfiguration = {
  jinaApiKey?: string
  exaApiKey?: string
  tavilyApiKey?: string
}

type CatalogSource = {
  id: string
  title: string
  url: string
  source: string
  snippet: string
  terms: string[]
  domains: string[]
  role: SearchSource['role']
  quality: SearchSource['quality']
}

type ProviderResult = {
  name: string
  results: SearchSource[]
}

const providerCooldownUntil = new Map<string, number>()

async function runProvider(adapter: { name: string; run: () => Promise<SearchSource[]> }): Promise<ProviderResult> {
  if ((providerCooldownUntil.get(adapter.name) || 0) > Date.now()) {
    throw new Error(`${adapter.name} 暂时处于失败冷却期`)
  }
  try {
    const results = await adapter.run()
    providerCooldownUntil.delete(adapter.name)
    return { name: adapter.name, results }
  } catch (error) {
    providerCooldownUntil.set(adapter.name, Date.now() + 120_000)
    throw error
  }
}

const SOURCE_CATALOG: CatalogSource[] = [
  { id: 'python', title: 'Python 3 Documentation', url: 'https://docs.python.org/3/', source: 'Python 官方文档', snippet: '语言教程、语言参考、标准库和 HOWTO；适合核对 Python 的精确定义与行为。', terms: ['python', 'pip', 'asyncio', '迭代器', '生成器', '装饰器'], domains: ['programming'], role: 'reference', quality: 'official' },
  { id: 'mdn', title: 'MDN Web Docs', url: 'https://developer.mozilla.org/', source: 'Web 平台文档', snippet: 'Web 平台、JavaScript、HTML、CSS 和浏览器 API 的解释与参考。', terms: ['javascript', 'js', 'html', 'css', 'web', '前端', '浏览器', 'dom', 'http'], domains: ['web', 'networking'], role: 'reference', quality: 'official' },
  { id: 'typescript', title: 'TypeScript Handbook', url: 'https://www.typescriptlang.org/docs/handbook/intro.html', source: 'TypeScript 官方手册', snippet: 'TypeScript 类型系统、语言特性和常见模式的官方学习入口。', terms: ['typescript', 'ts', '类型体操'], domains: ['programming'], role: 'textbook', quality: 'official' },
  { id: 'rust', title: 'The Rust Programming Language', url: 'https://doc.rust-lang.org/book/', source: 'Rust 官方教材', snippet: '从所有权开始系统解释 Rust，并配有连续示例。', terms: ['rust', '所有权', '借用', '生命周期'], domains: ['programming', 'systems'], role: 'textbook', quality: 'official' },
  { id: 'go', title: 'The Go Programming Language Specification', url: 'https://go.dev/ref/spec', source: 'Go 官方规范', snippet: 'Go 语言语法、类型、语义与运行行为的规范来源。', terms: ['golang', 'go language', 'goroutine', 'channel', '协程'], domains: ['programming'], role: 'standard', quality: 'official' },
  { id: 'cppreference', title: 'cppreference', url: 'https://en.cppreference.com/w/', source: 'C/C++ 参考', snippet: 'C 与 C++ 语言及标准库的系统参考，适合核对精确语义和版本差异。', terms: ['c++', 'cpp', 'c语言', 'c 语言', '指针', '内存管理', '模板'], domains: ['programming', 'systems'], role: 'reference', quality: 'official' },
  { id: 'java', title: 'Java Documentation', url: 'https://docs.oracle.com/en/java/', source: 'Java 官方文档', snippet: 'Java 平台、语言、JVM 与核心 API 的官方文档入口。', terms: ['java', 'jvm', 'spring'], domains: ['programming'], role: 'reference', quality: 'official' },
  { id: 'ostep', title: 'Operating Systems: Three Easy Pieces', url: 'https://pages.cs.wisc.edu/~remzi/OSTEP/', source: '开放教材 OSTEP', snippet: '围绕虚拟化、并发和持久化组织的开放操作系统教材。', terms: ['操作系统', 'operating system', '进程', '线程', '虚拟内存', '分页', '并发', '文件系统', '锁', '死锁'], domains: ['operating-systems', 'systems'], role: 'textbook', quality: 'official' },
  { id: 'ostep-vm-intro', title: 'OSTEP: The Abstraction — Address Spaces', url: 'https://pages.cs.wisc.edu/~remzi/OSTEP/vm-intro.pdf', source: 'OSTEP 虚拟内存章节', snippet: '从地址空间抽象出发解释虚拟内存为什么存在，以及程序看到的地址空间和物理内存的关系。', terms: ['虚拟内存', 'virtual memory', '地址空间', 'address space'], domains: ['operating-systems', 'systems'], role: 'textbook', quality: 'official' },
  { id: 'csapp', title: 'Computer Systems: A Programmer’s Perspective', url: 'https://csapp.cs.cmu.edu/', source: 'CMU 系统教材', snippet: '从程序员视角串联硬件、汇编、编译、链接、缓存、虚拟内存与并发。', terms: ['计算机系统', '汇编', '链接', '缓存', '系统编程', 'computer systems', '内存层次'], domains: ['systems', 'architecture'], role: 'textbook', quality: 'official' },
  { id: 'linux', title: 'The Linux Kernel Documentation', url: 'https://docs.kernel.org/', source: 'Linux 内核文档', snippet: 'Linux 内核子系统、接口、开发和管理文档。', terms: ['linux', '内核', 'kernel', '驱动', '系统调用'], domains: ['operating-systems', 'systems'], role: 'reference', quality: 'official' },
  { id: 'rfc', title: 'RFC Editor', url: 'https://www.rfc-editor.org/', source: '互联网协议规范', snippet: '互联网协议 RFC 的正式发布和检索入口，用于核对协议字段、状态机与规范语义。', terms: ['网络', 'tcp', 'udp', 'http', 'https', 'dns', 'tls', 'ip', '协议', 'network', 'quic'], domains: ['networking'], role: 'standard', quality: 'official' },
  { id: 'rfc5681', title: 'RFC 5681: TCP Congestion Control', url: 'https://www.rfc-editor.org/rfc/rfc5681.html', source: 'TCP 拥塞控制规范', snippet: '定义慢启动、拥塞避免、快速重传和快速恢复等标准 TCP 拥塞控制算法。', terms: ['tcp 拥塞控制', 'tcp congestion control', '慢启动', 'slow start', '拥塞避免'], domains: ['networking'], role: 'standard', quality: 'official' },
  { id: 'rfc9110', title: 'RFC 9110: HTTP Semantics', url: 'https://www.rfc-editor.org/rfc/rfc9110.html', source: 'HTTP 语义规范', snippet: 'HTTP 的方法、状态码、字段、缓存语义和统一接口的核心规范。', terms: ['http 语义', 'http semantics', 'http 方法', '状态码', 'http status'], domains: ['networking', 'web'], role: 'standard', quality: 'official' },
  { id: 'networking-book', title: 'Computer Networking: Principles, Protocols and Practice', url: 'https://www.computer-networking.info/', source: '开放网络教材', snippet: '面向本科课程解释网络原理和主要互联网协议，并带练习与实验。', terms: ['网络', 'tcp', 'udp', 'dns', '路由', '拥塞控制', 'network'], domains: ['networking'], role: 'textbook', quality: 'official' },
  { id: 'algs4', title: 'Algorithms, 4th Edition', url: 'https://algs4.cs.princeton.edu/home/', source: 'Princeton 算法教材', snippet: '算法、数据结构、代码、可视化与习题的系统学习资源。', terms: ['算法', '数据结构', 'algorithm', 'sorting', 'graph', '排序', '图论', '最短路', '搜索树'], domains: ['algorithms'], role: 'textbook', quality: 'official' },
  { id: 'mit-distributed', title: 'MIT 6.5840 Distributed Systems', url: 'https://pdos.csail.mit.edu/6.824/', source: 'MIT 分布式系统课程', snippet: '分布式系统的课程讲义、论文、实验与 Raft 等核心主题。', terms: ['分布式', 'distributed systems', 'raft', '一致性', '共识', 'mapreduce'], domains: ['distributed-systems'], role: 'course', quality: 'official' },
  { id: 'postgresql', title: 'PostgreSQL Documentation', url: 'https://www.postgresql.org/docs/current/', source: 'PostgreSQL 官方文档', snippet: 'SQL、事务、索引、查询、数据库管理和内部机制的官方参考。', terms: ['postgres', 'postgresql', 'sql', '数据库', '事务', '索引', 'mvcc'], domains: ['databases'], role: 'reference', quality: 'official' },
  { id: 'cmu-db', title: 'CMU 15-445/645 Database Systems', url: 'https://15445.courses.cs.cmu.edu/', source: 'CMU 数据库课程', snippet: '从存储、索引和执行到并发控制的数据库系统课程与项目。', terms: ['数据库', 'database systems', 'b+树', '查询优化', '事务', 'mvcc'], domains: ['databases'], role: 'course', quality: 'official' },
  { id: 'crafting-interpreters', title: 'Crafting Interpreters', url: 'https://craftinginterpreters.com/', source: '开放编译器教材', snippet: '通过两个完整解释器逐层说明词法、语法、语义、字节码与垃圾回收。', terms: ['编译器', '解释器', 'compiler', 'interpreter', '词法分析', '语法分析', 'ast', '字节码'], domains: ['compilers', 'programming-languages'], role: 'textbook', quality: 'official' },
  { id: 'llvm', title: 'LLVM Documentation', url: 'https://llvm.org/docs/', source: 'LLVM 官方文档', snippet: 'LLVM IR、编译流程、优化 Pass 与工具链的官方文档。', terms: ['llvm', '编译器', 'compiler', 'ir', '优化 pass'], domains: ['compilers'], role: 'reference', quality: 'official' },
  { id: 'owasp', title: 'OWASP Web Security Testing Guide', url: 'https://owasp.org/www-project-web-security-testing-guide/', source: 'OWASP 安全指南', snippet: 'Web 安全风险、测试方法与防护边界的开放权威指南。', terms: ['安全', 'security', '漏洞', 'xss', 'csrf', 'sql注入', '认证', '授权'], domains: ['security', 'web'], role: 'standard', quality: 'official' },
  { id: 'sklearn', title: 'scikit-learn User Guide', url: 'https://scikit-learn.org/stable/user_guide.html', source: 'scikit-learn 官方指南', snippet: '机器学习算法、模型选择、预处理和评估的实现型指南。', terms: ['machine learning', '机器学习', '分类器', '回归', '朴素贝叶斯', '核方法', '支持向量机', '聚类'], domains: ['machine-learning'], role: 'reference', quality: 'official' },
  { id: 'sklearn-naive-bayes', title: 'scikit-learn: Naive Bayes', url: 'https://scikit-learn.org/stable/modules/naive_bayes.html', source: '朴素贝叶斯官方实现指南', snippet: '解释条件独立假设，并区分 Gaussian、Multinomial、Bernoulli、Categorical 等朴素贝叶斯变体。', terms: ['朴素贝叶斯', 'naive bayes'], domains: ['machine-learning'], role: 'reference', quality: 'official' },
  { id: 'sklearn-svm-kernel', title: 'scikit-learn: Kernel functions', url: 'https://scikit-learn.org/stable/modules/svm.html#kernel-functions', source: 'SVM 核函数实现指南', snippet: '说明 SVM 中线性、多项式、RBF、sigmoid 和自定义核函数的接口与参数。', terms: ['核方法', 'kernel methods', '核函数', '支持向量机'], domains: ['machine-learning'], role: 'reference', quality: 'official' },
  { id: 'd2l', title: 'Dive into Deep Learning', url: 'https://d2l.ai/', source: '开放深度学习教材', snippet: '把数学、代码、模型和练习结合起来的交互式深度学习教材。', terms: ['深度学习', '神经网络', 'attention', 'transformer', 'cnn', 'rnn'], domains: ['machine-learning'], role: 'textbook', quality: 'official' },
  { id: 'huggingface-peft-lora', title: 'LoRA conceptual guide', url: 'https://huggingface.co/docs/peft/en/conceptual_guides/lora', source: 'Hugging Face PEFT 文档', snippet: 'LoRA 的低秩更新、适配器参数和 PEFT 实现边界的官方概念指南。', terms: ['lora', '低秩适配', 'low-rank adaptation', 'peft'], domains: ['machine-learning'], role: 'reference', quality: 'official' },
  { id: 'lora-paper', title: 'LoRA: Low-Rank Adaptation of Large Language Models', url: 'https://arxiv.org/abs/2106.09685', source: 'LoRA 原始论文', snippet: 'LoRA 冻结预训练权重，把可训练更新表示为低秩分解，从而显著减少适配参数和训练内存。', terms: ['lora', '低秩适配', 'low-rank adaptation'], domains: ['machine-learning'], role: 'research', quality: 'academic' },
  { id: 'pytorch', title: 'PyTorch Documentation', url: 'https://pytorch.org/docs/stable/index.html', source: 'PyTorch 官方文档', snippet: '张量、自动微分、神经网络与分布式训练的官方参考。', terms: ['pytorch', '深度学习', '神经网络', 'tensor', 'autograd'], domains: ['machine-learning'], role: 'reference', quality: 'official' },
  { id: 'git', title: 'Git Reference', url: 'https://git-scm.com/docs', source: 'Git 官方参考', snippet: 'Git 命令、对象模型、概念和版本控制工作流的官方资料。', terms: ['git', '版本控制', 'rebase', 'merge', '分支'], domains: ['software-engineering'], role: 'reference', quality: 'official' },
  { id: 'docker', title: 'Docker Documentation', url: 'https://docs.docker.com/', source: 'Docker 官方文档', snippet: '容器、镜像、构建、Compose 和运行时的官方资料。', terms: ['docker', '容器', '镜像', 'compose'], domains: ['devops', 'systems'], role: 'reference', quality: 'official' },
  { id: 'kubernetes', title: 'Kubernetes Documentation', url: 'https://kubernetes.io/docs/', source: 'Kubernetes 官方文档', snippet: 'Kubernetes 概念、任务、配置和 API 的官方文档。', terms: ['kubernetes', 'k8s', 'pod', '容器编排'], domains: ['devops', 'distributed-systems'], role: 'reference', quality: 'official' },
]

const TERM_TRANSLATIONS: Array<[RegExp, string]> = [
  [/朴素贝叶斯/g, 'naive bayes'], [/核方法/g, 'kernel methods'], [/支持向量机/g, 'support vector machine'],
  [/操作系统/g, 'operating systems'], [/虚拟内存/g, 'virtual memory'], [/进程/g, 'process'], [/线程/g, 'thread'],
  [/并发/g, 'concurrency'], [/死锁/g, 'deadlock'], [/指针/g, 'pointer'], [/数据结构/g, 'data structures'],
  [/算法/g, 'algorithm'], [/排序/g, 'sorting'], [/图论/g, 'graph theory'], [/计算机网络/g, 'computer networking'],
  [/网络/g, 'network'], [/拥塞控制/g, 'congestion control'], [/数据库/g, 'database'], [/事务/g, 'transaction'],
  [/编译器/g, 'compiler'], [/解释器/g, 'interpreter'], [/机器学习/g, 'machine learning'], [/深度学习/g, 'deep learning'],
  [/神经网络/g, 'neural network'], [/分类器/g, 'classifier'], [/回归/g, 'regression'], [/哈希/g, 'hashing'],
  [/链表/g, 'linked list'], [/二叉树/g, 'binary tree'], [/动态规划/g, 'dynamic programming'], [/递归/g, 'recursion'],
  [/分布式系统/g, 'distributed systems'], [/一致性/g, 'consistency'], [/共识/g, 'consensus'],
  [/低秩适配/g, 'low rank adaptation'],
]

const INTENT_LABELS: Record<SearchIntent, string> = {
  explanation: '概念讲解', comparison: '对比辨析', troubleshooting: '问题排查',
  implementation: '实现与实践', research: '论文研究', current: '最新变化',
}

const TOPIC_EXPANSIONS: Array<[RegExp, string]> = [
  [/tcp.*(?:拥塞控制|congestion control)/i, 'slow start congestion avoidance fast retransmit fast recovery cwnd ssthresh'],
  [/(?:虚拟内存|virtual memory)/i, 'address space page table address translation MMU page fault'],
  [/(?:朴素贝叶斯|naive bayes)/i, 'conditional independence posterior likelihood prior'],
  [/(?:核方法|kernel methods?)/i, 'kernel trick feature space similarity function'],
  [/(?:lora|低秩适配|low rank adaptation)/i, 'frozen weights low rank matrices trainable parameters'],
  [/(?:数据库事务|database transaction)/i, 'ACID isolation concurrency control commit rollback'],
  [/(?:死锁|deadlock)/i, 'mutual exclusion hold and wait circular wait prevention'],
  [/(?:dns|域名系统)/i, 'recursive resolver authoritative server caching record'],
]

function compactText(value: unknown, limit = 640) {
  return String(value || '').replace(/<script[\s\S]*?<\/script>/gi, ' ').replace(/<style[\s\S]*?<\/style>/gi, ' ')
    .replace(/<[^>]*>/g, ' ').replace(/&(?:amp|#38);/g, '&').replace(/&(?:lt|#60);/g, '<')
    .replace(/&(?:gt|#62);/g, '>').replace(/&(?:quot|#34);/g, '"').replace(/&#39;|&apos;/g, "'")
    .replace(/\s+/g, ' ').trim().slice(0, limit)
}

function translatedQuery(query: string) {
  let translated = query.toLowerCase()
  for (const [pattern, replacement] of TERM_TRANSLATIONS) translated = translated.replace(pattern, ` ${replacement} `)
  translated = translated
    .replace(/跟我讲讲|讲讲|讲一下|解释一下|解释|什么是|怎么理解|如何理解|请问|帮我|一下/g, ' ')
    .replace(/[，。！？：；“”‘’]/g, ' ').replace(/\s+/g, ' ').trim()
  return translated.slice(0, 220)
}

function extractTopic(query: string) {
  return compactText(query, 220)
    .replace(/^(?:请|你)?(?:联网)?(?:搜索|搜一下|查一下)?(?:并)?(?:跟我)?(?:讲解|讲讲|讲一下|解释一下|解释|介绍一下)?\s*/i, '')
    .replace(/^(?:什么是|怎么理解|如何理解)\s*/i, '')
    .replace(/[：:]\s*(?:先|请|包括|重点|要求)[\s\S]*$/i, '')
    .replace(/[？?。！!]+$/g, '').trim() || compactText(query, 120)
}

function detectIntent(query: string): SearchIntent {
  if (/最新|近期|现在|当前|版本|release|latest|recent|202[4-9]/i.test(query)) return 'current'
  if (/论文|研究|paper|research|benchmark|sota/i.test(query)) return 'research'
  if (/报错|为什么报|错误|异常|失败|为什么.*(?:不|没)|is closed|cannot|failed|debug|error|exception|troubleshoot/i.test(query)) return 'troubleshooting'
  if (/区别|对比|比较|差异|vs\.?|versus/i.test(query)) return 'comparison'
  if (/代码|实现|怎么写|示例|仓库|项目|工程|api|library|框架/i.test(query)) return 'implementation'
  return 'explanation'
}

function sourceMatches(source: CatalogSource, query: string) {
  const normalized = query.toLowerCase().replace(/\s+/g, ' ')
  return source.terms.some(term => {
    const needle = term.toLowerCase()
    if (/[\u3400-\u9fff]/.test(needle)) return normalized.includes(needle)
    const escaped = needle.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
    return new RegExp(`(^|[^a-z0-9])${escaped}(?=$|[^a-z0-9])`, 'i').test(normalized)
  })
}

export function buildSearchPlan(query: string): SearchPlan {
  const topic = extractTopic(query)
  const translated = translatedQuery(topic)
  const intent = detectIntent(query)
  const facets = intent === 'explanation'
    ? ['准确定义', '核心机制', '最小例子', '边界与常见误区']
    : intent === 'comparison'
      ? ['共同前提', '关键差异', '适用场景', '反例']
      : intent === 'troubleshooting'
        ? ['官方行为', '可能原因', '可复现检查', '修复边界']
        : intent === 'implementation'
          ? ['官方接口', '最小实现', '工程约束', '常见陷阱']
          : intent === 'research'
            ? ['问题定义', '代表方法', '实验结论', '局限']
            : ['当前规范', '版本变化', '迁移影响', '发布日期']
  const matched = SOURCE_CATALOG.filter(source => sourceMatches(source, `${query} ${translated}`))
  const trustedDomains = [...new Set(matched.map(source => new URL(source.url).hostname))].slice(0, 12)
  const facetTerms = intent === 'explanation' ? 'definition mechanism example common misconception'
    : intent === 'comparison' ? 'differences tradeoffs examples'
      : intent === 'troubleshooting' ? 'official documentation cause fix'
        : intent === 'implementation' ? 'official documentation tutorial example implementation'
          : intent === 'research' ? 'survey paper method limitations'
            : 'latest official documentation release changes'
  const expansion = TOPIC_EXPANSIONS.find(([pattern]) => pattern.test(`${topic} ${translated}`))?.[1] || ''
  return {
    topic,
    query: `${translated || topic} ${expansion} ${facetTerms}`.replace(/\s+/g, ' ').trim().slice(0, 380),
    intent,
    intentLabel: INTENT_LABELS[intent],
    facets,
    trustedDomains,
  }
}

function curatedResults(query: string): SearchSource[] {
  const translated = translatedQuery(query)
  return SOURCE_CATALOG.filter(source => sourceMatches(source, `${query} ${translated}`)).slice(0, 5).map(source => ({
    title: source.title, url: source.url, snippet: source.snippet, source: source.source,
    quality: source.quality, role: source.role, reason: '与主题直接匹配的规范、官方文档、教材或大学课程入口',
  }))
}

export function extractRelevantExcerpt(html: string, plan: SearchPlan) {
  const text = html.slice(0, 1_200_000)
    .replace(/<script[\s\S]*?<\/script>/gi, ' ').replace(/<style[\s\S]*?<\/style>/gi, ' ')
    .replace(/<\/(?:p|li|h1|h2|h3|h4|section|article|pre|tr|div)>/gi, '\n')
    .replace(/<br\s*\/?\s*>/gi, '\n').replace(/<[^>]*>/g, ' ')
  const tokens = queryTokens(plan)
  const lines = text.split(/\n+/).map(line => compactText(line, 900)).filter(Boolean)
  const windows = lines.flatMap((line, index) => {
    if (line.length < 320) return [{ line: compactText(lines.slice(index, index + 5).join(' '), 1400), index }]
    return [{ line, index }]
  })
  const seen = new Set<string>()
  const candidates = windows
    .filter(item => item.line.length >= 90 && item.line.length <= 1400 && !/\.{4,}/.test(item.line))
    .filter(item => {
      const key = item.line.slice(0, 180).toLowerCase()
      return !seen.has(key) && seen.add(key)
    })
    .map(({ line, index }) => {
      const lower = line.toLowerCase()
      const overlap = tokens.filter(token => lower.includes(token)).length
      const mechanism = /define|means|mechanism|algorithm|address|mapping|window|congestion|page|memory|转换|定义|机制|算法|地址|映射|窗口|拥塞|内存/i.test(line) ? 1 : 0
      const prose = /[.!?。！？]\s|\b(?:is|are|means|defines|uses|when|because)\b/i.test(line) ? 2 : 0
      const lengthBonus = Math.min(4, Math.floor(line.length / 180))
      return { line, index, score: overlap * 4 + mechanism + prose + lengthBonus }
    })
    .filter(item => item.score >= 5)
    .sort((a, b) => b.score - a.score || a.index - b.index)
  const selected: typeof candidates = []
  for (const candidate of candidates) {
    if (selected.some(item => Math.abs(item.index - candidate.index) <= 2)) continue
    selected.push(candidate)
    if (selected.length >= 4) break
  }
  selected.sort((a, b) => a.index - b.index)
  return compactText(selected.map(item => item.line).join(' '), 1800)
}

async function readCuratedPages(plan: SearchPlan, sources: SearchSource[]) {
  const readable = sources.filter(source => !/\.pdf(?:$|[?#])/i.test(source.url)).slice(0, 3)
  const settled = await Promise.allSettled(readable.map(async source => {
    const response = await fetchWithTimeout(source.url, { headers: { Accept: 'text/html,application/xhtml+xml' } }, 4600)
    const contentType = response.headers.get('content-type') || ''
    const contentLength = Number(response.headers.get('content-length') || 0)
    if (!/text\/html|application\/xhtml\+xml/i.test(contentType) || contentLength > 1_200_000) return null
    const excerpt = extractRelevantExcerpt(await response.text(), plan)
    if (excerpt.length < 120) return null
    return { ...source, snippet: excerpt, reason: '已读取可信来源页面并抽取与当前问题直接相关的原文段落' }
  }))
  return settled.flatMap(result => result.status === 'fulfilled' && result.value ? [result.value] : [])
}

async function fetchWithTimeout(url: string, init: RequestInit = {}, timeoutMs = 6200) {
  const controller = new AbortController()
  const timeout = setTimeout(() => controller.abort(), timeoutMs)
  try {
    const response = await fetch(url, {
      ...init,
      headers: { 'User-Agent': 'LearnFlow-vNext/0.4', ...(init.headers || {}) },
      signal: controller.signal,
    })
    if (!response.ok) throw new Error(`HTTP ${response.status}`)
    return response
  } finally {
    clearTimeout(timeout)
  }
}

async function fetchJson(url: string, init: RequestInit = {}, timeoutMs = 6200) {
  const response = await fetchWithTimeout(url, {
    ...init,
    headers: { Accept: 'application/json', ...(init.headers || {}) },
  }, timeoutMs)
  return await response.json() as any
}

function isSafeWebUrl(value: unknown) {
  try {
    const url = new URL(String(value || ''))
    return url.protocol === 'https:' && !['localhost', '127.0.0.1', '::1'].includes(url.hostname)
  } catch {
    return false
  }
}

function catalogForUrl(url: string) {
  try {
    const hostname = new URL(url).hostname.replace(/^www\./, '')
    return SOURCE_CATALOG.find(source => new URL(source.url).hostname.replace(/^www\./, '') === hostname)
  } catch {
    return undefined
  }
}

function classifyResult(url: string): Pick<SearchSource, 'quality' | 'role' | 'source' | 'reason'> {
  const catalog = catalogForUrl(url)
  if (catalog) return {
    quality: catalog.quality, role: catalog.role, source: catalog.source,
    reason: '命中 LearnFlow 计算机知识可信来源目录',
  }
  const hostname = new URL(url).hostname.replace(/^www\./, '')
  if (hostname === 'arxiv.org' || hostname === 'dl.acm.org' || hostname === 'ieeexplore.ieee.org' || hostname === 'aclanthology.org') {
    return { quality: 'academic', role: 'research', source: hostname, reason: '学术论文或出版物；用于研究结论，不能代替规范' }
  }
  if (hostname === 'stackoverflow.com' || hostname.endsWith('.stackexchange.com')) {
    return { quality: 'community', role: 'discussion', source: 'Stack Overflow', reason: '社区实践证据；用于例子和故障经验，并与官方资料交叉核对' }
  }
  if (hostname === 'github.com') {
    return { quality: 'repository', role: 'example', source: 'GitHub', reason: '代码仓库；用于观察实现，不直接作为概念规范' }
  }
  if (hostname.endsWith('.edu') || hostname.endsWith('.ac.uk')) {
    return { quality: 'official', role: 'course', source: hostname, reason: '大学课程或实验室资料' }
  }
  return { quality: 'community', role: 'discussion', source: hostname, reason: '一般网页结果；仅作补充并需要交叉核对' }
}

function searchResult(title: unknown, url: unknown, snippet: unknown, source?: Partial<SearchSource>): SearchSource | null {
  if (!isSafeWebUrl(url)) return null
  const classified = classifyResult(String(url))
  const item = {
    title: compactText(title, 180), url: String(url), snippet: compactText(snippet, 720),
    ...classified, ...source,
  }
  return item.title ? item as SearchSource : null
}

async function searchJina(plan: SearchPlan, apiKey?: string): Promise<SearchSource[]> {
  const response = await fetchJson(`https://s.jina.ai/?q=${encodeURIComponent(plan.query)}`, {
    headers: { ...(apiKey ? { Authorization: `Bearer ${apiKey}` } : {}) },
  }, 4200)
  const candidates = Array.isArray(response) ? response : Array.isArray(response?.data) ? response.data : []
  return candidates.slice(0, 7).map((item: any) => searchResult(
    item?.title, item?.url,
    item?.content || item?.description || item?.snippet,
    { reason: 'Jina Search 返回的与讲解问题相关的正文片段' },
  )).filter((item: SearchSource | null): item is SearchSource => Boolean(item))
}

async function searchExa(plan: SearchPlan, apiKey: string): Promise<SearchSource[]> {
  const payload = await fetchJson('https://api.exa.ai/search', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${apiKey}`, 'x-api-key': apiKey },
    body: JSON.stringify({
      query: plan.query, type: 'auto', numResults: 7,
      ...(plan.trustedDomains.length ? { includeDomains: plan.trustedDomains } : {}),
      contents: { highlights: { query: plan.query, maxCharacters: 900 } },
    }),
  }, 7000)
  return (Array.isArray(payload?.results) ? payload.results : []).map((item: any) => searchResult(
    item?.title, item?.url,
    Array.isArray(item?.highlights) ? item.highlights.join(' ') : item?.text,
    { reason: 'Exa 语义检索返回的查询相关原文片段' },
  )).filter((item: SearchSource | null): item is SearchSource => Boolean(item))
}

async function searchTavily(plan: SearchPlan, apiKey: string): Promise<SearchSource[]> {
  const payload = await fetchJson('https://api.tavily.com/search', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      api_key: apiKey, query: plan.query, search_depth: 'basic', max_results: 7,
      chunks_per_source: 2, include_answer: false, include_raw_content: false,
      ...(plan.trustedDomains.length ? { include_domains: plan.trustedDomains } : {}),
    }),
  }, 7000)
  return (Array.isArray(payload?.results) ? payload.results : []).map((item: any) => searchResult(
    item?.title, item?.url, item?.content,
    { reason: 'Tavily 返回的与查询最相关的网页证据片段' },
  )).filter((item: SearchSource | null): item is SearchSource => Boolean(item))
}

async function searchWikipedia(plan: SearchPlan, originalQuery: string): Promise<SearchSource[]> {
  const language = /[\u3400-\u9fff]/.test(originalQuery) ? 'zh' : 'en'
  const url = new URL(`https://${language}.wikipedia.org/w/api.php`)
  url.searchParams.set('action', 'query')
  url.searchParams.set('generator', 'search')
  url.searchParams.set('gsrsearch', plan.topic)
  url.searchParams.set('gsrlimit', '3')
  url.searchParams.set('prop', 'extracts|info')
  url.searchParams.set('exintro', '1')
  url.searchParams.set('explaintext', '1')
  url.searchParams.set('inprop', 'url')
  url.searchParams.set('redirects', '1')
  url.searchParams.set('format', 'json')
  url.searchParams.set('origin', '*')
  const payload = await fetchJson(url.toString(), {}, 4200)
  const pages = payload?.query?.pages && typeof payload.query.pages === 'object' ? Object.values(payload.query.pages) : []
  return pages.slice(0, 3).map((item: any) => searchResult(item?.title, item?.fullurl, item?.extract, {
    source: language === 'zh' ? '中文维基百科' : 'Wikipedia', quality: 'community', role: 'definition',
    reason: '百科概览用于建立定义起点；关键机制继续以教材或官方资料核对',
  })).filter((item: SearchSource | null): item is SearchSource => Boolean(item))
}

async function searchStackExchange(plan: SearchPlan): Promise<SearchSource[]> {
  const url = new URL('https://api.stackexchange.com/2.3/search/advanced')
  url.searchParams.set('site', 'stackoverflow')
  url.searchParams.set('order', 'desc')
  url.searchParams.set('sort', 'relevance')
  url.searchParams.set('pagesize', '4')
  url.searchParams.set('q', plan.query.slice(0, 180))
  const payload = await fetchJson(url.toString(), {}, 4600)
  const questions = Array.isArray(payload?.items) ? payload.items.slice(0, 4) : []
  const questionIds = questions.map((item: any) => Number(item.question_id)).filter(Boolean)
  let bestAnswers = new Map<number, string>()
  if (questionIds.length) {
    try {
      const answerUrl = new URL(`https://api.stackexchange.com/2.3/questions/${questionIds.join(';')}/answers`)
      answerUrl.searchParams.set('site', 'stackoverflow')
      answerUrl.searchParams.set('order', 'desc')
      answerUrl.searchParams.set('sort', 'votes')
      answerUrl.searchParams.set('pagesize', '8')
      answerUrl.searchParams.set('filter', 'withbody')
      const answers = await fetchJson(answerUrl.toString(), {}, 3800)
      for (const answer of Array.isArray(answers?.items) ? answers.items : []) {
        if (!bestAnswers.has(Number(answer.question_id))) bestAnswers.set(Number(answer.question_id), compactText(answer.body, 700))
      }
    } catch {
      bestAnswers = new Map()
    }
  }
  return questions.map((item: any) => searchResult(
    item?.title, item?.link,
    bestAnswers.get(Number(item.question_id)) || `${Number(item.score || 0)} 票 · ${Number(item.answer_count || 0)} 个回答`,
    { source: 'Stack Overflow', quality: 'community', role: 'discussion', reason: '高票实践讨论；只用于补充例子、故障和边界' },
  )).filter((item: SearchSource | null): item is SearchSource => Boolean(item))
}

async function searchGitHub(plan: SearchPlan): Promise<SearchSource[]> {
  const url = new URL('https://api.github.com/search/repositories')
  url.searchParams.set('q', `${plan.query.slice(0, 160)} in:name,description,readme`)
  url.searchParams.set('sort', 'stars')
  url.searchParams.set('order', 'desc')
  url.searchParams.set('per_page', '4')
  const payload = await fetchJson(url.toString())
  return (Array.isArray(payload?.items) ? payload.items : []).slice(0, 4).map((item: any) => searchResult(
    item?.full_name, item?.html_url,
    `${compactText(item?.description, 500)} · ★ ${Number(item?.stargazers_count || 0).toLocaleString('en-US')}`,
    { source: 'GitHub', quality: 'repository', role: 'example', reason: '实现样例；不能单独作为概念或规范依据' },
  )).filter((item: SearchSource | null): item is SearchSource => Boolean(item))
}

async function searchArxiv(plan: SearchPlan): Promise<SearchSource[]> {
  const url = new URL('https://export.arxiv.org/api/query')
  const terms = translatedQuery(plan.topic).match(/[a-z0-9+#.-]{2,}/gi)?.slice(0, 7) || []
  url.searchParams.set('search_query', terms.length ? terms.map(term => `all:${term}`).join(' AND ') : `all:${plan.topic}`)
  url.searchParams.set('start', '0')
  url.searchParams.set('max_results', '4')
  url.searchParams.set('sortBy', plan.intent === 'current' ? 'submittedDate' : 'relevance')
  const response = await fetchWithTimeout(url.toString(), {}, 9000)
  const xml = await response.text()
  return [...xml.matchAll(/<entry>([\s\S]*?)<\/entry>/g)].slice(0, 4).map(match => {
    const entry = match[1]
    return searchResult(
      entry.match(/<title>([\s\S]*?)<\/title>/)?.[1],
      compactText(entry.match(/<id>([\s\S]*?)<\/id>/)?.[1], 300).replace('http://', 'https://'),
      entry.match(/<summary>([\s\S]*?)<\/summary>/)?.[1],
      { source: 'arXiv', quality: 'academic', role: 'research', reason: '论文摘要；用于研究进展与局限，不替代稳定概念的教材解释' },
    )
  }).filter((item: SearchSource | null): item is SearchSource => Boolean(item))
}

function canonicalUrl(value: string) {
  const url = new URL(value)
  url.hash = ''
  for (const key of [...url.searchParams.keys()]) {
    if (/^(?:utm_|ref$|source$|campaign$)/i.test(key)) url.searchParams.delete(key)
  }
  return url.toString().replace(/\/$/, '')
}

function queryTokens(plan: SearchPlan) {
  const ascii = plan.query.toLowerCase().match(/[a-z0-9+#.-]{2,}/g) || []
  const chinese = plan.topic.match(/[\u3400-\u9fff]{2,}/g)?.flatMap(value => value.length <= 4
    ? [value]
    : Array.from({ length: value.length - 1 }, (_, index) => value.slice(index, index + 2))) || []
  return [...new Set([...ascii, ...chinese])].slice(0, 24)
}

export function rankSearchSources(plan: SearchPlan, sources: SearchSource[], limit = 8) {
  const authority = { official: 100, academic: 86, community: 58, repository: 52 }
  const roleScore: Record<SearchSource['role'], number> = {
    standard: 18, reference: 15, textbook: 14, course: 12, definition: 8,
    research: plan.intent === 'research' || plan.intent === 'current' ? 16 : 5,
    example: plan.intent === 'implementation' ? 13 : 3,
    discussion: plan.intent === 'troubleshooting' ? 12 : 0,
  }
  const tokens = queryTokens(plan)
  const seen = new Set<string>()
  const scored = sources.flatMap(source => {
    let key = ''
    try { key = canonicalUrl(source.url) } catch { return [] }
    if (seen.has(key)) return []
    seen.add(key)
    const haystack = `${source.title} ${source.snippet} ${source.source}`.toLowerCase()
    const overlap = tokens.filter(token => haystack.includes(token)).length
    const catalog = catalogForUrl(source.url)
    const score = authority[source.quality] + roleScore[source.role] + Math.min(24, overlap * 4)
      + (catalog ? 12 : 0) + (source.snippet.length >= 160 ? 5 : 0)
    return [{ source: { ...source, url: key }, score }]
  }).sort((a, b) => b.score - a.score)

  const domainCounts = new Map<string, number>()
  const selected: SearchSource[] = []
  for (const item of scored) {
    const domain = new URL(item.source.url).hostname.replace(/^www\./, '')
    if ((domainCounts.get(domain) || 0) >= 2) continue
    selected.push(item.source)
    domainCounts.set(domain, (domainCounts.get(domain) || 0) + 1)
    if (selected.length >= limit) break
  }
  return selected
}

export async function searchComputerKnowledge(query: string, configuration: SearchProviderConfiguration = {}) {
  const plan = buildSearchPlan(query)
  const base = curatedResults(query)
  const primarySearch = configuration.exaApiKey
    ? { name: 'Exa', run: () => searchExa(plan, configuration.exaApiKey!) }
    : configuration.tavilyApiKey
      ? { name: 'Tavily', run: () => searchTavily(plan, configuration.tavilyApiKey!) }
      : { name: 'Jina Search', run: () => searchJina(plan, configuration.jinaApiKey) }
  const adapters: Array<{ name: string; run: () => Promise<SearchSource[]> }> = []
  if (base.length) adapters.push({ name: '权威原文', run: () => readCuratedPages(plan, base) })
  adapters.push(primarySearch)
  if (plan.intent === 'explanation' || plan.intent === 'comparison') adapters.push({ name: 'Wikipedia', run: () => searchWikipedia(plan, query) })
  if (plan.intent === 'troubleshooting' || plan.intent === 'implementation') adapters.push({ name: 'Stack Overflow', run: () => searchStackExchange(plan) })
  if (plan.intent === 'implementation') adapters.push({ name: 'GitHub', run: () => searchGitHub(plan) })
  const emergingExplanation = plan.intent === 'explanation' && base.length < 2
    && (/\b(?:lora|llm|transformer|rag|diffusion|bert|gpt|vit|clip)\b/i.test(plan.query) || plan.trustedDomains.length === 0 && /[A-Z]{2,}/.test(plan.topic))
  if (plan.intent === 'research' || plan.intent === 'current' || emergingExplanation) adapters.push({ name: 'arXiv', run: () => searchArxiv(plan) })

  const settled = await Promise.allSettled(adapters.map(runProvider))
  const fulfilled: ProviderResult[] = settled.flatMap(result => result.status === 'fulfilled' ? [result.value] : [])
  const remote = fulfilled.flatMap(result => result.results)
  const results = rankSearchSources(plan, [...remote, ...base])
  return {
    plan,
    results,
    providers: adapters.map((adapter, index) => {
      const result = settled[index]
      return {
        name: adapter.name,
        status: result.status === 'fulfilled' ? 'completed' as const : 'failed' as const,
        count: result.status === 'fulfilled' ? result.value.results.length : 0,
      }
    }),
    liveSources: fulfilled.filter(result => result.results.length > 0).length,
    attemptedSources: adapters.length,
  }
}
