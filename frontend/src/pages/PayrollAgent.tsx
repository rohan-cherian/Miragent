import { useState, useEffect } from 'react'
import { Receipt, Loader2, Download, Copy, CheckCheck, ChevronDown, ChevronUp } from 'lucide-react'
import { api } from '../api/client'
import type { PayrollResult, PayrollRequest } from '../api/client'

const DEFAULT_TENANT_KEY = 'miragent_default_tenant'
const DEFAULT_TENANT = 'acme-corp'

const CURRENT_YEAR = new Date().getFullYear()
const YEAR_OPTIONS = [CURRENT_YEAR, CURRENT_YEAR - 1, CURRENT_YEAR - 2, CURRENT_YEAR - 3]

const DOC_TYPE_OPTIONS = [
  { value: 'paystub', label: 'Pay Stub' },
  { value: 'w2',      label: 'W-2 (Annual)' },
  { value: '1099',    label: '1099-NEC' },
  { value: 'ytd',     label: 'Year-to-Date Summary' },
]

function fmt(n: unknown): string {
  const num = typeof n === 'number' ? n : parseFloat(String(n) || '0')
  if (isNaN(num)) return '$0.00'
  return num.toLocaleString('en-US', { style: 'currency', currency: 'USD' })
}

function docTypeLabel(dt: string) {
  return DOC_TYPE_OPTIONS.find(o => o.value === dt)?.label ?? dt
}

// ── W-2 Renderer ─────────────────────────────────────────────────────────────

