import type { LearningTask, LearningTaskPhase } from '../../services/api'

export type LearningPackageStageStatus =
  | 'not_ready'
  | 'ready'
  | 'current'
  | 'completed'
  | 'locked'
  | 'standby'
  | 'scheduled'

export type LearningPackageStageId =
  | 'lecture'
  | 'guided_practice'
  | 'verification'
  | 'remediation'
  | 'review'

export interface LearningPackageStage {
  id: LearningPackageStageId
  order: number
  title: string
  purpose: string
  amount: string
  status: LearningPackageStageStatus
  statusLabel: string
  actionLabel?: string
  path?: string
  logicalFilename?: string
}

const statusLabels: Record<LearningPackageStageStatus, string> = {
  not_ready: '尚未准备',
  ready: '可以开始',
  current: '当前阶段',
  completed: '已经完成',
  locked: '等待前置步骤',
  standby: '答错时触发',
  scheduled: '已经安排',
}

function phaseFor(task: LearningTask, kind: LearningTaskPhase['kind']) {
  return (task.plan.phases || []).find(phase => phase.kind === kind)
}

function withView(path: string, view: string) {
  return `${path}${path.includes('?') ? '&' : '?'}view=${view}`
}

export function learningPackagePresentation(task: LearningTask) {
  const materials = task.runtime.materials
  const lectureRef = materials.lecture
    || task.artifact_refs.find(item => item.type === 'managed_lecture')
    || null
  const questionRef = materials.question_set
    || task.artifact_refs.find(item => item.type === 'concept_question_set')
    || null
  const exerciseRefs = materials.exercises?.length
    ? materials.exercises
    : task.artifact_refs.filter(item => item.type === 'managed_exercise')
  const questionIds = Array.isArray(questionRef?.ids) ? questionRef.ids : []
  const learningFlow = task.runtime.learning_flow
  const questionCount = learningFlow?.total_items || questionIds.length || exerciseRefs.length
  const packageReady = materials.status !== 'not_prepared'
  const learnPhase = phaseFor(task, 'learn')
  const practicePhase = phaseFor(task, 'practice')
  const verifyPhase = phaseFor(task, 'verify')
  const consolidatePhase = phaseFor(task, 'consolidate')
  const currentKind = task.runtime.current_phase?.kind
  const executionPath = task.navigation.path
  const focusedPackage = Boolean(task.micro_learning_run_id)
  const activeFlowState = learningFlow?.active_state || learningFlow?.state || ''
  const completedItems = learningFlow?.completed_items || 0
  const successfulVerifications = task.runtime.evidence.successful_verifications || 0
  const afterLecture = ['teach_back', 'teach_back_feedback', 'verification', 'remediation', 'completed'].includes(activeFlowState)
  const afterPractice = ['verification', 'remediation', 'completed'].includes(activeFlowState)
  const lectureCompleted = focusedPackage ? afterLecture : learnPhase?.status === 'completed'
  const practiceCompleted = focusedPackage ? afterPractice : practicePhase?.status === 'completed'
  const verificationCompleted = focusedPackage && questionCount > 0
    ? activeFlowState === 'completed' || completedItems >= questionCount
    : verifyPhase?.status === 'completed'
  const lecturePath = task.navigation.kind === 'focused_learning' && activeFlowState !== 'learning_card'
    ? withView(executionPath, 'lecture')
    : String(lectureRef?.path || executionPath)

  const lectureStatus: LearningPackageStageStatus = !lectureRef
    ? 'not_ready'
    : lectureCompleted
      ? 'completed'
      : activeFlowState === 'learning_card' || (!focusedPackage && currentKind === 'learn')
        ? 'current'
        : 'ready'

  const practiceStatus: LearningPackageStageStatus = !packageReady
    ? 'not_ready'
    : practiceCompleted
      ? 'completed'
      : !lectureCompleted
        ? 'locked'
        : ['teach_back', 'teach_back_feedback'].includes(activeFlowState) || (!focusedPackage && currentKind === 'practice')
          ? 'current'
          : 'ready'

  const verificationStatus: LearningPackageStageStatus = questionCount === 0
    ? 'not_ready'
    : verificationCompleted
      ? 'completed'
      : !practiceCompleted
        ? 'locked'
        : ['verification', 'remediation'].includes(activeFlowState) || (!focusedPackage && currentKind === 'verify')
          ? 'current'
          : 'ready'

  const reviewItems = task.runtime.evidence.review_items || 0
  const reviewStatus: LearningPackageStageStatus = reviewItems > 0
    ? 'scheduled'
    : verifyPhase?.status === 'completed'
      ? consolidatePhase?.status === 'completed' ? 'completed' : 'ready'
      : 'locked'

  const stages: LearningPackageStage[] = [
    {
      id: 'lecture',
      order: 1,
      title: '讲义学习',
      purpose: '建立概念模型、例子和常见误区，负责学习输入。',
      amount: lectureRef ? '1 份可回看的讲义' : '等待生成讲义',
      status: lectureStatus,
      statusLabel: statusLabels[lectureStatus],
      actionLabel: lectureRef ? (lectureStatus === 'completed' ? '回看讲义' : '进入讲义') : undefined,
      path: lectureRef ? lecturePath : undefined,
      logicalFilename: String(lectureRef?.logical_filename || ''),
    },
    {
      id: 'guided_practice',
      order: 2,
      title: '引导练习',
      purpose: '用费曼复述或关卡练习暴露缺口，不直接宣称掌握。',
      amount: task.micro_learning_run_id ? '1 次复述诊断' : exerciseRefs.length ? `${exerciseRefs.length} 组关卡练习` : '由 Tutor 按任务引导',
      status: practiceStatus,
      statusLabel: statusLabels[practiceStatus],
      actionLabel: ['ready', 'current'].includes(practiceStatus) ? '继续引导练习' : undefined,
      path: ['ready', 'current'].includes(practiceStatus) ? executionPath : undefined,
    },
    {
      id: 'verification',
      order: 3,
      title: '独立验证',
      purpose: '无提示提交答案；只有这里的有效结果才升级能力证据。',
      amount: questionCount
        ? completedItems > 0 ? `已完成 ${Math.min(completedItems, questionCount)}/${questionCount} 道` : successfulVerifications > 0 ? `已通过 ${Math.min(successfulVerifications, questionCount)}/${questionCount} 道` : `${questionCount} 道验证题`
        : '等待生成验证题',
      status: verificationStatus,
      statusLabel: statusLabels[verificationStatus],
      actionLabel: ['ready', 'current'].includes(verificationStatus) ? '进入独立验证' : undefined,
      path: ['ready', 'current'].includes(verificationStatus) ? executionPath : undefined,
      logicalFilename: String(questionRef?.logical_filename || ''),
    },
    {
      id: 'remediation',
      order: 4,
      title: '错题纠正',
      purpose: '答错后依次完成换讲法、原题重做和变式迁移。',
      amount: '按错误证据触发',
      status: activeFlowState === 'remediation' ? 'current' : questionCount ? 'standby' : 'locked',
      statusLabel: statusLabels[activeFlowState === 'remediation' ? 'current' : questionCount ? 'standby' : 'locked'],
      actionLabel: activeFlowState === 'remediation' ? '继续错题纠正' : undefined,
      path: activeFlowState === 'remediation' ? executionPath : undefined,
    },
    {
      id: 'review',
      order: 5,
      title: '间隔复习',
      purpose: '把通过验证的题目交给复习工作台，检查跨时间保持。',
      amount: reviewItems ? `${reviewItems} 个复习项` : '验证通过后安排',
      status: reviewStatus,
      statusLabel: statusLabels[reviewStatus],
      actionLabel: reviewItems ? '打开复习工作台' : undefined,
      path: reviewItems ? '/review' : undefined,
    },
  ]

  return {
    stages,
    packageReady,
    lectureCount: lectureRef ? 1 : 0,
    questionCount,
    completedRequiredStageCount: stages.filter(stage => stage.id !== 'remediation' && ['completed', 'scheduled'].includes(stage.status)).length,
    canMaterialize: !task.checkpoint_id && ['queued', 'active', 'paused'].includes(task.status),
  }
}
