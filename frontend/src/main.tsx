import '@fontsource-variable/inter'
import '@fontsource-variable/jetbrains-mono'

import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import AnalysisProvider from './state/AnalysisProvider.tsx'
import RouterProvider from './state/RouterProvider.tsx'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <RouterProvider>
      <AnalysisProvider>
        <App />
      </AnalysisProvider>
    </RouterProvider>
  </StrictMode>,
)
