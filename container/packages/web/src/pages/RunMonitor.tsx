import { useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { getRun, getRunSegments } from '../api/client'
import { useRunProgress } from '../hooks/useRunProgress'

export default function RunMonitor() {
  const { id } = useParams<{ id: string }>()

  const { data: run, isLoading } = useQuery({
    queryKey: ['run', id],
    queryFn: () => getRun(id!),
    enabled: !!id,
    refetchInterval: (query) => {
      const status = query.state.data?.status
      return status && !['completed', 'failed'].includes(status) ? 5000 : false
    },
  })

  const { data: segments } = useQuery({
    queryKey: ['run-segments', id],
    queryFn: () => getRunSegments(id!),
    enabled: !!id && run?.status === 'completed',
  })

  const { events, latest, connected } = useRunProgress(
    run && !['completed', 'failed'].includes(run.status) ? id : undefined,
  )

  if (isLoading) return <div className="text-gray-500">Loading...</div>
  if (!run) return <div className="text-red-500">Run not found</div>

  const progress = run.progress || {}
  const isRunning = !['completed', 'failed'].includes(run.status)
  const percent = latest?.percent ?? 0

  return (
    <div className="space-y-6">
      <div className="flex justify-between items-center">
        <h1 className="text-2xl font-bold">Run {run.id.slice(0, 8)}...</h1>
        <span className={`px-3 py-1 rounded-full text-sm font-medium ${
          run.status === 'completed' ? 'bg-green-100 text-green-800' :
          run.status === 'failed' ? 'bg-red-100 text-red-800' :
          'bg-blue-100 text-blue-800'
        }`}>
          {run.status}
        </span>
      </div>

      {/* Progress bar */}
      {isRunning && (
        <div className="bg-white rounded-lg shadow p-4">
          <div className="flex justify-between text-sm mb-2">
            <span className="font-medium">{latest?.stage || run.status}</span>
            <span className="text-gray-500">
              {connected ? `${Math.round(percent * 100)}%` : 'Connecting...'}
            </span>
          </div>
          <div className="w-full bg-gray-200 rounded-full h-3">
            <div
              className="bg-circuit-600 h-3 rounded-full transition-all duration-500"
              style={{ width: `${Math.round(percent * 100)}%` }}
            />
          </div>
          {latest?.segment && (
            <p className="text-xs text-gray-500 mt-2">Processing: {latest.segment}</p>
          )}
        </div>
      )}

      {/* Summary stats */}
      {(progress.segments_total || run.status === 'completed') && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <StatCard label="Total Segments" value={progress.segments_total ?? '—'} />
          <StatCard label="Baselines OK" value={progress.baselines_succeeded ?? '—'} />
          <StatCard label="Deviations OK" value={progress.deviations_succeeded ?? '—'} />
          <StatCard label="Signals Registered" value={progress.signals_registered ?? '—'} />
        </div>
      )}

      {/* Error */}
      {run.error && (
        <div className="bg-red-50 border border-red-200 rounded-lg p-4">
          <h3 className="text-red-800 font-semibold mb-1">Error</h3>
          <pre className="text-sm text-red-700 whitespace-pre-wrap">{run.error}</pre>
        </div>
      )}

      {/* Timing */}
      <div className="bg-white rounded-lg shadow p-4">
        <h2 className="text-lg font-semibold mb-3">Timing</h2>
        <div className="grid grid-cols-2 gap-4 text-sm">
          <div>
            <span className="text-gray-500">Created:</span>{' '}
            {new Date(run.created_at).toLocaleString()}
          </div>
          {run.started_at && (
            <div>
              <span className="text-gray-500">Started:</span>{' '}
              {new Date(run.started_at).toLocaleString()}
            </div>
          )}
          {run.completed_at && (
            <div>
              <span className="text-gray-500">Completed:</span>{' '}
              {new Date(run.completed_at).toLocaleString()}
            </div>
          )}
        </div>
      </div>

      {/* Live events log */}
      {events.length > 0 && (
        <div className="bg-white rounded-lg shadow p-4">
          <h2 className="text-lg font-semibold mb-3">Progress Events</h2>
          <div className="max-h-48 overflow-y-auto space-y-1">
            {events.map((e, i) => (
              <div key={i} className="text-xs font-mono text-gray-600">
                [{e.stage}] {e.segment || ''} — {Math.round(e.percent * 100)}%
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Segments table */}
      {segments && segments.segments.length > 0 && (
        <div className="bg-white rounded-lg shadow overflow-hidden">
          <div className="px-4 py-3 border-b">
            <h2 className="text-lg font-semibold">Segments ({segments.total_segments})</h2>
          </div>
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Segment</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Rows</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Trend</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Seasonality</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Deviations</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200">
                {segments.segments.map((s) => (
                  <tr key={s.signal_id}>
                    <td className="px-4 py-3 text-sm font-medium">{s.segment}</td>
                    <td className="px-4 py-3 text-sm text-gray-600">{s.row_count ?? '—'}</td>
                    <td className="px-4 py-3 text-sm text-gray-600">
                      {s.trend_slope != null ? s.trend_slope.toFixed(3) : '—'}
                    </td>
                    <td className="px-4 py-3 text-sm text-gray-600">
                      {s.seasonality_strength != null ? s.seasonality_strength.toFixed(2) : '—'}
                    </td>
                    <td className="px-4 py-3 text-sm text-gray-600">{s.deviation_count_90d ?? '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
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
