import { useEffect, useId, useRef } from 'react'
import { AlertTriangle, Loader2, Trash2, X } from 'lucide-react'


interface DeleteConfirmationDialogProps {
  open: boolean
  itemType: '对话' | '项目'
  itemName: string
  consequence: string
  busy?: boolean
  onCancel: () => void
  onConfirm: () => void | Promise<void>
}


export default function DeleteConfirmationDialog({
  open,
  itemType,
  itemName,
  consequence,
  busy = false,
  onCancel,
  onConfirm,
}: DeleteConfirmationDialogProps) {
  const titleId = useId()
  const descriptionId = useId()
  const cancelRef = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    if (!open) return
    cancelRef.current?.focus()
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && !busy) onCancel()
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [busy, onCancel, open])

  if (!open) return null

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center bg-slate-950/45 p-4 backdrop-blur-[1px]">
      <section
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={descriptionId}
        className="w-full max-w-md rounded-2xl border border-slate-200 bg-white p-5 shadow-2xl"
      >
        <div className="flex items-start gap-3">
          <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-rose-50 text-rose-700">
            <AlertTriangle size={20} />
          </span>
          <div className="min-w-0 flex-1">
            <h2 id={titleId} className="text-base font-semibold text-slate-900">确认删除{itemType}？</h2>
            <p className="mt-1 break-words text-sm font-medium text-slate-700">{itemName || `未命名${itemType}`}</p>
          </div>
          <button
            type="button"
            aria-label="关闭删除确认"
            onClick={onCancel}
            disabled={busy}
            className="rounded-lg p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-700 disabled:opacity-40"
          >
            <X size={17} />
          </button>
        </div>
        <p id={descriptionId} className="mt-4 rounded-xl bg-amber-50 px-3 py-2.5 text-xs leading-5 text-amber-900">
          {consequence} 已形成的练习、复习与学习证据会保留。
        </p>
        <div className="mt-5 flex justify-end gap-2">
          <button
            ref={cancelRef}
            type="button"
            onClick={onCancel}
            disabled={busy}
            className="rounded-lg border border-slate-200 px-3.5 py-2 text-sm font-medium text-slate-600 hover:bg-slate-50 disabled:opacity-40"
          >
            取消
          </button>
          <button
            type="button"
            onClick={() => void onConfirm()}
            disabled={busy}
            className="flex items-center gap-1.5 rounded-lg bg-rose-700 px-3.5 py-2 text-sm font-semibold text-white hover:bg-rose-800 disabled:bg-rose-300"
          >
            {busy ? <Loader2 size={15} className="animate-spin" /> : <Trash2 size={15} />}
            {busy ? '删除中…' : `删除${itemType}`}
          </button>
        </div>
      </section>
    </div>
  )
}
