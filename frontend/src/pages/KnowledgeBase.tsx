import { useState, useCallback, useEffect, useRef } from 'react'
import {
  Database, Upload, Search, Trash2, ChevronDown, ChevronUp,
  RefreshCw, FileText, File, AlertCircle, CheckCircle2, Loader2,
} from 'lucide-react'
import { api } from '../api/client'
import type { KBDocumentSummary, KBStats, KBChunkResult } from '../api/client'

const DEFAULT_TENANT_KEY = 'miragent_default_tenant'
const DEFAULT_TENANT = 'acme-corp'

function getTenant(): string { return localStorage.getItem(DEFAULT_TENANT_KEY) || DEFAULT_TENANT }

// ── Constants ──────────────────────────────────────────────────────────────────

const KB_CATEGORIES = [
  { value: 'security_policy',   label: 'Security',         color: 'bg-red-100 text-red-700 border-red-200' },
  { value: 'hr_policy',         label: 'HR Policy',        color: 'bg-blue-100 text-blue-700 border-blue-200' },
  { value: 'finance',           label: 'Finance',          color: 'bg-green-100 text-green-700 border-green-200' },
  { value: 'legal',             label: 'Legal',            color: 'bg-purple-100 text-purple-700 border-purple-200' },
  { value: 'product',           label: 'Product',          color: 'bg-teal-100 text-teal-700 border-teal-200' },
  { value: 'company_overview',  label: 'Company',          color: 'bg-indigo-100 text-indigo-700 border-indigo-200' },
  { value: 'customer_success',  label: 'Customer Success', color: 'bg-orange-100 text-orange-700 border-orange-200' },
  { value: 'compliance',        label: 'Compliance',       color: 'bg-violet-100 text-violet-700 border-violet-200' },
  { value: 'general',           label: 'General',          color: 'bg-gray-100 text-gray-600 border-gray-200' },
]

function categoryMeta(value: string) {
  return KB_CATEGORIES.find(c => c.value === value) ?? KB_CATEGORIES[KB_CATEGORIES.length - 1]
}

function fileIcon(filename: string) {
  const lower = filename.toLowerCase()
  if (lower.endsWith('.pdf'))  return <File size={18} className="text-red-500 shrink-0" />
  if (lower.endsWith('.docx')) return <FileText size={18} className="text-blue-500 shrink-0" />
  return <FileText size={18} className="text-gray-400 shrink-0" />
}

