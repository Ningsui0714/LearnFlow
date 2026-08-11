import { useEffect, useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import remarkMath from 'remark-math'
import rehypeKatex from 'rehype-katex'
import 'katex/dist/katex.min.css'
import ProcessAnimationViewer from '../animation/ProcessAnimationViewer'
import { getAnimation, ProcessAnimation } from '../../services/api'

/** Repair block delimiters before remark-math sees them.
 *
 * Generated Markdown occasionally opens a display formula with `$$` and
 * closes it with a bare code fence. Without this guard remark-math consumes
 * the rest of the section as one invalid formula, including later code blocks.
 */
export function repairMarkdownFences(md: string): string {
  const lines = md.split('\n')
  const output: string[] = []
  let mathOpen = false
  let codeMarker = ''
  let codeMarkerLength = 0

  for (const line of lines) {
    const trimmed = line.trim()
    if (codeMarker) {
      output.push(line)
      const closing = new RegExp(`^${codeMarker === '`' ? '`' : '~'}{${codeMarkerLength},}\\s*$`)
      if (closing.test(trimmed)) {
        codeMarker = ''
        codeMarkerLength = 0
      }
      continue
    }

    if (trimmed === '$$') {
      output.push(line)
      mathOpen = !mathOpen
      continue
    }

    const fence = trimmed.match(/^(`{3,}|~{3,})(.*)$/)
    if (fence) {
      if (mathOpen) {
        if (fence[2].trim()) {
          output.push('$$')
          output.push(line)
          codeMarker = fence[1][0]
          codeMarkerLength = fence[1].length
        } else {
          output.push(line.replace(trimmed, () => '$$'))
        }
        mathOpen = false
        continue
      }
      output.push(line)
      codeMarker = fence[1][0]
      codeMarkerLength = fence[1].length
      continue
    }

    output.push(line)
  }

  if (mathOpen) output.push('$$')
  return output.join('\n')
}

function normalizeMarkdown(md: string): string {
  return repairMarkdownFences(md).replace(
    /^\$\$[ \t]*(\\begin\{([^}]+)\})\n([\s\S]*?)\\end\{\2\}[ \t]*\$\$$/gm,
    (_m, openEnv: string, environment: string, body: string) =>
      `$$\n${openEnv}\n${body}\\end{${environment}}\n$$`
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
        pre({ children }: any) {
          return (
            <pre className="bg-gray-900 text-gray-100 rounded-lg p-4 overflow-x-auto text-sm">
              {children}
            </pre>
          )
        },
        code({ className, children, ...props }: any) {
          const content = String(children ?? '')
          const isBlock = Boolean(className) || content.includes('\n')
          if (!isBlock) {
            return <code className="bg-gray-100 text-red-600 px-1 rounded text-sm" {...props}>{children}</code>
          }
          return <code className={className} {...props}>{children}</code>
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
      {normalizeMarkdown(content)}
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
