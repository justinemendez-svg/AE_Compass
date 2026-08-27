const API_BASE = '/api';

async function fetchJSON<T>(path: string, params?: Record<string, string>): Promise<T> {
  const url = new URL(`${window.location.origin}${API_BASE}${path}`);
  if (params) {
    Object.entries(params).forEach(([k, v]) => {
      if (v) url.searchParams.set(k, v);
    });
  }
  const res = await fetch(url.toString());
  if (!res.ok) throw new Error(`API error: ${res.status} ${res.statusText}`);
  return res.json();
}

export interface RosterAE {
  user_id: string;
  ae_name: string;
  email?: string;
  vp_team_c: string;
  dir_team_c: string;
  mgr_team_c: string;
  market_segment_c: string;
  manager_name: string | null;
  director_name: string | null;
  rvp_name: string | null;
  svp_name: string | null;
}

export interface DirectoryPerson {
  id: string;
  name: string;
  email: string;
  source: string;
}

export interface AuthIdentity {
  authenticated: boolean;
  email: string | null;
  name: string | null;
  subject_id: string | null;
  role: string | null;
  access_level: 'full' | 'scoped' | 'hierarchy' | 'own profile' | null;
  scope_value?: string;
  source: 'appfoundry' | 'local-development-fallback';
}

export interface PipelineDeal {
  crm_opportunity_id: string;
  opportunity_name: string;
  crm_account_name: string;
  opportunity_owner_name: string;
  opportunity_owner_id: string;
  stage_name: string;
  opportunity_type: string;
  opportunity_status: string;
  product_arr_usd: number;
  product_booking_arr_usd: number;
  closedate: string;
  stage_2_plus_date_c: string;
  gtm_team: string;
  vp_deal_forecast__c: string | null;
  manager_forecast__c: string | null;
  close_fiscal_quarter: string;
  d_score_latest__c: string | null;
}

export interface MetricsSummary {
  open_pipeline_total: number;
  open_pipeline_nb: number;
  open_pipeline_exp: number;
  open_pipeline_ai: number;
  open_deal_count: number;
  open_pipeline_nb_deal_count: number;
  open_pipeline_ai_deal_count: number;
  bookings_total: number;
  bookings_nb: number;
  bookings_exp: number;
  bookings_ai: number;
  bookings_deal_count: number;
  bookings_nb_deal_count: number;
  bookings_ai_deal_count: number;
}

export interface GongSignal {
  crm_opportunity_id: string;
  call_count: number;
  last_call_at: string | null;
  last_call_title: string | null;
  last_call_next_steps: string | null;
  last_call_key_points: string | null;
  days_since_call: number | null;
  has_next_steps: boolean;
  competitors: string[];
  buyer_signal: boolean;
  objection_signal: boolean;
  risk_signals: string[];
  recommended_actions: string[];
  source: string;
}

export interface GongResponse {
  connected: boolean;
  signals: GongSignal[];
  message: string;
}

export interface CompassAnswer {
  answer: string;
  evidence: Array<{ opportunity: string; amount: number; stage: string; close_date: string }>;
  source: string;
}

export interface ForecastSummary {
  name: string;
  quarter: string;
  quota: number;
  forecast: number;
  bookings: number;
  ai_target: number;
  ai_bookings: number;
  nb_target: number;
  nb_bookings: number;
  pipeline: number;
}

export interface StageEntry {
  stage_name: string;
  deal_count: number;
  total_arr: number;
}

export interface ProductEntry {
  product: string;
  total_arr: number;
  opp_count: number;
}

export interface HistoricalEntry {
  quarter: string;
  bookings_total: number;
  bookings_nb: number;
  bookings_exp: number;
  bookings_ai: number;
  deal_count: number;
}

export interface LinearityEntry {
  close_month: string;
  deals: number;
  bookings: number;
}

export interface PipeCreationEntry {
  created_period: string;
  opps: number;
  arr: number;
}

export interface CoachingNote {
  id: string;
  ae_user_id: string;
  category: string;
  content: string;
  timestamp: string;
}

export interface ActionItem {
  id: string;
  ae_user_id: string;
  title: string;
  status: 'Not Started' | 'In Progress' | 'Completed';
  quarter: string;
  category: string;
}

