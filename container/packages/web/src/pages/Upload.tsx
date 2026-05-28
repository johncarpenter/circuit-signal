import { useState } from 'react'
import { useDropzone } from 'react-dropzone'
import { useMutation } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { uploadDataset } from '../api/client'

export default function Upload() {
  const navigate = useNavigate()
  const [name, setName] = useState('')
  const [files, setFiles] = useState<File[]>([])

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    accept: { 'text/csv': ['.csv'], 'application/octet-stream': ['.parquet'] },
    onDrop: (accepted) => setFiles((prev) => [...prev, ...accepted]),
  })

  const mutation = useMutation({
    mutationFn: () => uploadDataset(name || files[0]?.name.replace(/\.\w+$/, '') || 'Unnamed', files),
    onSuccess: (data) => navigate(`/datasets/${data.id}`),
  })

  return (
    <div className="max-w-2xl mx-auto space-y-6">
      <h1 className="text-2xl font-bold">Upload Dataset</h1>

      <div>
        <label className="block text-sm font-medium text-gray-700 mb-1">Dataset Name</label>
        <input
          type="text"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="e.g., Bakery POS Q4 2025"
          className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-circuit-500"
        />
      </div>

      <div
        {...getRootProps()}
        className={`border-2 border-dashed rounded-lg p-10 text-center cursor-pointer transition-colors ${
          isDragActive ? 'border-circuit-500 bg-circuit-50' : 'border-gray-300 hover:border-gray-400'
        }`}
      >
        <input {...getInputProps()} />
        <p className="text-gray-600">
          {isDragActive ? 'Drop files here...' : 'Drag & drop CSV or Parquet files, or click to browse'}
        </p>
      </div>

      {files.length > 0 && (
        <div className="space-y-2">
          <h3 className="text-sm font-medium text-gray-700">Selected Files</h3>
          {files.map((f, i) => (
            <div key={i} className="flex justify-between items-center bg-white rounded px-3 py-2 shadow-sm">
              <span className="text-sm">{f.name}</span>
              <div className="flex items-center gap-3">
                <span className="text-xs text-gray-500">{(f.size / 1024 / 1024).toFixed(2)} MB</span>
                <button
                  onClick={() => setFiles((prev) => prev.filter((_, j) => j !== i))}
                  className="text-red-500 text-xs hover:underline"
                >
                  Remove
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      <button
        onClick={() => mutation.mutate()}
        disabled={files.length === 0 || mutation.isPending}
        className="w-full bg-circuit-600 text-white rounded-md py-2.5 font-medium hover:bg-circuit-700 disabled:opacity-50 disabled:cursor-not-allowed"
      >
        {mutation.isPending ? 'Uploading...' : 'Upload & Create Dataset'}
      </button>

      {mutation.isError && (
        <div className="bg-red-50 text-red-700 rounded-md p-3 text-sm">
          {mutation.error.message}
        </div>
      )}
    </div>
  )
}