function W2Document({ doc }: { doc: Record<string, unknown> }) {
  const employer = doc.employer as Record<string, string>
  const employee = doc.employee as Record<string, string>
  const box12a_code = doc.box_12a_code as string
  const box12a_amt = doc.box_12a_amount as number
  const box12b_code = doc.box_12b_code as string
  const box12b_amt = doc.box_12b_amount as number

  const Box = ({
    num, label, value, wide, className,
  }: { num: string; label: string; value: string; wide?: boolean; className?: string }) => (
    <div
      className={`border border-gray-300 p-2 ${wide ? 'col-span-2' : ''} ${className ?? ''}`}
    >
      <div className="text-[10px] font-bold text-gray-500 uppercase tracking-wide mb-0.5">
        Box {num} — {label}
      </div>
      <div className="text-sm font-semibold text-gray-900">{value}</div>
    </div>
  )

  return (
    <div className="bg-white border-2 border-gray-400 rounded-xl overflow-hidden font-mono text-xs">
      {/* Header */}
      <div className="flex items-start justify-between bg-gray-100 border-b border-gray-300 px-4 py-3">
        <div>
          <div className="text-xs font-bold text-gray-500 uppercase tracking-widest">
            Department of the Treasury — Internal Revenue Service
          </div>
          <div className="text-lg font-bold text-gray-900 mt-0.5">
            W-2 Wage and Tax Statement
          </div>
          <div className="text-sm text-gray-600">{String(doc.tax_year)}</div>
        </div>
        <div className="bg-navy-700 text-right">
          <div className="inline-block bg-gray-800 text-white text-sm font-bold px-3 py-1 rounded">
            TAX YEAR {String(doc.tax_year)}
          </div>
        </div>
      </div>

      {/* Employer / Employee info */}
      <div className="grid grid-cols-2 border-b border-gray-300">
        <div className="border-r border-gray-300 p-3">
          <div className="text-[10px] font-bold text-gray-500 uppercase mb-1">Employer</div>
          <div className="font-semibold text-gray-900">{employer?.name}</div>
          <div className="text-gray-600">{employer?.address}</div>
          <div className="text-gray-500 mt-1">EIN: {employer?.ein}</div>
        </div>
        <div className="p-3">
          <div className="text-[10px] font-bold text-gray-500 uppercase mb-1">Employee</div>
          <div className="font-semibold text-gray-900">{employee?.name}</div>
          <div className="text-gray-600">{employee?.address}</div>
          <div className="text-gray-500 mt-1">EIN/SSN: xxx-xx-{employee?.ssn_last4}</div>
        </div>
      </div>

      {/* Wage & Tax boxes */}
      <div className="grid grid-cols-4 border-b border-gray-300 divide-x divide-gray-300">
        <Box num="1" label="Wages" value={fmt(doc.box_1_wages)} />
        <Box num="2" label="Federal Tax Withheld" value={fmt(doc.box_2_federal_tax)} />
        <Box num="3" label="SS Wages" value={fmt(doc.box_3_ss_wages)} />
        <Box num="4" label="SS Tax Withheld" value={fmt(doc.box_4_ss_tax)} />
      </div>
      <div className="grid grid-cols-4 border-b border-gray-300 divide-x divide-gray-300">
        <Box num="5" label="Medicare Wages" value={fmt(doc.box_5_medicare_wages)} />
        <Box num="6" label="Medicare Tax" value={fmt(doc.box_6_medicare_tax)} />
        <Box num="7" label="SS Tips" value={fmt(doc.box_7_ss_tips)} />
        <Box num="8" label="Allocated Tips" value={fmt(doc.box_8_allocated_tips)} />
      </div>
      <div className="grid grid-cols-4 border-b border-gray-300 divide-x divide-gray-300">
        <Box num="10" label="Dependent Care" value={fmt(doc.box_10_dependent_care)} />
        <Box num="11" label="Nonqualified Plans" value={fmt(doc.box_11_nonqualified_plans)} />
        <Box num="12a" label={`Code ${box12a_code} (401k)`} value={fmt(box12a_amt)} />
        <Box num="12b" label={`Code ${box12b_code} (Health)`} value={fmt(box12b_amt)} />
      </div>
      <div className="grid grid-cols-4 border-b border-gray-300 divide-x divide-gray-300">
        <div className="border-r border-gray-300 p-2 col-span-2">
          <div className="text-[10px] font-bold text-gray-500 uppercase mb-1">Box 13 — Checkboxes</div>
          <div className="flex gap-3 text-xs">
            <span>{doc.box_13_statutory_employee ? '☑' : '☐'} Statutory Employee</span>
            <span>{doc.box_13_retirement_plan ? '☑' : '☐'} Retirement Plan</span>
            <span>{doc.box_13_third_party_sick ? '☑' : '☐'} 3rd Party Sick Pay</span>
          </div>
        </div>
        <Box num="15" label="State" value={String(doc.box_15_state)} />
        <Box num="16" label="State Wages" value={fmt(doc.box_16_state_wages)} />
      </div>
      <div className="grid grid-cols-4 divide-x divide-gray-300">
        <div className="col-span-2 p-2 border-r border-gray-300">
          <div className="text-[10px] font-bold text-gray-500 uppercase mb-1">Box 15 — Employer State ID</div>
          <div className="text-sm text-gray-700">{String(doc.box_15_employer_state_id)}</div>
        </div>
        <Box num="17" label="State Income Tax" value={fmt(doc.box_17_state_income_tax)} />
        <Box num="19" label="Local Tax" value={fmt(doc.box_19_local_tax)} />
      </div>
    </div>
  )
}

// ── Paystub Renderer ──────────────────────────────────────────────────────────

