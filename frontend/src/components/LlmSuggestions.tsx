import React, { useState } from 'react'

interface LlmSuggestion {
  name: string;
  size: string;
  description: string;
  gpu_accel: string;
}

interface LlmSuggestionsProps {
  suggestions: LlmSuggestion[];
  onGoToByok: () => void;
  onSelectModel: (model: LlmSuggestion) => void;
  hasApiKeyConfigured: boolean;
}

export type { LlmSuggestion };

export const LlmSuggestions: React.FC<LlmSuggestionsProps> = ({
  suggestions,
  onGoToByok,
  onSelectModel,
  hasApiKeyConfigured,
}) => {
  const [selected, setSelected] = useState<LlmSuggestion | null>(null)

  if (suggestions.length === 0) return null;

  return (
    <div className="w-full max-w-4xl mt-4 px-4 text-left">
      <div className="text-center mb-8">
        <h1 className="text-4xl md:text-5xl font-bold tracking-tight text-white mb-2">Recommended Local LLMs</h1>
        <p className="text-purple-400 font-medium text-lg">
          Best models for your hardware configuration
        </p>
      </div>

      <div className="border-b border-zinc-850 pb-3 mb-4 w-full">
        <h2 className="text-2xl font-semibold text-white">
          Recommended Local LLMs
        </h2>
      </div>

      <p className="text-zinc-400 text-sm mb-6">
        Based on your system specifications (especially RAM and GPU configurations), these are the best models to run locally. Select a model below to configure.
      </p>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6 w-full">
        {suggestions.map((model, idx) => {
          const isSelected = selected?.name === model.name;
          return (
            <div
              key={idx}
              onClick={() => setSelected(model)}
              className={`border rounded-xl p-6 flex flex-col justify-between hover:-translate-y-0.5 cursor-pointer transition-all duration-300 shadow-md ${
                isSelected
                  ? "bg-purple-950/15 border-purple-500 shadow-purple-950/20"
                  : "bg-zinc-900/30 border-zinc-850 hover:border-purple-900/40"
              }`}
            >
              <div>
                <div className="flex justify-between items-start gap-4 mb-3">
                  <h3 className={`font-bold text-lg leading-snug transition-colors ${
                    isSelected ? "text-purple-300" : "text-purple-400"
                  }`}>
                    {model.name}
                  </h3>
                  <span className="text-purple-300 bg-purple-900/20 text-[10px] uppercase font-bold tracking-wider px-2.5 py-1 rounded-md border border-purple-500/20 whitespace-nowrap">
                    {model.size}
                  </span>
                </div>
                <p className="text-zinc-400 text-sm leading-relaxed mb-4">
                  {model.description}
                </p>
              </div>

              <div className="pt-3 border-t border-zinc-850/50 flex items-center justify-between text-xs text-zinc-500">
                <span>GPU Acceleration</span>
                <span className={`font-semibold ${model.gpu_accel.includes('None') ? 'text-red-500' : 'text-green-500'}`}>
                  {model.gpu_accel}
                </span>
              </div>
            </div>
          )
        })}
      </div>

      {/* Navigation Buttons Row */}
      <div className="flex flex-col sm:flex-row justify-between items-center gap-4 mt-8 pt-6 border-t border-zinc-850">
        <button
          onClick={onGoToByok}
          className="w-full sm:w-auto text-xs bg-zinc-900 hover:bg-zinc-850 text-zinc-300 font-bold px-6 py-3.5 rounded-lg border border-zinc-800 transition-all active:scale-[0.98] flex items-center justify-center gap-2"
        >
          <span>🔑</span> {hasApiKeyConfigured ? "Manage API Key" : "Bring Your Own API Key"}
        </button>
        <button
          disabled={!selected}
          onClick={() => selected && onSelectModel(selected)}
          className={`w-full sm:w-auto px-8 py-3.5 rounded-lg font-bold text-xs uppercase tracking-wider transition-all shadow-lg active:scale-[0.98] ${
            selected
              ? "bg-purple-600 hover:bg-purple-500 text-white shadow-purple-950/30 cursor-pointer"
              : "bg-zinc-950 text-zinc-600 border border-zinc-850/40 cursor-not-allowed"
          }`}
        >
          Continue
        </button>
      </div>
    </div>
  )
}
