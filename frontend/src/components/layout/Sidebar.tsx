import React from 'react'

interface SidebarProps {
  activePage: 'home' | 'recommendations' | 'byok' | 'dashboard';
  onNavigate: (page: 'home' | 'recommendations' | 'byok' | 'dashboard') => void;
  username: string;
  isOpen: boolean;
  onToggle: () => void;
}

export const Sidebar: React.FC<SidebarProps> = ({
  activePage,
  onNavigate,
  username,
  isOpen,
  onToggle,
}) => {
  // Collapsed Mini Sidebar View
  if (!isOpen) {
    return (
      <div className="h-screen w-16 flex flex-col justify-between items-center pb-4 border-r border-zinc-900 bg-zinc-950/45 backdrop-blur-xl shrink-0 transition-all duration-300">
        <div className="flex flex-col items-center w-full">
          {/* Header containing Toggle expand button */}
          <div className="flex items-center justify-center h-16 border-b border-zinc-900/60 w-full">
            <button
              onClick={onToggle}
              className="hover:bg-zinc-900/40 text-zinc-500 hover:text-zinc-300 p-2 rounded-lg border border-transparent hover:border-zinc-900/60 transition-all"
              title="Expand Sidebar"
            >
              <svg className="w-5 h-5 rotate-180" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M11 19l-7-7 7-7m8 14l-7-7 7-7" />
              </svg>
            </button>
          </div>

          {/* Navigation Items (Only Home icon) */}
          <nav className="p-3 space-y-1.5 mt-4 w-full flex justify-center">
            <button
              onClick={() => onNavigate('home')}
              className={`w-10 h-10 rounded-xl flex items-center justify-center transition-all relative active:scale-[0.98] ${
                activePage === 'home'
                  ? 'bg-purple-950/15 border border-purple-500/20 text-purple-300 shadow-md shadow-purple-950/5'
                  : 'text-zinc-400 hover:text-zinc-200 hover:bg-zinc-900/30'
              }`}
              title="Home"
            >
              {activePage === 'home' && (
                <div className="absolute left-0 w-1 h-5 bg-purple-500 rounded-r" />
              )}
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-6 0a1 1 0 001-1v-4a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 001 1m-6 0h6" />
              </svg>
            </button>
          </nav>
        </div>

        {/* User Info Footer (Only circle) */}
        <div className="w-8 h-8 rounded-full bg-zinc-900 border border-zinc-800 flex items-center justify-center text-xs font-black text-purple-400 uppercase shadow-inner" title={`Logged in as ${username}`}>
          {username ? username.slice(0, 2) : 'Us'}
        </div>
      </div>
    );
  }

  // Expanded Sidebar View
  return (
    <div className="h-screen w-64 flex flex-col justify-between border-r border-zinc-900 bg-zinc-950/45 backdrop-blur-xl shrink-0 transition-all duration-300 overflow-hidden">
      <div className="flex flex-col w-64">
        {/* Header containing Toggle & Brand Name */}
        <div className="p-4 flex items-center justify-between border-b border-zinc-900/60 h-16 animate-fadeIn">
          <span className="font-extrabold text-white text-base tracking-tight select-none">
            Opsy
          </span>
          
          {/* Collapse Button inside Sidebar */}
          <button
            onClick={onToggle}
            className="hover:bg-zinc-900/40 text-zinc-500 hover:text-zinc-300 p-2 rounded-lg border border-transparent hover:border-zinc-900/60 transition-all"
            title="Collapse Sidebar"
          >
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M11 19l-7-7 7-7m8 14l-7-7 7-7" />
            </svg>
          </button>
        </div>

        {/* Navigation Items (Only Home button) */}
        <nav className="p-4 space-y-1.5 mt-4">
          <button
            onClick={() => onNavigate('home')}
            className={`w-full flex items-center gap-3.5 rounded-xl px-4 py-3 font-semibold transition-all relative active:scale-[0.98] ${
              activePage === 'home'
                ? 'bg-purple-950/15 border border-purple-500/20 text-purple-300 shadow-md shadow-purple-950/5'
                : 'text-zinc-400 hover:text-zinc-200 hover:bg-zinc-900/30 border border-transparent'
            }`}
          >
            {activePage === 'home' && (
              <div className="absolute left-0 w-1.5 h-5 bg-purple-500 rounded-r" />
            )}
            <span className={`transition-colors shrink-0 ${activePage === 'home' ? 'text-purple-400' : 'text-zinc-500'}`}>
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-6 0a1 1 0 001-1v-4a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 001 1m-6 0h6" />
              </svg>
            </span>
            <span className="text-xs tracking-wider uppercase font-bold select-none">
              Home
            </span>
          </button>
        </nav>
      </div>

      {/* User Info Footer */}
      <div className="p-4 border-t border-zinc-900/60 w-64 animate-fadeIn">
        <div className="px-3.5 py-3 flex items-center gap-3.5 bg-zinc-900/15 border border-zinc-900/35 rounded-xl select-none">
          <div className="w-8 h-8 rounded-full bg-zinc-900 border border-zinc-800 flex items-center justify-center text-xs font-black text-purple-400 uppercase shadow-inner">
            {username ? username.slice(0, 2) : 'Us'}
          </div>
          <div className="min-w-0">
            <p className="text-xs font-bold text-white truncate capitalize">{username || 'User'}</p>
            
          </div>
        </div>
      </div>
    </div>
  )
}
