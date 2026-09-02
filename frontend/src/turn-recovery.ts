import type { TutorMode, TutorContextMessage } from './tutor.ts'
import type { TutorToolRun } from './tooling.ts'

export type TutorTurnMessage = {
  role: 'assistant' | 'user' | 'system'
  content: string
  tutorMode?: TutorMode
  toolRuns?: TutorToolRun[]
  reasoningContent?: string
}

export function recoverableTutorTurn(messages: TutorTurnMessage[], pending: boolean) {
  if (pending) return undefined
  const latest = messages[messages.length - 1]
  return latest?.role === 'user' && latest.content.trim() ? latest : undefined
}

export function buildTutorContextMessages(
  messages: TutorTurnMessage[],
  content: string,
  replayInterruptedTurn = false,
): TutorContextMessage[] {
  const existing = messages
    .filter((message): message is TutorTurnMessage & { role: 'assistant' | 'user' } => message.role !== 'system')
    .map(message => ({
      role: message.role,
      content: message.content,
      ...(message.toolRuns ? { toolRuns: message.toolRuns } : {}),
      ...(message.reasoningContent ? { reasoningContent: message.reasoningContent } : {}),
    }))
  return replayInterruptedTurn ? existing : [...existing, { role: 'user', content }]
}
