import React from 'react'

interface OnboardingProps {
  submitting: boolean;
  errorMsg: string;
  onOnboard: () => void;
}

export const Onboarding: React.FC<OnboardingProps> = ({ submitting, errorMsg, onOnboard }) => {
  return (
    <div className="flex flex-col items-center justify-center flex-grow py-8 px-4 w-full">
      <div className="text-center mb-8">
        <h1 className="text-5xl font-bold tracking-tight text-white mb-2">Opsy</h1>
      </div>

      <div className="bg-zinc-900/50 border border-zinc-850 rounded-xl p-8 max-w-md w-full shadow-2xl backdrop-blur-md transition-all duration-300 hover:-translate-y-1 hover:border-purple-900/40 text-center">
        <h2 className="text-2xl font-semibold text-white mb-4">Welcome! Let’s get you started</h2>
        <p className="text-zinc-400">Welcome! Let's get your workstation set up.</p>
        <p className="text-zinc-400 text-sm mb-6">
          Set things up once, and you’re good to go.
        </p>

        {errorMsg && <p className="text-red-500 text-sm mb-4">{errorMsg}</p>}

        <button
          onClick={onOnboard}
          className="w-full bg-purple-600 text-white rounded-lg py-3 font-semibold text-base shadow-lg shadow-purple-950/20 hover:bg-purple-500 active:scale-[0.98] transition-all disabled:bg-zinc-800 disabled:text-zinc-500 disabled:cursor-not-allowed disabled:shadow-none"
          disabled={submitting}
        >
          {submitting ? (
            <span className="flex items-center justify-center gap-2">
              <svg className="animate-spin h-5 w-5 text-white" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
              </svg>
              Scanning System Specs...
            </span>
          ) : (
            'Get Started'
          )}
        </button>
      </div>
    </div>
  )
}
