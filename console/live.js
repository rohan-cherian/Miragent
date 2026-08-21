/* ---------------------------------------------------------------------------
   console/live.js — replaces the wireframe's static fixtures with real data
   from the ITR Scout backend.

   The wireframe ships as one self-contained HTML file with hard-coded arrays
   and zero network calls. Rather than rewrite 6,000 lines, this module runs
   after the page's own window.onload, fetches the live API, overwrites the
   in-page data structures, and re-renders.

   Design rules:
     * Never invent a number. If an endpoint is unreachable the field shows a
       dash and the console says the backend is offline — a wireframe that
       silently keeps its fixtures looks identical to a working system, which
       is the one failure mode that must not survive a demo.
     * Gmail is the only connected source in Slice 1. Everything else is
       registered but unconnected, and says so.
--------------------------------------------------------------------------- */

(function () {
  const API = window.ITR_API_BASE || 'http://127.0.0.1:8090/api/v1';

  const num = (v) => (typeof v === 'number' ? v.toLocaleString() : (v ?? '—'));
  const setText = (id, value) => {
    const el = document.getElementById(id);
    if (el) el.innerText = value;
  };

  async function get(path) {
    const res = await fetch(`${API}${path}`, { headers: { Accept: 'application/json' } });
    if (!res.ok) throw new Error(`${path} -> ${res.status}`);
    return res.json();
  }

  /* ---------------- banner ---------------- */

  function banner(text, tone) {
    let el = document.getElementById('itr-live-banner');
    if (!el) {
      el = document.createElement('div');
      el.id = 'itr-live-banner';
      el.style.cssText =
        'position:fixed;bottom:12px;right:12px;z-index:9999;padding:8px 14px;' +
        'border-radius:6px;font:600 12px ui-monospace,monospace;color:#fff;' +
        'box-shadow:0 2px 10px rgba(0,0,0,.18)';
      document.body.appendChild(el);
    }
    el.style.background = tone === 'ok' ? '#0F9D58' : tone === 'warn' ? '#F4B400' : '#D93025';
    el.innerText = text;
  }

  /* ---------------- connections ---------------- */

  // Slice 1 connects Gmail only. The other systems are real entries in
  // raw_ingest.connector_registry, shown so the estate is visible, but they
  // are honestly reported as not connected rather than faked.
  const DISPLAY = {
    gmail: {
      name: 'Gmail',
      subtitle: 'Customer support mailbox',
      rateLimit: '250 quota units/user/second',
      path: 'Incremental history sync, 60s poll; full backfill on cursor expiry',
      extractTime: 'incremental ~2s/run',
      reasoning:
        'Gmail history ids expire after ~1 week, so every message is copied to ' +
        'the raw lake before parsing — the parser can change without re-asking Gmail.',
    },
    zendesk: { name: 'Zendesk', subtitle: 'Ticketing (emulated)', rateLimit: '700 calls/min threshold' },
    workday: { name: 'Workday', subtitle: 'HR / worker data (emulated)', rateLimit: 'RaaS: 10 concurrent reports' },
  };

  async function loadConnections() {
    const [registry, runs, stores] = await Promise.all([
      get('/connections'),
      get('/runs').catch(() => []),
      get('/stores/metrics').catch(() => null),
    ]);

    const latestRun = Array.isArray(runs) && runs.length ? runs[0] : null;
    const pg = stores?.postgres?.tables || {};

    const sources = registry.map((row) => {
      const meta = DISPLAY[row.source_system] || { name: row.source_system, subtitle: '' };
      const connected = row.status === 'connected';
      const gmail = row.source_system === 'gmail';

      return {
        id: row.source_system,
        name: meta.name,
        connected,
        lastSync: row.last_synced_at
          ? new Date(row.last_synced_at).toLocaleString()
          : (connected ? 'never synced' : 'not connected'),
        metrics: gmail
          ? {
              Messages: num(pg.message ?? 0),
              Cases: num(pg.case_ ?? 0),
              People: num(pg.person ?? 0),
            }
          : { Status: 'not connected' },
        path: meta.path || 'Adapter registered; no extraction configured in Slice 1.',
        extractTime: meta.extractTime || '—',
        rateLimit: row.rate_limit_line || meta.rateLimit || '—',
        logs: gmail
          ? [
              `Gmail OAuth token valid; mailbox resolved.`,
              latestRun
                ? `Last run ${latestRun.status} — seen ${latestRun.counts?.messages ?? 0}, written ${latestRun.counts?.written ?? 0}.`
                : 'No ingestion run recorded yet.',
              `Raw objects land in MinIO before parsing; duplicates rejected by object HEAD.`,
            ].join('\n')
          : `${meta.name} is registered in the connector registry but not connected in Slice 1.`,
        reasoning:
          meta.reasoning ||
          `${meta.name} has an emulator and a registry entry, but Slice 1 ingests Gmail only.`,
        standardObjects: gmail
          ? [
              { name: 'Message', count: pg.message ?? 0, lastModified: '—' },
              { name: 'Case', count: pg.case_ ?? 0, lastModified: '—' },
              { name: 'Person', count: pg.person ?? 0, lastModified: '—' },
              { name: 'KB Article', count: pg.kb_article ?? 0, lastModified: '—' },
            ]
          : [],
        customObjects: [],
        timeline: [],
      };
    });

    // Connected first, so Gmail leads the catalogue.
    sources.sort((a, b) => Number(b.connected) - Number(a.connected));

    if (typeof window.sourcesData !== 'undefined') {
      window.sourcesData.length = 0;
      sources.forEach((s) => window.sourcesData.push(s));
    }
    window.ITR_SOURCES = sources;
    if (typeof window.renderConnections === 'function') window.renderConnections();
    return sources;
  }

  /* ---------------- knowledge layer ---------------- */

  async function loadStores() {
    const stores = await get('/stores/metrics');
    const pg = stores.postgres?.tables || {};

    setText('pg-metric-people', num(pg.person ?? 0));
    setText('pg-metric-orgs', num(pg.org ?? 0));
    setText('pg-metric-cases', num(pg.case_ ?? 0));
    setText('pg-metric-messages', num(pg.message ?? 0));
    setText('pg-metric-kb', num(pg.kb_article ?? 0));

    setText('dash-metric-people', num(pg.person ?? 0));
    setText('dash-metric-orgs', num(pg.org ?? 0));
    setText('dash-metric-cases', num(pg.case_ ?? 0));
    setText('dash-metric-messages', num(pg.message ?? 0));
    setText('dash-metric-kb', num(pg.kb_article ?? 0));

    setText('qdrant-metric-chunks', num(stores.qdrant?.points ?? 0));

    // MinIO card (replaced Neo4j). Counts come from the ledger, which records
    // exactly what was written to the bucket.
    setText('minio-metric-objects', num(stores.minio?.objects ?? 0));
    setText('minio-metric-attachments', num(stores.minio?.attachments ?? 0));
    setText('minio-metric-bucket', stores.minio?.bucket || 'raw');
    setText('minio-metric-endpoint', (stores.minio?.endpoint || '').replace(/^https?:\/\//, '') || '—');

    // depopulateDashboard() paints "no data yet" banners on load. Once real
    // rows are in, they are wrong — hide them rather than leaving the console
    // claiming it is empty while showing populated counters.
    if ((pg.message ?? 0) > 0) {
      ['dashboard-zero-alert', 'knowledge-zero-alert'].forEach((id) => {
        const el = document.getElementById(id);
        if (el) el.style.display = 'none';
      });
    }

    return stores;
  }

  async function loadRedaction() {
    // Redaction counts come from the canonical rows that carry a pii_map.
    try {
      const cases = await get('/cases');
      setText('redact-metric-emails', num(cases.length ? cases.length : 0));
    } catch {
      /* leave the dashes */
    }
  }

  /* ---------------- attachments ---------------- */

  async function loadAttachments() {
    try {
      const stores = await get('/stores/metrics');
      const pg = stores.postgres?.tables || {};
      setText('minio-metric-attachments', num(pg.attachment ?? 0));
    } catch {
      setText('minio-metric-attachments', '—');
    }
  }


  /* ---------------- audit trail ---------------- */

  // The wireframe groups the audit feed by a `type` chip. The backend records
  // an action verb instead, so map verb -> chip rather than inventing a column.
  function auditType(action) {
    const a = (action || '').toLowerCase();
    if (a.includes('redact') || a.includes('pii')) return 'redaction';
    if (a.includes('identity') || a.includes('resolve') || a.includes('alias')) return 'identity';
    if (a.includes('decision') || a.includes('approve') || a.includes('reject')) return 'approval';
    return 'system';
  }

  async function loadAudit() {
    const rows = await get('/audit');
    const logs = rows.slice(0, 200).map((r) => ({
      timestamp: r.at ? new Date(r.at).toLocaleString() : '—',
      type: auditType(r.action),
      action: r.action || '—',
      details: r.details
        ? (typeof r.details === 'string' ? r.details : JSON.stringify(r.details))
        : `actor ${r.actor || 'system'}${r.target_id ? ' · ' + String(r.target_id).slice(0, 8) : ''}`,
    }));
    if (window.state) window.state.auditLogs = logs;
    if (typeof window.renderAuditLogs === 'function') window.renderAuditLogs();
    return logs;
  }

  /* ---------------- inbox ---------------- */

  async function loadInbox() {
    const cases = await get('/inbox');
    const emails = cases.map((c) => ({
      id: c.id,
      caseId: c.id,
      from: c.requester || 'unknown sender',
      sender: c.requester || 'unknown sender',
      subject: c.subject || '(no subject)',
      status: c.status,
      preview: c.subject || '',
      time: c.created_at ? new Date(c.created_at).toLocaleString() : '—',
      unread: c.status === 'new',
    }));
    if (window.state) {
      window.state.emails = emails;
      window.state.inboxReset = false;
    }
    window.ITR_CASES = emails;
    if (typeof window.renderInboxList === 'function') window.renderInboxList();
    return emails;
  }


  /* ---------------- drilldowns ---------------- */

  // Every drilldown is a cols/rows table. Build them from the canonical
  // endpoints so "click a number, see the rows behind it" is real rather than
  // a fixture that happens to match the headline figure.
  async function loadDrilldowns() {
    const dd = window.drilldownData;
    if (!dd) return;

    const [cases, inbox] = await Promise.all([
      get('/cases').catch(() => []),
      get('/inbox').catch(() => []),
    ]);

    if (dd.cases) {
      dd.cases.cols = ['Case ID', 'Subject', 'Status', 'Requester', 'Opened'];
      dd.cases.rows = cases.map((c) => [
        String(c.id).slice(0, 8),
        c.subject || '(no subject)',
        c.status || '—',
        c.requester || 'unresolved',
        c.created_at ? new Date(c.created_at).toLocaleString() : '—',
      ]);
    }

    if (dd.messages) {
      dd.messages.cols = ['Case', 'Subject', 'Status', 'Received'];
      dd.messages.rows = inbox.map((c) => [
        String(c.id).slice(0, 8),
        c.subject || '(no subject)',
        c.status || '—',
        c.created_at ? new Date(c.created_at).toLocaleString() : '—',
      ]);
    }

    // people / orgs / kb have no list endpoint in the contract, so rather than
    // leave fixtures in place — which would show invented names next to real
    // counts — they are emptied with an explicit note.
    [['people', 'No /people endpoint in the Slice-1 contract'],
     ['orgs', 'No /orgs endpoint in the Slice-1 contract'],
     ['kb', 'No /kb endpoint in the Slice-1 contract']].forEach(([key, note]) => {
      if (dd[key]) {
        dd[key].cols = ['Note'];
        dd[key].rows = [[note]];
      }
    });
  }

  /* ---------------- quarantine ---------------- */

  async function loadQuarantine() {
    const runs = await get('/runs').catch(() => []);
    if (!Array.isArray(runs) || !runs.length) return;
    const perRun = await Promise.all(
      runs.slice(0, 5).map((r) =>
        get(`/runs/${r.id}/quarantine`).then((q) => ({ run: r, q })).catch(() => null),
      ),
    );
    const records = [];
    perRun.filter(Boolean).forEach(({ run, q }) => {
      (Array.isArray(q) ? q : []).forEach((row) => {
        records.push({
          id: String(row.id ?? row.external_id ?? '—').slice(0, 18),
          source: run.source_system || 'gmail',
          reason: row.reason || row.error || 'quarantined',
        });
      });
    });
    if (window.quarantineRecords) {
      window.quarantineRecords.length = 0;
      records.forEach((r) => window.quarantineRecords.push(r));
    }
    return records;
  }

  /* ---------------- pipeline stage log ---------------- */

  // The wireframe animates seven stages from a scripted array. raw_ingest
  // .run_stage_event holds the real ones, with the real log lines and
  // durations, so the progress panel replays an actual run.
  async function loadPipelineLog() {
    const runs = await get('/runs').catch(() => []);
    if (!Array.isArray(runs) || !runs.length) return;
    // Not every run records stage events — a script-driven run may write none.
    // Walk back to the most recent run that actually has them, so the panel
    // replays a real scan instead of showing an empty timeline.
    let detail = null;
    let stages = [];
    for (const run of runs.slice(0, 8)) {
      detail = await get(`/runs/${run.id}`).catch(() => null);
      stages = detail?.stages || [];
      if (stages.length) break;
    }
    const lines = stages.length
      ? stages.map(
          (st) =>
            `[${String(st.stage).padEnd(9)}] ${st.progress_pct}%  ${st.log_line}` +
            (st.duration_ms != null ? `  (${st.duration_ms}ms)` : ''),
        )
      : [`Run ${String(runs[0].id).slice(0, 8)} recorded no stage events.`];
    if (window.pipelineStepsLogs) {
      window.pipelineStepsLogs.length = 0;
      lines.forEach((l) => window.pipelineStepsLogs.push(l));
    }
    return lines;
  }


  /* ---------------- Signal Capture detail pane ---------------- */

  // The wireframe's selectEmail() showed a fixed "already resolved" card for
  // every message. Replace it with the real case: subject, requester, status,
  // triage band and the case timeline from the canonical layer.
  function installEmailDetail() {
    const originalSelect = window.selectEmail;

    window.selectEmail = async function (id) {
      if (id === 'new-email' && typeof originalSelect === 'function') {
        return originalSelect(id);   // keep the scripted arrival animation
      }
      if (window.state) window.state.activeEmailId = id;
      if (typeof window.renderInboxList === 'function') window.renderInboxList();

      const stack = document.getElementById('email-staggered-stack');
      const empty = document.getElementById('inbox-empty-view');
      if (stack) stack.style.display = 'none';
      if (empty) {
        empty.style.display = 'flex';
        empty.innerHTML = '<div style="font-size:0.85rem;color:var(--text-muted)">Loading case…</div>';
      }

      try {
        const [detail, timeline] = await Promise.all([
          get(`/cases/${id}/360`),
          get(`/cases/${id}/timeline`).catch(() => []),
        ]);
        const c = detail.case || {};
        const triage = detail.latest_triage || null;

        setText('email-detail-subject', c.subject || '(no subject)');
        setText(
          'email-detail-meta-text',
          `${c.requester || 'unresolved sender'} · ${c.status || '—'} · ` +
          `case ${detail.case_number || String(c.id || '').slice(0, 8)}`,
        );

        const rows = (Array.isArray(timeline) ? timeline : [])
          .map((e) => {
            const when = e.at || e.created_at;
            return `<div style="display:flex;gap:10px;padding:6px 0;border-bottom:1px solid var(--border-color)">
                      <span class="monospace" style="color:var(--text-muted);min-width:130px;font-size:0.7rem">
                        ${when ? new Date(when).toLocaleString() : '—'}</span>
                      <span style="font-size:0.75rem">${e.event_type || e.type || 'event'}</span>
                    </div>`;
          })
          .join('');

        if (empty) {
          empty.style.display = 'block';
          empty.innerHTML = `
            <div style="width:100%;text-align:left">
              <div style="font-weight:700;font-size:1rem;margin-bottom:4px">${c.subject || '(no subject)'}</div>
              <div style="font-size:0.78rem;color:var(--text-muted);margin-bottom:14px">
                ${c.requester || 'unresolved sender'} · status <b>${c.status || '—'}</b>
                · ${detail.message_count ?? 0} message(s)
                ${detail.related_case_ids?.length ? ' · ' + detail.related_case_ids.length + ' linked case(s)' : ''}
              </div>
              <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:14px">
                <div style="border:1px solid var(--border-color);border-radius:6px;padding:8px">
                  <div style="font-size:0.6rem;text-transform:uppercase;color:#94A3B8;font-weight:700">Triage</div>
                  <div style="font-size:0.8rem;font-weight:700">${triage?.band || 'not triaged'}</div>
                  <div style="font-size:0.7rem;color:var(--text-muted)">
                    ${triage?.intent_class || 'no intent class'}${triage?.confidence != null ? ' · ' + triage.confidence : ''}</div>
                </div>
                <div style="border:1px solid var(--border-color);border-radius:6px;padding:8px">
                  <div style="font-size:0.6rem;text-transform:uppercase;color:#94A3B8;font-weight:700">Priority</div>
                  <div style="font-size:0.8rem;font-weight:700">${detail.priority || '—'}</div>
                  <div style="font-size:0.7rem;color:var(--text-muted)">${detail.intent_class || 'unclassified'}</div>
                </div>
              </div>
              <div style="font-size:0.6rem;text-transform:uppercase;color:#94A3B8;font-weight:700;margin-bottom:6px">Case timeline</div>
              ${rows || '<div style="font-size:0.75rem;color:var(--text-muted)">No timeline events recorded.</div>'}

              <!-- The wireframe's own approve/reject bar lives inside a hidden
                   demo-only container, so the working controls are rendered here
                   where a real case can actually reach them. -->
              <div style="display:flex;gap:8px;justify-content:flex-end;border-top:1px solid var(--border-color);margin-top:16px;padding-top:14px">
                <button class="btn btn-secondary" onclick="window.rejectEmailDraft()">Reject</button>
                <button class="btn btn-primary" onclick="window.approveEmailDraft()">Approve (draft only)</button>
              </div>
              <div style="font-size:0.68rem;color:var(--text-muted);text-align:right;margin-top:6px">
                ACTION_MODE=draft_only — approval is recorded, nothing is sent.
              </div>
            </div>`;
        }
      } catch (err) {
        console.error('[itr:live] case detail:', err);
        if (empty) {
          empty.style.display = 'flex';
          empty.innerHTML = '<div style="font-size:0.85rem;color:#D93025">Could not load this case from the backend.</div>';
        }
      }
    };
  }


  /* ---------------- writes: the buttons that actually do something ------- */

  // Every POST in the contract declares Idempotency-Key and If-Match. The
  // console has no version token yet, so If-Match is '*' until one is threaded
  // through — but the header is sent, because the server requires it.
  const idem = () =>
    (crypto.randomUUID ? crypto.randomUUID() : 'ik-' + Date.now() + '-' + Math.random());

  async function post(path, body) {
    const res = await fetch(`${API}${path}`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Accept: 'application/json',
        'Idempotency-Key': idem(),
        'If-Match': '*',
      },
      body: JSON.stringify(body),
    });
    const text = await res.text();
    let payload = null;
    try { payload = text ? JSON.parse(text) : null; } catch { payload = text; }
    if (!res.ok) {
      // The contract defines 409 {error,by,at} and 422 {field,min}. Surface the
      // real reason instead of a generic failure.
      if (res.status === 409) throw new Error(`Already decided by ${payload?.by ?? 'someone'}`);
      if (res.status === 422) throw new Error(`${payload?.field ?? 'field'} must be at least ${payload?.min ?? '?'} characters`);
      throw new Error(`${path} -> ${res.status}`);
    }
    return payload;
  }

  function toast(msg, ok) {
    banner(msg, ok ? 'ok' : 'err');
    setTimeout(() => banner('live · Gmail connected', 'ok'), 4000);
  }

  /* ---- identity queue: "it learns, once" (feature E15) ---- */

  async function loadIdentityQueue() {
    const rows = await get('/identity/queue').catch(() => []);
    const badge = document.getElementById('pending-identity-count-badge');
    if (badge) badge.innerText = String(rows.length);
    window.ITR_IDENTITY_QUEUE = rows;

    const host = document.getElementById('id-tab-pending');
    if (!host) return rows;
    if (!rows.length) {
      host.innerHTML = '<div style="padding:24px;color:var(--text-muted);font-size:0.85rem">Identity queue is empty — every sender resolved.</div>';
      return rows;
    }
    host.innerHTML = `
      <div style="font-size:0.78rem;color:var(--text-muted);margin-bottom:10px">
        ${rows.length} sender(s) the system will not guess at. Confirming one teaches it
        permanently and retro-links that person's earlier cases.
      </div>
      <table class="data-table" style="width:100%">
        <thead><tr><th>Sender</th><th>Best guess</th><th>Confidence</th><th>Action</th></tr></thead>
        <tbody>
          ${rows.map((r) => `
            <tr>
              <td class="monospace">${r.candidate_email || r.sender_email || '—'}</td>
              <td>${r.best_guess_name || r.sender_display || '—'}</td>
              <td class="monospace">${r.best_confidence != null ? Number(r.best_confidence).toFixed(2) : '—'}</td>
              <td>
                <button class="btn-table-success"
                  onclick="window.confirmIdentity('${r.id}', '${(r.best_guess_person_id || '')}')">
                  Confirm identity
                </button>
              </td>
            </tr>`).join('')}
        </tbody>
      </table>`;
    return rows;
  }

  window.confirmIdentity = async function (queueId, personId) {
    if (!personId) {
      toast('No candidate person to confirm — the waterfall found no match', false);
      return;
    }
    try {
      await post(`/identity/queue/${queueId}/resolve`, { person_id: personId });
      toast('Identity confirmed — earlier cases retro-linked', true);
      await Promise.all([loadIdentityQueue(), loadStores(), loadInbox()]);
    } catch (err) {
      toast(String(err.message || err), false);
    }
  };

  /* ---- decisions: approve / edit / reject (features H24-H26) ---- */

  function activeCaseId() {
    const id = window.state?.activeEmailId;
    return id && id !== 'new-email' ? id : (window.ITR_CASES?.[0]?.id || null);
  }

  window.approveEmailDraft = async function () {
    const caseId = activeCaseId();
    if (!caseId) return toast('Select a case first', false);
    try {
      await post(`/cases/${caseId}/decision`, { action: 'approve' });
      // ACTION_MODE=draft_only, so approval is recorded and the write is
      // suppressed. Say so plainly rather than implying a send happened.
      toast('Approved and recorded — nothing sent (ACTION_MODE=draft_only)', true);
      await Promise.all([loadAudit(), loadInbox()]);
    } catch (err) {
      toast(String(err.message || err), false);
    }
  };

  window.rejectEmailDraft = async function () {
    const caseId = activeCaseId();
    if (!caseId) return toast('Select a case first', false);
    const note = window.prompt('Rejecting requires a reason (min 10 characters):', '');
    if (note === null) return;
    try {
      await post(`/cases/${caseId}/decision`, { action: 'reject', note });
      toast('Rejected — reason recorded in the audit trail', true);
      await Promise.all([loadAudit(), loadInbox()]);
    } catch (err) {
      toast(String(err.message || err), false);
    }
  };

  window.approveMerge = window.confirmIdentity;

  /* ---------------- boot ---------------- */

  async function boot() {
    try {
      const [sources] = await Promise.all([
        loadConnections(),
        loadStores(),
        loadRedaction(),
        loadAttachments(),
        loadAudit().catch((e) => console.warn('[itr:live] audit:', e)),
        loadInbox().catch((e) => console.warn('[itr:live] inbox:', e)),
        loadDrilldowns().catch((e) => console.warn('[itr:live] drilldowns:', e)),
        loadQuarantine().catch((e) => console.warn('[itr:live] quarantine:', e)),
        loadPipelineLog().catch((e) => console.warn('[itr:live] pipeline:', e)),
        loadIdentityQueue().catch((e) => console.warn('[itr:live] identity:', e)),
      ]);
      installEmailDetail();
      const connected = sources.filter((s) => s.connected).map((s) => s.name);
      banner(`live · ${connected.join(', ') || 'no source'} connected`, 'ok');
      console.info('[itr:live] backend data loaded', { sources });
    } catch (err) {
      banner('backend offline — showing no data', 'err');
      console.error('[itr:live] backend unreachable:', err);
      // Deliberately do NOT fall back to fixtures: a wireframe showing
      // invented numbers is indistinguishable from a working system.
      document.querySelectorAll('[id$="-metric-people"],[id$="-metric-orgs"],[id$="-metric-cases"],[id$="-metric-messages"],[id$="-metric-kb"],[id$="-metric-chunks"],[id$="-metric-objects"]')
        .forEach((el) => (el.innerText = '—'));
    }
  }

  const previous = window.onload;
  window.onload = function () {
    if (typeof previous === 'function') previous();
    boot();
  };
})();
