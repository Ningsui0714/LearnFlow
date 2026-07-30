import { useState, useRef, useEffect } from 'react'
import { askQuestion } from '../../services/api'

interface Message {
  role: 'user' | 'assistant'
  content: string
}

interface Props {
  checkpointId: number
  selectedText: string
  onClose: () => void
}

export default function BottomWorkspace({ checkpointId, selectedText, onClose }: Props) {
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const endRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  // Auto-ask when text is newly selected
  useEffect(() => {
    if (selectedText && messages.length === 0) {
      setMessages([{ role: 'user', content: `关于「${selectedText.slice(0, 80)}...」的提问` }])
    }
  }, [selectedText])

  const send = async () => {
    if (!input.trim() || loading) return
    const text = input.trim()
    setInput('')

    const userMsg: Message = { role: 'user', content: text }
    setMessages(prev => [...prev, userMsg])
    setLoading(true)

    try {
      const res = await askQuestion(checkpointId, {
        selection: selectedText,
        question: text,
        history: messages.map(m => ({ role: m.role, content: m.content })),
      })
      setMessages(prev => [...prev, { role: 'assistant', content: res.answer }])
    } catch (e: any) {
      const errMsg = e?.response?.data?.detail || '请求失败'
      setMessages(prev => [...prev, { role: 'assistant', content: `❌ ${errMsg}` }])
    }
    setLoading(false)
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      send()
    }
  }

  return (
    <div className="border-t border-gray-200 bg-white flex flex-col"
         style={{ height: '280px' }}>
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-2 border-b border-gray-100 shrink-0">
        <div className="flex items-center gap-2 text-sm">
          <span className="w-2 h-2 rounded-full bg-primary-400" />
          <span className="font-medium text-gray-700">追问工作区</span>
          {selectedText && (
            <span className="text-xs text-gray-400 truncate max-w-[300px]">
              「{selectedText.slice(0, 50)}...」
            </span>
          )}
        </div>
        <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-sm px-1">
          ✕
        </button>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-4 py-2 space-y-2">
        {messages.length === 0 && (
          <div className="text-center text-gray-400 text-xs py-6">
            选中讲义中的文字，然后在下方输入问题
          </div>
        )}
        {messages.map((m, i) => (
          <div key={i} className={`flex ${m.role === 'user' ? 'justify-end' : 'justify-start'}`}>
            <div className={`
              max-w-[85%] rounded-lg px-3 py-2 text-sm whitespace-pre-wrap
              ${m.role === 'user'
                ? 'bg-primary-600 text-white'
                : 'bg-gray-100 text-gray-800'
              }
            `}>
              {m.content}
            </div>
          </div>
        ))}
        {loading && (
          <div className="flex justify-start">
            <div className="bg-gray-100 rounded-lg px-3 py-2 text-sm text-gray-400">
              <span className="animate-pulse">思考中...</span>
            </div>
          </div>
        )}
        <div ref={endRef} />
      </div>

      {/* Input */}
      <div className="border-t border-gray-100 px-4 py-2 shrink-0">
        <div className="flex gap-2">
          <input
            type="text"
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="输入追问... (Enter 发送)"
            className="flex-1 border border-gray-300 rounded-lg px-3 py-1.5 text-sm
                       focus:outline-none focus:ring-2 focus:ring-primary-400"
          />
          <button
            onClick={send}
            disabled={loading || !input.trim()}
            className="bg-primary-600 text-white px-3 py-1.5 rounded-lg text-sm
                       hover:bg-primary-700 disabled:bg-gray-300 transition-colors"
          >
            发送
          </button>
        </div>
      </div>
    </div>
  )
}
