import React, { useState, useRef, useEffect } from 'react'

export interface Message {
  id: string;
  sender: 'user' | 'assistant';
  text: string;
  timestamp: string;
}

export interface ChatSession {
  id: string;
  title: string;
  created_at: string;
  messages: Message[];
}

interface HomeProps {
  currentSessionId?: string;
  onSessionUpdated?: (session: ChatSession) => void;
}

const API_BASE = 'http://localhost:8000';

export const Home: React.FC<HomeProps> = ({ currentSessionId, onSessionUpdated }) => {
  const [sessionId, setSessionId] = useState<string>(currentSessionId || '')
  const [messages, setMessages] = useState<Message[]>([])
  const [inputValue, setInputValue] = useState('')
  const [isTyping, setIsTyping] = useState(false)
  const messagesEndRef = useRef<HTMLDivElement>(null)

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }

  // Load session when currentSessionId prop changes
  useEffect(() => {
    if (currentSessionId) {
      setSessionId(currentSessionId)
      fetch(`${API_BASE}/chat/sessions/${currentSessionId}`)
        .then((res) => {
          if (!res.ok) throw new Error('Failed to load session');
          return res.json() as Promise<ChatSession>;
        })
        .then((session) => {
          setMessages(session.messages || []);
        })
        .catch(() => {
          // If session not found on server yet, keep empty
          setMessages([]);
        });
    } else {
      // Create or start fresh session
      setSessionId(`sess_${Date.now()}`);
      setMessages([]);
    }
  }, [currentSessionId])

  useEffect(() => {
    scrollToBottom()
  }, [messages, isTyping])

  const handleSend = async (e?: React.FormEvent) => {
    if (e) e.preventDefault()
    const trimmed = inputValue.trim()
    if (!trimmed || isTyping) return

    const activeSessId = sessionId || `sess_${Date.now()}`
    if (!sessionId) {
      setSessionId(activeSessId)
    }

    const userMessage: Message = {
      id: `msg_${Date.now()}`,
      sender: 'user',
      text: trimmed,
      timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
    }

    setMessages((prev) => [...prev, userMessage])
    setInputValue('')
    setIsTyping(true)

    try {
      const response = await fetch(`${API_BASE}/chat/sessions/${activeSessId}/messages`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text: trimmed }),
      })

      if (!response.ok) {
        throw new Error('Failed to get response from server')
      }

      const data = await response.json() as { session: ChatSession; reply: Message }
      setMessages(data.session.messages)
      if (onSessionUpdated) {
        onSessionUpdated(data.session)
      }
    } catch (err) {
      console.error('Chat error:', err)
      const fallbackReply: Message = {
        id: `msg_${Date.now() + 1}`,
        sender: 'assistant',
        text: `Error reaching LLM backend. Please check model configuration or connectivity.`,
        timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
      }
      setMessages((prev) => [...prev, fallbackReply])
    } finally {
      setIsTyping(false)
    }
  }

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  return (
    <div className="flex flex-col h-full w-full text-zinc-200 animate-fadeIn">
      {/* Message List */}
      <div className="flex-1 overflow-y-auto w-full px-4 sm:px-6 py-6">
        <div className="max-w-5xl mx-auto space-y-4">
          {messages.length === 0 ? (
            <div className="flex flex-col items-center justify-center min-h-[400px] text-center p-8 text-zinc-500 select-none">
              <div className="w-14 h-14 rounded-2xl bg-zinc-900/60 border border-zinc-800 flex items-center justify-center text-purple-400 mb-4 shadow-inner">
                <svg className="w-7 h-7" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.5" d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
                </svg>
              </div>
              <p className="text-base font-semibold text-zinc-300 mb-1">Start a conversation</p>
              <p className="text-xs text-zinc-500 max-w-md">
                Type your query below to begin chatting with your configured model.
              </p>
            </div>
          ) : (
            messages.map((msg) => (
              <div
                key={msg.id}
                className={`flex flex-col ${
                  msg.sender === 'user' ? 'items-end' : 'items-start'
                }`}
              >
                <div
                  className={`max-w-[85%] sm:max-w-[75%] rounded-2xl px-4 py-3 text-sm shadow-sm ${
                    msg.sender === 'user'
                      ? 'bg-purple-600 text-white rounded-br-sm'
                      : 'bg-zinc-900/80 border border-zinc-800 text-zinc-200 rounded-bl-sm'
                  }`}
                >
                  <p className="whitespace-pre-wrap leading-relaxed">{msg.text}</p>
                </div>
                <span className="text-[10px] text-zinc-600 mt-1 px-1">{msg.timestamp}</span>
              </div>
            ))
          )}

          {isTyping && (
            <div className="flex items-center gap-1.5 p-3 max-w-[80px] bg-zinc-900/80 border border-zinc-800 rounded-2xl rounded-bl-sm">
              <span className="w-1.5 h-1.5 bg-zinc-500 rounded-full animate-bounce [animation-delay:-0.3s]" />
              <span className="w-1.5 h-1.5 bg-zinc-500 rounded-full animate-bounce [animation-delay:-0.15s]" />
              <span className="w-1.5 h-1.5 bg-zinc-500 rounded-full animate-bounce" />
            </div>
          )}

          <div ref={messagesEndRef} />
        </div>
      </div>

      {/* Input Form */}
      <div className="p-4 sm:p-6 border-t border-zinc-900/80 bg-zinc-950/40 backdrop-blur-md shrink-0">
        <form onSubmit={handleSend} className="max-w-5xl mx-auto flex items-center">
          <div className="relative flex items-center w-full bg-zinc-900/70 border border-zinc-800 focus-within:border-purple-500/50 rounded-full transition-all pl-5 pr-2 py-1.5 shadow-lg shadow-black/40">
            <textarea
              value={inputValue}
              onChange={(e) => setInputValue(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Ask anything... (Press Enter to send, Shift+Enter for new line)"
              rows={1}
              className="w-full bg-transparent py-2.5 text-sm text-zinc-200 placeholder-zinc-500 focus:outline-none resize-none max-h-32 leading-relaxed"
            />
            <button
              type="submit"
              disabled={!inputValue.trim() || isTyping}
              className="h-10 w-10 flex items-center justify-center rounded-full bg-purple-600 hover:bg-purple-500 disabled:opacity-40 disabled:hover:bg-purple-600 text-white shadow-md shadow-purple-950/40 transition-all shrink-0 active:scale-95 ml-2 self-center"
              title="Send message"
            >
              <svg className="w-4 h-4 rotate-90" fill="currentColor" viewBox="0 0 20 20">
                <path d="M10.894 2.553a1 1 0 00-1.788 0l-7 14a1 1 0 001.169 1.409l5-1.429A1 1 0 009 15.571V11a1 1 0 112 0v4.571a1 1 0 00.725.962l5 1.428a1 1 0 001.17-1.408l-7-14z" />
              </svg>
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
