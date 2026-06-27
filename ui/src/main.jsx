import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'

import App from './App.jsx'
import { startInteractionRecording } from './utils/interactionLogger.jsx'

import '../src/styles/main.css'

startInteractionRecording();

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
