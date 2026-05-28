import { ScatterChart, Scatter, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, Cell } from 'recharts'
import { useNavigate } from 'react-router-dom'
import type { Cluster } from '../api/client'

interface Props {
  clusters: Cluster[]
}

const COLORS = [
  '#6366f1', '#ef4444', '#22c55e', '#f59e0b', '#3b82f6',
  '#ec4899', '#14b8a6', '#f97316', '#8b5cf6', '#06b6d4',
]

interface PointData {
  x: number
  y: number
  id: string
  signal_id: string
  segment: string
  dataset_name: string
  cluster_id: number
}

export default function ClusterMap({ clusters }: Props) {
  const navigate = useNavigate()

  // Flatten all cluster members into scatter data
  const allPoints: PointData[] = clusters.flatMap((c) =>
    c.members.map((m) => ({
      x: m.x,
      y: m.y,
      id: m.id,
      signal_id: m.signal_id,
      segment: m.segment,
      dataset_name: m.dataset_name,
      cluster_id: c.cluster_id,
    }))
  )

  if (allPoints.length === 0) {
    return <div className="text-gray-400 text-sm text-center py-8">No data to display</div>
  }

  const CustomTooltip = ({ active, payload }: { active?: boolean; payload?: Array<{ payload: PointData }> }) => {
    if (!active || !payload?.length) return null
    const d = payload[0].payload
    return (
      <div className="bg-white shadow rounded px-3 py-2 text-xs">
        <div className="font-medium">{d.segment}</div>
        <div className="text-gray-500">{d.dataset_name}</div>
        <div className="text-gray-400 mt-0.5">Cluster {d.cluster_id}</div>
      </div>
    )
  }

  return (
    <ResponsiveContainer width="100%" height={450}>
      <ScatterChart margin={{ top: 8, right: 16, left: 0, bottom: 8 }}>
        <CartesianGrid strokeDasharray="3 3" />
        <XAxis dataKey="x" type="number" tick={{ fontSize: 11 }} name="PC1" />
        <YAxis dataKey="y" type="number" tick={{ fontSize: 11 }} name="PC2" width={50} />
        <Tooltip content={<CustomTooltip />} />
        <Scatter
          data={allPoints}
          onClick={(point: PointData) => {
            if (point?.id) navigate(`/signals/${point.id}`)
          }}
        >
          {allPoints.map((p, i) => (
            <Cell key={i} fill={COLORS[p.cluster_id % COLORS.length]} cursor="pointer" />
          ))}
        </Scatter>
      </ScatterChart>
    </ResponsiveContainer>
  )
}