function PaystubDocument({ doc }: { doc: Record<string, unknown> }) {
  const employer = doc.employer as Record<string, string>
  const employee = doc.employee as Record<string, string>
  const earnings = doc.earnings as Record<string, unknown>
  const deductions = doc.deductions as Record<string, unknown>
  const ytd = doc.ytd as Record<string, unknown>

  return (
    <div className="bg-white border border-gray-200 rounded-xl overflow-hidden text-sm">
      {/* Header */}
      <div className="px-6 py-4 border-b border-gray-200" style={{ backgroundColor: '#1B2A4A' }}>
        <div className="flex justify-between items-start">
          <div>
            <div className="text-white font-bold text-base">{employer?.name}</div>
            <div className="text-gray-300 text-xs mt-0.5">{employer?.address}</div>
          </div>
          <div className="text-right">
            <div className="text-white font-semibold">Earnings Statement</div>
            <div className="text-gray-300 text-xs">Stub #{String(doc.pay_stub_number)}</div>
          </div>
        </div>
        <div className="mt-3 grid grid-cols-3 gap-4 text-xs">
          <div>
            <div className="text-gray-400">Pay Date</div>
            <div className="text-white font-medium">{String(doc.pay_date)}</div>
          </div>
          <div>
            <div className="text-gray-400">Pay Period</div>
            <div className="text-white font-medium">
              {String(doc.pay_period_start)} — {String(doc.pay_period_end)}
            </div>
          </div>
          <div>
            <div className="text-gray-400">Employee</div>
            <div className="text-white font-medium">{employee?.name}</div>
            <div className="text-gray-400">{employee?.title}</div>
          </div>
        </div>
      </div>

      {/* Earnings + Deductions side by side */}
      <div className="grid grid-cols-2 divide-x divide-gray-200">
        {/* Earnings */}
        <div className="p-5">
          <div className="text-xs font-bold text-gray-500 uppercase tracking-wide mb-3">Earnings</div>
          <table className="w-full text-sm">
            <thead>
              <tr className="text-xs text-gray-400 border-b border-gray-100">
                <th className="text-left pb-1 font-medium">Description</th>
                {earnings.regular_hours !== undefined && (
                  <th className="text-right pb-1 font-medium">Hrs</th>
                )}
                <th className="text-right pb-1 font-medium">Amount</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50">
              <tr>
                <td className="py-1.5 text-gray-700">
                  {employee?.pay_type === 'hourly' ? 'Regular Hours' : 'Regular Salary'}
                </td>
                {earnings.regular_hours !== undefined && (
                  <td className="py-1.5 text-right text-gray-600">
                    {String(earnings.regular_hours)}
                  </td>
                )}
                <td className="py-1.5 text-right font-medium text-gray-900">
                  {fmt(earnings.regular)}
                </td>
              </tr>
              <tr>
                <td className="py-1.5 text-gray-700">Overtime</td>
                {earnings.regular_hours !== undefined && (
                  <td className="py-1.5 text-right text-gray-600">0</td>
                )}
                <td className="py-1.5 text-right text-gray-500">{fmt(0)}</td>
              </tr>
              <tr className="border-t border-gray-200 font-semibold">
                <td className="pt-2 text-gray-900">Gross Pay</td>
                {earnings.regular_hours !== undefined && <td />}
                <td className="pt-2 text-right text-gray-900">{fmt(earnings.gross)}</td>
              </tr>
            </tbody>
          </table>
        </div>

        {/* Deductions */}
        <div className="p-5">
          <div className="text-xs font-bold text-gray-500 uppercase tracking-wide mb-3">Deductions</div>
          <table className="w-full text-sm">
            <thead>
              <tr className="text-xs text-gray-400 border-b border-gray-100">
                <th className="text-left pb-1 font-medium">Description</th>
                <th className="text-right pb-1 font-medium">Amount</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50">
              {[
                ['Federal Income Tax', deductions.federal_income_tax],
                ['State Income Tax', deductions.state_income_tax],
                ['Social Security', deductions.social_security_tax],
                ['Medicare', deductions.medicare_tax],
                ['Health Insurance', deductions.health_insurance],
                ['Dental', deductions.dental],
                ['Vision', deductions.vision],
                ['401(k)', deductions['401k_contribution']],
              ].map(([label, val]) => (
                <tr key={String(label)}>
                  <td className="py-1.5 text-gray-700">{String(label)}</td>
                  <td className="py-1.5 text-right text-gray-700">{fmt(val)}</td>
                </tr>
              ))}
              <tr className="border-t border-gray-200 font-semibold">
                <td className="pt-2 text-gray-900">Total Deductions</td>
                <td className="pt-2 text-right text-gray-900">{fmt(deductions.total)}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      {/* Net Pay banner */}
      <div className="mx-5 mb-5 rounded-lg px-5 py-3 bg-emerald-50 border border-emerald-200 flex justify-between items-center">
        <span className="font-bold text-emerald-800 text-base">Net Pay</span>
        <span className="font-bold text-emerald-800 text-xl">{fmt(doc.net_pay)}</span>
      </div>

      {/* YTD row */}
      <div className="px-5 pb-5">
        <div className="text-xs font-bold text-gray-500 uppercase tracking-wide mb-2">Year-to-Date</div>
        <div className="grid grid-cols-4 gap-2 text-xs">
          {[
            ['YTD Gross', ytd?.gross],
            ['YTD Taxes', (
              (ytd?.federal_income_tax as number || 0) +
              (ytd?.state_income_tax as number || 0) +
              (ytd?.social_security_tax as number || 0) +
              (ytd?.medicare_tax as number || 0)
            )],
            ['YTD 401k', ytd?.['401k_contribution']],
            ['YTD Net', ytd?.net],
          ].map(([label, val]) => (
            <div key={String(label)} className="bg-gray-50 rounded p-2">
              <div className="text-gray-500">{String(label)}</div>
              <div className="font-semibold text-gray-900">{fmt(val)}</div>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

// ── YTD Renderer ──────────────────────────────────────────────────────────────

function YTDDocument({ doc }: { doc: Record<string, unknown> }) {
  const employee = doc.employee as Record<string, string>
  const months = doc.monthly_breakdown as Array<Record<string, unknown>>
  const totals = doc.totals as Record<string, unknown>

  const cols = [
    { key: 'gross',              label: 'Gross' },
    { key: 'federal_tax',        label: 'Fed Tax' },
    { key: 'state_tax',          label: 'State Tax' },
    { key: 'social_security',    label: 'SS' },
    { key: 'medicare',           label: 'Medicare' },
    { key: '401k',               label: '401k' },
    { key: 'health_insurance',   label: 'Health' },
    { key: 'net_pay',            label: 'Net Pay' },
  ]

  return (
    <div className="bg-white border border-gray-200 rounded-xl overflow-hidden text-sm">
      {/* Header */}
      <div className="px-6 py-4 border-b border-gray-100">
        <div className="flex justify-between items-start">
          <div>
            <div className="text-lg font-bold text-gray-900">Year-to-Date Earnings Summary</div>
            <div className="text-gray-500 text-xs">
              {employee?.name} · {employee?.department} · {employee?.title}
            </div>
          </div>
          <div className="text-right">
            <div className="text-sm font-semibold text-gray-700">{String(doc.year)}</div>
            <div className="text-xs text-gray-400">Through {String(doc.through_month)}</div>
          </div>
        </div>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="bg-gray-50 border-b border-gray-200">
              <th className="text-left px-3 py-2 font-semibold text-gray-600 sticky left-0 bg-gray-50">Month</th>
              {cols.map(c => (
                <th key={c.key} className="text-right px-3 py-2 font-semibold text-gray-600 whitespace-nowrap">
                  {c.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {months.map((row, i) => (
              <tr
                key={String(row.month)}
                className={`border-b border-gray-50 ${i % 2 === 0 ? 'bg-white' : 'bg-gray-50/50'} hover:bg-blue-50/30`}
              >
                <td className="px-3 py-2 font-medium text-gray-700 sticky left-0">
                  {String(row.month)}
                </td>
                {cols.map(c => (
                  <td key={c.key} className={`px-3 py-2 text-right ${c.key === 'net_pay' ? 'font-semibold text-emerald-700' : 'text-gray-600'}`}>
                    {fmt(row[c.key])}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
          <tfoot>
            <tr className="border-t-2 border-gray-300 bg-gray-100 font-bold">
              <td className="px-3 py-2 text-gray-900">TOTAL</td>
              {cols.map(c => {
                const totalKey = c.key === 'net_pay' ? 'net_pay' : c.key
                return (
                  <td key={c.key} className={`px-3 py-2 text-right ${c.key === 'net_pay' ? 'text-emerald-700' : 'text-gray-900'}`}>
                    {fmt(totals[totalKey])}
                  </td>
                )
              })}
            </tr>
          </tfoot>
        </table>
      </div>
    </div>
  )
}

// ── 1099 Renderer ─────────────────────────────────────────────────────────────

function Doc1099({ doc }: { doc: Record<string, unknown> }) {
  const payer = doc.payer as Record<string, string>
  const recipient = doc.recipient as Record<string, string>

  return (
    <div className="bg-white border-2 border-gray-400 rounded-xl overflow-hidden font-mono text-xs">
      <div className="flex justify-between items-start bg-gray-100 border-b border-gray-300 px-4 py-3">
        <div>
          <div className="text-xs font-bold text-gray-500 uppercase tracking-widest">
            Department of the Treasury — Internal Revenue Service
          </div>
          <div className="text-lg font-bold text-gray-900">1099-NEC — Nonemployee Compensation</div>
          <div className="text-sm text-gray-600">{String(doc.tax_year)}</div>
        </div>
        <div className="inline-block bg-gray-800 text-white text-sm font-bold px-3 py-1 rounded">
          TAX YEAR {String(doc.tax_year)}
        </div>
      </div>
      <div className="grid grid-cols-2 border-b border-gray-300">
        <div className="border-r border-gray-300 p-3">
          <div className="text-[10px] font-bold text-gray-500 uppercase mb-1">Payer</div>
          <div className="font-semibold text-gray-900">{payer?.name}</div>
          <div className="text-gray-600">{payer?.address}</div>
          <div className="text-gray-500 mt-1">EIN: {payer?.ein}</div>
        </div>
        <div className="p-3">
          <div className="text-[10px] font-bold text-gray-500 uppercase mb-1">Recipient</div>
          <div className="font-semibold text-gray-900">{recipient?.name}</div>
          <div className="text-gray-500">TIN: xxx-xx-{recipient?.tin_last4}</div>
        </div>
      </div>
      <div className="grid grid-cols-3 divide-x divide-gray-300 border-b border-gray-300">
        <div className="p-3">
          <div className="text-[10px] font-bold text-gray-500 uppercase mb-1">Box 1 — Nonemployee Compensation</div>
          <div className="text-xl font-bold text-gray-900">{fmt(doc.box_1_nonemployee_compensation)}</div>
        </div>
        <div className="p-3">
          <div className="text-[10px] font-bold text-gray-500 uppercase mb-1">Box 4 — Federal Tax Withheld</div>
          <div className="text-sm font-semibold text-gray-500">{fmt(0)}</div>
        </div>
        <div className="p-3">
          <div className="text-[10px] font-bold text-gray-500 uppercase mb-1">Box 6 — State</div>
          <div className="text-sm font-semibold text-gray-700">{String(doc.box_6_state)}</div>
        </div>
      </div>
      <div className="px-4 py-3 bg-amber-50 text-amber-800 text-xs">
        {String(doc.note)}
      </div>
    </div>
  )
}

// ── Document viewer dispatch ───────────────────────────────────────────────────

function DocumentViewer({ result }: { result: PayrollResult }) {
  const [copied, setCopied] = useState(false)

  if (!result.document) return null

  const doc = result.document

  function handleCopy() {
    navigator.clipboard.writeText(JSON.stringify(doc, null, 2))
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  function handleDownload() {
    const blob = new Blob([JSON.stringify(doc, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${result.document_type}-${result.period}-${result.request_id.slice(0, 8)}.json`
    a.click()
    URL.revokeObjectURL(url)
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-base font-semibold text-gray-900">
          {docTypeLabel(result.document_type)} — {result.period}
        </h2>
        <div className="flex gap-2">
          <button
            onClick={handleCopy}
            className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-gray-600 border border-gray-200 rounded-lg hover:bg-gray-50 transition-colors"
          >
            {copied ? <CheckCheck size={13} className="text-emerald-500" /> : <Copy size={13} />}
            {copied ? 'Copied!' : 'Copy JSON'}
          </button>
          <button
            onClick={handleDownload}
            className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-gray-600 border border-gray-200 rounded-lg hover:bg-gray-50 transition-colors"
          >
            <Download size={13} />
            Download
          </button>
        </div>
      </div>

      {result.document_type === 'w2' && <W2Document doc={doc} />}
      {result.document_type === 'paystub' && <PaystubDocument doc={doc} />}
      {result.document_type === '1099' && <Doc1099 doc={doc} />}
      {result.document_type === 'ytd' && <YTDDocument doc={doc} />}
    </div>
  )
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function PayrollAgent() {
  const [docType, setDocType] = useState<'w2' | 'paystub' | '1099' | 'ytd'>('paystub')
  const [period, setPeriod] = useState('latest')
  const [tenantId, setTenantId] = useState(DEFAULT_TENANT)
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<PayrollResult | null>(null)
  const [history, setHistory] = useState<PayrollRequest[]>([])
  const [error, setError] = useState('')
  const [historyExpanded, setHistoryExpanded] = useState(true)

  const token = localStorage.getItem('miragent_token') ?? ''

  useEffect(() => {
    const stored = localStorage.getItem(DEFAULT_TENANT_KEY)
    if (stored) setTenantId(stored)
    loadHistory()
  }, [])

  // Reset period when docType changes
  useEffect(() => {
    if (docType === 'paystub') setPeriod('latest')
    else if (docType === 'ytd') setPeriod(String(CURRENT_YEAR))
    else setPeriod(String(CURRENT_YEAR - 1))
  }, [docType])

  async function loadHistory() {
    if (!token) return
    try {
      const reqs = await api.listPayrollRequests(token, tenantId || DEFAULT_TENANT)
      setHistory(reqs.slice(0, 10))
    } catch {
      // history is non-critical; ignore silently
    }
  }

  async function handleRequest() {
    if (!token) {
      setError('You must be logged in to request payroll documents.')
      return
    }
    setLoading(true)
    setError('')
    setResult(null)
    try {
      const res = await api.requestPayrollDocument(token, tenantId, docType, period)
      setResult(res)
      await loadHistory()
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Request failed. Please try again.')
    } finally {
      setLoading(false)
    }
  }

  async function handleViewHistory(req: PayrollRequest) {
    if (!token) return
    setLoading(true)
    setError('')
    try {
      const res = await api.getPayrollRequest(token, req.id)
      setResult(res)
      window.scrollTo({ top: 0, behavior: 'smooth' })
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to load request.')
    } finally {
      setLoading(false)
    }
  }

  const needsYear = docType === 'w2' || docType === '1099'
  const isYtd = docType === 'ytd'
  const isPaystub = docType === 'paystub'

  return (
    <div className="max-w-5xl mx-auto space-y-6">
      {/* Page header */}
      <div className="mb-2">
        <div className="flex items-center gap-2 mb-1">
          <Receipt size={22} style={{ color: '#1B2A4A' }} />
          <h1 className="text-3xl font-bold text-gray-900">Payroll Documents</h1>
        </div>
        <p className="text-gray-500">
          Request your pay stubs, W-2s, and tax documents instantly.
        </p>
      </div>

      {/* Request form */}
      <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-6">
        <h2 className="text-base font-semibold text-gray-900 mb-4">Request a Document</h2>
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
          {/* Document type */}
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">Document Type</label>
            <select
              value={docType}
              onChange={e => setDocType(e.target.value as typeof docType)}
              className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 bg-white"
            >
              {DOC_TYPE_OPTIONS.map(opt => (
                <option key={opt.value} value={opt.value}>{opt.label}</option>
              ))}
            </select>
          </div>

          {/* Period selector — changes based on doc type */}
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">
              {isPaystub ? 'Pay Date' : 'Tax Year'}
            </label>
            {isYtd ? (
              <input
                value={CURRENT_YEAR}
                readOnly
                className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg bg-gray-50 text-gray-500 cursor-not-allowed"
              />
            ) : needsYear ? (
              <select
                value={period}
                onChange={e => setPeriod(e.target.value)}
                className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 bg-white"
              >
                {YEAR_OPTIONS.map(y => (
                  <option key={y} value={String(y)}>{y}</option>
                ))}
              </select>
            ) : (
              // Paystub: "latest" or date input
              <select
                value={period === 'latest' ? 'latest' : 'custom'}
                onChange={e => {
                  if (e.target.value === 'latest') setPeriod('latest')
                  else setPeriod(new Date().toISOString().split('T')[0])
                }}
                className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 bg-white"
              >
                <option value="latest">Latest Pay Stub</option>
                <option value="custom">Specific Pay Date…</option>
              </select>
            )}
            {isPaystub && period !== 'latest' && (
              <input
                type="date"
                value={period}
                onChange={e => setPeriod(e.target.value)}
                className="mt-2 w-full px-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
            )}
          </div>

          {/* Submit */}
          <div className="flex items-end">
            <button
              onClick={handleRequest}
              disabled={loading}
              style={{ backgroundColor: '#1B2A4A' }}
              className="w-full flex items-center justify-center gap-2 px-5 py-2.5 text-sm font-medium text-white rounded-lg hover:opacity-90 disabled:opacity-50 transition-opacity"
            >
              {loading ? (
                <>
                  <Loader2 size={16} className="animate-spin" />
                  Retrieving…
                </>
              ) : (
                <>
                  <Receipt size={16} />
                  Request Document
                </>
              )}
            </button>
          </div>
        </div>

        {error && (
          <p className="mt-4 text-sm text-red-600 bg-red-50 rounded-lg px-3 py-2">
            {error}
          </p>
        )}
      </div>

      {/* Document viewer */}
      {result && result.status === 'delivered' && result.document && (
        <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-6">
          <DocumentViewer result={result} />
        </div>
      )}

      {result && result.status === 'not_found' && (
        <div className="bg-amber-50 border border-amber-200 rounded-xl p-5">
          <p className="text-amber-800 font-medium text-sm">Document not found</p>
          <p className="text-amber-700 text-sm mt-1">{result.error}</p>
        </div>
      )}

      {result && result.status === 'error' && (
        <div className="bg-red-50 border border-red-200 rounded-xl p-5">
          <p className="text-red-800 font-medium text-sm">Error retrieving document</p>
          <p className="text-red-700 text-sm mt-1">{result.error}</p>
        </div>
      )}

      {/* Request history */}
      <div className="bg-white rounded-xl border border-gray-100 shadow-sm overflow-hidden">
        <button
          className="w-full flex items-center justify-between px-6 py-4 border-b border-gray-100 hover:bg-gray-50 transition-colors text-left"
          onClick={() => setHistoryExpanded(p => !p)}
        >
          <span className="text-base font-semibold text-gray-900">Request History</span>
          <div className="flex items-center gap-2">
            <span className="text-xs text-gray-400">{history.length} request{history.length !== 1 ? 's' : ''}</span>
            {historyExpanded ? <ChevronUp size={16} className="text-gray-400" /> : <ChevronDown size={16} className="text-gray-400" />}
          </div>
        </button>

        {historyExpanded && (
          history.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12 text-center px-6">
              <Receipt size={36} className="text-gray-300 mb-3" />
              <p className="text-gray-500 font-medium">No requests yet.</p>
              <p className="text-gray-400 text-sm mt-1">Your document requests will appear here.</p>
            </div>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-gray-50 border-b border-gray-100">
                  <th className="text-left px-4 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">Date</th>
                  <th className="text-left px-4 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">Document</th>
                  <th className="text-left px-4 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">Period</th>
                  <th className="text-left px-4 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">Status</th>
                  <th className="w-20" />
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-50">
                {history.map(req => (
                  <tr key={req.id} className="hover:bg-gray-50">
                    <td className="px-4 py-3 text-gray-500 text-xs">
                      {new Date(req.created_at).toLocaleDateString()}
                    </td>
                    <td className="px-4 py-3 text-gray-800 font-medium">
                      {docTypeLabel(req.document_type)}
                    </td>
                    <td className="px-4 py-3 text-gray-600">{req.period}</td>
                    <td className="px-4 py-3">
                      {req.status === 'delivered' ? (
                        <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-semibold bg-emerald-100 text-emerald-800">
                          Delivered
                        </span>
                      ) : req.status === 'pending' ? (
                        <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-semibold bg-blue-100 text-blue-800">
                          Pending
                        </span>
                      ) : req.status === 'not_found' ? (
                        <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-semibold bg-amber-100 text-amber-800">
                          Not Found
                        </span>
                      ) : (
                        <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-semibold bg-red-100 text-red-800">
                          Error
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-3">
                      {req.status === 'delivered' && (
                        <button
                          onClick={() => handleViewHistory(req)}
                          className="text-xs font-medium text-blue-600 hover:text-blue-800"
                        >
                          View
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )
        )}
      </div>
    </div>
  )
}
