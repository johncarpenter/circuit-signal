import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { clusterSignals, type Cluster } from '../api/client'
import ClusterMap from '../components/ClusterMap'

const AXIS_OPTIONS = [
  { value: 'shape', label: 'Shape (seasonal)' },
  { value: 'deviation', label: 'Deviation (anomaly)' },
  { value: 'text', label: 'Text (semantic)' },
]

export default function ClusterView() {
  const [axis, setAxis] = useState('shape')
  const [nClusters, setNClusters] = useState(5)
  const [datasetFilter, setDatasetFilter] = useState('')

  const mutation = useMutation({
    mutationFn: () =>
      clusterSignals({
        axis,
        n_clusters: nClusters,
        dataset_filter: datasetFilter || undefined,
      }),
  })

  const rawClusters = mutation.data?.clusters ?? []
  // Filter out error responses from the API
  const clusters: Cluster[] = rawClusters.filter((c) => !('error' in c))
  const clusterError = rawClusters.length > 0 && 'error' in rawClusters[0]
    ? (rawClusters[0] as unknown as { error: string }).error
    : null

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold">Signal Clusters</h1>

      {/* Controls */}
      <div className="bg-white rounded-lg shadow p-4">
        <div className="flex gap-3 items-end flex-wrap">
          <div>
            <label className="block text-xs text-gray-500 mb-1">Embedding Axis</label>
            <select
              value={axis}
              onChange={(e) => setAxis(e.target.value)}
              className="rounded-md border border-gray-300 px-3 py-2 text-sm"
            >
              {AXIS_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>{o.label}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="block text-xs text-gray-500 mb-1">Clusters</label>
            <input
              type="number"
              min={2}
              max={20}
              value={nClusters}
              onChange={(e) => setNClusters(Number(e.target.value))}
              className="w-20 rounded-md border border-gray-300 px-3 py-2 text-sm"
            />
          </div>
          <div>
            <label className="block text-xs text-gray-500 mb-1">Dataset Filter</label>
            <input
              type="text"
              value={datasetFilter}
              onChange={(e) => setDatasetFilter(e.target.value)}
              placeholder="All datasets"
              className="w-48 rounded-md border border-gray-300 px-3 py-2 text-sm"
            />
          </div>
          <button
            onClick={() => mutation.mutate()}
            disabled={mutation.isPending}
            className="bg-circuit-600 text-white rounded-md px-4 py-2 text-sm font-medium hover:bg-circuit-700 disabled:opacity-50"
          >
            {mutation.isPending ? 'Clustering...' : 'Run Clustering'}
          </button>
        </div>
      </div>

      {/* Error */}
      {(mutation.isError || clusterError) && (
        <div className="bg-red-50 text-red-700 rounded-lg p-3 text-sm">
          {clusterError || (mutation.error as Error).message}
        </div>
      )}

      {/* Scatter plot */}
      {clusters.length > 0 && (
        <div className="bg-white rounded-lg shadow p-4">
          <h3 className="text-sm font-semibold text-gray-700 mb-3">
            Cluster Map ({mutation.data?.axis})
          </h3>
          <ClusterMap clusters={clusters} />
        </div>
      )}

      {/* Cluster summary cards */}
      {clusters.length > 0 && (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {clusters.map((c) => (
            <div key={c.cluster_id} className="bg-white rounded-lg shadow p-4">
              <div className="flex justify-between items-center mb-2">
                <h4 className="font-medium text-sm">Cluster {c.cluster_id}</h4>
                <span className="bg-gray-100 text-gray-600 px-2 py-0.5 rounded text-xs">
                  {c.size} signals
                </span>
              </div>
              <div className="space-y-1">
                {c.members.slice(0, 5).map((m) => (
                  <div key={m.signal_id} className="text-xs text-gray-600 truncate">
                    {m.segment} <span className="text-gray-400">({m.dataset_name})</span>
                  </div>
                ))}
                {c.size > 5 && (
                  <div className="text-xs text-gray-400">+{c.size - 5} more</div>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
