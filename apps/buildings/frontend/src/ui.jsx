import { useEffect, useState } from 'react'
import { useApp } from './store.jsx'
import { api } from './api.js'

const ICONS = {
  select: 'M5 3l14 7-6 2-2 6z', move: 'M12 3v18M3 12h18M12 3l-3 3m3-3l3 3M12 21l-3-3m3 3l3-3M3 12l3-3m-3 3l3 3M21 12l-3-3m3 3l-3 3',
  hand: 'M8 13V6a1.5 1.5 0 013 0v5m0-6a1.5 1.5 0 013 0v6m0-4a1.5 1.5 0 013 0v7a6 6 0 01-6 6h-1a6 6 0 01-5-3l-2-4a1.5 1.5 0 012-2l2 2',
  delete: 'M5 7h14M10 7V4h4v3M7 7l1 13h8l1-13M10 11v6M14 11v6', wall: 'M3 9h18v6H3zM9 9v6M15 9v6', circle: 'M12 3a9 9 0 100 18 9 9 0 000-18zM12 12h9', arc: 'M4 19A9 9 0 0119 5M4 19v.1M19 5v.1',
  door: 'M6 21V4h9l3 2v15M6 21h12M13 12.5v.1', window: 'M5 4h14v16H5zM12 4v16M5 12h14',
  column: 'M8 4h8M9 4v16M15 4v16M7 20h10', beam: 'M3 9h18v5H3zM3 9l2-3h14l2 3', floor: 'M3 15l9-5 9 5-9 5zM3 11l9-5 9 5',
  roof: 'M2 13l10-9 10 9M5 11v9h14v-9', stair: 'M3 20h5v-4h5v-4h5V8h3', room: 'M4 4h16v16H4zM4 12h8v8',
  roomwiz: 'M4 4h16v16H4zM12 8v8M8 12h8', opening: 'M5 20V8a7 7 0 0114 0v12M5 20h14', decor: 'M12 3l3 6 6 1-4.5 4.5L18 21l-6-3-6 3 1.5-6.5L3 10l6-1z',
  rect: 'M4 6h16v12H4z', triangle: 'M12 4l9 16H3z', star: 'M12 3l2.6 6 6.4.6-4.8 4.3 1.4 6.3L12 17l-5.6 3.2 1.4-6.3L3 9.6 9.4 9z', poly: 'M5 18l2-12 8-2 4 8-6 6z',
  undo: 'M9 14L4 9l5-5M4 9h10a6 6 0 010 12h-3', redo: 'M15 14l5-5-5-5M20 9H10a6 6 0 000 12h3',
  road: 'M8 3L5 21M16 3l3 18M12 4v3M12 11v3M12 18v3', lamp: 'M12 21V9M8 21h8M12 9a5 5 0 015-5h1M18 4v3M16 7h4', guide: 'M3 8h18M3 16h18M8 3v18M16 3v18',
  fit: 'M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5',
}
export function Icon({ name, size = 20 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d={ICONS[name] || ''} />
    </svg>
  )
}

/** Persisted open/closed state of a collapsible card (per card key; falls back to the default when storage is unavailable). */
function useFold(key, dflt) {
  const k = 'bim.fold.' + key
  const [open, setOpen] = useState(() => { try { const v = window.localStorage.getItem(k); return v === null ? dflt : v === '1' } catch { return dflt } })
  const set = (v) => { setOpen(v); try { window.localStorage.setItem(k, v ? '1' : '0') } catch { /* storage may be blocked */ } }
  return [open, set]
}

export function Card({ title, children, actions, className = '', fold, defaultOpen = false, badge, sub }) {
  const [open, setOpen] = useFold(fold || '_', defaultOpen)
  if (!fold) {
    return (
      <section className={`card ${className}`}>
        {(title || actions) && <header className="card-h"><h3>{title}</h3><div className="row">{actions}</div></header>}
        {children}
      </section>
    )
  }
  return (
    <section className={`card fold ${open ? 'open' : ''} ${className}`}>
      <header className="card-h">
        <button type="button" className="fold-btn" aria-expanded={open} onClick={() => setOpen(!open)}>
          <h3>{title}</h3>{sub && <small className="card-sub">{sub}</small>}
          {badge !== undefined && badge !== null && <span className="badge">{badge}</span>}
          <svg className="chev" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M9 6l6 6-6 6" /></svg>
        </button>
        {open && actions && <div className="row">{actions}</div>}
      </header>
      {open && children}
    </section>
  )
}

