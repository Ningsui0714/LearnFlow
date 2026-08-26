import { useEffect, useMemo, useState } from 'react'
import type { VisualArtifact as VisualArtifactData } from './tooling'

const SAFE_TAGS = new Set([
  'svg', 'g', 'circle', 'rect', 'line', 'path', 'text', 'polygon', 'polyline',
  'marker', 'defs', 'title', 'desc', 'tspan', 'ellipse', 'linearGradient',
  'radialGradient', 'stop',
])

const SAFE_ATTRS = new Set([
  'viewBox', 'preserveAspectRatio', 'fill', 'stroke', 'stroke-width',
  'stroke-dasharray', 'stroke-linecap', 'stroke-linejoin', 'opacity', 'transform',
  'x', 'y', 'x1', 'y1', 'x2', 'y2', 'cx', 'cy', 'r', 'rx', 'ry', 'width',
  'height', 'd', 'points', 'font-size', 'font-weight', 'text-anchor',
  'font-family', 'marker-end', 'marker-start', 'id', 'offset', 'stop-color',
  'stop-opacity', 'gradientUnits', 'paint-order', 'xmlns',
  'refX', 'refY', 'markerWidth', 'markerHeight', 'orient',
])

function sanitizeSvg(raw: string) {
  if (!raw || raw.length > 80_000) return ''
  const documentNode = new DOMParser().parseFromString(raw, 'image/svg+xml')
  if (documentNode.querySelector('parsererror')) return ''
  const root = documentNode.documentElement
  if (root.tagName !== 'svg') return ''

  for (const element of Array.from(root.querySelectorAll('*'))) {
    if (!SAFE_TAGS.has(element.tagName)) {
      element.remove()
      continue
    }
    for (const attribute of Array.from(element.attributes)) {
      const value = attribute.value.trim()
      const safeReference = /^(?:url\(#[A-Za-z][\w:.-]*\)|#[A-Za-z][\w:.-]*)$/.test(value)
      if (!SAFE_ATTRS.has(attribute.name)
        || /^on/i.test(attribute.name)
        || /javascript:|data:|https?:|expression\s*\(/i.test(value)
        || (/url\s*\(/i.test(value) && !safeReference)) {
        element.removeAttribute(attribute.name)
      }
    }
  }
  root.setAttribute('xmlns', 'http://www.w3.org/2000/svg')
  if (!root.getAttribute('viewBox')) root.setAttribute('viewBox', '0 0 800 450')
  root.removeAttribute('width')
  root.removeAttribute('height')
  return new XMLSerializer().serializeToString(root)
}

function svgDataUrl(svg: string) {
  return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`
}

export default function VisualArtifact({ artifact }: { artifact: VisualArtifactData }) {
  const [stepIndex, setStepIndex] = useState(0)
  const [playing, setPlaying] = useState(false)
  const steps = artifact.steps || []
  const safeSvgs = useMemo(() => steps.map(step => sanitizeSvg(step.svg)), [steps])

  useEffect(() => {
    setStepIndex(0)
    setPlaying(false)
  }, [artifact.title])

  useEffect(() => {
    if (!playing || steps.length < 2) return
    const timer = globalThis.setInterval(() => {
      setStepIndex(current => {
        if (current >= steps.length - 1) {
          setPlaying(false)
          return current
        }
        return current + 1
      })
    }, 1500)
    return () => globalThis.clearInterval(timer)
  }, [playing, steps.length])

  if (!steps.length) return null
  const activeIndex = Math.min(stepIndex, steps.length - 1)
  const activeStep = steps[activeIndex]
  const imageUrl = safeSvgs[activeIndex] ? svgDataUrl(safeSvgs[activeIndex]) : ''

  return (
    <figure className={`visual-artifact visual-artifact-${artifact.kind}`}>
      <figcaption>
        <strong>{artifact.title}</strong>
        {artifact.subtitle && <span>{artifact.subtitle}</span>}
      </figcaption>
      <div className="visual-canvas">
        {imageUrl
          ? <img src={imageUrl} alt={`${artifact.title}${activeStep.title ? `：${activeStep.title}` : ''}`} />
          : <span>可视化内容未通过安全校验</span>}
      </div>
      {artifact.kind === 'animation' && (
        <div className="animation-caption">
          <strong>{activeStep.title || `第 ${activeIndex + 1} 步`}</strong>
          {activeStep.text && <span>{activeStep.text}</span>}
        </div>
      )}
      {artifact.kind === 'animation' && steps.length > 1 && (
        <div className="animation-controls">
          <button type="button" onClick={() => { setPlaying(false); setStepIndex(Math.max(0, activeIndex - 1)) }} disabled={activeIndex === 0} aria-label="上一步">←</button>
          <button type="button" className="animation-play" onClick={() => {
            if (!playing && activeIndex === steps.length - 1) setStepIndex(0)
            setPlaying(value => !value)
          }}>{playing ? '暂停' : '播放'}</button>
          <input type="range" min={0} max={steps.length - 1} value={activeIndex} onChange={event => { setPlaying(false); setStepIndex(Number(event.target.value)) }} aria-label="动画步骤" />
          <span>{activeIndex + 1} / {steps.length}</span>
          <button type="button" onClick={() => { setPlaying(false); setStepIndex(Math.min(steps.length - 1, activeIndex + 1)) }} disabled={activeIndex === steps.length - 1} aria-label="下一步">→</button>
        </div>
      )}
    </figure>
  )
}
