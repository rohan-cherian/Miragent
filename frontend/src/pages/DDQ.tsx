import { useState, useEffect } from 'react'
import { FileSearch, Upload, Trash2, Loader2, Download, ChevronDown, ChevronUp, FileUp, Copy } from 'lucide-react'
import { api } from '../api/client'
import type { DDQResult, DDQAnswer, KBDocument, DDQTemplateResult, DDQTemplateQuestion } from '../api/client'

const DEFAULT_TENANT_KEY = 'miragent_default_tenant'
const DEFAULT_TENANT = 'acme-corp'

const DOC_TYPE_OPTIONS = [
  { value: 'soc2',           label: 'SOC 2 Report' },
  { value: 'security_policy', label: 'Security Policy' },
  { value: 'privacy_policy', label: 'Privacy Policy' },
  { value: 'bcp',            label: 'Business Continuity Plan' },
  { value: 'data_retention', label: 'Data Retention Policy' },
  { value: 'msa',            label: 'MSA / Contract Template' },
  { value: 'pen_test',       label: 'Pen Test Summary' },
  { value: 'previous_ddq',   label: 'Previous DDQ Responses' },
  { value: 'general',        label: 'General' },
]

function confidenceBadge(label: string) {
  if (label === 'High') {
    return (
      <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-semibold bg-emerald-100 text-emerald-800">
        High
      </span>
    )
  }
  if (label === 'Review') {
    return (
      <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-semibold bg-amber-100 text-amber-800">
        Review
      </span>
    )
  }
  return (
    <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-semibold bg-red-100 text-red-800">
      Unknown
    </span>
  )
}

