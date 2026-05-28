import { useParams, Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { getSignal, getSimilarSignals, type SearchResult } from '../api/client'
import SeasonalShape from '../components/SeasonalShape'
import DeviationTimeline from '../components/DeviationTimeline'

export default function SignalDetail() {
  const { id } = useParams<{ id: string }>()

  const { data: signal, isLoading, error } = useQuery({
    queryKey: ['signal', id],
    queryFn: () => getSignal(id!),
    enabled: !!id,
  })

  const { data: similarData } = useQuery({
    queryKey: ['similar', id],
    queryFn: () => getSimilarSignals(id!, 'shape'),
    enabled: !!id && !!signal?.has_shape_embedding,
  })

  if (isLoading) return <p className="text-gray-500">Loading signal...</p>
  if (error || !signal) return <p className="text-red-500">Signal not found.</p>

  const metrics = [
    { label: 'Trend Slope', value: signal.trend_slope?.toFixed(4) },
    { label: 'Seasonality', value: signal.seasonality_strength?.toFixed(3) },
    { label: 'Residual Std', value: signal.residual_std?.toFixed(4) },
    { label: 'Deviations (90d)', value: signal.deviation_count_90d },
    { label: 'Dev Density', value: signal.deviation_density?.toFixed(4) },
    { label: 'Critical %', value: signal.critical_pct != null ? `${(signal.critical_pct * 100).toFixed(1)}%` : undefined },
    { label: 'Row Count', value: signal.row_count?.toLocaleString() },
    { label: 'Grain', value: signal.temporal_grain },
  ]

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <Link to="/signals" className="text-sm text-circuit-600 hover:underline">&larr; Back to Explorer</Link>
        <h1 className="text-2xl font-bold mt-2">{signal.segment}</h1>
        <div className="text-sm text-gray-500 mt-1">
          {signal.dataset_name} &middot; {signal.segment_by} &middot; {signal.status}
        </div>
        <div className="text-xs text-gray-400 mt-0.5">
          Registered {new Date(signal.registered_at).toLocaleDateString()}
        </div>
      </div>

      {/* Text description */}
      {signal.text_description && (
        <div className="bg-white rounded-lg shadow p-4">
          <h3 className="text-sm font-semibold text-gray-700 mb-1">Description</h3>
          <p className="text-sm text-gray-600">{signal.text_description}</p>
        </div>
      )}

      {/* Metrics row */}
      <div className="grid grid-cols-4 gap-3">
        {metrics.map((m) => (
          m.value != null && (
            <div key={m.label} className="bg-white rounded-lg shadow p-3">
              <div className="text-xs text-gray-500">{m.label}</div>
              <div className="text-lg font-semibold mt-0.5">{m.value}</div>
            </div>
          )
        ))}
      </div>

      {/* Embedding badges */}
      <div className="flex gap-2">
        {signal.has_shape_embedding && <Badge label="Shape Embedding" />}
        {signal.has_deviation_embedding && <Badge label="Deviation Embedding" />}
        {signal.has_text_embedding && <Badge label="Text Embedding" />}
      </div>

      {/* Seasonal Shape */}
      <div className="bg-white rounded-lg shadow p-4">
        <h3 className="text-sm font-semibold text-gray-700 mb-3">Seasonal Patterns</h3>
        <SeasonalShape
          weekly={signal.seasonal_weekly}
          hourly={signal.seasonal_hourly}
          monthly={signal.seasonal_monthly}
        />
      </div>

      {/* Deviation Timeline */}
      <div className="bg-white rounded-lg shadow p-4">
        <h3 className="text-sm font-semibold text-gray-700 mb-3">Deviations</h3>
        <DeviationTimeline
          change_points={signal.change_points}
          deviation_count_90d={signal.deviation_count_90d}
        />
      </div>

      {/* Similar Signals */}
      {similarData && similarData.results.length > 0 && (
        <div className="bg-white rounded-lg shadow p-4">
          <h3 className="text-sm font-semibold text-gray-700 mb-3">
            Similar Signals ({similarData.axis})
          </h3>
          <div className="space-y-2">
            {similarData.results.map((s: SearchResult) => (
              <SimilarSignalRow key={s.signal_id} signal={s} />
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

function Badge({ label }: { label: string }) {
  return (
    <span className="bg-green-50 text-green-700 px-2 py-0.5 rounded text-xs font-medium">
      {label}
    </span>
  )
}

function SimilarSignalRow({ signal }: { signal: SearchResult }) {
  const inner = (
    <div className="flex justify-between items-center p-2 rounded hover:bg-gray-50 cursor-pointer">
      <div>
        <div className="text-sm font-medium">{signal.segment}</div>
        <div className="text-xs text-gray-500">{signal.dataset_name}</div>
      </div>
      {signal.similarity != null && (
        <span className="bg-circuit-50 text-circuit-700 px-2 py-0.5 rounded text-xs font-medium">
          {Math.round(signal.similarity * 100)}%
        </span>
      )}
    </div>
  )

  if (signal.id) {
    return <Link to={`/signals/${signal.id}`}>{inner}</Link>
  }
  return inner
}
