import React, { useState } from 'react'

interface ByokConfigurationProps {
  initialApiKey: string;
  initialProvider: string;
  onBack: () => void;
  onSave: (provider: string, key: string) => void;
}

export const ByokConfiguration: React.FC<ByokConfigurationProps> = ({
  initialApiKey,
  initialProvider,
  onBack,
  onSave,
}) => {
  const [apiKey, setApiKey] = useState(initialApiKey)
  const [provider, setProvider] = useState(initialProvider)

  const handleSave = (e: React.FormEvent) => {
    e.preventDefault()
    onSave(provider, apiKey)
  }

  return (
    <div className="flex flex-col items-center justify-center flex-grow py-8 px-4 w-full max-w-xl">
      {/* Back button */}
      <div className="w-full flex justify-start mb-6">
        <button
          onClick={onBack}
          className="text-zinc-400 hover:text-white flex items-center gap-2 text-sm font-medium transition-colors"
        >
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M15 19l-7-7 7-7" />
          </svg>
          Back to Local Models
        </button>
      </div>

      <div className="bg-zinc-900/50 border border-zinc-850 rounded-xl p-8 w-full shadow-2xl backdrop-blur-md transition-all duration-300 hover:border-purple-900/40 text-left">
        <div className="flex items-center gap-3 mb-6">
          <span className="text-3xl">🔑</span>
          <div>
            <h2 className="text-2xl font-bold text-white">Bring Your Own API Key</h2>
            <p className="text-zinc-400 text-xs mt-1">Configure your cloud model API credentials</p>
          </div>
        </div>

        <p className="text-zinc-400 text-sm mb-6 leading-relaxed">
          If you want to use powerful cloud models (like GPT-4o, Claude 3.5 Sonnet, or Gemini 1.5 Pro) instead of running models locally, paste your provider API key below. Keys are stored locally on your machine.
        </p>

        <form onSubmit={handleSave} className="space-y-5">
          <div>
            <label className="text-[10px] text-zinc-500 uppercase font-bold tracking-wider block mb-1.5">
              Select Provider
            </label>
            <select
              value={provider}
              onChange={(e) => setProvider(e.target.value)}
              className="w-full bg-zinc-950 border border-zinc-800 rounded-lg p-3 text-zinc-300 text-sm focus:border-purple-500 outline-none transition-all"
            >
              <option value="openai">OpenAI</option>
              <option value="anthropic">Anthropic</option>
              <option value="gemini">Google Gemini</option>
            </select>
          </div>

          <div>
            <label className="text-[10px] text-zinc-500 uppercase font-bold tracking-wider block mb-1.5">
              API Key Credentials
            </label>
            <input
              type="password"
              placeholder="sk-..."
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              className="w-full bg-zinc-950 border border-zinc-800 rounded-lg p-3 text-zinc-300 text-sm focus:border-purple-500 outline-none transition-all"
            />
          </div>

          <button
            type="submit"
            className="w-full bg-purple-600 hover:bg-purple-500 text-white rounded-lg py-3 font-semibold text-base shadow-lg shadow-purple-950/20 active:scale-[0.98] transition-all"
          >
            Save Credentials
          </button>
        </form>
      </div>
    </div>
  )
}
