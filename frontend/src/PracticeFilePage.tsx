import { useEffect, useState } from 'react'
import {
  loadPracticeFile,
  recordLearningFileAccess,
  submitFormalConceptAnswer,
  submitFormalExercise,
} from './formal-runtime'

type Props = {
  practiceRef: string
  embedded?: boolean
  conversationId?: string
  sheetId?: string
  onAttach?: (file: { kind: 'practice'; ref: string; title: string }) => void
}

export default function PracticeFilePage({ practiceRef, embedded, conversationId, sheetId, onAttach }: Props) {
  const [file, setFile] = useState<Awaited<ReturnType<typeof loadPracticeFile>>>()
  const [answers, setAnswers] = useState<Record<number, number[]>>({})
  const [results, setResults] = useState<Record<number, { correct: boolean; answer_indexes: number[] }>>({})
  const [code, setCode] = useState('')
  const [codeResult, setCodeResult] = useState<{ passed: boolean; stdout?: string; stderr?: string }>()
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  useEffect(() => {
    let alive = true
    void loadPracticeFile(practiceRef).then(result => {
      if (!alive) return
      setFile(result); setCode(result.starter_code || '')
      void recordLearningFileAccess('practice', practiceRef, 'opened', { conversation_id: conversationId, sheet_id: sheetId }).catch(() => undefined)
    }).catch(failure => alive && setError(failure instanceof Error ? failure.message : '练习读取失败'))
    return () => { alive = false }
  }, [practiceRef, conversationId, sheetId])
  if (error) return <div className="formal-inline-error">{error}</div>
  if (!file) return <div className="page-loading">正在打开正式练习…</div>
  const submitQuestion = async (questionId: number) => {
    setBusy(`question:${questionId}`)
    try {
      const result = await submitFormalConceptAnswer(file.checkpoint_id, questionId, answers[questionId] || [])
      setResults(previous => ({ ...previous, [questionId]: result }))
    }
    catch (failure) { setError(failure instanceof Error ? failure.message : '提交失败') }
    finally { setBusy('') }
  }
  const submitCode = async () => {
    if (!file.id) return
    setBusy('code')
    try { setCodeResult(await submitFormalExercise(file.id, code)) }
    catch (failure) { setError(failure instanceof Error ? failure.message : '代码评估失败') }
    finally { setBusy('') }
  }
  return (
    <section className={`practice-file-workbench${embedded ? ' learning-file-embedded' : ''}`}>
      <header className="learning-file-workbench-heading"><div><span>PRACTICE · ANSWER SAFE</span><h1>{file.title}</h1><code>{file.logical_filename}</code></div>{onAttach && !embedded && <button type="button" onClick={() => onAttach({ kind: 'practice', ref: file.ref, title: file.title })}>作为对话纸张打开</button>}</header>
      <div className="learning-evidence-notice">答案与解释在提交前隔离。正式提交会建立 Attempt，经确定性判题后才写入 Knowledge / Practice 证据。</div>
      {file.practice_kind === 'concept_question_set' ? <div className="practice-question-list">{(file.questions || []).map((question, index) => {
        const selected = answers[question.id] || []
        const result = results[question.id]
        return <article key={question.id}><span>QUESTION {String(index + 1).padStart(2, '0')} · {question.difficulty}</span><h2>{question.question}</h2><div className="practice-options">{question.options.map((option, optionIndex) => <label key={optionIndex} className={selected.includes(optionIndex) ? 'selected' : ''}><input type={question.q_type === 'multi' ? 'checkbox' : 'radio'} name={`q-${question.id}`} checked={selected.includes(optionIndex)} disabled={Boolean(result)} onChange={() => setAnswers(previous => ({ ...previous, [question.id]: question.q_type === 'multi' ? (selected.includes(optionIndex) ? selected.filter(item => item !== optionIndex) : [...selected, optionIndex]) : [optionIndex] }))} /><i>{String.fromCharCode(65 + optionIndex)}</i><span>{option}</span></label>)}</div><button type="button" disabled={!selected.length || Boolean(result) || Boolean(busy)} onClick={() => void submitQuestion(question.id)}>{busy === `question:${question.id}` ? '判定中…' : result ? result.correct ? '回答正确' : '回答有误' : '提交独立作答'}</button>{result && <p className={result.correct ? 'practice-correct' : 'practice-wrong'}>{result.correct ? '正确。该结果已进入正式证据链，但一次答对仍不等于稳定掌握。' : `本次未通过。正确选项：${result.answer_indexes.map(item => String.fromCharCode(65 + item)).join('、')}。系统会保留具体错误证据。`}</p>}</article>
      })}</div> : <div className="code-practice-surface"><p>{file.description}</p><textarea value={code} onChange={event => setCode(event.target.value)} spellCheck={false} /><button type="button" disabled={Boolean(busy) || !code.trim()} onClick={() => void submitCode()}>{busy === 'code' ? '正在沙箱判题…' : '提交代码并验证'}</button>{codeResult && <pre className={codeResult.passed ? 'practice-correct' : 'practice-wrong'}>{codeResult.passed ? '全部验证通过' : '验证未通过'}{codeResult.stdout ? `\n${codeResult.stdout}` : ''}{codeResult.stderr ? `\n${codeResult.stderr}` : ''}</pre>}</div>}
    </section>
  )
}
