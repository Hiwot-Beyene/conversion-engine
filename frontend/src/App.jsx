import React, { useState, useEffect, useCallback, useRef } from 'react';
import axios from 'axios';
import { Toaster, toast } from 'sonner';
import {
  Users, Mail, Phone, Calendar, TrendingUp, ChevronRight, Brain, Zap,
  Send, Database, Settings, Activity, CheckCircle2, BarChart3,
  MessageSquare, Terminal, Loader2, Sparkles, Mic, Layers, RefreshCw,
  ExternalLink, Info,
} from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';

const API_BASE = import.meta.env.VITE_API_BASE ?? 'http://localhost:8000';
const LEADS_LIMIT = Number(import.meta.env.VITE_LEADS_LIMIT ?? 2000);

/** Demo targets — set only in `frontend/.env` (VITE_DEMO_EMAIL, VITE_DEMO_PHONE). */
const DEFAULT_EMAIL = import.meta.env.VITE_DEMO_EMAIL ?? '';
const DEFAULT_PHONE = import.meta.env.VITE_DEMO_PHONE ?? '';

const api = axios.create({ baseURL: API_BASE, timeout: 180000 });

function newCorrelationId() {
  return typeof crypto !== 'undefined' && crypto.randomUUID
    ? crypto.randomUUID()
    : `cid-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
}

api.interceptors.request.use((config) => {
  const id = newCorrelationId();
  const headers = config.headers ?? {};
  headers['X-Correlation-Id'] = id;
  config.headers = headers;
  return config;
});

function SetupScreen({ missing }) {
  return (
    <div className="min-h-screen bg-zinc-950 text-zinc-100 flex items-center justify-center p-8">
      <div className="max-w-lg rounded-2xl border border-amber-900/50 bg-amber-950/20 p-8">
        <h1 className="text-lg font-semibold text-amber-100 mb-2">Dashboard configuration required</h1>
        <p className="text-sm text-zinc-400 mb-4">
          Set the following in <code className="text-zinc-300">frontend/.env</code> (Vite exposes only{' '}
          <code className="text-zinc-300">VITE_*</code> keys):
        </p>
        <ul className="list-disc pl-5 text-sm text-amber-200/90 space-y-1">
          {missing.map((k) => (
            <li key={k}>
              <code>{k}</code>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}

function splitSubjectBody(raw) {
  const text = (raw || '').trim();
  if (!text) return { subject: '', body: '' };
  const lines = text.split('\n');
  let subject = lines[0].replace(/^Subject:\s*/i, '').trim();
  let bodyStart = 1;
  if (lines.length > 1 && lines[1].trim() === '') bodyStart = 2;
  const body = lines.slice(bodyStart).join('\n').trim();
  return { subject, body };
}

/** When brief predates API `overall_evidence_strength`, derive from per-signal claim scores. */
function averageClaimStrength(brief) {
  if (brief?.overall_evidence_strength != null) return brief.overall_evidence_strength;
  const sig = brief?.signals || {};
  const vals = ['job_velocity', 'funding', 'layoffs', 'leadership', 'ai_maturity']
    .map((k) => sig[k]?.evidence_strength ?? sig[k]?.confidence)
    .filter((v) => typeof v === 'number');
  if (!vals.length) return 0;
  return vals.reduce((a, b) => a + b, 0) / vals.length;
}

/** Renders `tenacious_sales_data/schemas/hiring_signal_brief.schema.json` instance from API. */
function HiringSignalSchemaPanel({ data, schemaOk, schemaError }) {
  if (data == null || typeof data !== 'object') {
    return (
      <div className="mt-6 rounded-xl border border-amber-900/40 bg-amber-950/20 p-4 text-xs text-amber-200/90">
        <p className="font-semibold text-amber-100 mb-1">Hiring signal brief (schema)</p>
        <p>
          The API did not include <code className="text-amber-50">hiring_signal_brief</code>. Re-run{' '}
          <strong>Enrich</strong> on this lead, or confirm the backend returns it in{' '}
          <code className="text-amber-50">GET /api/leads</code> merge for enriched rows.
        </p>
      </div>
    );
  }
  const am = data.ai_maturity || {};
  const hv = data.hiring_velocity || {};
  const buy = data.buying_window_signals || {};
  const flags = data.honesty_flags || [];
  return (
    <section className="mt-6 rounded-xl border border-cyan-900/35 bg-cyan-950/15 p-5">
      <div className="flex flex-wrap items-center justify-between gap-2 mb-4">
        <h4 className="text-sm font-semibold text-white flex items-center gap-2">
          <Database size={16} className="text-cyan-400" />
          Hiring signal brief · JSON Schema instance
        </h4>
        {schemaOk != null && (
          <span
            className={`text-[10px] px-2 py-0.5 rounded font-mono border ${
              schemaOk
                ? 'bg-emerald-950/60 text-emerald-300 border-emerald-800/50'
                : 'bg-red-950/50 text-red-300 border-red-800/50'
            }`}
            title={schemaError || ''}
          >
            schema: {schemaOk ? 'valid' : 'invalid'}
          </span>
        )}
      </div>
      <dl className="grid sm:grid-cols-2 lg:grid-cols-3 gap-x-6 gap-y-3 text-[11px] text-zinc-400 mb-4">
        <div>
          <dt className="text-zinc-600 uppercase text-[10px] font-semibold">prospect_domain</dt>
          <dd className="text-zinc-200 font-mono mt-0.5">{String(data.prospect_domain ?? '—')}</dd>
        </div>
        <div>
          <dt className="text-zinc-600 uppercase text-[10px] font-semibold">prospect_name</dt>
          <dd className="text-zinc-200 mt-0.5">{String(data.prospect_name ?? '—')}</dd>
        </div>
        <div>
          <dt className="text-zinc-600 uppercase text-[10px] font-semibold">generated_at</dt>
          <dd className="text-zinc-300 font-mono mt-0.5">{String(data.generated_at ?? '—')}</dd>
        </div>
        <div>
          <dt className="text-zinc-600 uppercase text-[10px] font-semibold">primary_segment_match</dt>
          <dd className="text-zinc-200 font-mono mt-0.5">{String(data.primary_segment_match ?? '—')}</dd>
        </div>
        <div>
          <dt className="text-zinc-600 uppercase text-[10px] font-semibold">segment_confidence</dt>
          <dd className="text-zinc-300 tabular-nums mt-0.5">
            {data.segment_confidence != null ? Number(data.segment_confidence).toFixed(3) : '—'}
          </dd>
        </div>
        <div>
          <dt className="text-zinc-600 uppercase text-[10px] font-semibold">AI maturity score</dt>
          <dd className="text-cyan-300 font-semibold tabular-nums mt-0.5">
            {am.score ?? '—'}
            {am.confidence != null && (
              <span className="text-zinc-500 font-normal ml-2">
                (conf {Number(am.confidence).toFixed(2)})
              </span>
            )}
          </dd>
        </div>
      </dl>
      <div className="grid md:grid-cols-2 gap-4 text-[11px]">
        <div className="rounded-lg border border-zinc-800 bg-zinc-950/60 p-3">
          <p className="text-[10px] uppercase text-zinc-500 font-semibold mb-2">hiring_velocity</p>
          <ul className="space-y-1 text-zinc-400">
            <li>
              <span className="text-zinc-600">open_roles_today:</span>{' '}
              <span className="text-zinc-200 tabular-nums">{hv.open_roles_today ?? '—'}</span>
            </li>
            <li>
              <span className="text-zinc-600">open_roles_60_days_ago:</span>{' '}
              <span className="text-zinc-200 tabular-nums">{hv.open_roles_60_days_ago ?? '—'}</span>
            </li>
            <li>
              <span className="text-zinc-600">velocity_label:</span>{' '}
              <span className="text-zinc-200 font-mono">{hv.velocity_label ?? '—'}</span>
            </li>
            <li>
              <span className="text-zinc-600">sources:</span>{' '}
              <span className="text-zinc-300">{(hv.sources || []).join(', ') || '—'}</span>
            </li>
          </ul>
        </div>
        <div className="rounded-lg border border-zinc-800 bg-zinc-950/60 p-3">
          <p className="text-[10px] uppercase text-zinc-500 font-semibold mb-2">buying_window_signals</p>
          <pre className="text-[10px] text-zinc-400 whitespace-pre-wrap font-mono leading-relaxed max-h-32 overflow-y-auto">
            {JSON.stringify(buy, null, 2)}
          </pre>
        </div>
      </div>
      {(am.justifications || []).length > 0 && (
        <div className="mt-4">
          <p className="text-[10px] uppercase text-zinc-500 font-semibold mb-2">ai_maturity.justifications</p>
          <ul className="space-y-2 max-h-40 overflow-y-auto">
            {(am.justifications || []).slice(0, 6).map((j, i) => (
              <li key={i} className="text-[11px] text-zinc-400 border-l-2 border-zinc-700 pl-2">
                <span className="text-violet-300 font-mono text-[10px]">{j.signal}</span>
                <span className="text-zinc-600"> · {j.weight}/{j.confidence}</span>
                <p className="text-zinc-300 mt-0.5">{j.status}</p>
              </li>
            ))}
          </ul>
        </div>
      )}
      {flags.length > 0 && (
        <p className="mt-3 text-[10px] text-amber-200/90">
          <span className="text-zinc-500">honesty_flags:</span> {flags.join(', ')}
        </p>
      )}
      <details className="mt-4 text-[11px]">
        <summary className="cursor-pointer text-zinc-500 hover:text-zinc-300 select-none">
          Full JSON (hiring_signal_brief)
        </summary>
        <pre className="mt-2 p-3 rounded-lg bg-zinc-950 border border-zinc-800 overflow-x-auto text-[10px] text-zinc-400 max-h-80 overflow-y-auto">
          {JSON.stringify(data, null, 2)}
        </pre>
      </details>
    </section>
  );
}

/** Renders `competitor_gap_brief.schema.json` instance from API. */
function CompetitorGapSchemaPanel({ data, schemaOk, schemaError }) {
  if (data == null || typeof data !== 'object') {
    return (
      <div className="mt-4 rounded-xl border border-amber-900/40 bg-amber-950/20 p-4 text-xs text-amber-200/90">
        <p className="font-semibold text-amber-100 mb-1">Competitor gap brief (schema)</p>
        <p>
          Missing <code className="text-amber-50">competitor_gap_brief</code> — re-run <strong>Enrich</strong>.
        </p>
      </div>
    );
  }
  const comps = data.competitors_analyzed || [];
  const gaps = data.gap_findings || [];
  return (
    <section className="mt-4 rounded-xl border border-violet-900/35 bg-violet-950/15 p-5">
      <div className="flex flex-wrap items-center justify-between gap-2 mb-4">
        <h4 className="text-sm font-semibold text-white flex items-center gap-2">
          <Layers size={16} className="text-violet-400" />
          Competitor gap brief · JSON Schema instance
        </h4>
        {schemaOk != null && (
          <span
            className={`text-[10px] px-2 py-0.5 rounded font-mono border ${
              schemaOk
                ? 'bg-emerald-950/60 text-emerald-300 border-emerald-800/50'
                : 'bg-red-950/50 text-red-300 border-red-800/50'
            }`}
            title={schemaError || ''}
          >
            schema: {schemaOk ? 'valid' : 'invalid'}
          </span>
        )}
      </div>
      <dl className="grid sm:grid-cols-2 lg:grid-cols-4 gap-3 text-[11px] text-zinc-400 mb-4">
        <div>
          <dt className="text-[10px] uppercase text-zinc-600 font-semibold">prospect_sector</dt>
          <dd className="text-zinc-200 mt-0.5">{String(data.prospect_sector ?? '—')}</dd>
        </div>
        {data.prospect_sub_niche && (
          <div>
            <dt className="text-[10px] uppercase text-zinc-600 font-semibold">prospect_sub_niche</dt>
            <dd className="text-zinc-200 mt-0.5">{String(data.prospect_sub_niche)}</dd>
          </div>
        )}
        <div>
          <dt className="text-[10px] uppercase text-zinc-600 font-semibold">prospect_ai_maturity_score</dt>
          <dd className="text-violet-300 font-semibold tabular-nums mt-0.5">
            {data.prospect_ai_maturity_score ?? '—'}
          </dd>
        </div>
        <div>
          <dt className="text-[10px] uppercase text-zinc-600 font-semibold">sector_top_quartile_benchmark</dt>
          <dd className="text-zinc-200 tabular-nums mt-0.5">
            {data.sector_top_quartile_benchmark != null
              ? Number(data.sector_top_quartile_benchmark).toFixed(2)
              : '—'}
          </dd>
        </div>
      </dl>
      {comps.length > 0 && (
        <div className="overflow-x-auto rounded-lg border border-zinc-800 mb-4">
          <table className="w-full text-left text-[11px]">
            <thead>
              <tr className="border-b border-zinc-800 bg-zinc-950/80 text-[10px] uppercase text-zinc-500">
                <th className="p-2">Peer</th>
                <th className="p-2">domain</th>
                <th className="p-2">AI mat.</th>
                <th className="p-2">top Q</th>
              </tr>
            </thead>
            <tbody>
              {comps.slice(0, 10).map((c, i) => (
                <tr key={i} className="border-b border-zinc-800/80 text-zinc-400">
                  <td className="p-2 text-zinc-200">{c.name}</td>
                  <td className="p-2 font-mono text-[10px]">{c.domain}</td>
                  <td className="p-2 tabular-nums">{c.ai_maturity_score}</td>
                  <td className="p-2">{c.top_quartile ? 'yes' : '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {gaps.length > 0 && (
        <div className="space-y-3 mb-4">
          <p className="text-[10px] uppercase text-zinc-500 font-semibold">gap_findings</p>
          {gaps.map((g, i) => (
            <div key={i} className="rounded-lg border border-zinc-800 bg-zinc-950/50 p-3 text-[11px]">
              <p className="text-zinc-200 font-medium">{g.practice}</p>
              <p className="text-zinc-500 mt-1">confidence: {g.confidence}</p>
              <ul className="mt-2 space-y-1 text-zinc-400">
                {(g.peer_evidence || []).map((pe, j) => (
                  <li key={j} className="border-l border-zinc-700 pl-2">
                    <span className="text-zinc-300">{pe.competitor_name}</span>: {pe.evidence}
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      )}
      {data.suggested_pitch_shift && (
        <p className="text-[11px] text-zinc-400 mb-3 border-l-2 border-violet-700 pl-2">
          <span className="text-zinc-500">suggested_pitch_shift:</span> {data.suggested_pitch_shift}
        </p>
      )}
      <details className="text-[11px]">
        <summary className="cursor-pointer text-zinc-500 hover:text-zinc-300 select-none">
          Full JSON (competitor_gap_brief)
        </summary>
        <pre className="mt-2 p-3 rounded-lg bg-zinc-950 border border-zinc-800 overflow-x-auto text-[10px] text-zinc-400 max-h-80 overflow-y-auto">
          {JSON.stringify(data, null, 2)}
        </pre>
      </details>
    </section>
  );
}

const App = () => {
  const envPairs = [
    ['VITE_DEMO_EMAIL', import.meta.env.VITE_DEMO_EMAIL],
    ['VITE_HUBSPOT_PORTAL_ID', import.meta.env.VITE_HUBSPOT_PORTAL_ID],
  ];
  const missingEnv = envPairs
    .filter(([, v]) => v === undefined || v === null || String(v).trim() === '')
    .map(([k]) => k);

  const [activeTab, setActiveTab] = useState('pipeline');
  const [leads, setLeads] = useState([]);
  const [selectedLead, setSelectedLead] = useState(null);
  const [testEmail, setTestEmail] = useState(DEFAULT_EMAIL);
  const [testPhone, setTestPhone] = useState(DEFAULT_PHONE);
  const [stats, setStats] = useState({
    total_companies: 0,
    total_jobs: 0,
    active_outreach: 0,
    booked_calls: 0,
    kill_switch: false,
    live_outreach: false,
    outbound_suppressed: false,
  });
  const [loading, setLoading] = useState(true);
  const [hubspotData, setHubspotData] = useState(null);
  const [hubspotLoading, setHubspotLoading] = useState(false);
  const [hubspotError, setHubspotError] = useState(null);

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const [leadsRes, statsRes] = await Promise.all([
        api.get('/api/leads', { params: { limit: LEADS_LIMIT } }),
        api.get('/api/stats'),
      ]);
      setLeads(leadsRes.data);
      setStats(statsRes.data);
    } catch (err) {
      console.error(err);
      toast.error(err.response?.data?.detail || err.message || 'Failed to load /api/leads or /api/stats');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const fetchHubspot = useCallback(async () => {
    if (!testEmail?.trim()) {
      setHubspotError('Set a demo email to load HubSpot preview.');
      return;
    }
    setHubspotLoading(true);
    setHubspotError(null);
    try {
      const res = await api.get('/api/crm/hubspot-preview', { params: { email: testEmail.trim() } });
      setHubspotData(res.data);
    } catch (e) {
      setHubspotData(null);
      setHubspotError(e.response?.data?.detail || e.message || 'HubSpot request failed');
    } finally {
      setHubspotLoading(false);
    }
  }, [testEmail]);

  useEffect(() => {
    if (activeTab !== 'crm') return undefined;
    fetchHubspot();
    const t = setInterval(fetchHubspot, 15000);
    return () => clearInterval(t);
  }, [activeTab, fetchHubspot]);

  const updateLeadInState = (updated) => {
    setLeads((prev) => prev.map((l) =>
      (l.company?.crunchbase_id === updated.company?.crunchbase_id ? updated : l)));
    setSelectedLead(updated);
  };

  if (missingEnv.length > 0) {
    return <SetupScreen missing={missingEnv} />;
  }

  return (
    <div className="flex h-screen bg-zinc-950 text-zinc-100 overflow-hidden font-sans antialiased text-[14px]">
      <Toaster richColors position="top-center" />
      <aside className="w-72 border-r border-zinc-800/80 bg-zinc-900/40 flex flex-col backdrop-blur-xl">
        <div className="p-6 border-b border-zinc-800/80">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-lg bg-gradient-to-br from-violet-600 to-indigo-700 flex items-center justify-center shadow-lg shadow-violet-900/30">
              <Sparkles className="text-white" size={20} />
            </div>
            <div>
              <h1 className="text-base font-semibold tracking-tight text-white">Tenacious</h1>
              <p className="text-[10px] text-zinc-400 uppercase tracking-widest font-medium">Conversion Engine</p>
            </div>
          </div>
        </div>

        <nav className="flex-1 px-3 py-4 space-y-0.5">
          <NavItem icon={<Activity size={18} />} label="Signals & outreach" active={activeTab === 'pipeline'} onClick={() => setActiveTab('pipeline')} />
          <NavItem icon={<Users size={18} />} label="HubSpot sync" active={activeTab === 'crm'} onClick={() => setActiveTab('crm')} />
          <NavItem icon={<Layers size={18} />} label="Channel policy" active={activeTab === 'channels'} onClick={() => setActiveTab('channels')} />
          <NavItem icon={<Settings size={18} />} label="Demo settings" active={activeTab === 'settings'} onClick={() => setActiveTab('settings')} />
        </nav>

        <div className="p-4 border-t border-zinc-800/80">
          <div className="rounded-xl bg-zinc-800/30 border border-zinc-700/50 px-3 py-2.5">
            <div className="flex items-center gap-2">
              <span className={`w-2 h-2 rounded-full ${loading ? 'bg-amber-400 animate-pulse' : 'bg-emerald-400'}`} />
              <span className="text-[10px] font-medium text-zinc-400 uppercase tracking-wide">API</span>
              <code className="text-[10px] text-zinc-500 truncate flex-1">{API_BASE}</code>
            </div>
            {stats.kill_switch && (
              <p className="text-[10px] text-amber-400/90 mt-2 leading-snug">Kill switch on — outbound is suppressed until disabled in config.</p>
            )}
          </div>
        </div>
      </aside>

      <main className="flex-1 flex flex-col overflow-hidden bg-zinc-950">
        <header className="h-16 border-b border-zinc-800/80 flex items-center justify-between px-8 bg-zinc-900/30 backdrop-blur-md">
          <div>
            <h2 className="text-lg font-semibold text-white capitalize">
              {activeTab === 'pipeline' && 'Signal-grounded pipeline'}
              {activeTab === 'crm' && 'CRM mirror'}
              {activeTab === 'channels' && 'Channel hierarchy'}
              {activeTab === 'settings' && 'Demo configuration'}
            </h2>
            <p className="text-[11px] text-zinc-400 mt-0.5">
              Email primary → SMS after reply → Voice = human discovery on Cal.com
            </p>
          </div>
          <div className="flex items-center gap-3">
            <div className="flex items-center gap-2 bg-zinc-900 border border-zinc-800 rounded-lg px-3 py-1.5">
              <Mail className="text-zinc-500" size={14} />
              <input
                className="bg-transparent border-none outline-none text-xs w-52 text-zinc-200"
                value={testEmail}
                onChange={(e) => setTestEmail(e.target.value)}
                placeholder="Prospect email (HubSpot / Resend)"
              />
            </div>
            <div className="flex items-center gap-2 bg-zinc-900 border border-zinc-800 rounded-lg px-3 py-1.5">
              <Phone size={14} className="text-zinc-500" />
              <input
                className="bg-transparent border-none outline-none text-xs w-36 text-zinc-200 font-mono"
                value={testPhone}
                onChange={(e) => setTestPhone(e.target.value)}
                placeholder="+251…"
              />
            </div>
            <button
              type="button"
              onClick={fetchData}
              className="p-2 rounded-lg border border-zinc-700 hover:bg-zinc-800 text-zinc-300 transition-colors"
              title="Refresh"
            >
              <RefreshCw size={18} className={loading ? 'animate-spin' : ''} />
            </button>
          </div>
        </header>

        <section className="flex-1 overflow-y-auto p-8">
          {activeTab === 'pipeline' && (
            <PipelineView
              leads={leads}
              selectedLead={selectedLead}
              setSelectedLead={setSelectedLead}
              testEmail={testEmail}
              testPhone={testPhone}
              updateLeadInState={updateLeadInState}
              loading={loading}
              stats={stats}
            />
          )}
          {activeTab === 'crm' && (
            <CRMView
              stats={stats}
              hubspotData={hubspotData}
              hubspotLoading={hubspotLoading}
              hubspotError={hubspotError}
              onRefresh={fetchHubspot}
              testEmail={testEmail}
            />
          )}
          {activeTab === 'channels' && <ChannelPolicyView />}
          {activeTab === 'settings' && (
            <SettingsView
              testEmail={testEmail}
              setTestEmail={setTestEmail}
              testPhone={testPhone}
              setTestPhone={setTestPhone}
            />
          )}
        </section>
      </main>
    </div>
  );
};

const PipelineView = ({
  leads, selectedLead, setSelectedLead, testEmail, testPhone, updateLeadInState, loading, stats,
}) => {
  const [isDropdownOpen, setIsDropdownOpen] = useState(false);
  const [isEditing, setIsEditing] = useState(false);
  const [editedEmail, setEditedEmail] = useState('');
  const [webhookInput, setWebhookInput] = useState('');
  const [isEnriching, setIsEnriching] = useState(false);
  const [enrichSteps, setEnrichSteps] = useState([]);
  const dropdownRef = useRef(null);

  useEffect(() => {
    if (selectedLead?.is_enriched && selectedLead.draft_email) {
      setEditedEmail(selectedLead.draft_email);
      setIsEditing(false);
    }
  }, [selectedLead]);

  useEffect(() => {
    if (!isDropdownOpen) return undefined;
    const onKey = (e) => {
      if (e.key === 'Escape') setIsDropdownOpen(false);
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [isDropdownOpen]);

  const draftParts = splitSubjectBody(editedEmail);

  const handleEnrich = async () => {
    if (!selectedLead?.company?.crunchbase_id) return;
    setIsEnriching(true);
    setEnrichSteps([]);
    const cid = selectedLead.company.crunchbase_id;
    let es;
    try {
      es = new EventSource(`${API_BASE}/api/leads/enrich/stream/${encodeURIComponent(cid)}`);
      es.onmessage = (ev) => {
        try {
          const d = JSON.parse(ev.data);
          setEnrichSteps(d.progress || []);
        } catch (_) { /* ignore */ }
      };
    } catch (_) { /* SSE optional */ }
    try {
      const res = await api.post('/api/leads/enrich', {
        company_id: cid,
        hubspot_email: testEmail?.trim() || undefined,
      });
      updateLeadInState(res.data);
      toast.success('Enrichment complete');
    } catch (err) {
      console.error(err);
      toast.error(err.response?.data?.detail || 'Enrichment failed — check API logs.');
    } finally {
      setIsEnriching(false);
      if (es) es.close();
    }
  };

  const handleApproveOutreach = async (approve) => {
    if (!selectedLead?.company?.crunchbase_id) return;
    try {
      if (!approve) {
        toast.message('Edit draft, then approve when ready');
        return;
      }
      const ar = await api.post('/api/outreach/approve', { company_id: selectedLead.company.crunchbase_id });
      toast.success('Outreach approved — you can send email');
      updateLeadInState({
        ...selectedLead,
        channel_state: ar.data.channel_state || selectedLead.channel_state,
      });
    } catch (err) {
      toast.error(err.response?.data?.detail || err.message || 'Approve failed');
    }
  };

  const handleAction = async (endpoint, payload = {}) => {
    if (!selectedLead?.company?.crunchbase_id) return;
    try {
      const body = {
        company_id: selectedLead.company.crunchbase_id,
        content: editedEmail,
        test_email: testEmail,
        test_phone: testPhone,
        message: webhookInput,
        ...payload,
      };
      const res = await api.post(`/api/${endpoint}`, body);
      if (res.data?.needs_approval) {
        toast.message(res.data.message || 'Human approval required');
        return;
      }
      if (res.data?.channel_state) {
        updateLeadInState({
          ...selectedLead,
          channel_state: res.data.channel_state,
          is_enriched: selectedLead.is_enriched,
        });
      }
      if (endpoint.includes('simulate/reply')) setWebhookInput('');
      if (res.data?.suppressed) {
        toast.warning(`Outbound suppressed: ${res.data.reason || 'kill switch'}`);
      } else if (endpoint.includes('simulate/reply')) {
        toast.success(
          res.data.qualified_for_discovery
            ? 'Reply qualified — book discovery when ready.'
            : `Intent: ${res.data.intent || 'unclear'}`,
        );
      } else if (endpoint.includes('outreach/book-discovery')) {
        const b = res.data.booking;
        if (b?.success) toast.success(`Cal booking created (id: ${b.booking_id ?? '—'})`);
        else toast.error(`Cal booking failed: ${b?.error || 'see logs'}`);
      } else {
        const ch = payload.channel === 'sms' ? 'SMS' : 'Email';
        toast.success(`${ch} sent — check timeline`);
      }
    } catch (err) {
      toast.error(err.response?.data?.detail || err.message || 'Action failed');
    }
  };

  const ch = selectedLead?.channel_state || {};
  const smsAllowed = !!ch.prospect_replied;
  const qualifiedForDiscovery = !!ch.qualified_for_discovery;
  const timeline = (ch.events || []).slice().reverse();
  const booking = ch.booking_payload || {};
  const intentLabel = ch.last_intent || '';

  return (
    <div className="flex flex-col gap-8 max-w-[1400px] mx-auto">
      {stats && stats.workspace_persisted === false && (
        <div className="rounded-xl border border-amber-800/60 bg-amber-950/30 px-4 py-3 text-sm text-amber-100">
          Session mirror incomplete after restart — re-run <strong>Enrich</strong> for leads missing restored briefs
          ({stats.workspace_mirror_rows ?? 0} mirrored rows).
        </div>
      )}
      <div className="relative" ref={dropdownRef}>
        <div className="rounded-2xl border border-zinc-800 bg-zinc-900/40 p-4 shadow-xl">
          <p className="text-[10px] font-semibold text-zinc-400 uppercase tracking-widest mb-2">Company</p>
          <button
            type="button"
            aria-expanded={isDropdownOpen}
            aria-haspopup="listbox"
            onClick={() => setIsDropdownOpen(!isDropdownOpen)}
            className="w-full flex items-center justify-between rounded-xl border border-zinc-700 bg-zinc-950 px-4 py-3 text-left hover:border-zinc-600 transition-colors"
          >
            <div className="flex items-center gap-3 min-w-0">
              <span className={`shrink-0 w-2 h-2 rounded-full ${selectedLead ? 'bg-emerald-400' : 'bg-zinc-600'}`} />
              <span className="font-semibold text-white truncate">
                {selectedLead?.company?.name || 'Select a prospect'}
              </span>
            </div>
            <ChevronRight className={`shrink-0 text-zinc-500 transition-transform ${isDropdownOpen ? 'rotate-90' : ''}`} size={20} />
          </button>
        </div>

        <AnimatePresence>
          {isDropdownOpen && (
            <motion.div
              initial={{ opacity: 0, y: -8 }}
              animate={{ opacity: 1, y: 4 }}
              exit={{ opacity: 0, y: -8 }}
              className="absolute left-0 right-0 z-50 mt-1 rounded-2xl border border-zinc-800 bg-zinc-900 shadow-2xl max-h-[min(400px,50vh)] overflow-y-auto"
            >
              {leads.map((lead) => (
                <button
                  type="button"
                  key={lead.company?.crunchbase_id}
                  onClick={() => { setSelectedLead(lead); setIsDropdownOpen(false); }}
                  className="w-full flex justify-between items-center px-4 py-3 border-b border-zinc-800/80 hover:bg-zinc-800/50 text-left"
                >
                  <div>
                    <p className="font-medium text-white">{lead.company?.name}</p>
                    <p className="text-[11px] text-zinc-400">{lead.company?.industry}</p>
                  </div>
                  <div className="text-right text-[10px]">
                    <p className="text-zinc-400">{lead.company?.job_count ?? 0} roles</p>
                    <span className={lead.is_enriched ? 'text-emerald-400' : 'text-zinc-600'}>
                      {lead.is_enriched ? 'Enriched' : 'Detected'}
                    </span>
                  </div>
                </button>
              ))}
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      {!selectedLead && (
        <div className="flex flex-col items-center justify-center py-24 text-zinc-600">
          {loading ? <Loader2 className="animate-spin w-10 h-10 mb-4" /> : <BarChart3 className="w-10 h-10 mb-4 opacity-30" />}
          <p className="text-sm">Choose a company to run Crunchbase + jobs + layoffs + leadership + AI maturity.</p>
        </div>
      )}

      {selectedLead && !selectedLead.is_enriched && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          className="rounded-2xl border border-zinc-800 bg-zinc-900/30 p-12 text-center max-w-xl mx-auto"
        >
          <Brain className="w-14 h-14 mx-auto text-violet-400 mb-6" />
          <h3 className="text-2xl font-semibold text-white mb-2">{selectedLead.company.name}</h3>
          <p className="text-zinc-400 text-sm mb-8">{selectedLead.company.industry}</p>
          {isEnriching && enrichSteps.length > 0 && (
            <div className="mb-6 text-left max-w-md mx-auto rounded-lg border border-zinc-800 bg-zinc-950/80 p-3 text-[11px] text-zinc-400">
              <p className="text-zinc-300 font-semibold mb-2">Enrichment progress</p>
              <ul className="space-y-1 font-mono">
                {enrichSteps.map((s, i) => (
                  <li key={`${s.at}-${i}`}>{s.stage}</li>
                ))}
              </ul>
            </div>
          )}
          <button
            type="button"
            onClick={handleEnrich}
            disabled={isEnriching}
            className="inline-flex items-center gap-2 px-8 py-3 rounded-xl bg-white text-zinc-900 font-semibold text-sm hover:bg-zinc-100 disabled:opacity-50"
          >
            {isEnriching ? <Loader2 className="animate-spin" size={18} /> : <Zap size={18} />}
            {isEnriching ? 'Running enrichment…' : 'Run hiring signal + competitor gap'}
          </button>
          <p className="text-[11px] text-zinc-500 mt-4">
            Pushes a structured snapshot to HubSpot when demo email is set.
          </p>
        </motion.div>
      )}

      {selectedLead?.is_enriched && (
        <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} className="space-y-8">
          <section className="rounded-2xl border border-zinc-800 bg-zinc-900/40 p-8">
            <div className="flex flex-wrap items-start justify-between gap-4 mb-6">
              <div>
                <h3 className="text-xl font-semibold text-white">{selectedLead.company.name}</h3>
                <p className="text-sm text-zinc-400 mt-1">
                  Hiring signal brief · claim strength vs pipeline (Tenacious honesty)
                </p>
                {intentLabel && (
                  <p className="mt-2 text-[11px]">
                    <span className="text-zinc-500">Last intent: </span>
                    <span className="rounded-md bg-violet-950/80 text-violet-200 px-2 py-0.5 font-mono">{intentLabel}</span>
                  </p>
                )}
              </div>
              <div className="text-right space-y-2">
                <div>
                  <p className="text-[10px] uppercase tracking-widest text-zinc-400" title="Average of module confidence scores on successful fetches">
                    Pipeline blend
                  </p>
                  <p className="text-2xl font-semibold text-zinc-300 tabular-nums">
                    {((selectedLead.brief?.overall_confidence ?? 0) * 100).toFixed(1)}%
                  </p>
                </div>
                <div>
                  <p className="text-[10px] uppercase tracking-widest text-emerald-500/90" title="Safe weight for outreach — absence findings capped">
                    Claim strength (avg)
                  </p>
                  <p className="text-2xl font-semibold text-emerald-400/90 tabular-nums">
                    {(averageClaimStrength(selectedLead.brief) * 100).toFixed(1)}%
                  </p>
                </div>
              </div>
            </div>

            <SignalTable brief={selectedLead.brief} research={selectedLead.research} />

            <HiringSignalSchemaPanel
              data={selectedLead.hiring_signal_brief}
              schemaOk={selectedLead.schema_validation?.hiring_signal_ok}
              schemaError={selectedLead.schema_validation?.hiring_signal_error}
            />

            {selectedLead.outreach_policy && (
              <section className="mt-6 rounded-xl border border-violet-900/40 bg-violet-950/20 p-5">
                <h4 className="text-[11px] font-semibold uppercase tracking-widest text-violet-300/90 mb-3 flex items-center gap-2">
                  <Info size={14} /> ICP & outreach policy (Tenacious Week 10)
                </h4>
                <div className="grid sm:grid-cols-2 gap-4 text-xs text-zinc-400">
                  <div>
                    <p className="text-zinc-500 text-[10px] uppercase font-semibold mb-1">Segment key</p>
                    <p className="text-zinc-200 font-mono text-[11px]">{selectedLead.outreach_policy.icp_segment_key}</p>
                    <p className="mt-2 text-zinc-500 text-[10px] uppercase font-semibold">Classifier confidence</p>
                    <p className="text-zinc-300 tabular-nums">
                      {((selectedLead.outreach_policy.icp_confidence ?? 0) * 100).toFixed(0)}%
                    </p>
                  </div>
                  <div className="space-y-2">
                    <p className="flex flex-wrap gap-2">
                      {selectedLead.outreach_policy.exploratory_mode && (
                        <span className="px-2 py-0.5 rounded-md bg-amber-950/60 text-amber-200 border border-amber-800/50 text-[10px]">
                          Exploratory / ICP abstain — no hard segment pitch
                        </span>
                      )}
                      {selectedLead.outreach_policy.weak_job_signal && (
                        <span className="px-2 py-0.5 rounded-md bg-zinc-800 text-zinc-300 border border-zinc-700 text-[10px]">
                          Weak job-post signal — email asks; does not assert scale
                        </span>
                      )}
                      {!selectedLead.outreach_policy.segment_4_pitch_allowed && (
                        <span className="px-2 py-0.5 rounded-md bg-zinc-800 text-zinc-400 border border-zinc-700 text-[10px]">
                          Segment 4 (specialized AI gap) gated until AI maturity is 2+
                        </span>
                      )}
                      {selectedLead.outreach_policy.segment_4_pitch_allowed && (
                        <span className="px-2 py-0.5 rounded-md bg-emerald-950/50 text-emerald-200 border border-emerald-800/40 text-[10px]">
                          Segment 4 language allowed (AI maturity ≥ 2)
                        </span>
                      )}
                    </p>
                    <p className="text-[11px] text-zinc-500 leading-relaxed border-t border-zinc-800/80 pt-3">
                      {selectedLead.outreach_policy.documentation}
                    </p>
                  </div>
                </div>
              </section>
            )}

            <div className="mt-8 pt-6 border-t border-zinc-800 flex flex-wrap items-center gap-6">
              <div className="flex items-center gap-3">
                <div className="w-14 h-14 rounded-full border-2 border-violet-500/40 flex items-center justify-center">
                  <span className="text-lg font-bold text-violet-300 tabular-nums">
                    {selectedLead.hiring_signal_brief?.ai_maturity?.score
                      ?? selectedLead.brief?.signals?.ai_maturity?.score
                      ?? 0}
                  </span>
                </div>
                <div>
                  <p className="text-[10px] uppercase text-zinc-500 font-semibold">AI maturity (0–3)</p>
                  <p className="text-[10px] text-zinc-500 mt-0.5">
                    Claim {((selectedLead.brief?.signals?.ai_maturity?.evidence_strength ?? selectedLead.brief?.signals?.ai_maturity?.confidence ?? 0) * 100).toFixed(0)}%
                    {' · '}
                    Pipeline {((selectedLead.brief?.signals?.ai_maturity?.source_confidence ?? 0) * 100).toFixed(0)}%
                  </p>
                  <p className="text-sm text-zinc-300 mt-1">{selectedLead.brief?.signals?.ai_maturity?.narrative?.slice(0, 200)}…</p>
                </div>
              </div>
            </div>
          </section>

          <section className="rounded-2xl border border-zinc-800 bg-zinc-900/40 p-8">
            <h4 className="text-sm font-semibold text-white mb-2 flex items-center gap-2">
              <MessageSquare size={16} className="text-violet-400" />
              Competitor gap · research summary
            </h4>
            <p className="text-[11px] text-zinc-500 mb-4">
              Short list from internal models; the JSON Schema instance below is what HubSpot notes and validators use.
            </p>
            <ul className="space-y-3">
              {(selectedLead.research?.key_gaps || []).map((gap, i) => (
                <li key={i} className="flex gap-3 text-sm text-zinc-400">
                  <CheckCircle2 className="shrink-0 text-emerald-500/80 mt-0.5" size={16} />
                  {gap}
                </li>
              ))}
            </ul>
            {selectedLead.research?.competitors_analyzed?.length > 0 && (
              <p className="text-[11px] text-zinc-600 mt-4">
                Peers analyzed: {selectedLead.research.competitors_analyzed.slice(0, 8).join(', ')}
                {selectedLead.research.competitors_analyzed.length > 8 ? '…' : ''}
              </p>
            )}
            <CompetitorGapSchemaPanel
              data={selectedLead.competitor_gap_brief}
              schemaOk={selectedLead.schema_validation?.competitor_gap_ok}
              schemaError={selectedLead.schema_validation?.competitor_gap_error}
            />
          </section>

          <div className="grid md:grid-cols-2 gap-6">
            <div className="rounded-2xl border border-zinc-800 bg-zinc-900/40 p-6">
              <div className="flex justify-between items-center mb-4">
                <h4 className="text-sm font-semibold flex items-center gap-2 text-white">
                  <Send size={16} /> Outreach
                </h4>
                <button
                  type="button"
                  onClick={() => setIsEditing(!isEditing)}
                  className="text-[11px] text-violet-400 hover:text-violet-300"
                >
                  {isEditing ? 'Preview' : 'Edit draft'}
                </button>
              </div>
              <ChannelLadder compact />
              {stats?.require_human_approval && (
                <div className="mb-4 flex flex-wrap gap-2">
                  <button
                    type="button"
                    onClick={() => handleApproveOutreach(true)}
                    className="px-3 py-2 rounded-lg bg-emerald-800/40 border border-emerald-700/50 text-emerald-100 text-xs font-semibold"
                  >
                    Approve outreach
                  </button>
                  <button
                    type="button"
                    onClick={() => handleApproveOutreach(false)}
                    className="px-3 py-2 rounded-lg bg-zinc-800 border border-zinc-700 text-zinc-300 text-xs"
                  >
                    Dismiss
                  </button>
                </div>
              )}
              {isEditing ? (
                <textarea
                  className="w-full h-52 bg-zinc-950 border border-zinc-700 rounded-xl p-4 text-xs text-zinc-200 font-mono outline-none focus:ring-1 ring-violet-500"
                  value={editedEmail}
                  onChange={(e) => setEditedEmail(e.target.value)}
                />
              ) : (
                <div className="space-y-3">
                  <div className="rounded-xl border border-zinc-800 bg-zinc-950 p-3">
                    <p className="text-[10px] uppercase text-zinc-500 font-semibold mb-1">Subject</p>
                    <p className="text-sm text-zinc-200">{draftParts.subject || '—'}</p>
                  </div>
                  <div className="text-sm text-zinc-400 bg-zinc-950 rounded-xl p-4 min-h-[10rem] whitespace-pre-wrap border border-zinc-800">
                    {draftParts.body || editedEmail}
                  </div>
                </div>
              )}
              <div className="flex gap-3 mt-4">
                <button
                  type="button"
                  onClick={() => handleAction('outreach/send', { channel: 'email' })}
                  className="flex-1 py-3 rounded-xl bg-violet-600 hover:bg-violet-500 text-white text-xs font-semibold uppercase tracking-wide flex items-center justify-center gap-2"
                >
                  <Mail size={16} /> 1 · Send email
                </button>
                <button
                  type="button"
                  disabled={!smsAllowed}
                  onClick={() => handleAction('outreach/send', { channel: 'sms' })}
                  className={`flex-1 py-3 rounded-xl text-xs font-semibold uppercase tracking-wide flex items-center justify-center gap-2 border ${smsAllowed ? 'border-amber-600/50 text-amber-200 hover:bg-amber-950/50' : 'border-zinc-700 text-zinc-600 cursor-not-allowed'}`}
                >
                  <Phone size={16} /> 2 · SMS
                </button>
              </div>
              {!smsAllowed && (
                <p className="text-[10px] text-zinc-500 mt-2">Simulate a reply first to unlock SMS (warm lead).</p>
              )}
            </div>

            <div className="rounded-2xl border border-zinc-800 bg-zinc-900/40 p-6">
              <div className="flex items-center gap-2 text-amber-400 mb-4">
                <Terminal size={16} />
                <h4 className="text-sm font-semibold">Simulate prospect reply</h4>
              </div>
              <textarea
                className="w-full h-40 bg-zinc-950 border border-zinc-700 rounded-xl p-4 text-xs text-zinc-300 font-mono outline-none mb-4"
                placeholder="e.g. Yes — interested. Send a few times next week."
                value={webhookInput}
                onChange={(e) => setWebhookInput(e.target.value)}
              />
              <button
                type="button"
                onClick={() => handleAction('simulate/reply')}
                className="w-full py-3 rounded-xl bg-amber-600/20 border border-amber-700/40 text-amber-200 text-xs font-semibold hover:bg-amber-600/30"
              >
                Qualify reply (hiring brief)
              </button>
              <button
                type="button"
                disabled={!qualifiedForDiscovery || !!ch.discovery_booked}
                onClick={() => handleAction('outreach/book-discovery')}
                className={`w-full mt-3 py-3 rounded-xl text-xs font-semibold flex items-center justify-center gap-2 border ${qualifiedForDiscovery && !ch.discovery_booked ? 'border-emerald-600/50 text-emerald-200 hover:bg-emerald-950/40' : 'border-zinc-700 text-zinc-600 cursor-not-allowed'}`}
              >
                <Calendar size={16} /> Book discovery (Cal.com API)
              </button>
              {(booking.booking_id || booking.error || ch.discovery_booked) && (
                <div className="mt-4 rounded-xl border border-zinc-800 bg-zinc-950/80 p-3 text-[11px] text-zinc-300 space-y-1">
                  <p className="font-semibold text-zinc-200">Cal booking</p>
                  {booking.booking_id != null && <p>ID: <span className="font-mono">{String(booking.booking_id)}</span></p>}
                  {booking.status && <p>Status: {booking.status}</p>}
                  {booking.error && <p className="text-amber-400">Error: {booking.error}</p>}
                  {ch.discovery_booked && !booking.error && <p className="text-emerald-400/90">Booked</p>}
                </div>
              )}
              {ch.cal_booking_link && qualifiedForDiscovery && (
                <p className="text-[10px] text-zinc-400 mt-2 break-all">
                  Optional public link after qualify:{' '}
                  <a href={ch.cal_booking_link} className="text-violet-400 hover:underline" target="_blank" rel="noreferrer">open Cal page</a>
                </p>
              )}
              <div className="flex items-start gap-2 mt-4 text-[11px] text-zinc-400">
                <Mic size={14} className="shrink-0 mt-0.5" />
                <span>Email 1 has no calendar link; API booking runs only after qualify. Voice is the human discovery call.</span>
              </div>
            </div>
          </div>

          <section className="rounded-2xl border border-zinc-800 bg-zinc-900/40 p-6">
            <h4 className="text-sm font-semibold text-white mb-4 flex items-center gap-2">
              <Activity size={16} className="text-emerald-400" />
              End-to-end conversation status
            </h4>
            <div className="grid md:grid-cols-4 gap-3 mb-5">
              <StepPill title="Email sent" ok={!!ch.email_sent_at} />
              <StepPill title="Reply received" ok={!!ch.prospect_replied} />
              <StepPill title="Qualified" ok={qualifiedForDiscovery} />
              <StepPill title="Cal booked" ok={!!ch.discovery_booked} />
            </div>
            <div className="rounded-xl border border-zinc-800 bg-zinc-950/50">
              {(timeline.length ? timeline : [{ type: 'no_events', at: '', note: 'No channel events yet.' }]).map((evt, idx) => (
                <div key={`${evt.at}-${idx}`} className="px-4 py-3 border-b border-zinc-800/70 last:border-b-0 text-xs">
                  <div className="flex items-center justify-between gap-3">
                    <p className="font-semibold text-zinc-200">{evt.type.replaceAll('_', ' ')}</p>
                    <p className="text-zinc-400 font-mono">{evt.at ? new Date(evt.at).toLocaleString() : '—'}</p>
                  </div>
                  <p className="text-zinc-400 mt-1 break-all">
                    {evt.message_preview || evt.preview || evt.subject || evt.reason || evt.note || ''}
                    {evt.correlation_id && (
                      <span className="block text-[10px] text-zinc-500 mt-1" title="Correlation id">
                        cid: {evt.correlation_id}
                      </span>
                    )}
                  </p>
                </div>
              ))}
            </div>
          </section>
        </motion.div>
      )}
    </div>
  );
};

const SIGNAL_KEYS = ['job_velocity', 'funding', 'layoffs', 'leadership', 'ai_maturity'];

const SignalTable = ({ brief, research }) => {
  const rows = [];
  const sig = brief?.signals || {};
  SIGNAL_KEYS.forEach((k) => {
    const b = sig[k];
    rows.push({
      key: k,
      label: b?.label || k.replace(/_/g, ' '),
      narrative: b?.narrative || '—',
      evidence: b ? (b.evidence_strength ?? b.confidence ?? 0) : 0,
      pipeline: b ? (b.source_confidence ?? 0) : 0,
      caveat: b?.evidence_caveat,
    });
  });
  const per = research?.per_signal_confidence || [];
  const model = brief?.confidence_model || {};
  return (
    <div className="overflow-x-auto rounded-xl border border-zinc-800">
      <table className="w-full text-left text-sm">
        <thead>
          <tr className="border-b border-zinc-800 bg-zinc-950/80">
            <th className="p-3 text-[10px] uppercase tracking-wider text-zinc-400 font-semibold">Signal</th>
            <th className="p-3 text-[10px] uppercase tracking-wider text-zinc-400 font-semibold">Narrative</th>
            <th
              className="p-3 text-[10px] uppercase tracking-wider text-emerald-500/90 font-semibold w-24"
              title={model.evidence_strength || 'Safe weight for claims; absence in a snapshot is not certainty'}
            >
              Claim
            </th>
            <th
              className="p-3 text-[10px] uppercase tracking-wider text-zinc-400 font-semibold w-24"
              title={model.source_confidence || 'Module reported success / fetch completed'}
            >
              Pipeline
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.key} className="border-b border-zinc-800/80 hover:bg-zinc-800/20 align-top">
              <td className="p-3 text-zinc-300 font-medium capitalize">{r.label}</td>
              <td className="p-3 text-zinc-400 text-xs max-w-xl">
                <span className="block">{r.narrative}</span>
                {r.caveat && (
                  <span className="mt-1.5 block text-[10px] text-amber-500/90 leading-snug">{r.caveat}</span>
                )}
              </td>
              <td className="p-3 tabular-nums text-emerald-400/90 font-medium">{((r.evidence ?? 0) * 100).toFixed(0)}%</td>
              <td className="p-3 tabular-nums text-zinc-500">{((r.pipeline ?? 0) * 100).toFixed(0)}%</td>
            </tr>
          ))}
        </tbody>
      </table>
      {per.length > 0 && (
        <div className="px-3 py-2 border-t border-zinc-800 bg-zinc-950/40 flex flex-wrap gap-2">
          <span className="text-[10px] text-zinc-500 uppercase tracking-wide font-semibold self-center mr-2">Raw source σ</span>
          {per.map((p) => (
            <span key={p.source_key} className="text-[10px] px-2 py-0.5 rounded-md bg-zinc-800/80 text-zinc-400 font-mono border border-zinc-700/50">
              {p.source_key}: {((p.confidence ?? 0) * 100).toFixed(0)}%
            </span>
          ))}
        </div>
      )}
    </div>
  );
};

const ChannelLadder = ({ compact }) => (
  <div className={`${compact ? 'mb-4' : ''} rounded-xl bg-zinc-950/60 border border-zinc-800 p-4`}>
    <ol className="space-y-2 text-xs text-zinc-400">
      <li className="flex gap-2"><span className="text-violet-400 font-mono">1</span> Email — primary outbound for founders / CTO / VP Eng</li>
      <li className="flex gap-2"><span className="text-amber-400 font-mono">2</span> SMS — only after they replied by email; scheduling nudges</li>
      <li className="flex gap-2"><span className="text-emerald-400 font-mono">3</span> Voice — human discovery call once Cal.com is booked</li>
    </ol>
  </div>
);

const CRMView = ({
  stats, hubspotData, hubspotLoading, hubspotError, onRefresh, testEmail,
}) => (
  <div className="max-w-5xl mx-auto space-y-8">
    <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
      <StatCard title="Prospects (ODM)" value={stats.total_companies} icon={<Users className="text-zinc-300" />} />
      <StatCard title="Role signals (workspace)" value={stats.total_jobs} icon={<TrendingUp className="text-emerald-400" />} />
      <StatCard title="Email sends" value={stats.active_outreach} icon={<Mail className="text-violet-400" />} />
      <StatCard title="Booked discoveries" value={stats.booked_calls} icon={<Calendar className="text-amber-400" />} />
    </div>

    <div className="rounded-2xl border border-zinc-800 bg-zinc-900/40 p-8">
      <div className="flex flex-wrap items-center justify-between gap-4 mb-6">
        <div>
          <h4 className="text-lg font-semibold text-white flex items-center gap-2">
            <Database size={20} className="text-violet-400" />
            HubSpot contact mirror
          </h4>
          <p className="text-sm text-zinc-500 mt-1">
            Live read for <span className="text-zinc-300 font-mono">{testEmail || '—'}</span> — refresh after enrich or simulate reply.
          </p>
        </div>
        <button
          type="button"
          onClick={onRefresh}
          disabled={hubspotLoading}
          className="inline-flex items-center gap-2 px-4 py-2 rounded-lg border border-zinc-700 text-sm text-zinc-200 hover:bg-zinc-800"
        >
          <RefreshCw size={16} className={hubspotLoading ? 'animate-spin' : ''} />
          Refresh
        </button>
      </div>

      <div className="rounded-xl border border-zinc-800 bg-zinc-950/60 p-4 text-xs text-zinc-300 space-y-1 mb-4">
        <p>
          Outbound status:{' '}
          <span className={stats.outbound_suppressed ? 'text-amber-400' : 'text-emerald-400'}>
            {stats.outbound_suppressed ? 'suppressed by policy' : 'live'}
          </span>
        </p>
        <p>
          Dev override:{' '}
          <span className={stats.live_outreach ? 'text-emerald-400' : 'text-zinc-500'}>
            {stats.live_outreach ? 'LIVE_OUTREACH=true' : 'off'}
          </span>
        </p>
      </div>

      {hubspotError && (
        <div className="rounded-xl border border-amber-900/50 bg-amber-950/20 text-amber-200 text-sm p-4 mb-4">
          {hubspotError}
        </div>
      )}

      {hubspotData?.demo_health && (
        <div className="mb-5 grid md:grid-cols-2 gap-3">
          <div className={`rounded-lg border px-3 py-2 ${hubspotData.demo_health.required_non_null ? 'border-emerald-800/60 bg-emerald-950/20' : 'border-amber-800/60 bg-amber-950/20'}`}>
            <p className="text-[10px] uppercase tracking-wide text-zinc-400 font-semibold">Required fields non-null</p>
            <p className="text-sm mt-1">{hubspotData.demo_health.required_non_null ? 'Yes' : `Missing: ${hubspotData.demo_health.missing_fields.join(', ')}`}</p>
          </div>
          <div className={`rounded-lg border px-3 py-2 ${hubspotData.demo_health.enrichment_timestamp_current ? 'border-emerald-800/60 bg-emerald-950/20' : 'border-amber-800/60 bg-amber-950/20'}`}>
            <p className="text-[10px] uppercase tracking-wide text-zinc-400 font-semibold">Enrichment timestamp current</p>
            <p className="text-sm mt-1">
              {hubspotData.demo_health.enrichment_timestamp_current
                ? `Yes (${hubspotData.demo_health.seconds_since_update ?? 0}s ago)`
                : `No (${hubspotData.demo_health.seconds_since_update ?? 'unknown'}s ago)`}
            </p>
          </div>
        </div>
      )}

      {hubspotData?.demo_properties && (
        <div className="grid sm:grid-cols-2 gap-3">
          {Object.entries(hubspotData.demo_properties)
            .map(([k, v]) => (
              <div key={k} className="rounded-lg border border-zinc-800 bg-zinc-950/50 px-3 py-2">
                <p className="text-[10px] uppercase tracking-wide text-zinc-500 font-semibold">{k}</p>
                <p className="text-sm text-zinc-200 break-all">{String(v)}</p>
              </div>
            ))}
        </div>
      )}

      {hubspotData?.id && (
        <a
          href={`https://app.hubspot.com/contacts/${import.meta.env.VITE_HUBSPOT_PORTAL_ID || ''}/record/0-1/${hubspotData.id}`}
          target="_blank"
          rel="noreferrer"
          className="inline-flex items-center gap-2 mt-6 text-sm text-violet-400 hover:text-violet-300"
        >
          Open in HubSpot <ExternalLink size={14} />
        </a>
      )}
    </div>
  </div>
);

