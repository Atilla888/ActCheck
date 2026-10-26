import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react"
import messages from "./messages.json"

export type Locale = "en" | "ru" | "kk"
type Theme = "light" | "dark"
type Params = Record<string, string | number>
const locales: Record<Locale, string> = {
  en: "en-US",
  ru: "ru-KZ",
  kk: "kk-KZ",
}
const catalog: Record<string, { ru: string; kk: string }> = messages

export function translate(locale: Locale, key: string, params: Params = {}) {
  const text = locale === "en" ? key : (catalog[key]?.[locale] ?? key)
  return text.replace(/\{(\w+)\}/g, (match, name: string) =>
    String(params[name] ?? match)
  )
}
function saved(key: string) {
  try {
    return localStorage.getItem(key)
  } catch {
    return null
  }
}
function persist(key: string, value: string) {
  try {
    localStorage.setItem(key, value)
  } catch {
    /* Preferences still work in memory. */
  }
}
function initialLocale(): Locale {
  const value = saved("actcheck.locale")
  return value === "ru" || value === "kk" ? value : "en"
}
function initialTheme(): Theme {
  const value = saved("actcheck.theme")
  if (value === "dark" || value === "light") return value
  return window.matchMedia("(prefers-color-scheme: dark)").matches
    ? "dark"
    : "light"
}

type Preferences = {
  locale: Locale
  setLocale: (locale: Locale) => void
  theme: Theme
  setTheme: (theme: Theme) => void
  t: (key: string, params?: Params) => string
  number: (value: number, digits?: number) => string
  money: (value: number) => string
}
const PreferencesContext = createContext<Preferences | null>(null)

export function PreferencesProvider({ children }: { children: ReactNode }) {
  const [locale, setLocale] = useState<Locale>(initialLocale)
  const [theme, setTheme] = useState<Theme>(initialTheme)
  useEffect(() => {
    persist("actcheck.locale", locale)
    document.documentElement.lang = locale
    document.title = `ActCheck — ${translate(locale, "Renovation inspections")}`
  }, [locale])
  useEffect(() => {
    persist("actcheck.theme", theme)
    document.documentElement.classList.toggle("dark", theme === "dark")
    document.documentElement.style.colorScheme = theme
    document
      .querySelector('meta[name="theme-color"]')
      ?.setAttribute("content", theme === "dark" ? "#171b18" : "#285849")
  }, [theme])
  const value = useMemo<Preferences>(
    () => ({
      locale,
      setLocale,
      theme,
      setTheme,
      t: (key, params) => translate(locale, key, params),
      number: (value, digits = 1) =>
        new Intl.NumberFormat(locales[locale], {
          maximumFractionDigits: digits,
        }).format(value),
      money: (value) =>
        new Intl.NumberFormat(locales[locale], {
          maximumFractionDigits: 0,
        }).format(value),
    }),
    [locale, theme]
  )
  return (
    <PreferencesContext.Provider value={value}>
      {children}
    </PreferencesContext.Provider>
  )
}
export function useI18n() {
  const context = useContext(PreferencesContext)
  if (!context) throw new Error("useI18n requires PreferencesProvider")
  return context
}
