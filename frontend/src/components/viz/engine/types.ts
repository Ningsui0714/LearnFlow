/**
 * VizLab DSL types — object language for teaching visualizations.
 *
 * 可视化 = 对象场景(Scene) + 状态序列(States) + 交互(Params + Events)
 */

// ── 对象（类型化图元）──

export interface ObjBase {
  id: string
  type: string
  label?: string
  color?: string
  hidden?: boolean
}

export interface ArrayObj extends ObjBase {
  type: 'array'
  values: (number | string)[]
  layout?: 'row' | 'column'
}

/** vertical stack — top at the top of its band */
export interface StackObj extends ObjBase {
  type: 'stack'
  values: (number | string)[]
}

/** bar chart (sorting animations) */
export interface BarObj extends ObjBase {
  type: 'bar'
  values: number[]
}

export interface PointerObj extends ObjBase {
  type: 'pointer'
  target: string
  index: number
}

export interface GridObj extends ObjBase {
  type: 'grid'
  matrix: (number | string)[][]
}

export interface CurveObj extends ObjBase {
  type: 'curve'
  fn: string
  range: [number, number]
  yrange?: [number, number]
}

export interface PointObj extends ObjBase {
  type: 'point'
  x: number
  y: number
  on?: string
}

export interface NodeObj extends ObjBase {
  type: 'node'
  value?: string
}

export interface EdgeObj extends ObjBase {
  type: 'edge'
  from: string
  to: string
  weight?: number
  directed?: boolean
}

/** arrow from one object's anchor to another */
export interface ArrowObj extends ObjBase {
  type: 'arrow'
  from: string
  to: string
}

export interface TextObj extends ObjBase {
  type: 'text'
  content: string
}

/** group: children render inside the group's band, coordinates relative */
export interface GroupObj extends ObjBase {
  type: 'group'
  children: ObjSpec[]
}

export type ObjSpec =
  | ArrayObj | StackObj | BarObj | PointerObj | GridObj | CurveObj | PointObj
  | NodeObj | EdgeObj | ArrowObj | TextObj | GroupObj

// ── 场景布局 ──

export interface SceneLayout {
  /** graph layout mode for node/edge objects */
  mode?: 'ring' | 'tree' | 'layered'
  /** root node id for tree layout */
  root?: string
}

// ── 状态（增量变化）──

export interface State {
  note?: string
  /** set "objId.attr.path" = value */
  set?: Record<string, unknown>
  /** swap array/bar elements: { "arrId": [i, j] } */
  swap?: Record<string, [number, number]>
  /** push onto a stack: { "stackId": value } */
  push?: Record<string, number | string>
  /** pop from a stack: { "stackId": 1 } (count) */
  pop?: Record<string, number>
  /** highlight cells: { "arrId": [[idx]], "gridId": [[r, c]] } */
  highlight?: Record<string, number[][]>
  hide?: string[]
  show?: string[]
}

// ── 交互 ──

export interface InteractParam {
  param: string
  min: number
  max: number
  step?: number
  default: number
  /** bind: JS expression computing a set payload, e.g. "w.x = 3 - lr*5" */
  bind?: string
}

export interface VizEvent {
  /** trigger */
  on: 'click' | 'drag'
  /** object id that receives the event */
  target: string
  /** apply these state changes when triggered */
  set?: Record<string, unknown>
  /** toggle highlight on target (click) */
  toggleHighlight?: boolean
  /** for drag: which attribute to update ("index" | "x" | "y") */
  attr?: 'index' | 'x' | 'y'
}

// ── 文档 ──

export interface VizDoc {
  title?: string
  scene: { objects: ObjSpec[]; layout?: SceneLayout }
  states?: State[]
  interact?: InteractParam[]
  events?: VizEvent[]
}