function categoryBadge(category: string) {
  const colors: Record<string, string> = {
    security:   'bg-blue-100 text-blue-800',
    privacy:    'bg-purple-100 text-purple-800',
    compliance: 'bg-indigo-100 text-indigo-800',
    business:   'bg-teal-100 text-teal-800',
    technical:  'bg-cyan-100 text-cyan-800',
    legal:      'bg-orange-100 text-orange-800',
    financial:  'bg-yellow-100 text-yellow-800',
    vendor:     'bg-pink-100 text-pink-800',
    general:    'bg-gray-100 text-gray-700',
  }
  const cls = colors[category] ?? 'bg-gray-100 text-gray-700'
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium ${cls}`}>
      {category}
    </span>
  )
}

function downloadDocx(b64: string, filename: string) {
  const binary = atob(b64)
  const bytes = new Uint8Array(binary.length)
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i)
  const isDocx = filename.toLowerCase().endsWith('.docx')
  const mimeType = isDocx
    ? 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
    : 'text/plain'
  const blob = new Blob([bytes], { type: mimeType })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}

export default function DDQ() {
  const [activeTab, setActiveTab] = useState<'analyze' | 'fill' | 'kb'>('analyze')
  const [tenantId, setTenantId] = useState(DEFAULT_TENANT)
  const token = localStorage.getItem('miragent_token') ?? ''

  // Analyze tab state
  const [questionsText, setQuestionsText] = useState('')
  const [analyzing, setAnalyzing] = useState(false)
  const [result, setResult] = useState<DDQResult | null>(null)
  const [analyzeError, setAnalyzeError] = useState('')
  const [editedAnswers, setEditedAnswers] = useState<Record<number, string>>({})
  const [expandedRows, setExpandedRows] = useState<Set<number>>(new Set())

  // KB tab state
  const [kbDocs, setKbDocs] = useState<KBDocument[]>([])
  const [uploadFile, setUploadFile] = useState<File | null>(null)
  const [docType, setDocType] = useState('general')
  const [uploading, setUploading] = useState(false)
  const [kbError, setKbError] = useState('')
  const [kbLoading, setKbLoading] = useState(false)

  // Template Fill tab state
  const [templateFile, setTemplateFile] = useState<File | null>(null)
  const [templateFilling, setTemplateFilling] = useState(false)
  const [templateResult, setTemplateResult] = useState<DDQTemplateResult | null>(null)
  const [templateError, setTemplateError] = useState('')
  const [editedTemplateAnswers, setEditedTemplateAnswers] = useState<Record<number, string>>({})

  useEffect(() => {
    const stored = localStorage.getItem(DEFAULT_TENANT_KEY)
    if (stored) setTenantId(stored)
  }, [])

  useEffect(() => {
    if (activeTab === 'kb') loadKBDocs()
  }, [activeTab, tenantId])

  async function loadKBDocs() {
    if (!token) return
    setKbLoading(true)
    setKbError('')
    try {
      const docs = await api.listKBDocuments(token, tenantId)
      setKbDocs(docs)
    } catch (e: unknown) {
      setKbError(e instanceof Error ? e.message : 'Failed to load documents')
    } finally {
      setKbLoading(false)
    }
  }

  async function handleAnalyze() {
    if (!questionsText.trim()) return
    setAnalyzing(true)
    setAnalyzeError('')
    setResult(null)
    setEditedAnswers({})
    setExpandedRows(new Set())
    try {
      const res = await api.analyzeDDQ(token, tenantId, questionsText)
      setResult(res)
    } catch (e: unknown) {
      setAnalyzeError(e instanceof Error ? e.message : 'Analysis failed')
    } finally {
      setAnalyzing(false)
    }
  }

  async function handleUpload() {
    if (!uploadFile) return
    setUploading(true)
    setKbError('')
    try {
      await api.uploadKBDocument(token, tenantId, uploadFile, docType)
      setUploadFile(null)
      await loadKBDocs()
    } catch (e: unknown) {
      setKbError(e instanceof Error ? e.message : 'Upload failed')
    } finally {
      setUploading(false)
    }
  }

  async function handleDeleteDoc(docId: string) {
    if (!confirm('Delete this document and all its chunks?')) return
    try {
      await api.deleteKBDocument(token, docId)
      setKbDocs(prev => prev.filter(d => d.id !== docId))
    } catch (e: unknown) {
      setKbError(e instanceof Error ? e.message : 'Delete failed')
    }
  }

  function getAnswerText(answer: DDQAnswer): string {
    return editedAnswers[answer.question_index] ?? answer.drafted_text
  }

  function handleExport() {
    if (!result) return
    const lines: string[] = [`DDQ Responses — ${new Date().toLocaleDateString()}\n`]
    result.answers.forEach((a, i) => {
      lines.push(`Q${i + 1} [${a.category}]: ${a.question_text}`)
      lines.push(`A: ${getAnswerText(a)}`)
      lines.push(`Confidence: ${a.confidence_label}`)
      if (a.sources.length > 0) lines.push(`Sources: ${a.sources.join(', ')}`)
      lines.push('')
    })
    const blob = new Blob([lines.join('\n')], { type: 'text/plain' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `ddq-responses-${Date.now()}.txt`
    a.click()
    URL.revokeObjectURL(url)
  }

  function toggleRow(idx: number) {
    setExpandedRows(prev => {
      const next = new Set(prev)
      if (next.has(idx)) next.delete(idx)
      else next.add(idx)
      return next
    })
  }

  async function handleFillTemplate() {
    setTemplateFilling(true)
    setTemplateError('')
    setTemplateResult(null)
    setEditedTemplateAnswers({})
    try {
      const res = await api.fillDDQTemplate(tenantId, undefined, templateFile ?? undefined, token)
      setTemplateResult(res)
    } catch (e: unknown) {
      setTemplateError(e instanceof Error ? e.message : 'Template fill failed')
    } finally {
      setTemplateFilling(false)
    }
  }

  async function handleUseSampleTemplate() {
    setTemplateFilling(true)
    setTemplateError('')
    setTemplateResult(null)
    setEditedTemplateAnswers({})
    setTemplateFile(null)
    try {
      const res = await api.fillDDQTemplate(tenantId, undefined, undefined, token)
      setTemplateResult(res)
    } catch (e: unknown) {
      setTemplateError(e instanceof Error ? e.message : 'Template fill failed')
    } finally {
      setTemplateFilling(false)
    }
  }

  function getTemplateAnswerText(q: DDQTemplateQuestion): string {
    return editedTemplateAnswers[q.number] ?? q.answer
  }

  function handleDownloadFilled() {
    if (!templateResult?.filled_docx_b64) return
    const isDocx = !templateResult.source_filename.toLowerCase().endsWith('.txt')
    const ext = isDocx ? 'docx' : 'txt'
    const baseName = templateResult.source_filename.replace(/\.[^.]+$/, '')
    downloadDocx(templateResult.filled_docx_b64, `${baseName}-filled.${ext}`)
  }

  function handleCopyAllAsText() {
    if (!templateResult) return
    const lines: string[] = [`DDQ Responses — ${new Date().toLocaleDateString()}\n`]
    templateResult.questions.forEach(q => {
      lines.push(`Q${q.number}. ${q.question_text}`)
      lines.push(`Answer: ${getTemplateAnswerText(q)}`)
      lines.push(`Confidence: ${q.confidence_label}`)
      lines.push('')
    })
    navigator.clipboard.writeText(lines.join('\n')).catch(() => undefined)
  }

  const tabBase = 'px-4 py-2 text-sm font-medium rounded-lg transition-colors duration-150'
  const tabActive = 'bg-white text-gray-900 shadow-sm'
  const tabInactive = 'text-gray-500 hover:text-gray-700'

  return (
    <div className="max-w-6xl mx-auto">
      {/* Header */}
      <div className="mb-8">
        <div className="flex items-center gap-2 mb-1">
          <FileSearch size={22} style={{ color: '#1B2A4A' }} />
          <h1 className="text-3xl font-bold text-gray-900">DDQ Agent v2</h1>
        </div>
        <p className="text-gray-500">
          Draft answers to Due Diligence Questionnaires — or upload an investor's DOCX template and get a filled copy back.
        </p>
      </div>

      {/* Tab bar */}
      <div className="flex items-center gap-1 bg-gray-100 p-1 rounded-lg w-fit mb-6">
        <button
          className={`${tabBase} ${activeTab === 'analyze' ? tabActive : tabInactive}`}
          onClick={() => setActiveTab('analyze')}
        >
          Analyze DDQ
        </button>
        <button
          className={`${tabBase} ${activeTab === 'fill' ? tabActive : tabInactive}`}
          onClick={() => setActiveTab('fill')}
        >
          Template Fill
        </button>
        <button
          className={`${tabBase} ${activeTab === 'kb' ? tabActive : tabInactive}`}
          onClick={() => setActiveTab('kb')}
        >
          Knowledge Base
        </button>
      </div>

      {/* ── Analyze tab ── */}
      {activeTab === 'analyze' && (
        <div className="space-y-5">
          <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-6">
            <label className="block text-sm font-medium text-gray-700 mb-2">
              Paste DDQ Questions
            </label>
            <textarea
              value={questionsText}
              onChange={e => setQuestionsText(e.target.value)}
              rows={10}
              placeholder="Paste your DDQ questions here — one per line or numbered...&#10;&#10;Example:&#10;1. Do you have a SOC 2 Type II report?&#10;2. What encryption standard do you use for data at rest?&#10;3. How do you handle GDPR data subject requests?"
              className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 font-mono resize-y"
            />
            <div className="flex items-center justify-between mt-4">
              <span className="text-xs text-gray-400">
                Tenant: <span className="font-mono text-gray-600">{tenantId}</span>
              </span>
              <button
                onClick={handleAnalyze}
                disabled={analyzing || !questionsText.trim()}
                style={{ backgroundColor: '#1B2A4A' }}
                className="flex items-center gap-2 px-5 py-2.5 text-sm font-medium text-white rounded-lg hover:opacity-90 disabled:opacity-50 transition-opacity"
              >
                {analyzing ? (
                  <>
                    <Loader2 size={16} className="animate-spin" />
                    Drafting answers…
                  </>
                ) : (
                  <>
                    <FileSearch size={16} />
                    Analyze
                  </>
                )}
              </button>
            </div>
            {analyzeError && (
              <p className="mt-3 text-sm text-red-600 bg-red-50 rounded-lg px-3 py-2">
                {analyzeError}
              </p>
            )}
          </div>

          {result && (
            <>
              {/* Summary bar */}
              <div className="flex items-center justify-between bg-white rounded-xl border border-gray-100 shadow-sm px-6 py-4">
                <div className="flex items-center gap-6 text-sm">
                  <span>
                    <span className="font-semibold text-gray-900">{result.total_questions}</span>
                    <span className="text-gray-500 ml-1">questions</span>
                  </span>
                  <span className="flex items-center gap-1.5">
                    <span className="w-2 h-2 rounded-full bg-emerald-500" />
                    <span className="font-semibold text-gray-900">{result.answered - result.needs_review}</span>
                    <span className="text-gray-500">answered</span>
                  </span>
                  <span className="flex items-center gap-1.5">
                    <span className="w-2 h-2 rounded-full bg-amber-400" />
                    <span className="font-semibold text-gray-900">{result.needs_review}</span>
                    <span className="text-gray-500">need review</span>
                  </span>
                  <span className="flex items-center gap-1.5">
                    <span className="w-2 h-2 rounded-full bg-red-400" />
                    <span className="font-semibold text-gray-900">{result.unanswerable}</span>
                    <span className="text-gray-500">unanswerable</span>
                  </span>
                </div>
                <button
                  onClick={handleExport}
                  className="flex items-center gap-1.5 px-3 py-2 text-xs font-medium text-gray-600 border border-gray-200 rounded-lg hover:bg-gray-50 transition-colors"
                >
                  <Download size={13} />
                  Export as Text
                </button>
              </div>

              {/* Results table */}
              <div className="bg-white rounded-xl border border-gray-100 shadow-sm overflow-hidden">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-gray-100 bg-gray-50">
                      <th className="text-left px-4 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide w-8">#</th>
                      <th className="text-left px-4 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide w-24">Category</th>
                      <th className="text-left px-4 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">Question</th>
                      <th className="text-left px-4 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide w-24">Confidence</th>
                      <th className="w-8" />
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-50">
                    {result.answers.map((answer) => {
                      const isExpanded = expandedRows.has(answer.question_index)
                      return (
                        <>
                          <tr
                            key={`q-${answer.question_index}`}
                            className="hover:bg-gray-50 cursor-pointer"
                            onClick={() => toggleRow(answer.question_index)}
                          >
                            <td className="px-4 py-3 text-gray-400 text-xs font-mono">
                              {answer.question_index + 1}
                            </td>
                            <td className="px-4 py-3">
                              {categoryBadge(answer.category)}
                            </td>
                            <td className="px-4 py-3 text-gray-800 text-sm">
                              {answer.question_text.length > 100
                                ? answer.question_text.slice(0, 100) + '…'
                                : answer.question_text}
                            </td>
                            <td className="px-4 py-3">
                              {confidenceBadge(answer.confidence_label)}
                            </td>
                            <td className="px-4 py-3 text-gray-400">
                              {isExpanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
                            </td>
                          </tr>
                          {isExpanded && (
                            <tr key={`a-${answer.question_index}`} className="bg-gray-50">
                              <td colSpan={5} className="px-6 pb-4 pt-2">
                                <div className="space-y-3">
                                  {answer.question_text.length > 100 && (
                                    <p className="text-sm text-gray-700 font-medium">
                                      {answer.question_text}
                                    </p>
                                  )}
                                  <div>
                                    <label className="block text-xs font-medium text-gray-500 mb-1">
                                      Drafted Answer{answer.needs_human ? ' — human review recommended' : ''}
                                    </label>
                                    <textarea
                                      value={getAnswerText(answer)}
                                      onChange={e =>
                                        setEditedAnswers(prev => ({
                                          ...prev,
                                          [answer.question_index]: e.target.value,
                                        }))
                                      }
                                      rows={4}
                                      className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 resize-y"
                                    />
                                  </div>
                                  {answer.sources.length > 0 && (
                                    <p className="text-xs text-gray-500">
                                      Sources:{' '}
                                      {answer.sources.map((s, i) => (
                                        <span key={i} className="inline-flex items-center px-1.5 py-0.5 rounded text-xs bg-blue-50 text-blue-700 mr-1">
                                          {s}
                                        </span>
                                      ))}
                                    </p>
                                  )}
                                  <p className="text-xs text-gray-400">
                                    Confidence score: {(answer.confidence * 100).toFixed(0)}%
                                  </p>
                                </div>
                              </td>
                            </tr>
                          )}
                        </>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </div>
      )}

      {/* ── Template Fill tab ── */}
      {activeTab === 'fill' && (
        <div className="grid grid-cols-2 gap-5">
          {/* Left panel — upload + controls */}
          <div className="space-y-4">
            <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-6">
              <h2 className="text-base font-semibold text-gray-900 mb-1">Upload DDQ Template</h2>
              <p className="text-xs text-gray-500 mb-4">
                Upload the investor's actual DDQ form (.docx, .txt) and Miragent will fill it in automatically.
              </p>

              {/* Drag-and-drop zone */}
              <label className="block border-2 border-dashed border-gray-200 rounded-lg px-4 py-8 text-center cursor-pointer hover:border-blue-300 hover:bg-blue-50/30 transition-colors">
                <FileUp size={28} className="mx-auto text-gray-400 mb-2" />
                <span className="block text-sm font-medium text-gray-700">
                  {templateFile ? templateFile.name : 'Drop your DDQ template here'}
                </span>
                {templateFile ? (
                  <span className="text-xs text-gray-400 mt-1 block">
                    {(templateFile.size / 1024).toFixed(1)} KB — click to change
                  </span>
                ) : (
                  <span className="text-xs text-gray-400 mt-1 block">
                    Accepts .docx, .txt, .pdf
                  </span>
                )}
                <input
                  type="file"
                  accept=".docx,.txt,.pdf"
                  className="hidden"
                  onChange={e => setTemplateFile(e.target.files?.[0] ?? null)}
                />
              </label>

              <div className="flex items-center gap-2 mt-3">
                <div className="flex-1 h-px bg-gray-100" />
                <span className="text-xs text-gray-400">or</span>
                <div className="flex-1 h-px bg-gray-100" />
              </div>

              <button
                onClick={handleUseSampleTemplate}
                disabled={templateFilling}
                className="w-full mt-3 px-4 py-2 text-sm font-medium text-gray-600 border border-gray-200 rounded-lg hover:bg-gray-50 transition-colors disabled:opacity-50"
              >
                Use Sample Template
              </button>

              <button
                onClick={handleFillTemplate}
                disabled={templateFilling}
                style={{ backgroundColor: '#1B2A4A' }}
                className="w-full mt-3 flex items-center justify-center gap-2 px-5 py-2.5 text-sm font-medium text-white rounded-lg hover:opacity-90 disabled:opacity-50 transition-opacity"
              >
                {templateFilling ? (
                  <>
                    <Loader2 size={16} className="animate-spin" />
                    Filling template…
                  </>
                ) : (
                  <>
                    <FileSearch size={16} />
                    Fill Template
                  </>
                )}
              </button>

              {templateError && (
                <p className="mt-3 text-sm text-red-600 bg-red-50 rounded-lg px-3 py-2">
                  {templateError}
                </p>
              )}
            </div>

            {/* Summary card */}
            {templateResult && (
              <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-5">
                <h3 className="text-sm font-semibold text-gray-900 mb-2">Result Summary</h3>
                <div className="flex items-center gap-4 text-sm mb-3">
                  <span>
                    <span className="font-semibold text-gray-900">{templateResult.total_questions}</span>
                    <span className="text-gray-500 ml-1">questions parsed</span>
                  </span>
                  <span>
                    <span className="font-semibold text-emerald-600">{templateResult.filled_questions}</span>
                    <span className="text-gray-500 ml-1">filled</span>
                  </span>
                </div>
                <p className="text-xs text-gray-500">{templateResult.summary}</p>
              </div>
            )}
          </div>

          {/* Right panel — answer review */}
          <div className="space-y-4">
            {templateResult ? (
              <>
                {/* Action buttons */}
                <div className="flex items-center gap-2">
                  {templateResult.can_download && (
                    <button
                      onClick={handleDownloadFilled}
                      style={{ backgroundColor: '#1B2A4A' }}
                      className="flex items-center gap-1.5 px-4 py-2 text-sm font-medium text-white rounded-lg hover:opacity-90 transition-opacity"
                    >
                      <Download size={14} />
                      Download Filled DOCX
                    </button>
                  )}
                  <button
                    onClick={handleCopyAllAsText}
                    className="flex items-center gap-1.5 px-4 py-2 text-sm font-medium text-gray-600 border border-gray-200 rounded-lg hover:bg-gray-50 transition-colors"
                  >
                    <Copy size={14} />
                    Copy All as Text
                  </button>
                </div>

                {/* Q&A list */}
                <div className="space-y-3 max-h-[700px] overflow-y-auto pr-1">
                  {templateResult.questions.map(q => (
                    <div key={q.number} className="bg-white rounded-xl border border-gray-100 shadow-sm p-4">
                      <div className="flex items-start justify-between gap-2 mb-2">
                        <p className="text-sm font-semibold text-gray-800">
                          <span className="text-gray-400 font-mono text-xs mr-1">Q{q.number}.</span>
                          {q.question_text}
                        </p>
                        {confidenceBadge(q.confidence_label)}
                      </div>
                      <textarea
                        value={getTemplateAnswerText(q)}
                        onChange={e =>
                          setEditedTemplateAnswers(prev => ({
                            ...prev,
                            [q.number]: e.target.value,
                          }))
                        }
                        rows={4}
                        className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 resize-y"
                      />
                      <p className="text-xs text-gray-400 mt-1">
                        Confidence: {(q.confidence * 100).toFixed(0)}%
                      </p>
                    </div>
                  ))}
                </div>
              </>
            ) : (
              <div className="flex flex-col items-center justify-center h-64 text-center bg-white rounded-xl border border-gray-100 shadow-sm">
                <FileUp size={36} className="text-gray-300 mb-3" />
                <p className="text-gray-500 font-medium">No template filled yet.</p>
                <p className="text-gray-400 text-sm mt-1">
                  Upload a DDQ or click "Use Sample Template" to get started.
                </p>
              </div>
            )}
          </div>
        </div>
      )}

      {/* ── Knowledge Base tab ── */}
      {activeTab === 'kb' && (
        <div className="space-y-5">
          {/* Upload card */}
          <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-6">
            <h2 className="text-base font-semibold text-gray-900 mb-1">Upload Document</h2>
            <p className="text-xs text-gray-500 mb-4">
              Add policy documents to improve DDQ answer quality. Accepts .txt, .pdf, .docx.
            </p>
            <div className="flex items-end gap-3 flex-wrap">
              <div className="flex-1 min-w-48">
                <label className="block text-xs font-medium text-gray-600 mb-1">File</label>
                <input
                  type="file"
                  accept=".txt,.pdf,.docx,.md"
                  onChange={e => setUploadFile(e.target.files?.[0] ?? null)}
                  className="block w-full text-sm text-gray-500 file:mr-3 file:py-1.5 file:px-3 file:rounded-lg file:border file:border-gray-200 file:text-xs file:font-medium file:text-gray-700 file:bg-gray-50 file:hover:bg-gray-100 cursor-pointer"
                />
              </div>
              <div className="w-52">
                <label className="block text-xs font-medium text-gray-600 mb-1">Document Type</label>
                <select
                  value={docType}
                  onChange={e => setDocType(e.target.value)}
                  className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 bg-white"
                >
                  {DOC_TYPE_OPTIONS.map(opt => (
                    <option key={opt.value} value={opt.value}>
                      {opt.label}
                    </option>
                  ))}
                </select>
              </div>
              <button
                onClick={handleUpload}
                disabled={!uploadFile || uploading}
                style={{ backgroundColor: '#1B2A4A' }}
                className="flex items-center gap-2 px-4 py-2 text-sm font-medium text-white rounded-lg hover:opacity-90 disabled:opacity-50 transition-opacity"
              >
                {uploading ? (
                  <>
                    <Loader2 size={15} className="animate-spin" />
                    Uploading…
                  </>
                ) : (
                  <>
                    <Upload size={15} />
                    Upload
                  </>
                )}
              </button>
            </div>
            {uploadFile && (
              <p className="mt-2 text-xs text-gray-500">
                Selected: <span className="font-medium text-gray-700">{uploadFile.name}</span>{' '}
                ({(uploadFile.size / 1024).toFixed(1)} KB)
              </p>
            )}
            {kbError && (
              <p className="mt-3 text-sm text-red-600 bg-red-50 rounded-lg px-3 py-2">
                {kbError}
              </p>
            )}
          </div>

          {/* Documents table */}
          <div className="bg-white rounded-xl border border-gray-100 shadow-sm overflow-hidden">
            <div className="px-6 py-4 border-b border-gray-100 flex items-center justify-between">
              <h2 className="text-base font-semibold text-gray-900">Documents</h2>
              <span className="text-xs text-gray-400">{kbDocs.length} document{kbDocs.length !== 1 ? 's' : ''}</span>
            </div>

            {kbLoading ? (
              <div className="flex items-center justify-center py-12">
                <Loader2 size={24} className="animate-spin text-gray-400" />
              </div>
            ) : kbDocs.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-16 text-center px-6">
                <FileSearch size={40} className="text-gray-300 mb-3" />
                <p className="text-gray-500 font-medium">No documents uploaded yet.</p>
                <p className="text-gray-400 text-sm mt-1">
                  Add your policy docs to get better DDQ answers.
                </p>
              </div>
            ) : (
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-gray-100 bg-gray-50">
                    <th className="text-left px-4 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">Filename</th>
                    <th className="text-left px-4 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide w-40">Type</th>
                    <th className="text-left px-4 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide w-24">Chunks</th>
                    <th className="text-left px-4 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide w-36">Uploaded</th>
                    <th className="w-12" />
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-50">
                  {kbDocs.map(doc => {
                    const typeLabel = DOC_TYPE_OPTIONS.find(o => o.value === doc.doc_type)?.label ?? doc.doc_type
                    return (
                      <tr key={doc.id} className="hover:bg-gray-50">
                        <td className="px-4 py-3 text-gray-800 font-medium truncate max-w-xs">
                          {doc.filename}
                        </td>
                        <td className="px-4 py-3">
                          <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-blue-50 text-blue-800">
                            {typeLabel}
                          </span>
                        </td>
                        <td className="px-4 py-3 text-gray-500 text-xs font-mono">
                          {doc.chunk_count}
                        </td>
                        <td className="px-4 py-3 text-gray-500 text-xs">
                          {new Date(doc.created_at).toLocaleDateString()}
                        </td>
                        <td className="px-4 py-3">
                          <button
                            onClick={() => handleDeleteDoc(doc.id)}
                            className="p-1.5 rounded-lg text-gray-400 hover:text-red-500 hover:bg-red-50 transition-colors"
                            title="Delete document"
                          >
                            <Trash2 size={14} />
                          </button>
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