const ChannelPolicyView = () => (
  <div className="max-w-3xl mx-auto rounded-2xl border border-zinc-800 bg-zinc-900/40 p-10">
    <h3 className="text-xl font-semibold text-white mb-6 flex items-center gap-2">
      <Info size={22} className="text-violet-400" />
      Tenacious channel policy
    </h3>
    <ChannelLadder />
    <p className="text-sm text-zinc-500 leading-relaxed mt-6">
      This mirrors the Week 10 brief: cold SMS to executives underperforms versus careful,
      signal-grounded email. The dashboard enforces SMS only after a simulated (or webhook) email reply.
      Cal.com represents scheduling for a human-led discovery — the final channel in the ladder.
    </p>
  </div>
);

const SettingsView = ({ testEmail, setTestEmail, testPhone, setTestPhone }) => (
  <div className="max-w-xl mx-auto rounded-2xl border border-zinc-800 bg-zinc-900/40 p-8">
    <h3 className="text-lg font-semibold text-white mb-6 flex items-center gap-2">
      <Settings className="text-zinc-400" />
      Demo targets
    </h3>
    <label className="block text-[10px] uppercase tracking-widest text-zinc-500 mb-2">Email</label>
    <input
      className="w-full rounded-xl border border-zinc-700 bg-zinc-950 px-4 py-3 text-sm text-zinc-200 mb-6 outline-none focus:ring-1 ring-violet-500"
      value={testEmail}
      onChange={(e) => setTestEmail(e.target.value)}
    />
    <label className="block text-[10px] uppercase tracking-widest text-zinc-500 mb-2">Phone (Africa&apos;s Talking sandbox)</label>
    <input
      className="w-full rounded-xl border border-zinc-700 bg-zinc-950 px-4 py-3 text-sm font-mono text-zinc-200 outline-none focus:ring-1 ring-violet-500"
      value={testPhone}
      onChange={(e) => setTestPhone(e.target.value)}
    />
    <p className="text-xs text-zinc-600 mt-6 leading-relaxed">
      Set <code className="text-zinc-500">VITE_API_BASE</code>, <code className="text-zinc-500">VITE_DEMO_EMAIL</code>,{' '}
      <code className="text-zinc-500">VITE_HUBSPOT_PORTAL_ID</code> in{' '}
      <code className="text-zinc-500">frontend/.env</code> for repeatable demos.
    </p>
  </div>
);

