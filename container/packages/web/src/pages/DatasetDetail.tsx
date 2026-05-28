import { useParams, useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { getDataset, triggerProfile, triggerAnalysis, listRuns } from '../api/client'

export default function DatasetDetail() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const queryClient = useQueryClient()

  const { data: dataset, isLoading } = useQuery({
    queryKey: ['dataset', id],
    queryFn: () => getDataset(id!),
    enabled: !!id,
    refetchInterval: (query) => {
      const status = query.state.data?.status
      return status === 'profiling' ? 3000 : false
    },
  })

  const { data: runs } = useQuery({
    queryKey: ['runs', id],
    queryFn: () => listRuns({ dataset_id: id }),
    enabled: !!id,
  })

  const profileMutation = useMutation({
    mutationFn: () => triggerProfile(id!),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['dataset', id] }),
  })

  const analyzeMutation = useMutation({
    mutationFn: () => triggerAnalysis(id!),
    onSuccess: (data) => navigate(`/runs/${data.run_id}`),
  })

  if (isLoading || !dataset) return <div className="text-gray-500">Loading...</div>

  const profile = dataset.profile as Record<string, any> | null
  const stage1 = profile?.stage1 as Record<string, any> | undefined

  return (
    <div className="space-y-6">
      <div className="flex justify-between items-center">
        <div>
          <h1 className="text-2xl font-bold">{dataset.name}</h1>
          <p className="text-sm text-gray-500 mt-1">ID: {dataset.id}</p>
        </div>
        <div className="flex gap-3">
          {dataset.status === 'uploaded' && (
            <button
              onClick={() => profileMutation.mutate()}
              disabled={profileMutation.isPending}
              className="bg-purple-600 text-white rounded-md px-4 py-2 text-sm font-medium hover:bg-purple-700 disabled:opacity-50"
            >
              {profileMutation.isPending ? 'Starting...' : 'Run Profile'}
            </button>
          )}
          {dataset.status === 'profiled' && (
            <button
              onClick={() => analyzeMutation.mutate()}
              disabled={analyzeMutation.isPending}
              className="bg-circuit-600 text-white rounded-md px-4 py-2 text-sm font-medium hover:bg-circuit-700 disabled:opacity-50"
            >
              {analyzeMutation.isPending ? 'Starting...' : 'Run Analysis'}
            </button>
          )}
        </div>
      </div>

      {/* Status */}
      <div className="bg-white rounded-lg shadow p-4">
        <span className={`inline-flex items-center px-3 py-1 rounded-full text-sm font-medium ${
          dataset.status === 'profiled' ? 'bg-green-100 text-green-800' :
          dataset.status === 'profiling' ? 'bg-purple-100 text-purple-800' :
          dataset.status === 'error' ? 'bg-red-100 text-red-800' :
          'bg-gray-100 text-gray-800'
        }`}>
          {dataset.status}
        </span>
      </div>

      {/* Files */}
      {dataset.file_refs && (
        <div className="bg-white rounded-lg shadow p-4">
          <h2 className="text-lg font-semibold mb-3">Files</h2>
          <div className="space-y-2">
            {(dataset.file_refs as any[]).map((f: any, i: number) => (
              <div key={i} className="flex justify-between text-sm">
                <span>{f.filename}</span>
                <span className="text-gray-500">{(f.size_bytes / 1024 / 1024).toFixed(2)} MB</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Profile Results */}
      {stage1 && (
        <div className="bg-white rounded-lg shadow p-4">
          <h2 className="text-lg font-semibold mb-3">Profile Results</h2>
          <div className="grid grid-cols-3 gap-4">
            <div>
              <div className="text-sm text-gray-500">Datasets</div>
              <div className="text-xl font-bold">{stage1.datasets}</div>
            </div>
            <div>
              <div className="text-sm text-gray-500">Discriminators</div>
              <div className="text-xl font-bold">{stage1.discriminators}</div>
            </div>
            <div>
              <div className="text-sm text-gray-500">Hierarchies</div>
              <div className="text-xl font-bold">{stage1.hierarchies}</div>
            </div>
          </div>
        </div>
      )}

      {/* Analysis Runs */}
      {runs && runs.length > 0 && (
        <div className="bg-white rounded-lg shadow p-4">
          <h2 className="text-lg font-semibold mb-3">Analysis Runs</h2>
          <div className="space-y-2">
            {runs.map((run) => (
              <a
                key={run.id}
                href={`/runs/${run.id}`}
                className="block rounded border px-3 py-2 hover:bg-gray-50 text-sm"
              >
                <div className="flex justify-between">
                  <span className="font-mono">{run.id.slice(0, 8)}...</span>
                  <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${
                    run.status === 'completed' ? 'bg-green-100 text-green-800' :
                    run.status === 'failed' ? 'bg-red-100 text-red-800' :
                    'bg-blue-100 text-blue-800'
                  }`}>{run.status}</span>
                </div>
              </a>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
