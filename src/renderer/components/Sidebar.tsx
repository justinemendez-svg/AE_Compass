import { BarChart3, GraduationCap, Compass, Settings, Eye, Upload } from 'lucide-react';
import { AccessProfile } from '../auth';
import type { AdminSection } from '../pages/AdminPanel';

interface SidebarProps {
  activeTab: 'dashboard' | 'development' | 'admin';
  setActiveTab: (tab: 'dashboard' | 'development' | 'admin') => void;
  theme: 'light' | 'dark';
  toggleTheme: () => void;
  currentUser: AccessProfile;
  onLogout: () => void;
  adminSection: AdminSection;
  setAdminSection: (section: AdminSection) => void;
}

export default function Sidebar({ activeTab, setActiveTab, theme, toggleTheme, currentUser, onLogout, adminSection, setAdminSection }: SidebarProps) {
  return (
    <aside className="app-sidebar w-[248px] shrink-0 border-r border-[#e6ebe4] bg-white text-[#17221c] dark:border-[#29352b] dark:bg-[#1a231c] dark:text-[#f1f5ec]">
      <div className="h-16 flex items-center px-5 border-b border-[#e6ebe4] dark:border-[#29352b]">
        <div className="flex items-center gap-2">
          <div className="brand-mark"><Compass className="w-4 h-4" /></div>
          <div>
            <span className="block font-bold text-sm tracking-tight">AE Compass</span>
            <span className="block text-[9px] font-semibold uppercase tracking-[0.16em] text-[#8a958b]">Find your next move</span>
          </div>
        </div>
      </div>

      <nav className="flex-1 p-3 space-y-1">
        {currentUser.role !== 'Admin' && <>
          <button
            onClick={() => setActiveTab('dashboard')}
            className={`sidebar-item w-full ${
              activeTab === 'dashboard' ? 'sidebar-item-active' : 'sidebar-item-inactive'
            }`}
          >
            <BarChart3 className="w-4 h-4" />
            Performance
          </button>
          <button
            onClick={() => setActiveTab('development')}
            className={`sidebar-item w-full ${
              activeTab === 'development' ? 'sidebar-item-active' : 'sidebar-item-inactive'
            }`}
          >
            <GraduationCap className="w-4 h-4" />
            Development
          </button>
        </>}
        {currentUser.role === 'Admin' && <div className="mt-2 space-y-1 border-t border-gray-100 pt-3">
          <button onClick={() => setAdminSection('access')} className={`sidebar-item w-full ${adminSection === 'access' ? 'sidebar-item-active' : 'sidebar-item-inactive'}`}><Settings className="w-4 h-4" />Access</button>
          <button onClick={() => setAdminSection('visits')} className={`sidebar-item w-full ${adminSection === 'visits' ? 'sidebar-item-active' : 'sidebar-item-inactive'}`}><Eye className="w-4 h-4" />Who visits the page</button>
          <button onClick={() => setAdminSection('data')} className={`sidebar-item w-full ${adminSection === 'data' ? 'sidebar-item-active' : 'sidebar-item-inactive'}`}><Upload className="w-4 h-4" />Data Management</button>
        </div>}
      </nav>

      <div className="p-3 border-t border-gray-100">
        <p className="text-[10px] text-gray-400 text-center mt-3">AE Compass v0.1 · local playground</p>
      </div>
    </aside>
  );
}
