/**
 * Safe math expression evaluator — whitelist only.
 * Supports: + - * / ^ ( ) digits . x pi e sin cos tan exp log abs sqrt
 * Rejects: import/require/eval/function/window/__proto__/{ }/=> etc.
 */

const ALLOWED = /^[0-9a-zA-Z+\-*/().,\s^]*$/
const BAD_WORDS = [
  'import', 'require', 'eval', 'function', 'window', 'document',
  'constructor', '__proto__', '=>', '{', '}', ';', 'process', 'global',
]

export function safeExpr(expr: string): (x: number) => number {
  if (!ALLOWED.test(expr)) throw new Error('非法字符')
  for (const w of BAD_WORDS) {
    if (expr.includes(w)) throw new Error(`非法表达式: ${w}`)
  }
  const cleaned = expr.replace(/\^/g, '**')
  // eslint-disable-next-line no-new-func
  const fn = new Function('x', `with (Math) { return ${cleaned}; }`)
  return (x: number) => fn(x)
}
