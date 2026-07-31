import { useEffect, useRef } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import remarkMath from 'remark-math'
import rehypeKatex from 'rehype-katex'
import 'katex/dist/katex.min.css'
import VizRenderer from '../viz/VizRenderer'

interface Section {
  title: string
  content: string
  keywords?: string[]
  questions?: string[]
}

interface Props {
  sections: Section[]
  onSelect?: (text: string, sectionIndex: number) => void
  onDeleteImage?: (sectionIndex: number, src: string) => void
}

export default function LectureRenderer({ sections, onSelect, onDeleteImage }: Props) {
  const containerRef = useRef<HTMLDivElement>(null)

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

  return (
    <div ref={containerRef} className="prose prose-sm max-w-none px-1">
      {sections.map((section, i) => (
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

          {/* Content rendered as Markdown with KaTeX */}
          <div className="lecture-content text-gray-800 leading-relaxed">
            <ReactMarkdown
              remarkPlugins={[remarkGfm, remarkMath]}
              rehypePlugins={[rehypeKatex]}
              components={{
                // Style code blocks
                code({ className, children, ...props }: any) {
                  const isInline = !className
                  // viz blocks: JSON-driven interactive visualizations
                  if (className?.includes('language-viz')) {
                    return <VizRenderer code={String(children || '').replace(/\n$/, '')} />
                  }
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
              {section.content}
            </ReactMarkdown>
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
      ))}
    </div>
  )
}
