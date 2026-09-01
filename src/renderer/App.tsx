import { useEffect, useMemo, useState } from 'react';
import AdminPanel, { AdminSection } from './pages/AdminPanel';
import AECompassVision from './pages/AECompassVision';
import LoginScreen from './components/LoginScreen';
import Sidebar from './components/Sidebar';
import { AccessProfile, clearSession, getSessionId, loadProfiles, profileFromIdentity, recordVisit, saveProfiles, setSessionId } from './auth';
import { api, RosterAE } from './data/api';
import { Loader2, LogOut, Moon, Sun } from 'lucide-react';

export default function App() {
  const [profiles, setProfiles] = useState<AccessProfile[]>(() => loadProfiles());
  const [sessionId, setSession] = useState<string | null>(() => getSessionId());
  const [authLoading, setAuthLoading] = useState(true);
  const [landingMode, setLandingMode] = useState(() => {
    const params = new URLSearchParams(window.location.search);
    const intentionalEntry = sessionStorage.getItem('ae-compass-entry') === '1';
    // Shared/direct URLs—including the root URL—always start at landing.
    // Only the immediately-following navigation from profile authentication
    // is allowed to enter Compass directly.
    return params.get('landing') === '1' || (!intentionalEntry && (window.location.pathname === '/' || window.location.pathname === '/compass'));
  });
  const [adminSection, setAdminSection] = useState<AdminSection>('access');
  const [roster, setRoster] = useState<RosterAE[]>([]);
  const [rosterLoading, setRosterLoading] = useState(false);
  const [theme, setTheme] = useState<'light' | 'dark'>(() => localStorage.getItem('ae-compass-theme') === 'dark' ? 'dark' : 'light');
  const currentUser = useMemo(() => profiles.find((profile) => profile.id === sessionId && profile.active) || null, [profiles, sessionId]);

  useEffect(() => {
    // Clear the one-time navigation marker after the initial route decision.
    // Keeping this out of the state initializer prevents React StrictMode's
    // development re-render from cancelling a valid email login.
    sessionStorage.removeItem('ae-compass-entry');
  }, []);

  useEffect(() => {
    document.documentElement.classList.toggle('dark', theme === 'dark');
    localStorage.setItem('ae-compass-theme', theme);
  }, [theme]);

  useEffect(() => {
    if (currentUser) recordVisit(currentUser);
  }, [currentUser?.id]);

  useEffect(() => {
    if (landingMode) {
      setAuthLoading(false);
      return;
    }
    let active = true;
    api.getAuthMe().then((identity) => {
      if (!active) return;
      // In local development the server has a convenience fallback identity
      // (Justine) so the shell can be previewed without SSO. Do not let that
      // fallback overwrite a profile the user explicitly selected by email
      // on the landing screen. App Foundry/SSO identities still take priority.
      if (identity.source === 'local-development-fallback' && getSessionId()) return;
      const identityProfile = profileFromIdentity(identity);
      if (identityProfile) {
        setProfiles((existing) => {
          const managed = existing.find((profile) => profile.active && (profile.subjectId === identityProfile.subjectId || profile.email.toLowerCase() === identityProfile.email.toLowerCase()));
          const effective = managed && managed.id !== 'profile-admin' ? { ...identityProfile, accessLevel: managed.accessLevel, accessScopes: managed.accessScopes, scopeValue: managed.scopeValue } : identityProfile;
          const withoutIdentity = existing.filter((profile) => profile.id !== effective.id || profile.id === 'profile-admin');
          return withoutIdentity.some((profile) => profile.id === effective.id) ? withoutIdentity : [...withoutIdentity, effective];
        });
        setSessionId(identityProfile.id);
        setSession(identityProfile.id);
      } else {
        clearSession();
        setSession(null);
      }
    }).catch(() => {
      clearSession();
      setSession(null);
    }).finally(() => { if (active) setAuthLoading(false); });
    return () => { active = false; };
  }, [landingMode]);

  useEffect(() => {
    if (currentUser?.role !== 'Admin') return;
    setRosterLoading(true);
    api.getRoster().then(setRoster).catch(() => setRoster([])).finally(() => setRosterLoading(false));
  }, [currentUser?.id, currentUser?.role]);

  if (window.location.pathname === '/vision') window.history.replaceState({}, '', '/compass');
  const login = (profile: AccessProfile) => {
    setProfiles((existing) => {
      const next = existing.some((entry) => entry.id === profile.id)
        ? existing.map((entry) => entry.id === profile.id ? { ...entry, ...profile } : entry)
        : [...existing, profile];
      saveProfiles(next);
      return next;
    });
    setSessionId(profile.id);
    setSession(profile.id);
  };
  if (landingMode) return <LoginScreen profiles={profiles} onLogin={(profile) => { window.history.replaceState({}, '', '/'); setLandingMode(false); login(profile); }} />;
  if (authLoading) return <div className="flex min-h-screen items-center justify-center bg-surface-secondary text-sm text-gray-500">Checking your company identity…</div>;
  if (window.location.pathname === '/compass') {
    if (!currentUser) return <LoginScreen profiles={profiles} onLogin={login} />;
    return <AECompassVision viewerName={currentUser.name} dark={theme === 'dark'} toggleTheme={() => setTheme(theme === 'light' ? 'dark' : 'light')} onLogout={() => { clearSession(); setSession(null); window.location.href = '/?landing=1'; }} />;
  }
  if (!currentUser) return <LoginScreen profiles={profiles} onLogin={login} />;

  const updateProfiles = (next: AccessProfile[]) => { setProfiles(next); saveProfiles(next); };
  const logout = () => { clearSession(); setSession(null); window.location.href = '/?landing=1'; };

  return <div className={`app-shell flex h-screen overflow-hidden bg-[#f7f8f5] text-[#17221c] dark:bg-[#111712] dark:text-[#f1f5ec] ${theme === 'dark' ? 'theme-dark' : 'theme-light'}`}>
    <Sidebar activeTab="admin" setActiveTab={() => undefined} theme={theme} toggleTheme={() => setTheme(theme === 'light' ? 'dark' : 'light')} currentUser={currentUser} onLogout={logout} adminSection={adminSection} setAdminSection={setAdminSection} />
    <main className="flex-1 overflow-y-auto">
      <header className="flex items-center justify-end border-b border-[#e6ebe4] bg-white/80 px-6 py-4 backdrop-blur dark:border-[#29352b] dark:bg-[#111712]/80 sm:px-10"><div className="flex items-center gap-3"><button onClick={() => setTheme(theme === 'light' ? 'dark' : 'light')} className="rounded-lg p-2 text-[#829087] hover:bg-[#f1f4ef] dark:hover:bg-[#223024]" aria-label={`Switch to ${theme === 'light' ? 'dark' : 'light'} mode`}>{theme === 'light' ? <Moon className="h-4 w-4" /> : <Sun className="h-4 w-4" />}</button><div className="h-6 w-px bg-[#e6ebe4] dark:bg-[#29352b]" /><div className="flex items-center gap-2"><div className="flex h-7 w-7 items-center justify-center rounded-full bg-[#d9f579] text-[10px] font-bold text-[#25402c]">JM</div><span className="text-xs font-semibold">{currentUser.name}</span></div><div className="h-6 w-px bg-[#e6ebe4] dark:bg-[#29352b]" /><button onClick={logout} className="flex items-center gap-1.5 rounded-lg px-2 py-2 text-xs font-semibold text-[#829087] transition-colors hover:bg-[#f1f4ef] hover:text-[#2e603d] dark:text-[#9eafa0] dark:hover:bg-[#223024] dark:hover:text-[#d9f579]"><LogOut className="h-3.5 w-3.5" />Log out</button></div></header>
      <div className="p-6">{rosterLoading ? <div className="flex h-full items-center justify-center text-sm text-[#78847b]"><Loader2 className="mr-2 h-4 w-4 animate-spin" />Loading Workday directory…</div> : <AdminPanel currentUser={currentUser} profiles={profiles} roster={roster} onProfilesChange={updateProfiles} activeSection={adminSection} setActiveSection={setAdminSection} />}</div>
    </main>
  </div>;
}
