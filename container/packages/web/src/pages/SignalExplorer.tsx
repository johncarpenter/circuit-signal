import { useState } from 'react'
import { useQuery, useMutation } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { listSignals, searchSignals, type Signal, type SearchResult } from '../api/client'

export default function SignalExplorer() {
  const [query, setQuery] = useState('')
  const [datasetFilter, setDatasetFilter] = useState('')

  const { data: signals, isLoading } = useQuery({
    queryKey: ['signals', datasetFilter],
    queryFn: () => listSignals({ dataset_name: datasetFilter || undefined, limit: 50 }),
  })

  const searchMutation = useMutation({
    mutationFn: (q: string) => searchSignals({ query: q, limit: 20 }),
  })

  const handleSearch = () => {
    if (query.trim()) searchMutation.mutate(query)
  }

  const displaySignals = searchMutation.data?.results ?? null

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold">Signal Explorer</h1>

      {/* Search */}
      <div className="bg-white rounded-lg shadow p-4">
        <div className="flex gap-3">
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
            placeholder="Search signals by description..."
            className="flex-1 rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-circuit-500"
          />
          <input
            type="text"
            value={datasetFilter}
            onChange={(e) => setDatasetFilter(e.target.value)}
            placeholder="Filter by dataset"
            className="w-48 rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-circuit-500"
          />
          <button
            onClick={handleSearch}
            disabled={!query.trim() || searchMutation.isPending}
            className="bg-circuit-600 text-white rounded-md px-4 py-2 text-sm font-medium hover:bg-circuit-700 disabled:opacity-50"
          >
            Search
          </button>
        </div>
      </div>

      {/* Search results */}
      {displaySignals && (
        <div>
          <h2 className="text-lg font-semibold mb-3">
            Search Results ({displaySignals.length})
          </h2>
          <div className="grid gap-3">
            {displaySignals.map((s) => (
              <SignalCard key={s.signal_id} signal={s} />
            ))}
            {displaySignals.length === 0 && (
              <p className="text-gray-500 text-sm">No matching signals found.</p>
            )}
          </div>
        </div>
      )}

      {/* Browse all signals */}
      {!displaySignals && (
        <div>
          <h2 className="text-lg font-semibold mb-3">
            All Signals {signals ? `(${signals.length})` : ''}
          </h2>
          {isLoading ? (
            <p className="text-gray-500">Loading...</p>
          ) : (
            <div className="grid gap-3">
              {signals?.map((s) => (
                <SignalCard key={s.signal_id} signal={s} />
              ))}
              {signals?.length === 0 && (
                <p className="text-gray-500 text-sm">No signals in the store yet. Upload a dataset and run analysis.</p>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function SignalCard({ signal }: { signal: Signal | SearchResult }) {
  const s = signal
  // Link to detail page — use `id` from Signal or fall back to signal_id
  const linkId = 'id' in s ? (s as Signal).id : undefined

  const card = (
    <div className="bg-white rounded-lg shadow p-4 hover:shadow-md transition-shadow cursor-pointer">
      <div className="flex justify-between items-start">
        <div>
          <div className="font-medium text-sm">{s.signal_id}</div>
          <div className="text-xs text-gray-500 mt-0.5">
            {s.dataset_name} &middot; {s.segment}
          </div>
        </div>
        {'similarity' in s && s.similarity != null && (
          <span className="bg-circuit-50 text-circuit-700 px-2 py-0.5 rounded text-xs font-medium">
            {Math.round(s.similarity * 100)}% similar
          </span>
        )}
      </div>
      {s.text_description && (
        <p className="text-sm text-gray-600 mt-2 line-clamp-2">{s.text_description}</p>
      )}
      <div className="flex gap-4 mt-3 text-xs text-gray-500">
        {s.trend_slope != null && <span>Trend: {s.trend_slope.toFixed(3)}</span>}
        {s.seasonality_strength != null && <span>Seasonality: {s.seasonality_strength.toFixed(2)}</span>}
        {s.deviation_count_90d != null && <span>Deviations: {s.deviation_count_90d}</span>}
      </div>
    </div>
  )

  if (linkId) {
    return <Link to={`/signals/${linkId}`}>{card}</Link>
  }
  return card
}
