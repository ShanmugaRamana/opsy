import { useEffect, useState } from 'react'
import './App.css'

const API_BASE = 'http://localhost:8000'

function App() {
  const [welcomeMessage, setWelcomeMessage] = useState<string>('Loading...')
  const [healthStatus, setHealthStatus] = useState<string>('Checking...')

  useEffect(() => {
    // Fetch onboarding message
    fetch(`${API_BASE}/onboard`)
      .then((res) => {
        if (!res.ok) throw new Error('Failed to fetch onboarding message')
        return res.text()
      })
      .then((data) => setWelcomeMessage(data))
      .catch((err) => setWelcomeMessage(`Error: ${err.message}`))

    // Fetch health status
    fetch(`${API_BASE}/health`)
      .then((res) => {
        if (!res.ok) throw new Error('Failed to fetch health status')
        return res.text()
      })
      .then((data) => setHealthStatus(data))
      .catch((err) => setHealthStatus(`Error: ${err.message}`))
  }, [])

  return (
    <div id="center">
      <div className="hero">
        <div className="base">
          <h1>Opsy</h1>
        </div>
      </div>
      
      <div className="welcome-container">
        <h2>Onboarding Message</h2>
        <p className="welcome-message">{welcomeMessage}</p>
      </div>

      <div className="health-container">
        <span>System Status: </span>
        <span className={`status-badge ${healthStatus === 'OK' ? 'healthy' : 'unhealthy'}`}>
          {healthStatus}
        </span>
      </div>
    </div>
  )
}

export default App
