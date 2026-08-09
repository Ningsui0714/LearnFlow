import { useEffect, useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import remarkMath from 'remark-math'
import rehypeKatex from 'rehype-katex'
import 'katex/dist/katex.min.css'
import ProcessAnimationViewer from '../animation/ProcessAnimationViewer'
import { getAnimation, ProcessAnimation } from '../../services/api'

/**
 * remark-math 的显示公式解析要求 `$$` 独占一行：
 * - 若 `$$` 同行紧跟着内容（如 `$$\begin{aligned}`），该内容会被当作 fence 元信息（类似 ```python 的 python）丢弃；
 * - 行尾的 `$$`（如 `\end{aligned}$$`）不满足「闭合 fence 必须在行首」的规则，不会被认作闭合符，
 *   导致 math 节点吞掉后续整段文档，KaTeX 收到残缺输入 → 解析失败 → 渲染成红色 katex-error。
 * LLM 经常输出 `$$\begin{aligned}...\end{aligned}$$` 的多行同行写法，这里在渲染前归一化。
 * 注意：替换串必须用函数返回，不能用字符串字面量（字符串里 `$$` 会被 JS 解释成单个 `$`）。
 * 只匹配多行块，单行 `$$...$$` 公式不受影响。
 */
function normalizeMath(md: string): string {
  return md.replace(
    /^\$\$[ \t]*(\\begin\{[^}]+})?\n([\s\S]*?)\\end\{([^}]+)\}[ \t]*\$\$$/gm,
    (_m, openEnv: string | undefined, body: string, closeEnv: string) =>
      openEnv
        ? `$$\n${openEnv}\n${body}\\end{${closeEnv}}\n$$`
        : `$$\n${body}\\end{${closeEnv}}\n$$`
  )
}

/**
 * 拆分讲义小节内容：markdown 文本与 process-animator 占位符
 * `:::process-anim {id}` → {type:'anim', id}
 */
const ANIM_MARKER_RE = /^:::\s*process-anim\s+(\d+)\s*$/gm

function splitContent(content: string): Array<{ type: 'md'; text: string } | { type: 'anim'; id: number }> {
  const parts: Array<{ type: 'md'; text: string } | { type: 'anim'; id: number }> = []
  ANIM_MARKER_RE.lastIndex = 0
  let last = 0
  let m: RegExpExecArray | null
  while ((m = ANIM_MARKER_RE.exec(content))) {
    if (m.index > last) parts.push({ type: 'md', text: content.slice(last, m.index) })
    parts.push({ type: 'anim', id: Number(m[1]) })
    last = m.index + m[0].length
  }
  if (last < content.length) parts.push({ type: 'md', text: content.slice(last) })
  return parts
}

interface Section {
  title: string
  content: string
  keywords?: string[]
  questions?: string[]
}

interface Props {
  sections: Section[]
  animations?: Record<number, ProcessAnimation>
  onSelect?: (text: string, sectionIndex: number) => void
  onDeleteImage?: (sectionIndex: number, src: string) => void
}

