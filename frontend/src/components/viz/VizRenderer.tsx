/**
 * VizRenderer: renders ```viz JSON blocks embedded in lecture markdown.
 *
 * Config-driven: the LLM only emits JSON (component type + data + params),
 * never free JS — safe, style-consistent, previewable/deletable like images.
 *
 * DSL v1:
 *   ```viz
 *   {
 *     "type": "array-pointer" | "function-plot" | "tensor-shape" | "neural-net",
 *     "title": "…",
 *     ...component-specific fields
 *   }
 *   ```
 */
import { useState } from 'react'
import ArrayPointer from './ArrayPointer'
import FunctionPlot from './FunctionPlot'
import TensorShape from './TensorShape'
import NeuralNet from './NeuralNet'

const REGISTRY: Record<string, any> = {
  'array-pointer': ArrayPointer,
  'function-plot': FunctionPlot,
  'tensor-shape': TensorShape,
  'neural-net': NeuralNet,
}

export default function VizRenderer({ code }: { code: string }) {
  let config: any = null
  try {
    config = JSON.parse(code)
  } catch (e: any) {
    return (
      <div className="my-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-700">
        ⚠️ viz 配置解析失败：{e.message}
        <pre className="mt-1 text-[10px] whitespace-pre-wrap text-amber-600">{code.slice(0, 400)}</pre>
      </div>
    )
  }
  const Comp = REGISTRY[config?.type]
  if (!Comp) {
    return (
      <div className="my-3 rounded-lg border border-gray-200 bg-gray-50 px-3 py-2 text-xs text-gray-500">
        未知可视化类型：「{config?.type || '?'}」（支持：{Object.keys(REGISTRY).join(' / ')}）
      </div>
    )
  }
  return (
    <div className="my-4">
      {config.title && (
        <p className="text-xs font-semibold text-gray-500 mb-1.5">{config.title}</p>
      )}
      <Comp config={config} />
    </div>
  )
}