function formatBytes(bytes: number): string {
  if (bytes === 0) return '0 B'
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function formatDate(iso: string): string {
  try {
    return new Date(iso).toLocaleDateString('en-US', { year: 'numeric', month: 'short', day: 'numeric' })
  } catch {
    return iso.slice(0, 10)
  }
}

// ── Agent dot colors ───────────────────────────────────────────────────────────

const AGENT_COLORS: Record<string, string> = {
  DDQAgent:         'bg-blue-500',
  ComplianceAgent:  'bg-purple-500',
  MeetingPrepAgent: 'bg-teal-500',
}

// ── Document Card ──────────────────────────────────────────────────────────────

function DocumentCard({
  doc,
  onDelete,
}: {
  doc: KBDocumentSummary
  onDelete: (docId: string, chunkCount: number) => void
}) {
  const [expanded, setExpanded] = useState(false)
  const [confirming, setConfirming] = useState(false)
  const meta = categoryMeta(doc.category)

  return (
    <div className="border border-gray-200 bg-white rounded-xl p-4 space-y-2 hover:border-gray-300 transition-colors">
      {/* Header row */}
      <div className="flex items-start gap-2">
        {fileIcon(doc.filename)}
        <div className="flex-1 min-w-0">
          <p className="font-semibold text-gray-900 text-sm truncate" title={doc.filename}>
            {doc.filename}
          </p>
          <div className="flex items-center gap-2 mt-1 flex-wrap">
            <span className={`text-xs px-2 py-0.5 rounded-full border font-medium ${meta.color}`}>
              {meta.label}
            </span>
            {doc.description && (
              <span className="text-xs text-gray-500 truncate max-w-xs">{doc.description}</span>
            )}
          </div>
        </div>
        <button
          onClick={() => setConfirming(true)}
          className="text-gray-400 hover:text-red-500 transition-colors p-1 shrink-0"
          title="Delete document"
        >
          <Trash2 size={15} />
        </button>
      </div>

      {/* Metadata row */}
      <div className="flex items-center gap-3 text-xs text-gray-400">
        <span>{doc.chunk_count} chunk{doc.chunk_count !== 1 ? 's' : ''}</span>
        <span>·</span>
        <span>{formatBytes(doc.file_size_bytes)}</span>
        <span>·</span>
        <span>{formatDate(doc.uploaded_at)}</span>
      </div>

      {/* Preview */}
      {doc.content_preview && (
        <div className="text-xs text-gray-500 leading-snug">
          {expanded || doc.content_preview.length <= 150
            ? doc.content_preview
            : doc.content_preview.slice(0, 150) + '…'}
          {doc.content_preview.length > 150 && (
            <button
              onClick={() => setExpanded(e => !e)}
              className="ml-1 text-indigo-500 hover:underline inline-flex items-center gap-0.5"
            >
              {expanded ? <><ChevronUp size={11} /> less</> : <><ChevronDown size={11} /> more</>}
            </button>
          )}
        </div>
      )}

      {/* Delete confirmation */}
      {confirming && (
        <div className="bg-red-50 border border-red-200 rounded-lg p-3 text-xs text-red-700 space-y-2">
          <p>
            Are you sure? This will remove <strong>{doc.chunk_count} chunk{doc.chunk_count !== 1 ? 's' : ''}</strong> from
            the knowledge base.
          </p>
          <div className="flex gap-2">
            <button
              onClick={() => { onDelete(doc.doc_id, doc.chunk_count); setConfirming(false) }}
              className="px-3 py-1 bg-red-600 text-white rounded font-medium hover:bg-red-700"
            >
              Delete
            </button>
            <button
              onClick={() => setConfirming(false)}
              className="px-3 py-1 bg-white border border-red-200 text-red-600 rounded font-medium hover:bg-red-50"
            >
              Cancel
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

// ── Search Chunk Result ────────────────────────────────────────────────────────

function ChunkResultCard({ result }: { result: KBChunkResult }) {
  const meta = categoryMeta(result.category)
  return (
    <div className="border border-gray-200 rounded-lg p-2.5 bg-white space-y-1">
      <div className="flex items-center gap-2 flex-wrap">
        <span className="text-xs font-medium text-gray-700 truncate max-w-[140px]">{result.filename}</span>
        <span className={`text-xs px-1.5 py-0.5 rounded-full border ${meta.color}`}>{meta.label}</span>
        <span className="text-xs text-gray-400 ml-auto">score: {result.score}</span>
      </div>
      <p className="text-xs text-gray-600 leading-snug">{result.chunk_text.slice(0, 180)}…</p>
    </div>
  )
}

// ── Main Page ──────────────────────────────────────────────────────────────────

export default function KnowledgeBase() {
  const tenant = getTenant()

  // Documents + stats
  const [docs, setDocs]         = useState<KBDocumentSummary[]>([])
  const [stats, setStats]       = useState<KBStats | null>(null)
  const [loading, setLoading]   = useState(true)
  const [refreshing, setRefreshing] = useState(false)

  // Category filter
  const [activeCategory, setActiveCategory] = useState<string>('all')

  // Upload form
  const [uploadFile, setUploadFile]         = useState<File | null>(null)
  const [uploadCategory, setUploadCategory] = useState('general')
  const [uploadDesc, setUploadDesc]         = useState('')
  const [uploading, setUploading]           = useState(false)
  const [uploadSuccess, setUploadSuccess]   = useState('')
  const [uploadError, setUploadError]       = useState('')
  const [dragOver, setDragOver]             = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)

  // Search
  const [searchQuery, setSearchQuery]       = useState('')
  const [searchResults, setSearchResults]   = useState<KBChunkResult[]>([])
  const [searching, setSearching]           = useState(false)

  const loadAll = useCallback(async (isRefresh = false) => {
    if (isRefresh) setRefreshing(true)
    else setLoading(true)
    try {
      const [docsData, statsData] = await Promise.all([
        api.knowledgeBase.getDocuments(tenant),
        api.knowledgeBase.getStats(tenant),
      ])
      setDocs(docsData)
      setStats(statsData)
    } catch (err) {
      console.error('Failed to load KB data', err)
    } finally {
      setLoading(false)
      setRefreshing(false)
    }
  }, [tenant])

  useEffect(() => { loadAll() }, [loadAll])

  // ── Upload handlers ──────────────────────────────────────────────────────────

  const handleFileDrop = useCallback((e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault()
    setDragOver(false)
    const file = e.dataTransfer.files[0]
    if (file) setUploadFile(file)
  }, [])

  const handleFileSelect = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (file) setUploadFile(file)
  }, [])

  const handleUpload = useCallback(async () => {
    if (!uploadFile) { setUploadError('Please select a file first.'); return }
    setUploading(true)
    setUploadError('')
    setUploadSuccess('')
    try {
      const newDoc = await api.knowledgeBase.upload(tenant, uploadFile, uploadCategory, uploadDesc)
      setDocs(prev => [newDoc, ...prev])
      setStats(prev => prev ? {
        ...prev,
        total_documents: prev.total_documents + 1,
        total_chunks: prev.total_chunks + newDoc.chunk_count,
        by_category: {
          ...prev.by_category,
          [newDoc.category]: (prev.by_category[newDoc.category] ?? 0) + 1,
        },
        last_ingested: newDoc.uploaded_at,
      } : prev)
      setUploadSuccess(`"${newDoc.filename}" uploaded — ${newDoc.chunk_count} chunks indexed.`)
      setUploadFile(null)
      setUploadDesc('')
      if (fileInputRef.current) fileInputRef.current.value = ''
    } catch (err) {
      setUploadError('Upload failed. Please try again.')
      console.error(err)
    } finally {
      setUploading(false)
    }
  }, [uploadFile, uploadCategory, uploadDesc, tenant])

  // ── Delete handler ───────────────────────────────────────────────────────────

  const handleDelete = useCallback(async (docId: string, chunkCount: number) => {
    try {
      await api.knowledgeBase.deleteDocument(docId, tenant)
      setDocs(prev => {
        const removed = prev.find(d => d.doc_id === docId)
        if (!removed) return prev
        return prev.filter(d => d.doc_id !== docId)
      })
      setStats(prev => {
        if (!prev) return prev
        const removed = docs.find(d => d.doc_id === docId)
        const cat = removed?.category ?? 'general'
        const newByCat = { ...prev.by_category }
        if (newByCat[cat] > 1) newByCat[cat] -= 1
        else delete newByCat[cat]
        return {
          ...prev,
          total_documents: Math.max(0, prev.total_documents - 1),
          total_chunks: Math.max(0, prev.total_chunks - chunkCount),
          by_category: newByCat,
        }
      })
    } catch (err) {
      console.error('Delete failed', err)
    }
  }, [tenant, docs])

  // ── Search handler ───────────────────────────────────────────────────────────

  const handleSearch = useCallback(async () => {
    if (!searchQuery.trim()) { setSearchResults([]); return }
    setSearching(true)
    try {
      const results = await api.knowledgeBase.search(tenant, searchQuery, 3)
      setSearchResults(results)
    } catch (err) {
      console.error('Search failed', err)
    } finally {
      setSearching(false)
    }
  }, [searchQuery, tenant])

  // ── Filtered docs ────────────────────────────────────────────────────────────

  const filteredDocs = activeCategory === 'all'
    ? docs
    : docs.filter(d => d.category === activeCategory)

  // ── Render ────────────────────────────────────────────────────────────────────

  return (
    <div className="flex h-full gap-4 p-4 overflow-hidden">

      {/* ── Left panel: Upload + Stats ─────────────────────────────────────── */}
      <div className="w-80 flex flex-col gap-4 overflow-y-auto shrink-0">

        {/* Header */}
        <div className="flex items-center gap-2">
          <Database size={20} className="text-indigo-600" />
          <h1 className="text-lg font-bold text-gray-900">Knowledge Base</h1>
        </div>
        <p className="text-xs text-gray-500 -mt-3">
          Upload company documents to power DDQ, Compliance, and other AI agents.
        </p>

        {/* Stats card */}
        {stats && (
          <div className="border border-indigo-200 bg-indigo-50 rounded-xl p-4 space-y-3">
            <p className="text-sm font-semibold text-gray-900">
              {stats.total_documents} document{stats.total_documents !== 1 ? 's' : ''}
              {' · '}
              {stats.total_chunks} chunk{stats.total_chunks !== 1 ? 's' : ''}
            </p>

            {/* Category breakdown */}
            {Object.keys(stats.by_category).length > 0 && (
              <div className="flex flex-wrap gap-1.5">
                {Object.entries(stats.by_category).map(([cat, count]) => {
                  const meta = categoryMeta(cat)
                  return (
                    <span key={cat} className={`text-xs px-2 py-0.5 rounded-full border font-medium ${meta.color}`}>
                      {meta.label} {count}
                    </span>
                  )
                })}
              </div>
            )}

            {/* Agents powered */}
            <div>
              <p className="text-xs font-medium text-gray-600 mb-1">Agents powered:</p>
              <div className="flex flex-col gap-1">
                {stats.agents_powered.map(agent => (
                  <div key={agent} className="flex items-center gap-2 text-xs text-gray-700">
                    <span className={`w-2 h-2 rounded-full shrink-0 ${AGENT_COLORS[agent] ?? 'bg-gray-400'}`} />
                    {agent}
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}

        {/* Upload form */}
        <div className="space-y-3">
          <p className="text-xs font-semibold text-gray-700 uppercase tracking-wide">Upload Document</p>

          {/* Drag and drop zone */}
          <div
            onDragOver={e => { e.preventDefault(); setDragOver(true) }}
            onDragLeave={() => setDragOver(false)}
            onDrop={handleFileDrop}
            onClick={() => fileInputRef.current?.click()}
            className={`border-2 border-dashed rounded-xl p-4 text-center cursor-pointer transition-colors ${
              dragOver ? 'border-indigo-400 bg-indigo-50' : 'border-gray-300 hover:border-indigo-300 hover:bg-gray-50'
            }`}
          >
            <Upload size={20} className="mx-auto text-gray-400 mb-2" />
            {uploadFile ? (
              <p className="text-xs text-indigo-700 font-medium truncate px-2">{uploadFile.name}</p>
            ) : (
              <>
                <p className="text-xs text-gray-600 font-medium">Drop a PDF, DOCX, or TXT file here</p>
                <p className="text-xs text-gray-400 mt-0.5">or click to browse</p>
              </>
            )}
            <input
              ref={fileInputRef}
              type="file"
              accept=".pdf,.docx,.txt,.md"
              onChange={handleFileSelect}
              className="hidden"
            />
          </div>

          {/* Category dropdown */}
          <div>
            <label className="text-xs font-medium text-gray-700 block mb-1">Category</label>
            <select
              value={uploadCategory}
              onChange={e => setUploadCategory(e.target.value)}
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400 bg-white"
            >
              {KB_CATEGORIES.map(c => (
                <option key={c.value} value={c.value}>{c.label}</option>
              ))}
            </select>
          </div>

          {/* Description */}
          <div>
            <label className="text-xs font-medium text-gray-700 block mb-1">Description <span className="text-gray-400 font-normal">(optional)</span></label>
            <textarea
              value={uploadDesc}
              onChange={e => setUploadDesc(e.target.value)}
              rows={2}
              placeholder="Brief description of this document…"
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-xs resize-none focus:outline-none focus:ring-2 focus:ring-indigo-400"
            />
          </div>

          {/* Upload button */}
          <button
            onClick={handleUpload}
            disabled={uploading || !uploadFile}
            className="w-full bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg py-2.5 text-sm font-medium flex items-center justify-center gap-2 disabled:opacity-50"
          >
            {uploading ? <Loader2 size={16} className="animate-spin" /> : <Upload size={16} />}
            {uploading ? 'Uploading…' : 'Upload to Knowledge Base'}
          </button>

          {uploadSuccess && (
            <div className="flex items-start gap-2 bg-green-50 border border-green-200 rounded-lg p-2.5 text-xs text-green-700">
              <CheckCircle2 size={14} className="mt-0.5 shrink-0" />
              {uploadSuccess}
            </div>
          )}
          {uploadError && (
            <div className="flex items-start gap-2 bg-red-50 border border-red-200 rounded-lg p-2.5 text-xs text-red-700">
              <AlertCircle size={14} className="mt-0.5 shrink-0" />
              {uploadError}
            </div>
          )}
        </div>

        {/* Search */}
        <div className="space-y-2">
          <p className="text-xs font-semibold text-gray-700 uppercase tracking-wide">Search Knowledge Base</p>
          <div className="flex gap-2">
            <input
              value={searchQuery}
              onChange={e => setSearchQuery(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && handleSearch()}
              placeholder="Search knowledge base…"
              className="flex-1 border border-gray-300 rounded-lg px-3 py-2 text-xs focus:outline-none focus:ring-2 focus:ring-indigo-400"
            />
            <button
              onClick={handleSearch}
              disabled={searching}
              className="px-3 py-2 bg-indigo-100 text-indigo-700 rounded-lg hover:bg-indigo-200 disabled:opacity-50"
            >
              {searching ? <Loader2 size={14} className="animate-spin" /> : <Search size={14} />}
            </button>
          </div>

          {searchResults.length > 0 && (
            <div className="space-y-2">
              {searchResults.map((r, i) => (
                <ChunkResultCard key={`${r.doc_id}-${i}`} result={r} />
              ))}
            </div>
          )}
          {searchQuery && !searching && searchResults.length === 0 && (
            <p className="text-xs text-gray-400 text-center py-2">No matching chunks found.</p>
          )}
        </div>
      </div>

      {/* ── Right panel: Document Library ──────────────────────────────────── */}
      <div className="flex-1 flex flex-col min-h-0 overflow-hidden">

        {/* Header */}
        <div className="flex items-center justify-between mb-3 shrink-0">
          <h2 className="font-semibold text-gray-800 flex items-center gap-2">
            <Database size={16} className="text-indigo-600" />
            Document Library
            <span className="text-xs text-gray-400 font-normal bg-gray-100 px-2 py-0.5 rounded-full">
              {filteredDocs.length}
            </span>
          </h2>
          <button
            onClick={() => loadAll(true)}
            disabled={refreshing}
            className="flex items-center gap-1.5 text-xs text-gray-500 hover:text-gray-700 px-2 py-1.5 rounded-lg hover:bg-gray-100 disabled:opacity-50"
          >
            <RefreshCw size={13} className={refreshing ? 'animate-spin' : ''} />
            Refresh
          </button>
        </div>

        {/* Category filter pills */}
        <div className="flex gap-1.5 overflow-x-auto pb-2 shrink-0 scrollbar-hide">
          <button
            onClick={() => setActiveCategory('all')}
            className={`text-xs px-3 py-1 rounded-full border font-medium whitespace-nowrap transition-colors ${
              activeCategory === 'all'
                ? 'bg-indigo-600 text-white border-indigo-600'
                : 'bg-white text-gray-600 border-gray-300 hover:border-indigo-300'
            }`}
          >
            All {docs.length > 0 && `(${docs.length})`}
          </button>
          {KB_CATEGORIES.map(cat => {
            const count = docs.filter(d => d.category === cat.value).length
            if (count === 0) return null
            return (
              <button
                key={cat.value}
                onClick={() => setActiveCategory(cat.value)}
                className={`text-xs px-3 py-1 rounded-full border font-medium whitespace-nowrap transition-colors ${
                  activeCategory === cat.value
                    ? 'bg-indigo-600 text-white border-indigo-600'
                    : `bg-white ${cat.color} hover:border-indigo-300`
                }`}
              >
                {cat.label} ({count})
              </button>
            )
          })}
        </div>

        {/* Document list */}
        <div className="flex-1 overflow-y-auto space-y-3 pr-1 mt-2">
          {loading ? (
            <div className="flex items-center justify-center h-40">
              <Loader2 size={24} className="animate-spin text-indigo-400" />
            </div>
          ) : filteredDocs.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-40 text-gray-400 text-sm space-y-2">
              <Database size={36} className="opacity-30" />
              {docs.length === 0
                ? <p>No documents yet. Upload your first document to power your AI agents.</p>
                : <p>No documents in this category.</p>
              }
            </div>
          ) : (
            filteredDocs.map(doc => (
              <DocumentCard key={doc.doc_id} doc={doc} onDelete={handleDelete} />
            ))
          )}
        </div>
      </div>
    </div>
  )
}