export function Field({ label, children, hint }) {
  return <label className="field"><span className="field-l">{label}</span>{children}{hint && <small className="hint">{hint}</small>}</label>
}

/** Number input that lets the user type freely (e.g. "0.") and commits only valid numbers. */
export function NumField({ value, onChange, min, max, step = 'any', disabled, label, hint, decimals = 4 }) {
  const fmt = (v) => (v == null || Number.isNaN(v) ? '' : String(Math.round(v * 10 ** decimals) / 10 ** decimals))
  const [txt, setTxt] = useState(fmt(value))
  const [focus, setFocus] = useState(false)
  useEffect(() => { if (!focus) setTxt(fmt(value)) }, [value, focus]) // eslint-disable-line react-hooks/exhaustive-deps
  const input = (
    <input type="number" inputMode="decimal" step={step} min={min} max={max} disabled={disabled} value={txt}
      onFocus={() => setFocus(true)} onBlur={() => { setFocus(false); setTxt(fmt(value)) }}
      onChange={(e) => {
        setTxt(e.target.value)
        const n = parseFloat(e.target.value)
        if (Number.isFinite(n) && (min == null || n >= min) && (max == null || n <= max)) onChange(n)
      }} />
  )
  return label ? <Field label={label} hint={hint}>{input}</Field> : input
}

export function Select({ value, onChange, options, label, disabled }) {
  const el = (
    <select value={value ?? ''} disabled={disabled} onChange={(e) => onChange(e.target.value === '' ? null : e.target.value)}>
      {options.map((o) => <option key={String(o.value)} value={o.value ?? ''}>{o.label}</option>)}
    </select>
  )
  return label ? <Field label={label}>{el}</Field> : el
}

export function Toggle({ checked, onChange, label }) {
  return <label className="toggle"><input type="checkbox" checked={!!checked} onChange={(e) => onChange(e.target.checked)} /><span>{label}</span></label>
}

export function ErrorBox({ error }) {
  const { t } = useApp()
  if (!error) return null
  return (
    <div className="errbox" role="alert">
      <strong>{error.what}</strong>
      {error.where && <div><b>{t('err_where')}:</b> {error.where}</div>}
      {error.why && <div><b>{t('err_why')}:</b> {error.why}</div>}
      {error.fix && <div><b>{t('err_fix')}:</b> {error.fix}</div>}
    </div>
  )
}

export function Stat({ label, value }) {
  return <div className="stat"><div className="stat-v">{value}</div><div className="stat-l">{label}</div></div>
}

export function NeedProject() {
  const { t, set } = useApp()
  return (
    <div className="empty">
      <h2>{t('no_project')}</h2><p>{t('open_projects')}</p>
      <button type="button" className="btn primary" onClick={() => set({ section: 'projects' })}>{t('nav_projects')}</button>
    </div>
  )
}

/** Status line + error + warnings for a useJob() instance. */
export function JobBox({ job }) {
  const { t } = useApp()
  if (job.phase === 'idle') return null
  const label = job.phase === 'saving' ? t('job_saving_first') : { queued: t('job_queued'), running: t('job_running'), succeeded: t('job_succeeded'), failed: t('job_failed'), cancelled: t('job_cancelled') }[job.status] || job.status
  const warnings = job.result?.blender?.report?.warnings || []
  return (
    <div className="jobbox" aria-live="polite">
      <div className="row"><span className={`dot ${job.status}`} /> <strong>{label}</strong>
        {job.busy && job.jobId && <button type="button" className="btn small" onClick={job.cancel}>{t('job_cancel')}</button>}
      </div>
      <ErrorBox error={job.error} />
      {warnings.length > 0 && <ul className="warn"><li><b>{t('warnings')}</b></li>{warnings.map((w, i) => <li key={i}>{w}</li>)}</ul>}
    </div>
  )
}

const modCache = new Map()
/** Module library from the backend (built-ins + project modules); cached per project/module-set. */
export function useModules() {
  const { project } = useApp()
  const key = project ? `${project.id}:${project.modules.map((m) => m.id + JSON.stringify(m.defaults)).join('|')}` : ''
  const [mods, setMods] = useState(modCache.get(key) || [])
  useEffect(() => {
    if (!project) return undefined
    if (modCache.has(key)) { setMods(modCache.get(key)); return undefined }
    let live = true
    api.modules(project.id).then((r) => { modCache.set(key, r.modules); if (live) setMods(r.modules) }).catch(() => {})
    return () => { live = false }
  }, [key]) // eslint-disable-line react-hooks/exhaustive-deps
  return mods
}
