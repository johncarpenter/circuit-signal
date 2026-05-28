import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { listDatasets } from '../api/client'

export default function Datasets() {
  const { data: datasets, isLoading } = useQuery({ queryKey: ['datasets'], queryFn: listDatasets })

  if (isLoading) return <div className="text-gray-500">Loading...</div>

  return (
    <div className="space-y-4">
      <div className="flex justify-between items-center">
        <h1 className="text-2xl font-bold">Datasets</h1>
        <Link to="/upload" className="bg-circuit-600 text-white rounded-md px-4 py-2 text-sm font-medium hover:bg-circuit-700">
          Upload New
        </Link>
      </div>

      {!datasets?.length ? (
        <div className="text-center py-12 text-gray-500">
          No datasets yet. <Link to="/upload" className="text-circuit-600 hover:underline">Upload one</Link> to get started.
        </div>
      ) : (
        <div className="bg-white rounded-lg shadow overflow-hidden">
          <table className="min-w-full divide-y divide-gray-200">
            <thead className="bg-gray-50">
              <tr>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Name</th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Status</th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Created</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200">
              {datasets.map((d) => (
                <tr key={d.id} className="hover:bg-gray-50">
                  <td className="px-6 py-4">
                    <Link to={`/datasets/${d.id}`} className="text-sm font-medium text-circuit-600 hover:underline">
                      {d.name}
                    </Link>
                  </td>
                  <td className="px-6 py-4">
                    <StatusBadge status={d.status} />
                  </td>
                  <td className="px-6 py-4 text-sm text-gray-500">
                    {new Date(d.created_at).toLocaleDateString()}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

function StatusBadge({ status }: { status: string }) {
  const colors: Record<string, string> = {
    uploaded: 'bg-gray-100 text-gray-800',
    profiling: 'bg-purple-100 text-purple-800',
    profiled: 'bg-green-100 text-green-800',
    error: 'bg-red-100 text-red-800',
  }
  return (
    <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${colors[status] || 'bg-gray-100 text-gray-800'}`}>
      {status}
    </span>
  )
}
