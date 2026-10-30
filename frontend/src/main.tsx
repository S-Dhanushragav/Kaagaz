import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'

localStorage.removeItem('kaagaz.guest')  // the first Phase 9 build's "guest" flag: login is no longer the front door

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
