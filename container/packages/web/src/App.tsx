import { Routes, Route, Link, useLocation } from 'react-router-dom'
import { clsx } from 'clsx'
import Upload from './pages/Upload'
import Datasets from './pages/Datasets'
import DatasetDetail from './pages/DatasetDetail'
import RunMonitor from './pages/RunMonitor'
import SignalExplorer from './pages/SignalExplorer'
import SignalDetail from './pages/SignalDetail'
import ClusterView from './pages/ClusterView'
import Dashboard from './pages/Dashboard'

const navItems = [
  { path: '/', label: 'Dashboard' },
  { path: '/upload', label: 'Upload' },
  { path: '/datasets', label: 'Datasets' },
  { path: '/signals', label: 'Signals' },
  { path: '/clusters', label: 'Clusters' },
]

export default function App() {
  const location = useLocation()

  return (
    <div className="min-h-screen">
      <nav className="bg-white border-b border-gray-200">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex justify-between h-16">
            <div className="flex">
              <div className="flex-shrink-0 flex items-center">
                <span className="text-xl font-bold text-circuit-700">Circuit Signal</span>
              </div>
              <div className="ml-10 flex space-x-4 items-center">
                {navItems.map((item) => (
                  <Link
                    key={item.path}
                    to={item.path}
                    className={clsx(
                      'px-3 py-2 rounded-md text-sm font-medium',
                      location.pathname === item.path
                        ? 'bg-circuit-50 text-circuit-700'
                        : 'text-gray-600 hover:text-gray-900 hover:bg-gray-50'
                    )}
                  >
                    {item.label}
                  </Link>
                ))}
              </div>
            </div>
          </div>
        </div>
      </nav>

      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/upload" element={<Upload />} />
          <Route path="/datasets" element={<Datasets />} />
          <Route path="/datasets/:id" element={<DatasetDetail />} />
          <Route path="/runs/:id" element={<RunMonitor />} />
          <Route path="/signals" element={<SignalExplorer />} />
          <Route path="/signals/:id" element={<SignalDetail />} />
          <Route path="/clusters" element={<ClusterView />} />
        </Routes>
      </main>
    </div>
  )
}
