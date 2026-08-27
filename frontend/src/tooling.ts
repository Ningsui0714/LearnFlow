import type { LearningPathPlanProposal, PersonalPathNodeProposal } from './learning-path-graph.ts'
import type { ProjectLearningFileProposal, ProjectRoadmapProposal } from './project.ts'

export type TutorToolChoice = 'auto' | 'domain' | 'search' | 'image' | 'animation'

export type SearchSource = {
  id?: string
  title: string
  url: string
  snippet: string
  source: string
  quality: 'official' | 'academic' | 'community' | 'repository'
  role: 'standard' | 'reference' | 'textbook' | 'course' | 'definition' | 'research' | 'example' | 'discussion'
  reason: string
  provider?: string
  facetIds?: string[]
  publishedAt?: string
  retrievedAt?: string
  retrievalScore?: number
  readState?: 'catalog_summary' | 'search_snippet' | 'page_excerpt'
}

export type VisualStep = {
  title: string
  text: string
  svg: string
}

export type VisualArtifact = {
  kind: 'image' | 'animation'
  title: string
  subtitle: string
  steps: VisualStep[]
}

export type TutorToolRun = {
  id: string
  kind: 'memory' | 'workspace' | 'domain' | 'review' | 'path' | 'project' | 'assessment' | 'file' | 'search' | 'video' | 'image' | 'animation'
  status: 'running' | 'completed' | 'failed'
  title: string
  detail: string
  durationMs: number
  startedAt?: number
  sequence?: number
  toolName?: string
  toolCallId?: string
  inputSummary?: string
  observationSummary?: string
  errorType?: 'transient' | 'model_recoverable' | 'user_fixable' | 'unexpected'
  sources?: SearchSource[]
  searchMeta?: {
    intent?: string
    depth?: string
    status?: string
    coverageRatio?: number
    coverageGaps?: string[]
    pageRead?: boolean
  }
  artifact?: VisualArtifact
  pathProposal?: PersonalPathNodeProposal
  pathPlanProposal?: LearningPathPlanProposal
  projectRoadmapProposal?: ProjectRoadmapProposal
  projectLearningFileProposal?: ProjectLearningFileProposal
  assessmentBlueprint?: {
    id: number
    rubricId: number
    title: string
    purpose: string
    itemCount: number
  }
  learningFile?: {
    kind: 'lecture' | 'practice' | 'source'
    ref: string
    title: string
    checkpointId?: number
    questionCount?: number
    qualityStatus?: string
  }
}

export const TOOL_CHOICE_LABELS: Record<TutorToolChoice, string> = {
  auto: '自动',
  domain: '对话资料',
  search: '联网搜索',
  image: '生成图解',
  animation: '生成动画',
}

export function isTutorToolChoice(value: unknown): value is TutorToolChoice {
  return value === 'auto' || value === 'domain' || value === 'search' || value === 'image' || value === 'animation'
}
