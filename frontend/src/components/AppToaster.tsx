import { useEffect, useState } from 'react'
import { Toaster } from 'sonner'

/** Sonner themed from the <html class="dark"> toggle (not the OS setting). */
export default function AppToaster() {
  const [dark, setDark] = useState(() => document.documentElement.classList.contains('dark'))
  useEffect(() => {
    const obs = new MutationObserver(() => setDark(document.documentElement.classList.contains('dark')))
    obs.observe(document.documentElement, { attributes: true, attributeFilter: ['class'] })
    return () => obs.disconnect()
  }, [])
  return <Toaster position="bottom-right" theme={dark ? 'dark' : 'light'} />
}