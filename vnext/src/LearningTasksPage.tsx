import type { FormalLearningTask, FormalRuntimeConnection } from './formal-runtime'

const STATUS_LABELS: Record<FormalLearningTask['status'], string> = {
  proposed: '待确认', queued: '待开始', active: '进行中', paused: '已暂停', completed: '已完成', canceled: '已取消',
}

type Props = {
  connection: FormalRuntimeConnection
  tasks: FormalLearningTask[]
  busyTaskId?: number
  error: string
  onRefresh: () => void
  onAction: (task: FormalLearningTask, action: 'start' | 'pause' | 'resume' | 'cancel' | 'reopen') => void
}

export default function LearningTasksPage({ connection, tasks, busyTaskId, error, onRefresh, onAction }: Props) {
  const active = tasks.filter(task => !['completed', 'canceled'].includes(task.status))
  return (
    <section className="task-queue-page">
      <header className="task-queue-heading">
        <div><span className="eyebrow">ATOMIC LEARNING QUEUE</span><h1>学习任务队列</h1><p>对话中识别出的原子学习任务会进入这里。队列负责安排与恢复；具体学习仍回到原对话中完成。</p></div>
        <button type="button" onClick={onRefresh}>刷新正式队列</button>
      </header>
      <div className={`formal-runtime-strip formal-runtime-${connection.status}`}><i /> <strong>{connection.status === 'connected' ? '正式事件链已连接' : '正式事件链未连接'}</strong><span>{connection.detail}</span></div>
      {error && <div className="formal-inline-error" role="alert">{error}</div>}
      <div className="task-queue-summary"><strong>{active.length}</strong><span>个待完成任务</span><small>任务完成只表示流程结束，不自动宣称知识掌握。</small></div>
      <div className="task-queue-list">
        {tasks.length === 0 && <div className="formal-empty-copy">还没有正式学习任务。在对话中说“带我学……”或切到带领学习态即可创建。</div>}
        {tasks.map((task, index) => (
          <article key={task.id} className={`task-queue-card task-status-${task.status}`}>
            <span className="task-queue-order">{String(index + 1).padStart(2, '0')}</span>
            <div className="task-queue-copy"><span>{STATUS_LABELS[task.status]} · {task.estimated_minutes} 分钟</span><h2>{task.title}</h2><p>{task.objective}</p><small>{task.success_criteria?.[0] || '按任务计划完成可检查的学习动作'}</small></div>
            <div className="task-queue-actions">
              {task.available_actions.includes('start') && <button type="button" disabled={busyTaskId === task.id} onClick={() => onAction(task, 'start')}>开始</button>}
              {task.available_actions.includes('pause') && <button type="button" disabled={busyTaskId === task.id} onClick={() => onAction(task, 'pause')}>暂停</button>}
              {task.available_actions.includes('resume') && <button type="button" disabled={busyTaskId === task.id} onClick={() => onAction(task, 'resume')}>恢复</button>}
              {task.available_actions.includes('cancel') && <button type="button" className="task-cancel" disabled={busyTaskId === task.id} onClick={() => onAction(task, 'cancel')}>取消</button>}
              {task.available_actions.includes('reopen') && <button type="button" disabled={busyTaskId === task.id} onClick={() => onAction(task, 'reopen')}>重新加入</button>}
            </div>
          </article>
        ))}
      </div>
    </section>
  )
}