const NavItem = ({ icon, label, active, onClick }) => (
  <button
    type="button"
    onClick={onClick}
    className={`w-full flex items-center gap-3 px-4 py-3 rounded-xl text-sm font-medium transition-colors ${active ? 'bg-zinc-800 text-white' : 'text-zinc-500 hover:text-zinc-300 hover:bg-zinc-800/50'}`}
  >
    {icon}
    <span>{label}</span>
  </button>
);

const StatCard = ({ title, value, icon }) => (
  <div className="rounded-2xl border border-zinc-800 bg-zinc-900/40 p-5">
    <div className="w-10 h-10 rounded-lg bg-zinc-800/80 flex items-center justify-center mb-3">{icon}</div>
    <p className="text-[10px] uppercase tracking-wider text-zinc-500 font-semibold">{title}</p>
    <p className="text-2xl font-semibold text-white tabular-nums mt-1">{value}</p>
  </div>
);

const StepPill = ({ title, ok }) => (
  <div className={`rounded-lg border px-3 py-2 text-xs ${ok ? 'border-emerald-800/60 bg-emerald-950/20 text-emerald-200' : 'border-zinc-700 bg-zinc-900/50 text-zinc-400'}`}>
    <p className="uppercase tracking-wide text-[10px]">{title}</p>
    <p className="mt-1 font-semibold">{ok ? 'Done' : 'Pending'}</p>
  </div>
);

export default App;
