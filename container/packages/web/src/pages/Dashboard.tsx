import { useQuery } from '@tanstack/react-query'
import { getStoreStats, listRuns } from '../api/client'

export default function Dashboard() {
  const { data: stats, isLoading } = useQuery({ queryKey: ['store-stats'], queryFn: getStoreStats })
  const { data: runs } = useQuery({ queryKey: ['runs-recent'], queryFn: () => listRuns() })

  if (isLoading) return <div className="text-gray-500">Loading...</div>

  return (
    <div className="space-y-8">
      <h1 className="text-2xl font-bold">Dashboard</h1>

      {stats && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <StatCard label="Active Signals" value={stats.total_active} />
          <StatCard label="Datasets" value={stats.datasets} />
          <StatCard label="Avg Deviations" value={stats.avg_deviations?.toFixed(1) ?? '—'} />
          <StatCard label="Avg Seasonality" value={stats.avg_seasonality?.toFixed(2) ?? '—'} />
        </div>
      )}

      {stats?.per_dataset && stats.per_dataset.length > 0 && (
        <div>
          <h2 className="text-lg font-semibold mb-3">Datasets</h2>
          <div className="bg-white rounded-lg shadow overflow-hidden">
            <table className="min-w-full divide-y divide-gray-200">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Dataset</th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Signals</th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Avg Deviations</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200">
                {stats.per_dataset.map((d) => (
                  <tr key={d.dataset_name}>
                    <td className="px-6 py-4 text-sm font-medium text-gray-900">{d.dataset_name}</td>
                    <td className="px-6 py-4 text-sm text-gray-600">{d.signal_count}</td>
                    <td className="px-6 py-4 text-sm text-gray-600">{d.avg_deviations?.toFixed(1) ?? '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {runs && runs.length > 0 && (
        <div>
          <h2 className="text-lg font-semibold mb-3">Recent Runs</h2>
          <div className="space-y-2">
            {runs.slice(0, 5).map((run) => (
              <a
                key={run.id}
                href={`/runs/${run.id}`}
                className="block bg-white rounded-lg shadow px-4 py-3 hover:bg-gray-50"
              >
                <div className="flex justify-between">
                  <span className="text-sm font-medium">{run.id.slice(0, 8)}...</span>
                  <StatusBadge status={run.status} />
                </div>
                <div className="text-xs text-gray-500 mt-1">{new Date(run.created_at).toLocaleString()}</div>
              </a>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

function StatCard({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="bg-white rounded-lg shadow p-4">
      <div className="text-sm text-gray-500">{label}</div>
      <div className="text-2xl font-bold text-gray-900 mt-1">{value}</div>
    </div>
  )
}

function StatusBadge({ status }: { status: string }) {
  const colors: Record<string, string> = {
    completed: 'bg-green-100 text-green-800',
    failed: 'bg-red-100 text-red-800',
    analyzing: 'bg-blue-100 text-blue-800',
    queued: 'bg-yellow-100 text-yellow-800',
    profiling: 'bg-purple-100 text-purple-800',
  }
  return (
    <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${colors[status] || 'bg-gray-100 text-gray-800'}`}>
      {status}
    </span>
  )
}
