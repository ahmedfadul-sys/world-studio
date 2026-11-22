import { createContext, useCallback, useContext, useEffect, useMemo, useReducer, useRef, useState } from 'react'
import { api, formatError } from './api.js'
import { histNew, histPush, histRedo, histUndo } from './model.js'
import { LANGS, translate } from './i18n.js'

const Ctx = createContext(null)
export const useApp = () => useContext(Ctx)

const ls = {
  get: (k, d) => { try { return localStorage.getItem(k) || d } catch { return d } },
  set: (k, v) => { try { localStorage.setItem(k, v) } catch { /* private mode: ignore */ } },
}

const initial = () => ({
  lang: ls.get('bim.lang', (typeof navigator !== 'undefined' && navigator.language || 'en').startsWith('ar') ? 'ar' : 'en'),
  theme: ls.get('bim.theme', 'dark'),
  autosave: ls.get('bim.autosave', '1') === '1',
  section: 'dashboard',
  hist: null, savedProject: null, saving: false,
  levelId: null, tool: 'select', selection: [], view: null,
  toasts: [], previewStamp: 0,
})

const ids = (els) => new Set(els.map((e) => e.id))

function reducer(s, a) {
  switch (a.type) {
    case 'open': return { ...s, hist: histNew(a.project), savedProject: a.project, levelId: a.project.levels[0]?.id ?? null, selection: [], view: null, tool: 'select', section: a.section || 'editor', previewStamp: 0 }
    case 'close': return { ...s, hist: null, savedProject: null, selection: [], section: 'projects' }
    case 'edit': {
      const cur = s.hist.present
      const next = a.fn(cur)
      if (next === cur) return s
      const present = ids(next.elements)
      const levelOk = next.levels.some((l) => l.id === s.levelId)
      return { ...s, hist: histPush(s.hist, next, a.key), selection: s.selection.filter((i) => present.has(i)), levelId: levelOk ? s.levelId : next.levels[0]?.id ?? null }
    }
    case 'undo': case 'redo': {
      const h = a.type === 'undo' ? histUndo(s.hist) : histRedo(s.hist)
      if (h === s.hist) return s
      const present = ids(h.present.elements)
      const levelOk = h.present.levels.some((l) => l.id === s.levelId)
      return { ...s, hist: h, selection: s.selection.filter((i) => present.has(i)), levelId: levelOk ? s.levelId : h.present.levels[0]?.id ?? null }
    }
    case 'saving': return { ...s, saving: a.value }
    case 'saved': {
      const cur = s.hist.present
      const merged = { ...cur, updated_at: a.saved.updated_at, build_history: a.saved.build_history }
      if (cur === a.sent) return { ...s, saving: false, hist: { ...s.hist, present: merged }, savedProject: merged }
      return { ...s, saving: false, hist: { ...s.hist, present: merged }, savedProject: a.sent }
    }
    case 'history_only': { // server-owned fields (build history) refreshed after a build; not a user edit
      if (!s.hist) return s
      const cur = s.hist.present
      const merged = { ...cur, build_history: a.project.build_history, updated_at: a.project.updated_at }
      const clean = s.savedProject === cur
      return { ...s, hist: { ...s.hist, present: merged }, savedProject: clean ? merged : s.savedProject }
    }
    case 'set': return { ...s, ...a.patch }
    case 'toast': return { ...s, toasts: [...s.toasts, { id: a.id, kind: a.kind, text: a.text }].slice(-4) }
    case 'untoast': return { ...s, toasts: s.toasts.filter((t) => t.id !== a.id) }
    default: return s
  }
}

let toastN = 0

