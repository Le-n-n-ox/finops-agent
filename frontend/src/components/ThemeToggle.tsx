import { useEffect, useState } from 'react'
import { Moon, Sun } from 'lucide-react'
import { Button } from '@/components/ui/button'

export default function ThemeToggle() {
  const [dark, setDark] = useState(() => document.documentElement.classList.contains('dark'))

  useEffect(() => {
    document.documentElement.classList.toggle('dark', dark)
    try { localStorage.setItem('theme', dark ? 'dark' : 'light') } catch { /* storage unavailable */ }
  }, [dark])

  return (
    <Button variant="outline" size="icon" onClick={() => setDark((d) => !d)} aria-label={dark ? 'Switch to light mode' : 'Switch to dark mode'}>
      {dark ? <Sun /> : <Moon />}
    </Button>
  )
}