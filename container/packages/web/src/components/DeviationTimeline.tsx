import { ScatterChart, Scatter, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, Cell } from 'recharts'

interface ChangePoint {
  date?: string
  timestamp?: string
  magnitude: number
  direction: string
}

interface Props {
  change_points?: ChangePoint[]
  deviation_count_90d?: number
}

export default function DeviationTimeline({ change_points, deviation_count_90d }: Props) {
  if (!change_points || change_points.length === 0) {
    return (
      <div className="bg-gray-50 rounded-lg p-6 text-center text-gray-400 text-sm">
        No change points detected
        {deviation_count_90d != null && deviation_count_90d > 0 && (
          <span className="block mt-1">{deviation_count_90d} deviation(s) in last 90 days</span>
        )}
      </div>
    )
  }

  const data = change_points.map((cp, i) => ({
    index: i,
    date: cp.date || cp.timestamp || `CP ${i + 1}`,
    magnitude: Math.abs(cp.magnitude),
    direction: cp.direction,
  }))

  return (
    <div>
      <div className="flex justify-between items-center mb-2">
        <h4 className="text-sm font-medium text-gray-700">Change Points</h4>
        {deviation_count_90d != null && (
          <span className="text-xs text-gray-500">{deviation_count_90d} deviations (90d)</span>
        )}
      </div>
      <ResponsiveContainer width="100%" height={200}>
        <ScatterChart margin={{ top: 8, right: 8, left: 0, bottom: 4 }}>
          <CartesianGrid strokeDasharray="3 3" />
          <XAxis dataKey="date" tick={{ fontSize: 10 }} />
          <YAxis dataKey="magnitude" tick={{ fontSize: 11 }} width={50} label={{ value: 'Magnitude', angle: -90, position: 'insideLeft', style: { fontSize: 11 } }} />
          <Tooltip formatter={(value: number) => value.toFixed(4)} />
          <Scatter data={data}>
            {data.map((d, i) => (
              <Cell key={i} fill={d.direction === 'increase' ? '#ef4444' : '#3b82f6'} />
            ))}
          </Scatter>
        </ScatterChart>
      </ResponsiveContainer>
      <div className="flex gap-4 mt-1 text-xs text-gray-500">
        <span className="flex items-center gap-1">
          <span className="w-2 h-2 rounded-full bg-red-500 inline-block" /> Increase
        </span>
        <span className="flex items-center gap-1">
          <span className="w-2 h-2 rounded-full bg-blue-500 inline-block" /> Decrease
        </span>
      </div>
    </div>
  )
}
