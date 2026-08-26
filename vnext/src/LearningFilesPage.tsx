import { useEffect, useState } from 'react'
import { loadLearningFiles, type FormalLearningFileRef } from './formal-runtime'

type Props = { onOpen: (file: FormalLearningFileRef) => void }

export default function LearningFilesPage({ onOpen }: Props) {
  const [lectures, setLectures] = useState<FormalLearningFileRef[]>([])
  const [practices, setPractices] = useState<FormalLearningFileRef[]>([])
  const [error, setError] = useState('')
  const refresh = async () => {
    try {
      const result = await loadLearningFiles()
      setLectures(result.lectures); setPractices(result.practices); setError('')
    } catch (failure) { setError(failure instanceof Error ? failure.message : '学习文件读取失败') }
  }
  useEffect(() => { void refresh() }, [])
  return (
    <section className="learning-files-page">
      <header className="file-page-heading"><div><span className="eyebrow">MANAGED LEARNING FILES</span><h1>讲义与练习</h1><p>这是正式学习对象的播放器，不是普通文件夹。讲义有版本和来源；练习隐藏答案并通过正式提交形成证据。</p></div><button type="button" onClick={() => void refresh()}>刷新</button></header>
      {error && <div className="formal-inline-error">{error}</div>}
      <div className="learning-file-columns">
        <section><header><span>LECTURES</span><h2>讲义</h2><i>{lectures.length}</i></header>{lectures.length === 0 && <p className="formal-empty-copy">学习任务生成后，讲义会出现在这里。</p>}{lectures.map(file => <FileCard key={`${file.kind}:${file.ref}`} file={file} onOpen={onOpen} />)}</section>
        <section><header><span>PRACTICE</span><h2>练习</h2><i>{practices.length}</i></header>{practices.length === 0 && <p className="formal-empty-copy">学习任务生成后，概念验证和代码练习会出现在这里。</p>}{practices.map(file => <FileCard key={`${file.kind}:${file.ref}`} file={file} onOpen={onOpen} />)}</section>
      </div>
    </section>
  )
}

function FileCard({ file, onOpen }: { file: FormalLearningFileRef; onOpen: (file: FormalLearningFileRef) => void }) {
  return <article className="learning-file-card"><span>{file.kind === 'lecture' ? '讲义文件' : file.practice_kind === 'concept_question_set' ? '概念验证' : '代码练习'}</span><h3>{file.title}</h3><code>{file.logical_filename}</code><small>{file.question_count ? `${file.question_count} 道题 · ` : ''}Checkpoint #{file.checkpoint_id}</small><button type="button" onClick={() => onOpen(file)}>打开工作台</button></article>
}
