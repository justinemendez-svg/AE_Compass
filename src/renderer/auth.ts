import { AuthIdentity, RosterAE } from './data/api';

export type AccessRole = 'AE' | 'GTM' | 'FLM' | 'Director' | 'RVP' | 'SVP' | 'Admin';
export type ScopeType = 'SVP' | '-1 SVP' | '-2 SVP' | '-3 SVP' | 'AE' | 'RVP' | 'Director' | 'FLM';

export interface AccessScope {
  type: ScopeType;
  value: string;
}

export interface AccessProfile {
  id: string;
  name: string;
  email: string;
  password: string;
  role: AccessRole;
  scopeValue: string;
  active: boolean;
  accessLevel?: 'full' | 'scoped' | 'director';
  subjectId?: string;
  accessScopes?: AccessScope[];
}

const STORAGE_KEY = 'ae-compass-access-profiles';
const SESSION_KEY = 'ae-compass-session';
const VISITS_KEY = 'ae-compass-visits';
export const ADMIN_PASSWORD = '12344321';

export interface VisitRecord {
  profileId: string;
  visitedAt: string;
}

export const ROLE_OPTIONS: AccessRole[] = ['AE', 'FLM', 'Director', 'RVP', 'SVP', 'Admin'];

export const DEFAULT_PROFILES: AccessProfile[] = [{
  id: 'profile-admin',
  name: 'Justine Mendez',
  email: 'admin@aecompass.local',
  password: ADMIN_PASSWORD,
  role: 'Admin',
  scopeValue: 'all',
  active: true,
  accessLevel: 'full',
}];

export function loadProfiles(): AccessProfile[] {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored) {
      const parsed = JSON.parse(stored) as AccessProfile[];
      const merged = [...parsed, ...DEFAULT_PROFILES.filter((profile) => !parsed.some((entry) => entry.id === profile.id))];
      const adminIndex = merged.findIndex((profile) => profile.id === 'profile-admin');
      if (adminIndex >= 0) merged[adminIndex] = { ...merged[adminIndex], ...DEFAULT_PROFILES[0], name: 'Justine Mendez' };
      if (merged.length !== parsed.length) localStorage.setItem(STORAGE_KEY, JSON.stringify(merged));
      return merged;
    }
  } catch {}
  localStorage.setItem(STORAGE_KEY, JSON.stringify(DEFAULT_PROFILES));
  return DEFAULT_PROFILES;
}

export function saveProfiles(profiles: AccessProfile[]) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(profiles));
}

export function getSessionId(): string | null {
  return sessionStorage.getItem(SESSION_KEY);
}

export function setSessionId(id: string) {
  sessionStorage.setItem(SESSION_KEY, id);
}

export function clearSession() {
  sessionStorage.removeItem(SESSION_KEY);
}

export function recordVisit(profile: AccessProfile) {
  try {
    const visits = JSON.parse(localStorage.getItem(VISITS_KEY) || '[]') as VisitRecord[];
    visits.push({ profileId: profile.id, visitedAt: new Date().toISOString() });
    localStorage.setItem(VISITS_KEY, JSON.stringify(visits.slice(-5000)));
  } catch {}
}

export function loadVisits(): VisitRecord[] {
  try {
    const visits = JSON.parse(localStorage.getItem(VISITS_KEY) || '[]');
    return Array.isArray(visits) ? visits : [];
  } catch { return []; }
}

export function authenticate(profiles: AccessProfile[], email: string, password: string): AccessProfile | null {
  if (password !== ADMIN_PASSWORD) return null;
  return profiles.find((p) => p.active && p.role === 'Admin') || null;
}

export function defaultSalesProfile(profiles: AccessProfile[]): AccessProfile | null {
  // Local playground identity: use Justine's configured Full Access profile
  // until the company identity header supplies the real signed-in user.
  const localAdmin = profiles.find((profile) => profile.active && profile.id === 'profile-admin');
  if (localAdmin) return localAdmin;
  return profiles.find((profile) => profile.active && profile.role !== 'Admin' && profile.id === 'profile-demo-ae')
    || profiles.find((profile) => profile.active && profile.role !== 'Admin')
    || null;
}

