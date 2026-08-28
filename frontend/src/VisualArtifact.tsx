import { useEffect, useId, useMemo, useState, type KeyboardEvent } from 'react'
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

type AccessibleVisualArtifact = VisualArtifactData & {
  status?: 'usable' | 'degraded'
  degraded?: boolean
  degradedTo?: 'diagram' | 'storyboard' | 'deterministic_animation' | string
  modelError?: string
  plannerSucceeded?: boolean
  readable?: {
    summary?: string
    readingOrder?: string[]
    frameDescriptions?: string[]
    nonColorStateCue?: string
  }
}

type AccessibleVisualStep = VisualArtifactData['steps'][number] & {
  durationMs?: number
  stateDescription?: string
}

function sanitizeSvg(raw: string) {
  if (!raw || raw.length > 80_000) return ''
  const documentNode = new DOMParser().parseFromString(raw, 'image/svg+xml')
  if (documentNode.querySelector('parsererror')) return ''
  const root = documentNode.documentElement
  if (root.tagName !== 'svg') return ''

  for (const element of [root, ...Array.from(root.querySelectorAll('*'))]) {
    if (element !== root && !SAFE_TAGS.has(element.tagName)) {
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

function useReducedMotion() {
  const [reducedMotion, setReducedMotion] = useState(false)

  useEffect(() => {
    if (typeof globalThis.matchMedia !== 'function') return
    const media = globalThis.matchMedia('(prefers-reduced-motion: reduce)')
    const update = () => setReducedMotion(media.matches)
    update()
    media.addEventListener?.('change', update)
    return () => media.removeEventListener?.('change', update)
  }, [])

  return reducedMotion
}

export default function VisualArtifact({ artifact }: { artifact: VisualArtifactData }) {
  const accessibleArtifact = artifact as AccessibleVisualArtifact
  const [stepIndex, setStepIndex] = useState(0)
  const [playing, setPlaying] = useState(false)
  const reducedMotion = useReducedMotion()
  const titleId = useId()
  const descriptionId = useId()
  const canvasId = useId()
  const rawKind = String(artifact.kind || 'image')
  const legacyHighlightOnly = rawKind === 'animation' && (!artifact.specVersion || artifact.specVersion === 'learnflow.visual.v1')
  const effectiveDegradedTo = legacyHighlightOnly ? 'storyboard' : accessibleArtifact.degradedTo
  const degradedToStoryboard = effectiveDegradedTo === 'storyboard'
  const isAnimation = rawKind === 'animation' && !degradedToStoryboard && effectiveDegradedTo !== 'diagram'
  const steps = (artifact.steps || []) as AccessibleVisualStep[]
  const safeSvgs = useMemo(() => steps.map(step => sanitizeSvg(step.svg)), [steps])

  useEffect(() => {
    setStepIndex(0)
    setPlaying(false)
  }, [artifact.title, artifact.specVersion])

  useEffect(() => {
    if (reducedMotion || !isAnimation) setPlaying(false)
  }, [isAnimation, reducedMotion])

  useEffect(() => {
    if (!playing || !isAnimation || reducedMotion || steps.length < 2) return
    const duration = Math.max(500, Math.min(10_000, steps[Math.min(stepIndex, steps.length - 1)]?.durationMs || 1500))
    const timer = globalThis.setTimeout(() => {
      setStepIndex(current => {
        if (current >= steps.length - 1) {
          setPlaying(false)
          return current
        }
        return current + 1
      })
    }, duration)
    return () => globalThis.clearTimeout(timer)
  }, [isAnimation, playing, reducedMotion, stepIndex, steps])

  if (!steps.length) return null
  const activeIndex = Math.min(stepIndex, steps.length - 1)
  const activeStep = steps[activeIndex]
  const imageUrl = safeSvgs[activeIndex] ? svgDataUrl(safeSvgs[activeIndex]) : ''
  const frameDescription = accessibleArtifact.readable?.frameDescriptions?.[activeIndex]
    || activeStep.stateDescription
    || activeStep.text
    || activeStep.title
    || `第 ${activeIndex + 1} 步`
  const summary = accessibleArtifact.readable?.summary || artifact.subtitle || artifact.title
  const showStepNavigation = steps.length > 1
  const degraded = legacyHighlightOnly || accessibleArtifact.degraded === true || accessibleArtifact.status === 'degraded' || Boolean(effectiveDegradedTo)

  const moveTo = (next: number) => {
    setPlaying(false)
    setStepIndex(Math.max(0, Math.min(steps.length - 1, next)))
  }

  const togglePlayback = () => {
    if (!isAnimation || reducedMotion) return
    if (!playing && activeIndex === steps.length - 1) setStepIndex(0)
    setPlaying(value => !value)
  }

  const handleKeyboard = (event: KeyboardEvent<HTMLElement>) => {
    if (event.target !== event.currentTarget || !showStepNavigation) return
    if (event.key === 'ArrowLeft') { event.preventDefault(); moveTo(activeIndex - 1) }
    else if (event.key === 'ArrowRight') { event.preventDefault(); moveTo(activeIndex + 1) }
    else if (event.key === 'Home') { event.preventDefault(); moveTo(0) }
    else if (event.key === 'End') { event.preventDefault(); moveTo(steps.length - 1) }
    else if ((event.key === ' ' || event.key === 'Enter') && isAnimation && !reducedMotion) { event.preventDefault(); togglePlayback() }
  }

  return (
    <figure
      className={`visual-artifact visual-artifact-${isAnimation ? 'animation' : 'image'}${degraded ? ' visual-artifact-degraded' : ''}`}
      tabIndex={showStepNavigation ? 0 : undefined}
      onKeyDown={handleKeyboard}
      aria-labelledby={titleId}
      aria-describedby={descriptionId}
    >
      <figcaption>
        <strong id={titleId}>{artifact.title}</strong>
        {artifact.subtitle && <span>{artifact.subtitle}</span>}
        {degraded && <em className="visual-status-badge">已降级为{effectiveDegradedTo === 'storyboard' ? '故事板' : effectiveDegradedTo === 'deterministic_animation' ? '确定性动画' : '图解'}</em>}
      </figcaption>
      <p id={descriptionId} className="visual-sr-only">{summary}。{accessibleArtifact.readable?.nonColorStateCue}</p>
      <div id={canvasId} className="visual-canvas" aria-live="off">
        {imageUrl
          ? <img src={imageUrl} alt={`${artifact.title}${activeStep.title ? `：${activeStep.title}` : ''}。${frameDescription}`} />
          : <span role="alert">可视化内容未通过安全校验</span>}
      </div>
      {(isAnimation || degradedToStoryboard || showStepNavigation) && (
        <div className="animation-caption" role="status" aria-live="polite" aria-atomic="true">
          <strong>{activeStep.title || `第 ${activeIndex + 1} 步`}</strong>
          <span>{frameDescription}</span>
        </div>
      )}
      {reducedMotion && isAnimation && <p className="visual-reduced-motion-note">已启用减少动态效果，请使用前后按钮逐帧查看。</p>}
      {showStepNavigation && (
        <div className="animation-controls" aria-label={isAnimation ? '动画控制' : '故事板控制'}>
          <button type="button" onClick={() => moveTo(activeIndex - 1)} disabled={activeIndex === 0} aria-label="查看上一步">←</button>
          {isAnimation && (
            <button
              type="button"
              className="animation-play"
              onClick={togglePlayback}
              disabled={reducedMotion}
              aria-pressed={playing}
              aria-controls={canvasId}
            >{playing ? '暂停' : '播放'}</button>
          )}
          <input
            type="range"
            min={0}
            max={steps.length - 1}
            value={activeIndex}
            onChange={event => moveTo(Number(event.target.value))}
            aria-label={isAnimation ? '动画步骤' : '故事板步骤'}
            aria-valuetext={`第 ${activeIndex + 1} 步：${activeStep.title || frameDescription}`}
          />
          <span>{activeIndex + 1} / {steps.length}</span>
          <button type="button" onClick={() => moveTo(activeIndex + 1)} disabled={activeIndex === steps.length - 1} aria-label="查看下一步">→</button>
        </div>
      )}
    </figure>
  )
}
