export type TutorToolChoice = 'auto' | 'search' | 'image' | 'animation'

export type SearchSource = {
  title: string
  url: string
  snippet: string
  source: string
  quality: 'official' | 'academic' | 'community' | 'repository'
  role: 'standard' | 'reference' | 'textbook' | 'course' | 'definition' | 'research' | 'example' | 'discussion'
  reason: string
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
  kind: 'memory' | 'search' | 'image' | 'animation'
  status: 'completed' | 'failed'
  title: string
  detail: string
  durationMs: number
  sources?: SearchSource[]
  artifact?: VisualArtifact
}

export const TOOL_CHOICE_LABELS: Record<TutorToolChoice, string> = {
  auto: '自动',
  search: '联网搜索',
  image: '生成图解',
  animation: '生成动画',
}

export function isTutorToolChoice(value: unknown): value is TutorToolChoice {
  return value === 'auto' || value === 'search' || value === 'image' || value === 'animation'
}
