const BASE = '/api'

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', ...options?.headers },
    ...options,
  })
  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(error.detail || `Request failed: ${res.status}`)
  }
  return res.json()
}

// --- Types ---

export interface Dataset {
  id: string
  name: string
  status: string
  file_refs?: Array<{ filename: string; size_bytes: number; key: string }>
  profile?: Record<string, unknown>
  config?: Record<string, unknown>
  tags?: Record<string, unknown>
  created_at: string
}

export interface AnalysisRun {
  id: string
  dataset_id: string
  status: string
  manifest?: Record<string, unknown>
  progress?: {
    segments_total?: number
    baselines_succeeded?: number
    deviations_succeeded?: number
    signals_registered?: number
  }
  result_refs?: Record<string, string>
  error?: string
  started_at?: string
  completed_at?: string
  created_at: string
}

export interface Signal {
  id: string
  signal_id: string
  dataset_name: string
  segment: string
  segment_by: string
  temporal_grain: string
  row_count?: number
  tags?: Record<string, unknown>
  trend_slope?: number
  trend_intercept?: number
  seasonality_strength?: number
  residual_std?: number
  deviation_count_90d?: number
  deviation_density?: number
  critical_pct?: number
  change_points?: Array<{ date?: string; timestamp?: string; magnitude: number; direction: string }>
  seasonal_weekly?: number[]
  seasonal_hourly?: number[]
  seasonal_monthly?: number[]
  has_shape_embedding?: boolean
  has_deviation_embedding?: boolean
  has_text_embedding?: boolean
  text_description?: string
  status: string
  superseded_by?: string
  registered_at: string
}

export interface StoreStats {
  total_active: number
  total_superseded: number
  datasets: number
  segment_types: number
  temporal_grains: number
  avg_deviations?: number
  avg_seasonality?: number
  with_shape_embedding: number
  with_text_embedding: number
  earliest_signal?: string
  latest_signal?: string
  per_dataset: Array<{
    dataset_name: string
    signal_count: number
    avg_deviations?: number
  }>
}

export interface SearchResult {
  id?: string
  signal_id: string
  dataset_name: string
  segment: string
  segment_by?: string
  text_description?: string
  similarity?: number
  trend_slope?: number
  seasonality_strength?: number
  deviation_count_90d?: number
}

export interface ProgressEvent {
  run_id: string
  stage: string
  segment?: string
  percent: number
}

// --- Datasets ---

export async function uploadDataset(name: string, files: File[]): Promise<{ id: string; name: string; status: string }> {
  const form = new FormData()
  files.forEach((f) => form.append('files', f))
  const res = await fetch(`${BASE}/datasets?name=${encodeURIComponent(name)}`, {
    method: 'POST',
    body: form,
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(err.detail || 'Upload failed')
  }
  return res.json()
}

export const listDatasets = () => request<Dataset[]>('/datasets')
export const getDataset = (id: string) => request<Dataset>(`/datasets/${id}`)
export const deleteDataset = (id: string) => request<{ status: string }>(`/datasets/${id}`, { method: 'DELETE' })
export const triggerProfile = (id: string) => request<{ status: string; dataset_id: string }>(`/datasets/${id}/profile`, { method: 'POST' })
export const updateConfig = (id: string, config: Record<string, unknown>) =>
  request<{ status: string }>(`/datasets/${id}/config`, { method: 'PATCH', body: JSON.stringify(config) })

// --- Runs ---

export const triggerAnalysis = (datasetId: string) =>
  request<{ run_id: string; status: string }>(`/datasets/${datasetId}/analyze`, { method: 'POST' })
export const listRuns = (params?: { dataset_id?: string; status?: string }) => {
  const qs = new URLSearchParams()
  if (params?.dataset_id) qs.set('dataset_id', params.dataset_id)
  if (params?.status) qs.set('status', params.status)
  const q = qs.toString()
  return request<AnalysisRun[]>(`/runs${q ? `?${q}` : ''}`)
}
export const getRun = (id: string) => request<AnalysisRun>(`/runs/${id}`)
export const getRunSegments = (id: string) => request<{ run_id: string; total_segments: number; segments: Signal[] }>(`/runs/${id}/segments`)

export async function getRunReport(id: string): Promise<Blob> {
  const res = await fetch(`${BASE}/runs/${id}/report`)
  if (!res.ok) throw new Error(`Failed to fetch report: ${res.status}`)
  return res.blob()
}

export async function getRunChart(id: string, chartName: string): Promise<Blob> {
  const res = await fetch(`${BASE}/runs/${id}/charts/${encodeURIComponent(chartName)}`)
  if (!res.ok) throw new Error(`Failed to fetch chart: ${res.status}`)
  return res.blob()
}

// --- Signals ---

export const listSignals = (params?: { dataset_name?: string; segment_by?: string; limit?: number; offset?: number }) => {
  const qs = new URLSearchParams()
  if (params?.dataset_name) qs.set('dataset_name', params.dataset_name)
  if (params?.segment_by) qs.set('segment_by', params.segment_by)
  if (params?.limit) qs.set('limit', String(params.limit))
  if (params?.offset) qs.set('offset', String(params.offset))
  const q = qs.toString()
  return request<Signal[]>(`/signals${q ? `?${q}` : ''}`)
}
export const getSignal = (id: string) => request<Signal>(`/signals/${id}`)
export const getSimilarSignals = (signalId: string, axis?: string) =>
  request<{ results: SearchResult[]; axis: string }>(`/signals/${signalId}/similar${axis ? `?axis=${axis}` : ''}`)
export const searchSignals = (body: { query?: string; signal_id?: string; axis?: string; limit?: number }) =>
  request<{ results: SearchResult[]; search_type: string }>('/signals/search', { method: 'POST', body: JSON.stringify(body) })
export const explainSignals = (signalIdA: string, signalIdB: string) =>
  request<Record<string, unknown>>('/signals/explain', { method: 'POST', body: JSON.stringify({ signal_id_a: signalIdA, signal_id_b: signalIdB }) })

export interface ClusterMember {
  id: string
  signal_id: string
  dataset_name: string
  segment: string
  segment_by?: string
  text_description?: string
  x: number
  y: number
}

export interface Cluster {
  cluster_id: number
  size: number
  representative: string
  members: ClusterMember[]
}

export const clusterSignals = (body: { axis?: string; n_clusters?: number; dataset_filter?: string }) =>
  request<{ clusters: Cluster[]; axis: string }>('/signals/cluster', { method: 'POST', body: JSON.stringify(body) })
export const getStoreStats = () => request<StoreStats>('/store/stats')

// --- WebSocket ---

export function connectRunProgress(runId: string, onMessage: (event: ProgressEvent) => void, onClose?: () => void): WebSocket {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  const ws = new WebSocket(`${protocol}//${window.location.host}/api/ws/runs/${runId}`)
  ws.onmessage = (e) => {
    try {
      onMessage(JSON.parse(e.data))
    } catch {}
  }
  ws.onclose = () => onClose?.()
  return ws
}
