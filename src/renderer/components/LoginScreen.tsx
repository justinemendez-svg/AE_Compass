import { useEffect, useMemo, useState } from 'react';
import { Compass, Lock, AlertCircle, ArrowRight } from 'lucide-react';
import { AccessProfile, authenticate } from '../auth';
import { api, DirectoryPerson, RosterAE } from '../data/api';

interface Props { profiles: AccessProfile[]; onLogin: (profile: AccessProfile) => void; }

export default function LoginScreen({ profiles, onLogin }: Props) {
  const [adminPassword, setAdminPassword] = useState('');
  const [error, setError] = useState('');
  const [showAdmin, setShowAdmin] = useState(false);
  const [showProfileAuth, setShowProfileAuth] = useState(false);
  const [profileSearch, setProfileSearch] = useState('');
  const [roster, setRoster] = useState<RosterAE[]>([]);
  const [directory, setDirectory] = useState<DirectoryPerson[]>([]);
  const [loadingProfiles, setLoadingProfiles] = useState(false);
  const [profileError, setProfileError] = useState('');

  useEffect(() => {
    if (!showProfileAuth || roster.length) return;
    setLoadingProfiles(true);
    api.getRoster().then(setRoster).catch(() => setError('Could not load the local Workday profile directory.'))
      .finally(() => setLoadingProfiles(false));
  }, [showProfileAuth, roster.length]);

  useEffect(() => {
    if (!showProfileAuth || directory.length) return;
    api.getDirectory().then(setDirectory).catch(() => setDirectory([]));
  }, [showProfileAuth, directory.length]);

  const profileChoices = useMemo(() => {
    const term = profileSearch.trim().toLowerCase();
    const configured = profiles.filter((profile) => profile.active && (profile.role === 'Admin' || profile.subjectId));
    const fromRoster: AccessProfile[] = roster.map((person) => ({
      id: `workday-${person.user_id}`,
      name: person.ae_name,
      email: person.email || `${person.ae_name.toLowerCase().replace(/[^a-z0-9]+/g, '.')}@zendesk.com`,
      password: '', role: 'AE', scopeValue: person.user_id, active: true,
      accessLevel: 'scoped', subjectId: person.user_id, accessScopes: [],
    }));
    const fromDirectory: AccessProfile[] = directory.map((person) => {
      const role = (['AE', 'FLM', 'Director', 'RVP', 'SVP'].includes(person.source) ? person.source : 'GTM') as AccessProfile['role'];
      return {
        id: `workday-${person.id}`, name: person.name, email: person.email,
        password: '', role, scopeValue: person.id, active: true,
        accessLevel: 'scoped', subjectId: person.id, accessScopes: [],
      };
    });
    const all = [...configured,
      ...fromRoster.filter((person) => !configured.some((entry) => entry.subjectId === person.subjectId)),
      ...fromDirectory.filter((person) => !configured.some((entry) => entry.subjectId === person.subjectId) && !fromRoster.some((entry) => entry.subjectId === person.subjectId)),
    ];
    return all.filter((profile) => !term || `${profile.name} ${profile.email}`.toLowerCase().includes(term)).slice(0, 10);
  }, [profiles, roster, directory, profileSearch]);

  const openSales = () => {
    setProfileSearch('');
    setProfileError('');
    setShowProfileAuth(true);
  };

  const chooseProfile = (profile: AccessProfile) => {
    setShowProfileAuth(false);
    setError('');
    onLogin(profile);
    window.location.href = '/compass';
  };

  const authenticateWorkEmail = () => {
    const email = profileSearch.trim().toLowerCase();
    if (!email || !email.includes('@')) {
      setProfileError('Enter your work email to continue.');
      return;
    }
    // Local-only escape hatch for the current preview when the mock API is
    // being served by an older process. Production relies on App Foundry's
    // X-Forwarded-Email identity and never accepts a typed email.
    if (import.meta.env.DEV && email === 'justine.mendez@zendesk.com') {
      const localAdmin = profiles.find((profile) => profile.id === 'profile-admin' && profile.active);
      if (localAdmin) {
        setProfileError('');
        chooseProfile({ ...localAdmin, email });
        return;
      }
    }
    const match = profileChoices.find((profile) => profile.email.toLowerCase() === email);
    if (!match) {
      setProfileError('We could not authenticate this company session.');
      return;
    }
    setProfileError('');
    chooseProfile(match);
  };

  const openAdmin = () => {
    const profile = authenticate(profiles, '', adminPassword);
    if (!profile) { setError('Incorrect Admin password.'); return; }
    setError(''); onLogin(profile);
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-surface-secondary p-6">
      <div className="w-full max-w-md overflow-hidden rounded-2xl border border-gray-100 bg-white shadow-elevated">
        <div className="bg-accent-fern px-8 pb-8 pt-9 text-white">
          <div className="brand-mark mb-5"><Compass className="h-4 w-4" /></div>
          <p className="text-[10px] font-bold uppercase tracking-[0.2em] text-accent-matcha">AE Compass</p>
          <h1 className="mt-2 text-2xl font-semibold tracking-tight">Find your next right move.</h1>
          <p className="mt-2 text-sm text-white/60">Your performance, your path, your scope.</p>
        </div>
        <div className="space-y-4 p-8">
          <button onClick={openSales} className="group flex w-full items-center justify-between rounded-2xl border border-accent-cactus/40 bg-zd-green-50 px-5 py-5 text-left transition-all hover:-translate-y-0.5 hover:border-accent-shamrock hover:shadow-card">
            <span className="flex items-center gap-4"><span className="flex h-11 w-11 items-center justify-center rounded-xl bg-accent-matcha text-accent-fern"><Compass className="h-5 w-5" /></span><span><span className="block text-base font-bold text-accent-fern">Enter Compass</span><span className="mt-1 block text-xs text-accent-shamrock/70">Open your performance view using your company profile.</span></span></span><ArrowRight className="h-5 w-5 text-accent-shamrock transition-transform group-hover:translate-x-1" />
          </button>
          <div className="pt-1 text-center">
            {!showAdmin ? <button onClick={() => { setShowAdmin(true); setError(''); }} className="text-[11px] font-medium text-gray-400 underline decoration-gray-300 underline-offset-2 transition-colors hover:text-accent-shamrock">Admin page</button> : <div className="mx-auto max-w-xs rounded-xl border border-gray-100 bg-gray-50/70 p-3 text-left"><div className="mb-2 flex items-center gap-2 text-xs font-semibold text-gray-700"><Lock className="h-3.5 w-3.5 text-accent-shamrock" /> Admin page</div><div className="flex gap-2"><input value={adminPassword} onChange={(e) => setAdminPassword(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && openAdmin()} placeholder="Password" type="password" className="min-w-0 flex-1 rounded-lg border border-gray-200 bg-white px-3 py-2 text-xs focus:border-accent-shamrock focus:outline-none focus:ring-2 focus:ring-accent-shamrock/20" /><button onClick={openAdmin} className="rounded-lg bg-accent-shamrock px-3 py-2 text-xs font-semibold text-white hover:bg-accent-fern">Open</button></div></div>}
          </div>
          {error && <div className="flex items-center gap-2 text-xs text-red-600"><AlertCircle className="h-3.5 w-3.5" />{error}</div>}
          <p className="pt-1 text-center text-[10px] leading-relaxed text-gray-400">Compass checks your company profile first, then follows the access path assigned to you.</p>
        </div>
      </div>
      {showProfileAuth && <div className="fixed inset-0 z-50 flex items-center justify-center bg-accent-fern/30 p-6 backdrop-blur-sm" onMouseDown={(event) => { if (event.target === event.currentTarget) setShowProfileAuth(false); }}>
        <div className="w-full max-w-md rounded-2xl border border-accent-cactus/40 bg-white p-6 shadow-elevated">
          <div className="flex items-start gap-3"><div className="flex h-10 w-10 items-center justify-center rounded-xl bg-accent-matcha text-accent-fern"><Compass className="h-5 w-5" /></div><div><h2 className="text-base font-bold text-accent-fern">Authenticate your profile</h2><p className="mt-1 text-xs leading-relaxed text-gray-500">Your company sign-in will supply your identity. Compass will never show a directory of other people’s profiles.</p></div></div>
          <div className="mt-5 flex gap-2"><input autoFocus value={profileSearch} onChange={(event) => { setProfileSearch(event.target.value); setProfileError(''); }} onKeyDown={(event) => event.key === 'Enter' && authenticateWorkEmail()} placeholder="your.name@zendesk.com" type="email" className="min-w-0 flex-1 rounded-lg border border-gray-200 px-3 py-2.5 text-sm focus:border-accent-shamrock focus:outline-none focus:ring-2 focus:ring-accent-shamrock/20" /><button onClick={authenticateWorkEmail} disabled={loadingProfiles} className="rounded-lg bg-accent-shamrock px-4 py-2 text-xs font-semibold text-white hover:bg-accent-fern disabled:opacity-50">{loadingProfiles ? 'Reading…' : 'Continue'}</button></div>
          {profileError && <p className="mt-2 flex items-center gap-1.5 text-[11px] text-red-600"><AlertCircle className="h-3 w-3" />{profileError}</p>}
          <div className="mt-4 rounded-lg bg-zd-green-50 px-3 py-3 text-[10px] leading-relaxed text-gray-500"><span className="font-semibold text-accent-fern">What Compass reads:</span> your authenticated Workday profile, manager, and hierarchy path. It then limits the dashboard to the AEs inside your permitted scope.</div>
          <p className="mt-3 text-center text-[10px] leading-relaxed text-gray-400">Local preview only: email lookup is a temporary stand-in until Zendesk/SSO is connected. It is not a production authentication method.</p>
          <div className="mt-4 flex items-center justify-between border-t border-gray-100 pt-4"><p className="text-[10px] text-gray-400">No other profiles are displayed</p><button onClick={() => setShowProfileAuth(false)} className="rounded-lg border border-gray-200 px-3 py-2 text-xs font-semibold text-gray-600">Cancel</button></div>
        </div>
      </div>}
    </div>
  );
}
