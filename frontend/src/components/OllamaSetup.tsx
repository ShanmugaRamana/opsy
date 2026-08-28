import React, { useState } from 'react'
import type { LlmSuggestion } from './LlmSuggestions'

interface InstallingStatus {
  status: string;
  percentage: number;
  message: string;
}

interface OllamaSetupProps {
  model: LlmSuggestion;
  allModels: LlmSuggestion[];
  onBack: () => void;
  onConfirm: (modelName: string) => void;
  onCancel: () => void;
  installingStatus: InstallingStatus | null;
}

const ALL_AVAILABLE_MODELS: LlmSuggestion[] = [
  {
    name: "Qwen 2.5 0.5B (Q4_K_M)",
    size: "0.39 GB download size",
    description: "Extremely small model optimized to run on devices with very limited memory. Fast CPU execution.",
    gpu_accel: "Supported (CPU Fallback available)"
  },
  {
    name: "Llama 3.2 1B (Q4_K_M)",
    size: "0.78 GB download size",
    description: "Meta's highly optimized small model, perfect for summarization and low-resource tasks.",
    gpu_accel: "Supported (CPU Fallback available)"
  },
  {
    name: "Qwen 2.5 1.5B (Q4_K_M)",
    size: "1.15 GB download size",
    description: "A great balance of minimal footprint and basic text reasoning capabilities.",
    gpu_accel: "Supported (CPU Fallback available)"
  },
  {
    name: "SmolLM2 1.7B (Q4_K_M)",
    size: "1.20 GB download size",
    description: "High-quality small model trained on highly curated educational data.",
    gpu_accel: "Supported (CPU Fallback available)"
  },
  {
    name: "Gemma 2 2B (Q4_K_M)",
    size: "1.65 GB download size",
    description: "Google's highly efficient open model with strong reasoning, logic, and safety features.",
    gpu_accel: "Supported (CPU Fallback available)"
  },
  {
    name: "Llama 3.2 3B (Q4_K_M)",
    size: "2.00 GB download size",
    description: "Meta's state-of-the-art lightweight model for general reasoning, writing, and instructions.",
    gpu_accel: "Supported (CPU Fallback available)"
  },
  {
    name: "Qwen 2.5 3B (Q4_K_M)",
    size: "2.20 GB download size",
    description: "A powerful multilingual model with solid coding capabilities and conversational skills.",
    gpu_accel: "Supported (CPU Fallback available)"
  },
  {
    name: "Phi 3.5 Mini (3.8B)",
    size: "2.40 GB download size",
    description: "Microsoft's small language model with outstanding coding, logic, and mathematics capabilities.",
    gpu_accel: "Supported (CPU Fallback available)"
  },
  {
    name: "Mistral 7B (Q4_K_M)",
    size: "4.10 GB download size",
    description: "A classic high-performance 7B parameter model with highly balanced general capability.",
    gpu_accel: "Supported (CPU Fallback available)"
  },
  {
    name: "Qwen 2.5 7B (Q4_K_M)",
    size: "4.70 GB download size",
    description: "Exceptional multilingual capabilities, strong tool usage, and general coding logic.",
    gpu_accel: "Supported (CPU Fallback available)"
  },
  {
    name: "Llama 3 8B (Q4_K_M)",
    size: "4.70 GB download size",
    description: "Meta's standard model for conversations, coding helper, and complex instructions.",
    gpu_accel: "Supported (CPU Fallback available)"
  },
  {
    name: "Gemma 2 9B (Q4_K_M)",
    size: "5.40 GB download size",
    description: "Highly rated 9B model that matches or outperforms many larger configurations.",
    gpu_accel: "Supported (CPU Fallback available)"
  },
  {
    name: "Mistral Nemo 12B (Q4_K_M)",
    size: "7.10 GB download size",
    description: "Co-developed with NVIDIA. Features large 128k context support and strong translation.",
    gpu_accel: "Supported (CPU Fallback available)"
  },
  {
    name: "Qwen 2.5 14B (Q4_K_M)",
    size: "9.00 GB download size",
    description: "Excellent intermediate option offering complex multi-step reasoning and deep knowledge.",
    gpu_accel: "Supported (CPU Fallback available)"
  },
  {
    name: "Codestral 22B (Q4_K_M)",
    size: "13.50 GB download size",
    description: "Mistral's highly specialized model optimized specifically for coding in 80+ languages.",
    gpu_accel: "Supported (CPU Fallback available)"
  },
  {
    name: "Command R 35B (Q4_K_M)",
    size: "20.00 GB download size",
    description: "Cohere's business model optimized for Retrieval Augmented Generation (RAG) and tool usage.",
    gpu_accel: "Supported (CPU Fallback available)"
  },
  {
    name: "Mixtral 8x7B (Q4_K_M)",
    size: "26.40 GB download size",
    description: "High-quality Mixture of Experts (MoE) model with fast inference times for its scale.",
    gpu_accel: "Supported (CPU Fallback available)"
  },
  {
    name: "Llama 3.3 70B (Q4_K_M)",
    size: "42.50 GB download size",
    description: "Meta's flagship SOTA model. Matches top commercial APIs in reasoning and task automation.",
    gpu_accel: "Supported (CPU Fallback available)"
  },
  {
    name: "Qwen 2.5 72B (Q4_K_M)",
    size: "47.00 GB download size",
    description: "Top-tier open-weight model with exceptional coding skills and mathematical logic.",
    gpu_accel: "Supported (CPU Fallback available)"
  },
  {
    name: "Command R+ 104B (Q4_K_M)",
    size: "60.00 GB download size",
    description: "Massive scale model designed for multi-step agents and advanced corporate automation.",
    gpu_accel: "Supported (CPU Fallback available)"
  }
]

