import React from 'react'

export interface ChatSession {
  id: string;
  title: string;
  created_at: string;
}

interface SidebarProps {
  onNavigate: (page: 'home' | 'recommendations' | 'byok' | 'dashboard') => void;
  username: string;
  isOpen: boolean;
  onToggle: () => void;
  onNewChat?: () => void;
  chatSessions?: ChatSession[];
  activeSessionId?: string;
  onSelectSession?: (sessionId: string) => void;
}

export const Sidebar: React.FC<SidebarProps> = ({
  onNavigate,
  username,
  isOpen,
  onToggle,
  onNewChat,
  chatSessions = [],
  activeSessionId,
  onSelectSession,
}) => {
  const handleStartNewChat = () => {
    onNavigate('home');
    if (onNewChat) {
      onNewChat();
    }
  };

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

          {/* New Chat Quick Button */}
          <div className="p-3 w-full flex justify-center mt-2">
            <button
              onClick={handleStartNewChat}
              className="w-10 h-10 rounded-xl bg-purple-600/20 hover:bg-purple-600/30 border border-purple-500/30 text-purple-300 flex items-center justify-center transition-all shadow-sm active:scale-95"
              title="New Chat"
            >
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M12 4v16m8-8H4" />
              </svg>
            </button>
          </div>
        </div>

        {/* User Info Footer (Only circle with green dot badge) */}
        <div className="relative">
          <div className="w-8 h-8 rounded-full bg-zinc-900 border border-zinc-800 flex items-center justify-center text-xs font-black text-purple-400 uppercase shadow-inner" title={`Logged in as ${username}`}>
            {username ? username.slice(0, 2) : 'Us'}
          </div>
          <div className="absolute -bottom-0.5 -right-0.5 w-2.5 h-2.5 rounded-full bg-emerald-500 border-2 border-zinc-950 animate-pulse shadow-sm shadow-emerald-500/50" />
        </div>
      </div>
    );
  }

  // Expanded Sidebar View
  return (
    <div className="h-screen w-64 flex flex-col justify-between border-r border-zinc-900 bg-zinc-950/45 backdrop-blur-xl shrink-0 transition-all duration-300 overflow-hidden">
      <div className="flex flex-col w-64 flex-1 min-h-0">
        {/* Header containing Toggle & Brand Name */}
        <div className="p-4 flex items-center justify-between border-b border-zinc-900/60 h-16 shrink-0 animate-fadeIn">
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

        {/* New Chat Button */}
        <div className="p-4 pb-2 shrink-0">
          <button
            onClick={handleStartNewChat}
            className="w-full flex items-center justify-center gap-2 rounded-xl bg-purple-600 hover:bg-purple-500 text-white px-4 py-2.5 text-xs font-bold uppercase tracking-wider transition-all shadow-md shadow-purple-950/40 active:scale-[0.98]"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2.5" d="M12 4v16m8-8H4" />
            </svg>
            <span>New Chat</span>
          </button>
        </div>

        {/* Chat History Section */}
        <div className="flex-1 overflow-y-auto px-4 py-2 min-h-0 space-y-1">
          <div className="px-2 py-1 text-[11px] font-bold uppercase tracking-wider text-zinc-500 select-none">
            Recent Chats
          </div>
          {chatSessions.length === 0 ? (
            <div className="px-3 py-4 text-center text-xs text-zinc-600">
              No recent chats
            </div>
          ) : (
            chatSessions.map((chat) => (
              <button
                key={chat.id}
                onClick={() => {
                  if (onSelectSession) {
                    onSelectSession(chat.id);
                  }
                  onNavigate('home');
                }}
                className={`w-full flex items-center gap-2.5 px-3 py-2 rounded-lg text-left text-xs transition-all group ${
                  activeSessionId === chat.id
                    ? 'bg-zinc-900/80 text-purple-300 border border-purple-500/30'
                    : 'text-zinc-400 hover:text-zinc-200 hover:bg-zinc-900/30 border border-transparent'
                }`}
              >
                <svg className="w-3.5 h-3.5 text-zinc-500 group-hover:text-purple-400 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
                </svg>
                <span className="truncate flex-1">{chat.title}</span>
              </button>
            ))
          )}
        </div>
      </div>

      {/* User Info Footer */}
      <div className="p-4 border-t border-zinc-900/60 w-64 shrink-0 animate-fadeIn">
        <div className="px-3.5 py-3 flex items-center justify-between bg-zinc-900/15 border border-zinc-900/35 rounded-xl select-none">
          <div className="flex items-center gap-3.5 min-w-0">
            <div className="w-8 h-8 rounded-full bg-zinc-900 border border-zinc-800 flex items-center justify-center text-xs font-black text-purple-400 uppercase shadow-inner shrink-0">
              {username ? username.slice(0, 2) : 'Us'}
            </div>
            <div className="min-w-0">
              <p className="text-xs font-bold text-white truncate capitalize">{username || 'User'}</p>
            </div>
          </div>
          <div className="flex items-center gap-1.5 shrink-0 ml-2">
            <div className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse shadow-sm shadow-emerald-500/50" />
          </div>
        </div>
      </div>
    </div>
  );
};
