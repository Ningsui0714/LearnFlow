/**
 * TensorShape: matrix/tensor grid with labels and cell highlighting.
 *
 * DSL:
 * {
 *   "type": "tensor-shape",
 *   "data": { "matrix": [[1,2,3],[4,5,6]], "label": "X" },
 *   "highlight": [[0,1]],            // [row, col] cells
 *   "row_labels": ["样本1"], "col_labels": ["特征1"]
 * }
 */
export default function TensorShape({ config }: { config: any }) {
  const data = config.data || {}
  const matrix: number[][] = data.matrix || []
  const label = data.label || ''
  const highlight: [number, number][] = config.highlight || []
  const rowLabels: string[] = config.row_labels || []
  const colLabels: string[] = config.col_labels || []
  const rows = matrix.length
  const cols = rows > 0 ? matrix[0].length : 0

  const isHi = (r: number, c: number) => highlight.some(([hr, hc]) => hr === r && hc === c)

  return (
    <div className="overflow-x-auto">
      <table className="border-collapse">
        {label && <caption className="text-left text-[10px] text-gray-400 mb-1 font-mono">{label}</caption>}
        <tbody>
          {colLabels.length > 0 && (
            <tr>
              <td />
              {colLabels.map((c, i) => (
                <td key={i} className="text-[9px] text-gray-400 px-1 text-center font-mono">{c}</td>
              ))}
            </tr>
          )}
          {matrix.map((rowArr, r) => (
            <tr key={r}>
              {rowLabels.length > 0 && (
                <td className="text-[9px] text-gray-400 pr-1 font-mono">{rowLabels[r]}</td>
              )}
              {rowArr.map((v, c) => (
                <td key={c}
                    className={`w-9 h-9 border-2 text-center text-xs font-mono transition-colors ${
                      isHi(r, c) ? 'bg-indigo-100 border-indigo-400 text-indigo-700' : 'bg-white border-gray-300 text-gray-700'
                    }`}>
                  {v}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      <p className="text-[10px] text-gray-400 mt-1 font-mono">
        shape: [{rows}, {cols}]
      </p>
    </div>
  )
}
