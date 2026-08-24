import type {
  LearningTask,
  LearningTaskStatus,
  LearningTaskSurfaceKind,
} from '../../services/api'

export const learningTaskStatusLabel: Record<LearningTaskStatus, string> = {
  proposed: '待确认',
  queued: '待开始',
  active: '进行中',
  paused: '已暂停',
  completed: '已完成',
  canceled: '已移除',
}

const surfaceCopy: Record<LearningTaskSurfaceKind, {
  label: string
  currentTitle: string
  description: string
}> = {
  conversation: {
    label: '原对话',
    currentTitle: '当前正在这段对话中学习',
    description: 'Tutor 会在这段对话里继续同一个目标、方法和完成条件。',
  },
  checkpoint: {
    label: '项目关卡',
    currentTitle: '当前正在本关学习',
    description: '这个关卡就是任务的学习现场，讲义、练习和关卡 Tutor 共用同一任务。',
  },
  focused_learning: {
    label: '专注学习',
    currentTitle: '当前正在专注学习中',
    description: '这里集中完成已保存的讲义、复述、正式验证和纠错。',
  },
  task: {
    label: '任务计划',
    currentTitle: '当前正在任务控制台中',
    description: '这个任务还没有独立学习现场；先在这里开始或准备学习包。',
  },
}

export type CurrentLearningSurface = LearningTaskSurfaceKind | 'project' | 'review'

export function learningTaskOriginLabel(task: Pick<LearningTask, 'origin_kind'>): string {
  const labels: Record<string, string> = {
    checkpoint: '来自项目关卡',
    conversation: '来自对话',
    recommendation: '来自 Tutor 建议',
    skill: '来自对话方法',
    micro_learning: '来自快速学习',
    manual: '手动添加',
  }
  return labels[task.origin_kind] || '学习任务'
}

export function learningTaskPresentation(
  task: LearningTask,
  currentSurface?: CurrentLearningSurface,
) {
  const target = surfaceCopy[task.navigation.kind]
  const isCurrentSurface = currentSurface === task.navigation.kind
  let locationTitle = isCurrentSurface
    ? target.currentTitle
    : `继续学习将进入${target.label}`
  let locationDescription = target.description

  if (currentSurface === 'conversation' && task.navigation.kind === 'focused_learning') {
    locationTitle = '当前对话保留任务上下文'
    locationDescription = '正式讲义与验证已经准备好；继续学习会进入专注学习，之后仍可返回本对话。'
  } else if (currentSurface === 'task') {
    locationTitle = task.navigation.kind === 'task'
      ? '当前在任务控制台准备学习现场'
      : `任务控制台只负责管理；继续学习将进入${target.label}`
  } else if (currentSurface === 'project' && task.navigation.kind === 'checkpoint') {
    locationTitle = '点击关卡即可进入学习任务'
  }

  let primaryActionLabel = `进入${target.label}`
  if (task.status === 'proposed') primaryActionLabel = '加入学习任务'
  else if (task.status === 'queued') {
    primaryActionLabel = task.navigation.kind === 'task'
      ? '开始任务'
      : `开始并进入${target.label}`
  } else if (task.status === 'paused') primaryActionLabel = '从暂停处继续'
  else if (task.status === 'canceled') primaryActionLabel = '重新加入任务'
  else if (task.status === 'completed') {
    primaryActionLabel = task.runtime.evidence.review_items > 0 ? '查看复习安排' : '查看完成记录'
  } else if (task.navigation.kind === 'task') primaryActionLabel = '准备讲义与验证题'
  else if (isCurrentSurface && currentSurface === 'conversation') primaryActionLabel = '继续在当前对话学习'
  else if (isCurrentSurface && currentSurface === 'checkpoint') primaryActionLabel = '继续本关学习'
  else if (isCurrentSurface && currentSurface === 'focused_learning') primaryActionLabel = '继续当前学习'

  return {
    statusLabel: learningTaskStatusLabel[task.status],
    originLabel: learningTaskOriginLabel(task),
    targetLabel: target.label,
    targetDescription: target.description,
    locationTitle,
    locationDescription,
    primaryActionLabel,
    isCurrentSurface,
  }
}