export const OllamaSetup: React.FC<OllamaSetupProps> = ({
  model,
  allModels,
  onBack,
  onConfirm,
  onCancel,
  installingStatus
}) => {
  const [selectedModelName, setSelectedModelName] = useState(model.name)

  const currentModel = ALL_AVAILABLE_MODELS.find(m => m.name === selectedModelName) || model

  // Grab custom acceleration status from user specific recommendations if there is a match
  const recommendedMatch = allModels.find(m => m.name === currentModel.name)
  const gpuAccelDisplay = recommendedMatch ? recommendedMatch.gpu_accel : model.gpu_accel

  if (installingStatus) {
    const isInstalling = installingStatus.status === 'installing';
    const isDownloading = installingStatus.status === 'downloading';
    
    return (
      <div className="flex flex-col items-center flex-grow py-8 px-4 w-full max-w-2xl text-left">
        <div className="bg-zinc-900/50 border border-zinc-850 rounded-xl p-8 w-full shadow-2xl backdrop-blur-md transition-all duration-300">
          <span className="text-[10px] text-purple-400 uppercase font-bold tracking-wider">
            {isInstalling ? "System Setup" : isDownloading ? "Downloading Model" : "Processing"}
          </span>
          <h2 className="text-2xl font-bold text-white mt-1 mb-6">
            {isInstalling ? "Installing Ollama Framework..." : `Pulling ${currentModel.name}`}
          </h2>

          <div className="space-y-6">
            {/* Progress status */}
            <div className="flex justify-between items-center text-sm font-semibold">
              <span className="text-zinc-300">{installingStatus.status.toUpperCase()}</span>
              <span className="text-purple-400">{installingStatus.percentage}%</span>
            </div>

            {/* Progress bar */}
            <div className="w-full bg-zinc-950 border border-zinc-850 rounded-full h-3.5 overflow-hidden">
              <div
                className="bg-gradient-to-r from-purple-600 to-indigo-500 h-full transition-all duration-300 rounded-full"
                style={{ width: `${installingStatus.percentage}%` }}
              />
            </div>

            {/* Real-time details console output */}
            <div className="bg-zinc-950 border border-zinc-850 rounded-lg p-4 font-mono text-[11px] text-zinc-400 min-h-[80px] break-all max-h-[140px] overflow-y-auto">
              <span className="text-purple-500 font-bold mr-1">$</span>
              {installingStatus.message}
            </div>

            {/* Cancel Button */}
            <div className="mt-8 flex justify-end">
              <button
                onClick={onCancel}
                className="bg-red-950/20 hover:bg-red-900/30 text-red-400 border border-red-500/20 rounded-lg px-6 py-2.5 font-semibold text-sm active:scale-[0.98] transition-all"
              >
                Cancel Download
              </button>
            </div>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="flex flex-col items-center flex-grow py-8 px-4 w-full max-w-2xl text-left">
      {/* Back button */}
      <button
        onClick={onBack}
        className="text-zinc-400 hover:text-white flex items-center gap-2 text-sm font-medium transition-colors mb-6"
      >
        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M15 19l-7-7 7-7" />
        </svg>
        Back to Model Recommendations
      </button>

      <div className="bg-zinc-900/50 border border-zinc-850 rounded-xl p-8 w-full shadow-2xl backdrop-blur-md transition-all duration-300">
        {/* Header card with selector */}
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-6 pb-6 border-b border-zinc-850 mb-6">
          <div className="w-full">
            <span className="text-[10px] text-purple-400 uppercase font-bold tracking-wider">Setup Guide</span>
            
            {/* Dropdown Selector */}
            <div className="mt-2 w-full max-w-md">
              <label className="text-[10px] text-zinc-500 uppercase font-bold tracking-wider block mb-1.5">
                Model Selector (Low to High Specs)
              </label>
              <select
                value={selectedModelName}
                onChange={(e) => setSelectedModelName(e.target.value)}
                className="w-full bg-zinc-950 border border-zinc-800 rounded-lg p-3 text-zinc-300 text-sm focus:border-purple-500 outline-none transition-all font-semibold"
              >
                {ALL_AVAILABLE_MODELS.map((m) => (
                  <option key={m.name} value={m.name}>
                    {m.name === model.name ? `${m.name} [${m.size}] (Recommended)` : `${m.name} [${m.size}]`}
                  </option>
                ))}
              </select>
            </div>
            
            <p className="text-zinc-400 text-xs mt-3">
              Size: <span className="text-zinc-300 font-medium">{currentModel.size}</span>
            </p>
          </div>
          
          <div className="bg-purple-950/20 text-purple-400 px-4 py-2 rounded-lg border border-purple-500/20 text-xs font-semibold self-start md:self-auto shrink-0">
            {gpuAccelDisplay}
          </div>
        </div>

        {/* Confirm Action */}
        <div className="mt-8 flex justify-end">
          <button
            onClick={() => onConfirm(selectedModelName)}
            className="bg-purple-600 hover:bg-purple-500 text-white rounded-lg px-8 py-3 font-semibold text-base shadow-lg shadow-purple-950/20 active:scale-[0.98] transition-all"
          >
            Confirm
          </button>
        </div>
      </div>
    </div>
  )
}
