import React, { useState, useRef, useEffect } from 'react'

interface Message {
  id: string;
  sender: 'user' | 'assistant';
  text: string;
  timestamp: string;
}

interface HomeProps {
  activeModel?: string;
  provider?: string;
}

export const Home: React.FC<HomeProps> = ({ activeModel, provider }) => {
  const [messages, setMessages] = useState<Message[]>([])
  const [inputValue, setInputValue] = useState('')
  const [isTyping, setIsTyping] = useState(false)
  const messagesEndRef = useRef<HTMLDivElement>(null)

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }

  useEffect(() => {
    scrollToBottom()
  }, [messages, isTyping])

  const handleSend = (e?: React.FormEvent) => {
    if (e) e.preventDefault()
    const trimmed = inputValue.trim()
    if (!trimmed || isTyping) return

    const userMessage: Message = {
      id: Date.now().toString(),
      sender: 'user',
      text: trimmed,
      timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
    }

    setMessages((prev) => [...prev, userMessage])
    setInputValue('')
    setIsTyping(true)

    // Temporary placeholder assistant response
    setTimeout(() => {
      const assistantMessage: Message = {
        id: (Date.now() + 1).toString(),
        sender: 'assistant',
        text: `Echo response from ${activeModel || provider || 'Assistant'}: "${trimmed}"`,
        timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
      }
      setMessages((prev) => [...prev, assistantMessage])
      setIsTyping(false)
    }, 800)
  }

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  const modelLabel = activeModel
    ? activeModel
    : provider
    ? `${provider.toUpperCase()} API`
    : 'Local Assistant'

  return (
    <div className="flex flex-col h-full w-full text-zinc-200 animate-fadeIn">
      {/* Header / Active Model Pill */}
      <div className="flex items-center justify-between px-6 py-3.5 border-b border-zinc-900/80 bg-zinc-950/40 backdrop-blur-md shrink-0">
        <div className="flex items-center gap-2.5">
          <div className="w-2.5 h-2.5 rounded-full bg-emerald-500 animate-pulse shadow-sm shadow-emerald-500/50" />
          <span className="text-xs font-semibold text-zinc-400">Ready</span>
          <span className="text-xs text-zinc-600">•</span>
          <span className="text-xs font-medium text-purple-400 bg-purple-950/40 border border-purple-500/20 px-2.5 py-0.5 rounded-full">
            {modelLabel}
          </span>
        </div>
        <div className="text-xs text-zinc-500">
          Chat Space
        </div>
      </div>

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
        <form onSubmit={handleSend} className="max-w-5xl mx-auto flex items-end gap-3">
          <div className="relative flex-1 bg-zinc-900/60 border border-zinc-800 focus-within:border-purple-500/50 rounded-xl transition-all">
            <textarea
              value={inputValue}
              onChange={(e) => setInputValue(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Ask anything... (Press Enter to send, Shift+Enter for new line)"
              rows={1}
              className="w-full bg-transparent px-4 py-3.5 text-sm text-zinc-200 placeholder-zinc-500 focus:outline-none resize-none max-h-36 min-h-[48px]"
            />
          </div>
          <button
            type="submit"
            disabled={!inputValue.trim() || isTyping}
            className="h-12 w-12 flex items-center justify-center rounded-xl bg-purple-600 hover:bg-purple-500 disabled:opacity-40 disabled:hover:bg-purple-600 text-white shadow-lg shadow-purple-950/30 transition-all shrink-0 active:scale-95"
            title="Send message"
          >
            <svg className="w-5 h-5 rotate-90" fill="currentColor" viewBox="0 0 20 20">
              <path d="M10.894 2.553a1 1 0 00-1.788 0l-7 14a1 1 0 001.169 1.409l5-1.429A1 1 0 009 15.571V11a1 1 0 112 0v4.571a1 1 0 00.725.962l5 1.428a1 1 0 001.17-1.408l-7-14z" />
            </svg>
          </button>
        </form>
      </div>
    </div>
  )
}