export function AppProvider({ children }) {
  const [s, dispatch] = useReducer(reducer, undefined, initial)
  const project = s.hist ? s.hist.present : null
  const dirty = !!project && project !== s.savedProject
  const failed = useRef(null)
  const stateRef = useRef(s)
  stateRef.current = s

  const t = useCallback((k) => translate(s.lang, k), [s.lang])

  useEffect(() => {
    document.documentElement.lang = s.lang
    document.documentElement.dir = LANGS[s.lang].dir
    document.documentElement.dataset.theme = s.theme
  }, [s.lang, s.theme])

  const toast = useCallback((text, kind = 'info') => {
    const id = ++toastN
    dispatch({ type: 'toast', id, kind, text })
    setTimeout(() => dispatch({ type: 'untoast', id }), kind === 'error' ? 9000 : 3500)
  }, [])

  const api2 = useMemo(() => ({
    dispatch,
    open: (p, section) => dispatch({ type: 'open', project: p, section }),
    edit: (fn, key) => dispatch({ type: 'edit', fn, key }),
    undo: () => dispatch({ type: 'undo' }),
    redo: () => dispatch({ type: 'redo' }),
    set: (patch) => dispatch({ type: 'set', patch }),
    setLang: (lang) => { ls.set('bim.lang', lang); dispatch({ type: 'set', patch: { lang } }) },
    setTheme: (theme) => { ls.set('bim.theme', theme); dispatch({ type: 'set', patch: { theme } }) },
    setAutosave: (v) => { ls.set('bim.autosave', v ? '1' : '0'); dispatch({ type: 'set', patch: { autosave: v } }) },
    select: (selection) => dispatch({ type: 'set', patch: { selection } }),
    toast,
  }), [toast])

  /** Save now. Resolves true on success. Edits made while saving stay dirty. */
  const save = useCallback(async () => {
    const cur = stateRef.current
    const p = cur.hist && cur.hist.present
    if (!p) return true
    if (p === cur.savedProject) return true
    dispatch({ type: 'saving', value: true })
    try {
      const saved = await api.putProject(p)
      failed.current = null
      dispatch({ type: 'saved', saved, sent: p })
      return true
    } catch (e) {
      failed.current = p
      dispatch({ type: 'saving', value: false })
      const info = formatError(e)
      toast(`${info.what}${info.why ? ': ' + info.why : ''}`, 'error')
      return false
    }
  }, [toast])

  useEffect(() => {
    if (!dirty || !s.autosave || s.saving || failed.current === project) return undefined
    const id = setTimeout(save, 1500)
    return () => clearTimeout(id)
  }, [dirty, project, s.autosave, s.saving, save])

  useEffect(() => {
    const warn = (e) => { if (stateRef.current.hist && stateRef.current.hist.present !== stateRef.current.savedProject) { e.preventDefault(); e.returnValue = '' } }
    window.addEventListener('beforeunload', warn)
    return () => window.removeEventListener('beforeunload', warn)
  }, [])

  const value = useMemo(() => ({ ...s, project, dirty, t, save, ...api2 }), [s, project, dirty, t, save, api2])
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

/** Run a backend job (save first, submit, poll). One active job per hook instance. */
export function useJob() {
  const app = useApp()
  const [st, setSt] = useState({ phase: 'idle', jobId: null, status: null, result: null, error: null })
  const alive = useRef(true)
  useEffect(() => () => { alive.current = false }, [])
  const jobRef = useRef(null)

  const run = useCallback(async (path, body) => {
    setSt({ phase: 'saving', jobId: null, status: 'saving', result: null, error: null })
    if (!(await app.save())) { setSt((x) => ({ ...x, phase: 'idle', status: null })); return null }
    try {
      const { job_id } = await api.submit(path, { project_id: app.project.id, ...body })
      jobRef.current = job_id
      setSt({ phase: 'running', jobId: job_id, status: 'queued', result: null, error: null })
      for (let n = 0; ; n++) {
        await new Promise((r) => setTimeout(r, n < 6 ? 120 : 450))   // fast first polls: cached previews finish in ~100 ms
        if (!alive.current) return null
        const s = await api.status(job_id)
        setSt((x) => ({ ...x, status: s.status }))
        if (s.status === 'queued' || s.status === 'running') continue
        if (s.status === 'succeeded') {
          const { result } = await api.result(job_id)
          const fresh = await api.getProject(app.project.id)
          app.dispatch({ type: 'history_only', project: fresh })
          setSt({ phase: 'done', jobId: job_id, status: 'succeeded', result, error: null })
          return result
        }
        setSt({ phase: 'done', jobId: job_id, status: s.status, result: null, error: s.error })
        return null
      }
    } catch (e) {
      setSt({ phase: 'done', jobId: null, status: 'failed', result: null, error: formatError(e) })
      return null
    }
  }, [app])

  const cancel = useCallback(() => { if (jobRef.current) api.cancel(jobRef.current).catch(() => {}) }, [])
  return { ...st, busy: st.phase === 'saving' || st.phase === 'running', run, cancel }
}