export default function LectureRenderer({ sections, animations, onSelect, onDeleteImage }: Props) {
  const containerRef = useRef<HTMLDivElement>(null)
  // 懒加载：讲义里出现但 props 里没有的动画（快照流/续生成场景）按 id 拉取
  const [lazy, setLazy] = useState<Record<number, ProcessAnimation>>({})

  useEffect(() => {
    const need: number[] = []
    for (const s of sections || []) {
      ANIM_MARKER_RE.lastIndex = 0
      let m: RegExpExecArray | null
      while ((m = ANIM_MARKER_RE.exec(s.content || ''))) {
        const id = Number(m[1])
        if (!animations?.[id] && !lazy[id] && !need.includes(id)) need.push(id)
      }
    }
    if (!need.length) return
    let alive = true
    need.forEach(id => {
      getAnimation(id)
        .then((a: ProcessAnimation) => { if (alive) setLazy(prev => ({ ...prev, [id]: a })) })
        .catch(() => {})
    })
    return () => { alive = false }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sections, animations])

  // Handle text selection
  useEffect(() => {
    const handleMouseUp = () => {
      const sel = window.getSelection()
      const text = sel?.toString().trim()
      if (text && text.length > 0 && onSelect) {
        // Find the section container via the selection anchor
        let node = sel?.anchorNode as HTMLElement | null
        let sectionIndex = 0
        while (node && node !== document.body) {
          const attr = node.getAttribute?.('data-section-index')
          if (attr !== undefined && attr !== null) {
            sectionIndex = Number(attr)
            break
          }
          node = node.parentElement
        }
        onSelect(text, sectionIndex)
      }
    }
    document.addEventListener('mouseup', handleMouseUp)
    return () => document.removeEventListener('mouseup', handleMouseUp)
  }, [onSelect])

  if (!sections || sections.length === 0) {
    return (
      <div className="text-center text-gray-400 py-16">
        <p className="text-4xl mb-2">📖</p>
        <p>暂无讲义内容</p>
      </div>
    )
  }

  // markdown 渲染配置（每个小节闭包 i，用于图片删除/选中定位）
  const renderMarkdown = (content: string, i: number) => (
    <ReactMarkdown
      remarkPlugins={[remarkGfm, remarkMath]}
      rehypePlugins={[rehypeKatex]}
      components={{
        // Style code blocks
        code({ className, children, ...props }: any) {
          const isInline = !className
          if (isInline) {
            return <code className="bg-gray-100 text-red-600 px-1 rounded text-sm" {...props}>{children}</code>
          }
          return (
            <pre className="bg-gray-900 text-gray-100 rounded-lg p-4 overflow-x-auto text-sm">
              <code className={className} {...props}>{children}</code>
            </pre>
          )
        },
        // Images: hover to delete (T6)
        img({ src, alt }: any) {
          return (
            <span className="relative inline-block group my-2">
              <img src={src} alt={alt || ''}
                   className="max-w-full rounded-lg border border-gray-200" />
              {onDeleteImage && (
                <button
                  onClick={() => onDeleteImage(i, src)}
                  title="删除这张图片"
                  className="absolute -top-2 -right-2 w-6 h-6 rounded-full bg-red-500 text-white
                             text-xs opacity-0 group-hover:opacity-100 transition-opacity
                             shadow hover:bg-red-600"
                >
                  ✕
                </button>
              )}
            </span>
          )
        },
        // Style blockquotes (used for questions)
        blockquote({ children }: any) {
          return (
            <blockquote className="border-l-4 border-primary-300 bg-primary-50
                                    pl-4 py-2 my-4 rounded-r-lg text-sm text-gray-700">
              {children}
            </blockquote>
          )
        },
      }}
    >
      {normalizeMath(content)}
    </ReactMarkdown>
  )

  return (
    <div ref={containerRef} className="prose prose-sm max-w-none px-1">
      {sections.map((section, i) => {
        const parts = splitContent(section.content || '')
        return (
          <div key={i} data-section-index={i} className="mb-10">
            {/* Section header */}
            <div className="flex items-center gap-3 mb-4 pb-3 border-b border-gray-200">
              <span className="w-7 h-7 rounded-full bg-primary-100 text-primary-700
                               flex items-center justify-center text-xs font-bold shrink-0">
                {i + 1}
              </span>
              <h2 className="text-lg font-bold text-gray-900 m-0">{section.title}</h2>
            </div>

            {/* Keywords */}
            {section.keywords && section.keywords.length > 0 && (
              <div className="flex flex-wrap gap-1.5 mb-3">
                {section.keywords.map((kw, j) => (
                  <span key={j} className="text-xs bg-gray-100 text-gray-600 px-2 py-0.5 rounded-full">
                    {kw}
                  </span>
                ))}
              </div>
            )}

            {/* Content: markdown + process-animator 动画块 */}
            <div className="lecture-content text-gray-800 leading-relaxed">
              {parts.map((part, j) => {
                if (part.type === 'md') {
                  return <div key={j}>{renderMarkdown(part.text, i)}</div>
                }
                const anim = animations?.[part.id] ?? lazy[part.id]
                if (!anim) {
                  return (
                    <div key={j} className="my-4 rounded-lg border border-dashed border-gray-300 text-xs text-gray-400 px-3 py-2">
                      🎞️ 过程动画 #{part.id}（加载中或已失效）
                    </div>
                  )
                }
                return <ProcessAnimationViewer key={j} animation={anim} />
              })}
            </div>

            {/* Questions */}
            {section.questions && section.questions.length > 0 && (
              <div className="mt-4 pt-3 border-t border-dashed border-gray-200">
                <p className="text-xs font-semibold text-gray-500 mb-1.5 uppercase tracking-wider">
                  💡 思考题
                </p>
                <ul className="space-y-1">
                  {section.questions.map((q, j) => (
                    <li key={j} className="text-sm text-gray-600">{q}</li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}
