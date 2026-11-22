import { Component, lazy, Suspense, useEffect } from 'react'
import { api } from './api.js'
import { useApp } from './store.jsx'
import { LANGS } from './i18n.js'
import { Icon } from './ui.jsx'
import Dashboard from './panels/Dashboard.jsx'
import Projects from './panels/Projects.jsx'
import Editor from './editor/Editor.jsx'
import Building from './panels/Building.jsx'
import Materials from './panels/Materials.jsx'
import Modules from './panels/Modules.jsx'
import AssetTool from './panels/AssetTool.jsx'
import Export from './panels/Export.jsx'
import Settings from './panels/Settings.jsx'
import Perf from './panels/Perf.jsx'
import { NeedProject } from './ui.jsx'

const Preview3D = lazy(() => import('./panels/Preview3D.jsx')) // three.js is only loaded when the tab is opened

const SECTIONS = [
  ['dashboard', () => <Dashboard />], ['projects', () => <Projects />], ['editor', () => <Editor />, true], ['preview', () => <Preview3D />],
  ['building', () => <Building />], ['materials', () => <Materials />], ['modules', () => <Modules />],
  ['optimize', () => <AssetTool kind="optimize" />], ['collision', () => <AssetTool kind="collision" />], ['lod', () => <AssetTool kind="lod" />], ['uv', () => <AssetTool kind="uv" />],
  ['export', () => <Export />], ['settings', () => <Settings />], ['perf', () => <Perf />],
]

class Boundary extends Component {
  state = { e: null }
  static getDerivedStateFromError(e) { return { e } }
  render() {
    if (!this.state.e) return this.props.children
    return <div className="errbox" role="alert"><strong>UI error</strong><div>{String(this.state.e.message)}</div><button className="btn" type="button" onClick={() => this.setState({ e: null })}>OK</button></div>
  }
}

export default function App() {
  const app = useApp()
  const { t, section, project, dirty, saving, lang, theme, toasts } = app
  const cur = SECTIONS.find((s) => s[0] === section) || SECTIONS[0]
  const needsProject = cur[2] && !project
  const qs = new URLSearchParams(window.location.search)
  const startId = qs.get('project'), fromStudio = qs.get('from') === 'studio' && window.parent !== window
  // Opened from a TerrainForge site (World Studio): load that project straight into the editor.
  useEffect(() => {
    if (!startId) return undefined
    let live = true
    api.getProject(startId).then((p) => { if (live) app.open(p, 'editor') }).catch((e) => app.toast(String(e.message || e), 'error'))
    return () => { live = false }
  }, [startId]) // eslint-disable-line react-hooks/exhaustive-deps
  const backToTerrain = async () => { if (dirty && !saving) { try { await app.save() } catch { /* the save state is shown in the header */ } } window.parent.postMessage({ type: 'studio.back' }, '*') }
  return (
    <div className="app">
      <header className="top">
        <div className="brand"><b>{t('appName')}</b> <span className="muted">{t('edition')}</span></div>
        {fromStudio && <button type="button" className="btn small" data-testid="back-terrain" onClick={backToTerrain}>{t('back_terrain')}</button>}
        <div className="grow">{project && <span className="pname">{project.name}</span>}{project && project.site && <span className="muted"> · {t('site_label')}: {project.site.kind} {project.site.shape === 'circle' ? `⌀${project.site.diameter_m} m` : `${project.site.width_m}×${project.site.length_m} m`}</span>}</div>
        {project && (
          <>
            <span className={`savestate ${dirty ? 'dirty' : ''}`} role="status">{saving ? t('saving') : dirty ? t('unsaved') : t('saved')}</span>
            <button type="button" className="btn small primary" disabled={!dirty || saving} onClick={app.save}>{t('save')}</button>
          </>
        )}
        <select aria-label={t('language')} value={lang} onChange={(e) => app.setLang(e.target.value)}>
          {Object.entries(LANGS).map(([k, v]) => <option key={k} value={k}>{v.name}</option>)}
        </select>
        <button type="button" className="icon-btn" aria-label={t('theme')} title={t('theme')} onClick={() => app.setTheme(theme === 'dark' ? 'light' : 'dark')}>{theme === 'dark' ? '☀' : '☾'}</button>
      </header>
      <div className="shell">
        <nav className="nav" aria-label="sections">
          {SECTIONS.map(([k]) => <button key={k} type="button" className={`navbtn ${k === section ? 'on' : ''}`} onClick={() => app.set({ section: k })} data-section={k}>{t('nav_' + k)}</button>)}
        </nav>
        <main className="main">
          <Boundary key={section}>
            <Suspense fallback={<div className="page">{t('loading')}</div>}>
              {needsProject ? <NeedProject /> : cur[1]()}
            </Suspense>
          </Boundary>
        </main>
      </div>
      <div className="toasts" aria-live="polite">{toasts.map((x) => <div key={x.id} className={`toast ${x.kind}`}>{x.text}</div>)}</div>
    </div>
  )
}