export const api = {
  lookupProfile: (email: string) => fetchJSON<AuthIdentity>('/profile', { email }),
  health: () => fetchJSON<{ status: string }>('/health'),

  getAuthMe: () => fetchJSON<AuthIdentity>('/auth/me'),

  getRoster: () => fetchJSON<RosterAE[]>('/roster'),

  getDirectory: () => fetchJSON<DirectoryPerson[]>('/directory'),

  getPipeline: (params: { owner_id?: string; owner_name?: string; mgr_team?: string; dir_team?: string; vp_team?: string; svp_name?: string; quarter?: string }) =>
    fetchJSON<PipelineDeal[]>('/pipeline', params as Record<string, string>),

  getMetricsSummary: (params: { owner_id?: string; owner_name?: string; mgr_team?: string; dir_team?: string; vp_team?: string; svp_name?: string; quarter?: string }) =>
    fetchJSON<MetricsSummary>('/metrics/summary', params as Record<string, string>),

  getStageDistribution: (owner_id: string, quarter: string) =>
    fetchJSON<StageEntry[]>('/stage_distribution', { owner_id, quarter }),

  getPipelineByProduct: (params: { owner_id?: string; owner_name?: string; mgr_team?: string; dir_team?: string; vp_team?: string; svp_name?: string; quarter?: string }) =>
    fetchJSON<ProductEntry[]>('/pipeline_by_product', params as Record<string, string>),

  getHistorical: (params: { owner_id?: string; mgr_team?: string; dir_team?: string; vp_team?: string; svp_name?: string }) =>
    fetchJSON<HistoricalEntry[]>('/historical', params as Record<string, string>),

  getBookings: (params: { owner_id?: string; owner_name?: string; quarter?: string; mgr_team?: string; dir_team?: string }) =>
    fetchJSON<any[]>('/bookings', params),

  // Quota
  getQuota: (aeId: string, quarter: string) =>
    fetchJSON<{ quota: number }>(`/quota/${aeId}`, { quarter }),

  setQuota: async (aeId: string, quarter: string, quota: number) => {
    const res = await fetch(`${API_BASE}/quota/${aeId}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ quarter, quota }),
    });
    return res.json();
  },

  getTeamQuota: (params: { quarter?: string; mgr_team?: string; dir_team?: string; vp_team?: string; svp_name?: string }) =>
    fetchJSON<{ quota: number }>('/quota/team', params as Record<string, string>),

  getForecast: (name: string, quarter: string) => fetchJSON<ForecastSummary>('/forecast', { name, quarter }),
  getTeamForecast: (names: string[], quarter: string) => fetchJSON<ForecastSummary>('/forecast/team', { names: names.join('|'), quarter }),
  getGong: (opportunityIds: string[]) => fetchJSON<GongResponse>('/gong', { opportunity_ids: opportunityIds.join('|') }),

  askCompass: async (question: string, owner_name: string, quarter: string) => {
    const res = await fetch(`${API_BASE}/ask`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question, owner_name, quarter }),
    });
    if (!res.ok) throw new Error(`API error: ${res.status}`);
    return res.json() as Promise<CompassAnswer>;
  },

  // Linearity (monthly bookings within quarter)
  getLinearity: (params: { owner_id?: string; owner_name?: string; mgr_team?: string; dir_team?: string; vp_team?: string; svp_name?: string; quarter?: string }) =>
    fetchJSON<LinearityEntry[]>('/linearity', params as Record<string, string>),

  // Pipeline creation (CiQ)
  getPipeCreation: (params: { owner_id?: string; owner_name?: string; mgr_team?: string; dir_team?: string; vp_team?: string; svp_name?: string; quarter?: string; cadence?: 'month' | 'week' }) =>
    fetchJSON<PipeCreationEntry[]>('/pipe_creation', params as Record<string, string>),

  // Coaching notes
  getNotes: (aeId: string) => fetchJSON<CoachingNote[]>(`/notes/${aeId}`),

  addNote: async (aeId: string, note: { id: string; category: string; content: string }) => {
    const res = await fetch(`${API_BASE}/notes/${aeId}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(note),
    });
    return res.json();
  },

  // Action items
  getActions: (aeId: string) => fetchJSON<ActionItem[]>(`/actions/${aeId}`),

  addAction: async (aeId: string, item: { id: string; title: string; status: string; quarter: string; category: string }) => {
    const res = await fetch(`${API_BASE}/actions/${aeId}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(item),
    });
    return res.json();
  },

  updateAction: async (aeId: string, itemId: string, updates: { status: string }) => {
    const res = await fetch(`${API_BASE}/actions/${aeId}/${itemId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(updates),
    });
    return res.json();
  },

  // Competencies
  getCompetencies: (aeId: string) => fetchJSON<number[]>(`/competencies/${aeId}`),

  setCompetencies: async (aeId: string, scores: number[]) => {
    const res = await fetch(`${API_BASE}/competencies/${aeId}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ scores }),
    });
    return res.json();
  },

  // Weekly tracker
  getWeeklyTracker: (aeId: string) => fetchJSON<any>(`/weekly-tracker/${aeId}`),

  setWeeklyTracker: async (aeId: string, rows: any[]) => {
    const res = await fetch(`${API_BASE}/weekly-tracker/${aeId}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ rows }),
    });
    return res.json();
  },

  // Deal maps
  getDealMaps: (aeId: string) => fetchJSON<any[]>(`/deal-maps/${aeId}`),

  setDealMaps: async (aeId: string, plans: any[]) => {
    const res = await fetch(`${API_BASE}/deal-maps/${aeId}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ plans }),
    });
    return res.json();
  },

  // Admin
  verifyAdmin: async (password: string) => {
    const res = await fetch(`${API_BASE}/admin/verify`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ password }),
    });
    return res.json();
  },

  adminUpload: async (file: File, password: string, dataset = 'Pipeline & bookings') => {
    const formData = new FormData();
    formData.append('file', file);
    formData.append('dataset', dataset);
    const res = await fetch(`${API_BASE}/admin/upload`, {
      method: 'POST',
      headers: { 'X-Admin-Password': password },
      body: formData,
    });
    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.error || 'Upload failed');
    }
    return res.json();
  },

  adminListUploads: async (password: string) => {
    const res = await fetch(`${API_BASE}/admin/uploads`, {
      headers: { 'X-Admin-Password': password },
    });
    return res.json();
  },
};
