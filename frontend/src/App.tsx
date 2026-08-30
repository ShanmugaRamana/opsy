import { useEffect, useState } from 'react'
import './index.css'
import { Onboarding } from './components/Onboarding'
import type { SystemSpecs } from './components/SystemSpecification'
import { LlmSuggestions } from './components/LlmSuggestions'
import type { LlmSuggestion } from './components/LlmSuggestions'
import { ByokConfiguration } from './components/ByokConfiguration'
import { OllamaSetup } from './components/OllamaSetup'
import { SystemSpecification } from './components/SystemSpecification'
import { Home } from './components/Home'
import { Sidebar } from './components/layout/Sidebar'

const API_BASE = 'http://localhost:8000'

interface ApiKeyConfig {
  provider: string;
  key: string;
}

interface UserData {
  onboarded: boolean;
  username: string;
  system_specs: SystemSpecs | null;
  suggestions: LlmSuggestion[];
  api_key: ApiKeyConfig | null;
  active_model: string | null;
}

interface InstallingStatus {
  status: string;
  percentage: number;
  message: string;
}

function App() {
  const [loading, setLoading] = useState<boolean>(true)
  const [onboarded, setOnboarded] = useState<boolean>(false)
  const [username, setUsername] = useState<string>('')
  const [systemSpecs, setSystemSpecs] = useState<SystemSpecs | null>(null)
  const [suggestions, setSuggestions] = useState<LlmSuggestion[]>([])
  
  const [activePage, setActivePage] = useState<'recommendations' | 'byok' | 'ollama' | 'dashboard' | 'home'>('recommendations')
  const [selectedModel, setSelectedModel] = useState<LlmSuggestion | null>(null)
  const [apiKey, setApiKey] = useState<string>(() => localStorage.getItem("opsy_api_key") || "")
  const [provider, setProvider] = useState<string>(() => localStorage.getItem("opsy_api_provider") || "openai")
  const [activeModel, setActiveModel] = useState<string>('')

  const [submitting, setSubmitting] = useState<boolean>(false)
  const [errorMsg, setErrorMsg] = useState<string>('')
  const [sidebarOpen, setSidebarOpen] = useState<boolean>(true)

  // Real-time progress updates state
  const [installingStatus, setInstallingStatus] = useState<InstallingStatus | null>(null)
  const [activeEventSource, setActiveEventSource] = useState<EventSource | null>(null)

  // Check onboarding status on load
  useEffect(() => {
    fetch(`${API_BASE}/onboard/status`)
      .then((res) => {
        if (!res.ok) throw new Error('Could not fetch onboarding status')
        return res.json() as Promise<UserData>
      })
      .then((data) => {
        setOnboarded(data.onboarded)
        if (data.onboarded) {
          setUsername(data.username || '')
          setSystemSpecs(data.system_specs || null)
          setSuggestions(data.suggestions || [])
          
          if (data.api_key) {
            setApiKey(data.api_key.key)
            setProvider(data.api_key.provider)
            localStorage.setItem("opsy_api_key", data.api_key.key)
            localStorage.setItem("opsy_api_provider", data.api_key.provider)
          } else {
            setApiKey("")
          }

          if (data.active_model) {
            setActiveModel(data.active_model)
          } else {
            setActiveModel("")
          }

          // Route to home if fully setup
          if (data.api_key || data.active_model) {
            setActivePage('home')
          } else {
            setActivePage('recommendations')
          }
        }
        setLoading(false)
      })
      .catch((err) => {
        setErrorMsg(`Initialization Error: ${err.message}`)
        setLoading(false)
      })
  }, [])

  const handleOnboard = () => {
    setSubmitting(true)
    setErrorMsg('')

    fetch(`${API_BASE}/onboard/submit`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
    })
      .then((res) => {
        if (!res.ok) throw new Error('Onboarding onboarding request failed')
        return res.json() as Promise<UserData>
      })
      .then((data) => {
        setOnboarded(data.onboarded)
        setUsername(data.username || '')
        setSystemSpecs(data.system_specs || null)
        setSuggestions(data.suggestions || [])
        setSubmitting(false)
        setActivePage('recommendations')
      })
      .catch((err) => {
        setErrorMsg(`Onboarding Error: ${err.message}`)
        setSubmitting(false)
      })
  }

  const handleSaveApiKey = (newProvider: string, newKey: string) => {
    fetch(`${API_BASE}/onboard/api-key`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ provider: newProvider, key: newKey })
    })
      .then((res) => {
        if (!res.ok) throw new Error('Failed to save API key to backend')
        setApiKey(newKey)
        setProvider(newProvider)
        setActiveModel('') // reset local model since switched to cloud
        localStorage.setItem("opsy_api_key", newKey)
        localStorage.setItem("opsy_api_provider", newProvider)
        alert("API Key saved successfully!")
        setActivePage('home')
      })
      .catch((err) => {
        alert(`Error: ${err.message}`)
      })
  }

  const handleSelectModel = (model: LlmSuggestion) => {
    setSelectedModel(model)
    setActivePage('ollama')
  }

  const handleConfirmModel = (modelName: string) => {
    // Close any previous EventSource safely
    if (activeEventSource) {
      activeEventSource.close()
    }

    setInstallingStatus({
      status: 'checking',
      percentage: 0,
      message: 'Checking dependencies...'
    })

    const es = new EventSource(`${API_BASE}/onboard/run-model-stream?model=${encodeURIComponent(modelName)}`)
    setActiveEventSource(es)

    es.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data) as InstallingStatus
        setInstallingStatus(data)

        if (data.status === 'completed') {
          es.close()
          setActiveEventSource(null)
          setActiveModel(modelName)
          setApiKey('') // reset cloud BYOK since switched to local
          localStorage.removeItem("opsy_api_key")
          
          setTimeout(() => {
            setInstallingStatus(null)
            setActivePage('home')
          }, 2000)
        } else if (data.status === 'failed') {
          es.close()
          setActiveEventSource(null)
          alert(`Failed: ${data.message}`)
          setInstallingStatus(null)
        }
      } catch (err) {
        console.error("Failed to parse event:", err)
      }
    }

    es.onerror = (e) => {
      console.error("SSE connection error:", e)
      es.close()
      setActiveEventSource(null)
      setInstallingStatus(null)
      alert("Lost connection to installation service.")
    }
  }

  const handleCancelInstall = () => {
    if (activeEventSource) {
      activeEventSource.close()
      setActiveEventSource(null)
    }

    fetch(`${API_BASE}/onboard/cancel-run`, { method: 'POST' })
      .then(() => {
        setInstallingStatus(null)
      })
      .catch((err) => {
        console.error("Failed to cancel on backend:", err)
        setInstallingStatus(null)
      })
  }

  if (loading) {
    return (
      <div id="center" className="flex items-center justify-center min-h-screen bg-black">
        <div className="text-center">
          <h1 className="text-5xl font-bold tracking-tight text-white mb-4">Opsy</h1>
          <div className="text-purple-500 font-medium text-lg animate-pulse">
            Analyzing configuration...
          </div>
        </div>
      </div>
    )
  }

  if (!onboarded) {
    return (
      <div id="center" className="flex flex-col min-h-screen bg-black text-zinc-300">
        <Onboarding
          submitting={submitting}
          errorMsg={errorMsg}
          onOnboard={handleOnboard}
        />
      </div>
    )
  }

  return (
    <div className="flex h-screen w-full bg-black text-zinc-300 overflow-hidden">
      {/* Navigation Sidebar */}
      <Sidebar
        activePage={activePage === 'ollama' ? 'recommendations' : activePage}
        onNavigate={(page) => setActivePage(page)}
        username={username}
        isOpen={sidebarOpen}
        onToggle={() => setSidebarOpen(!sidebarOpen)}
      />

      {/* Content Canvas */}
      <div className={`flex-1 h-full flex flex-col items-center w-full relative ${
        activePage === 'home' ? 'p-0 overflow-hidden' : 'py-6 pb-24 px-4 overflow-y-auto'
      }`}>
        <div className={`w-full flex justify-center ${activePage === 'home' ? 'h-full' : ''}`}>
          {activePage === 'home' ? (
            <Home activeModel={activeModel} provider={provider} />
          ) : activePage === 'dashboard' ? (
            <SystemSpecification
              username={username}
              systemSpecs={systemSpecs}
              activeModel={activeModel}
              apiKey={apiKey}
              provider={provider}
              onChangeConfig={() => setActivePage('recommendations')}
            />
          ) : activePage === 'recommendations' ? (
            <LlmSuggestions
              suggestions={suggestions}
              onGoToByok={() => setActivePage('byok')}
              onSelectModel={handleSelectModel}
              hasApiKeyConfigured={!!apiKey}
            />
          ) : activePage === 'byok' ? (
            <ByokConfiguration
              initialApiKey={apiKey}
              initialProvider={provider}
              onBack={() => {
                setActivePage('recommendations')
              }}
              onSave={handleSaveApiKey}
            />
          ) : (
            selectedModel && (
              <OllamaSetup
                model={selectedModel}
                allModels={suggestions}
                onBack={() => {
                  setActivePage('recommendations')
                }}
                onConfirm={handleConfirmModel}
                onCancel={handleCancelInstall}
                installingStatus={installingStatus}
              />
            )
          )}
        </div>
      </div>
    </div>
  )
}

export default App
