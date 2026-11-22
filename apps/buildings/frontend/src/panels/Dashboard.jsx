import { useEffect, useState } from 'react'
import { useApp } from '../store.jsx'
import { api } from '../api.js'
import { Card, Stat } from '../ui.jsx'

export function useSystem(ms = 3000) {
  const [sys, setSys] = useState(null)
  const [err, setErr] = useState(null)
  useEffect(() => {
    let live = true
    const tick = () => api.system().then((s) => { if (live) { setSys(s); setErr(null) } }).catch((e) => { if (live) setErr(e) })
    tick()
    const id = setInterval(tick, ms)
    return () => { live = false; clearInterval(id) }
  }, [ms])
  return { sys, err }
}

export default function Dashboard() {
  const app = useApp()
  const { t, project } = app
  const { sys, err } = useSystem()
  const hist = project ? [...project.build_history].reverse().slice(0, 6) : []
  return (
    <div className="page">
      <h2>{t('nav_dashboard')}</h2>
      <Card title={t('dash_system')}>
        {err && <p className="err">{t('conn_lost')}</p>}
        {sys && (
          <div className="stats">
            <Stat label={t('dash_debim')} value={String(sys.debim).startsWith('unavailable') ? t('dash_unavailable') : sys.debim} />
            <Stat label={t('dash_blender')} value={sys.blender.ok ? sys.blender.version || t('dash_ok') : t('dash_unavailable')} />
            <Stat label={t('dash_ram')} value={`${sys.rss_mb} MB`} />
            <Stat label={t('dash_ram_tree')} value={`${sys.tree_rss_mb} MB`} />
            <Stat label={t('dash_jobs')} value={`${sys.jobs.running ? 1 : 0} ${t('dash_running')} · ${sys.jobs.queued} ${t('dash_queued')}`} />
          </div>
        )}
        {sys && !sys.blender.ok && <p className="err">Blender: {sys.blender.error}</p>}
        <p className="muted">{t('dash_target')}</p>
      </Card>
      <div className="grid2">
        <Card title={t('dash_quick')}>
          <div className="row wrap">
            <button type="button" className="btn primary" onClick={() => app.set({ section: 'projects' })}>{t('dash_new')}</button>
            {project && <button type="button" className="btn" onClick={() => app.set({ section: 'editor' })}>{t('dash_continue')}: {project.name}</button>}
          </div>
        </Card>
        <Card title={t('dash_recent')}>
          {!hist.length && <p className="muted">{t('dash_none')}</p>}
          {hist.map((h) => (
            <div key={h.job_id} className="row between"><span>{h.kind} · <span className={`dot ${h.status}`} /> {h.status}</span><span className="muted">{h.triangles} ▲ · {h.seconds}{t('seconds')}</span></div>
          ))}
        </Card>
      </div>
    </div>
  )
}