export function profileFromIdentity(identity: AuthIdentity): AccessProfile | null {
  if (!identity.authenticated || !identity.email || !identity.name) return null;
  const isAdmin = identity.role === 'Admin' || identity.access_level === 'full';
  const role = (identity.role as AccessRole) || 'AE';
  return {
    id: isAdmin ? 'profile-admin' : `sso-${identity.subject_id || identity.email}`,
    name: identity.name,
    email: identity.email,
    password: '',
    role: isAdmin ? 'Admin' : role,
    scopeValue: isAdmin ? 'all' : (identity.scope_value || identity.subject_id || identity.email),
    active: true,
    accessLevel: isAdmin ? 'full' : (role === 'AE' ? 'scoped' : 'scoped'),
    subjectId: identity.subject_id || undefined,
    accessScopes: [],
  };
}

export function profileCanSeeAE(profile: AccessProfile | null, ae: RosterAE): boolean {
  if (!profile) return false;
  if (profile.role === 'Admin' || profile.accessLevel === 'full' || profile.scopeValue === 'all') return true;
  // Every person always gets their own Workday profile. Additional visibility
  // is granted by the multi-select hierarchy scopes below.
  if (ae.user_id === (profile.subjectId || profile.scopeValue)) return true;
  const scopes = profile.accessScopes || (profile.accessLevel === 'director' ? [{ type: 'Director' as ScopeType, value: profile.scopeValue }] : []);
  if (scopes.some((scope) => scope.type === 'SVP' && ae.svp_name === scope.value)) return true;
  if (scopes.some((scope) => scope.type === '-1 SVP' && ae.rvp_name === scope.value)) return true;
  if (scopes.some((scope) => scope.type === '-2 SVP' && ae.director_name === scope.value)) return true;
  if (scopes.some((scope) => scope.type === '-3 SVP' && ae.manager_name === scope.value)) return true;
  if (scopes.some((scope) => scope.type === 'AE' && ae.user_id === scope.value)) return true;
  if (scopes.some((scope) => scope.type === 'FLM' && (ae.manager_name === scope.value || ae.mgr_team_c === scope.value))) return true;
  if (scopes.some((scope) => scope.type === 'Director' && (ae.director_name === scope.value || ae.dir_team_c === scope.value))) return true;
  if (scopes.some((scope) => scope.type === 'RVP' && (ae.rvp_name === scope.value || ae.vp_team_c === scope.value))) return true;
  // Legacy profiles remain supported while the admin UI migrates them.
  if (profile.role === 'FLM') return ae.manager_name === profile.scopeValue || ae.mgr_team_c === profile.scopeValue;
  if (profile.role === 'Director') return ae.director_name === profile.scopeValue || ae.dir_team_c === profile.scopeValue;
  if (profile.role === 'RVP') return ae.rvp_name === profile.scopeValue || ae.vp_team_c === profile.scopeValue;
  if (profile.role === 'SVP') return ae.svp_name === profile.scopeValue;
  return false;
}

export function scopeLabel(profile: AccessProfile): string {
  if (profile.role === 'Admin') return 'All company data';
  if (profile.role === 'AE') return 'Personal performance';
  if (profile.role === 'GTM') return 'GTM profile';
  return `${profile.role} scope · ${profile.scopeValue || 'Not assigned'}`;
}

export function scopeOptions(role: AccessRole, roster: RosterAE[]): string[] {
  if (role === 'Admin') return ['all'];
  if (role === 'AE') return roster.map((r) => r.user_id);
  const values = role === 'FLM' ? roster.map((r) => r.manager_name || r.mgr_team_c)
    : role === 'Director' ? roster.map((r) => r.director_name || r.dir_team_c)
    : role === 'RVP' ? roster.map((r) => r.rvp_name || r.vp_team_c)
    : roster.map((r) => r.svp_name || '');
  return [...new Set(values.filter(Boolean))].sort();
}

export { STORAGE_KEY, SESSION_KEY, VISITS_KEY };
