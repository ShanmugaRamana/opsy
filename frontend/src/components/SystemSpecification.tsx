import React from 'react'

interface CpuInfo {
  model_name: string;
  physical_cores: number;
  logical_cores: number;
}

interface MemoryInfo {
  total_gb: number;
  free_gb: number;
}

interface DiskInfo {
  total_gb: number;
  available_gb: number;
}

interface GpuInfo {
  name: string;
  vendor: string;
}

interface OsInfo {
  kernel: string;
  distro: string;
  uts_version: string;
}

interface SystemSpecs {
  cpu: CpuInfo;
  ram: MemoryInfo;
  disk: DiskInfo;
  gpus: GpuInfo[];
  os?: OsInfo;
}

export type { SystemSpecs, CpuInfo, MemoryInfo, DiskInfo, GpuInfo };

interface SystemSpecificationProps {
  username: string;
  systemSpecs: SystemSpecs | null;
  activeModel: string | null;
  apiKey: string | null;
  provider: string | null;
  onChangeConfig: () => void;
}

export const SystemSpecification: React.FC<SystemSpecificationProps> = ({
  username,
  systemSpecs,
  activeModel,
  apiKey,
  provider,
  onChangeConfig,
}) => {
  return (
    <div className="w-full max-w-4xl mt-4 px-4 text-left space-y-8 animate-fadeIn">
      {/* Welcome Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 pb-6 border-b border-zinc-850">
        <div>
          <h1 className="text-3xl font-extrabold text-white tracking-tight">Opsy System Specification</h1>
          <p className="text-zinc-400 text-sm mt-1">
            Welcome back, <span className="text-purple-400 font-semibold">{username}</span>. Your local copilot environment is ready.
          </p>
        </div>
        <button
          onClick={onChangeConfig}
          className="text-xs bg-zinc-900 hover:bg-zinc-850 text-zinc-300 font-bold px-5 py-2.5 rounded-lg border border-zinc-800 transition-all active:scale-[0.98]"
        >
          Change Model / Configuration
        </button>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
        {/* Active Configuration Card */}
        <div className="bg-zinc-900/40 border border-zinc-850 rounded-xl p-6 shadow-xl backdrop-blur-md flex flex-col justify-between">
          <div>
            <span className="text-[10px] text-purple-400 uppercase font-bold tracking-wider">Active Configuration</span>
            {activeModel ? (
              <div className="mt-4 space-y-4">
                <div className="flex items-center gap-3">
                  <div className="w-10 h-10 rounded-lg bg-purple-950/30 border border-purple-500/20 flex items-center justify-center text-xl shadow-inner">
                    💻
                  </div>
                  <div>
                    <h3 className="text-lg font-bold text-white leading-tight">{activeModel}</h3>
                    <p className="text-zinc-500 text-xs mt-0.5">Local Ollama Model</p>
                  </div>
                </div>
                <p className="text-zinc-400 text-xs leading-relaxed pt-2">
                  Your local workspace is configured to pull and run this model. It fits your physical hardware parameters perfectly.
                </p>
              </div>
            ) : apiKey ? (
              <div className="mt-4 space-y-4">
                <div className="flex items-center gap-3">
                  <div className="w-10 h-10 rounded-lg bg-indigo-950/30 border border-indigo-500/20 flex items-center justify-center text-xl shadow-inner">
                    🔑
                  </div>
                  <div>
                    <h3 className="text-lg font-bold text-white leading-tight capitalize">{provider} API</h3>
                    <p className="text-zinc-500 text-xs mt-0.5">Cloud Intelligence Connected</p>
                  </div>
                </div>
                <div className="bg-zinc-950 border border-zinc-850/50 rounded-lg p-3 font-mono text-xs text-zinc-500 flex justify-between items-center">
                  <span>Key:</span>
                  <span>••••••••{apiKey.slice(-4)}</span>
                </div>
              </div>
            ) : (
              <p className="text-zinc-500 text-sm mt-4">No active model configured yet.</p>
            )}
          </div>

          <div className="mt-6 pt-4 border-t border-zinc-850/50 flex items-center justify-between text-xs">
            <span className="text-zinc-500">Service Status</span>
            <span className="text-green-500 font-semibold flex items-center gap-1.5">
              <span className="w-2 h-2 rounded-full bg-green-500 animate-pulse"></span>
              Active
            </span>
          </div>
        </div>

        {/* System Specs Card */}
        <div className="bg-zinc-900/40 border border-zinc-850 rounded-xl p-6 shadow-xl backdrop-blur-md space-y-4">
          <div>
            <span className="text-[10px] text-purple-400 uppercase font-bold tracking-wider">Hardware Specifications</span>
            <h3 className="text-lg font-bold text-white mt-1">Resource Diagnostics</h3>
          </div>

          {systemSpecs ? (
            <div className="grid grid-cols-2 gap-4 text-xs">
              <div className="bg-zinc-950/50 border border-zinc-850/30 rounded-lg p-3 space-y-1">
                <span className="text-zinc-500 block uppercase tracking-wider text-[9px] font-bold">OS Platform</span>
                <span className="text-zinc-300 font-semibold truncate block">
                  {systemSpecs.os?.distro || "Linux"}
                </span>
                <span className="text-[10px] text-zinc-600 truncate block">
                  Kernel: {systemSpecs.os?.kernel || "Unknown"}
                </span>
              </div>

              <div className="bg-zinc-950/50 border border-zinc-850/30 rounded-lg p-3 space-y-1">
                <span className="text-zinc-500 block uppercase tracking-wider text-[9px] font-bold">System Memory</span>
                <span className="text-zinc-300 font-semibold block">
                  {systemSpecs.ram.total_gb.toFixed(1)} GB RAM
                </span>
                <span className="text-[10px] text-zinc-500 block">
                  {(systemSpecs.ram.total_gb - systemSpecs.ram.free_gb).toFixed(1)} GB used
                </span>
              </div>

              <div className="bg-zinc-950/50 border border-zinc-850/30 rounded-lg p-3 space-y-1 col-span-2">
                <span className="text-zinc-500 block uppercase tracking-wider text-[9px] font-bold">Processor (CPU)</span>
                <span className="text-zinc-300 font-semibold truncate block" title={systemSpecs.cpu.model_name}>
                  {systemSpecs.cpu.model_name}
                </span>
                <span className="text-[10px] text-zinc-500 block">
                  {systemSpecs.cpu.physical_cores} Cores / {systemSpecs.cpu.logical_cores} Threads
                </span>
              </div>

              {systemSpecs.gpus && systemSpecs.gpus.length > 0 && (
                <div className="bg-zinc-950/50 border border-zinc-850/30 rounded-lg p-3 space-y-1 col-span-2">
                  <span className="text-zinc-500 block uppercase tracking-wider text-[9px] font-bold">Graphics Card (GPU)</span>
                  <span className="text-zinc-300 font-semibold truncate block">
                    {systemSpecs.gpus[0].name}
                  </span>
                  <span className="text-[10px] text-purple-400 block font-medium">
                    Acceleration active ({systemSpecs.gpus[0].vendor})
                  </span>
                </div>
              )}
            </div>
          ) : (
            <p className="text-zinc-500 text-xs">No diagnostic data gathered.</p>
          )}
        </div>
      </div>
    </div>
  )
}
