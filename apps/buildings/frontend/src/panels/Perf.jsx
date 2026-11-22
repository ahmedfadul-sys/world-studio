import { useEffect, useState } from 'react'
import { useApp } from '../store.jsx'
import { api } from '../api.js'
import { Card, Stat } from '../ui.jsx'
import { useSystem } from './Dashboard.jsx'

const LIMIT_MB = 8192

function Spark({ data, max }) {
  const w = 480, h = 90
  if (data.length < 2) return <svg viewBox={`0 0 ${w} ${h}`} className="spark" role="img" aria-label="memory history" />
  const pts = data.map((v, i) => `${(i / (data.length - 1)) * w},${h - (Math.min(v, max) / max) * h}`).join(' ')
  return <svg viewBox={`0 0 ${w} ${h}`} className="spark" role="img" aria-label="memory history"><polyline points={pts} fill="none" stroke="var(--accent)" strokeWidth="2" /></svg>
}

export default function Perf() {
  const { t } = useApp()
  const { sys } = useSystem(1000)
  const [series, setSeries] = useState([])
  const [runs, setRuns] = useState([])
  useEffect(() => { if (sys) setSeries((s) => [...s.slice(-59), sys.tree_rss_mb]) }, [sys])
  useEffect(() => { api.perf(30).then((r) => setRuns(r.runs.reverse())).catch(() => {}) }, [sys?.jobs?.running])
  const max = Math.max(1024, ...series) * 1.15
  return (
    <div className="page">
      <h2>{t('perf_title')}</h2>
      <Card title={t('perf_live')}>
        {sys && <div className="stats"><Stat label={t('dash_ram')} value={`${sys.rss_mb} MB`} /><Stat label={t('dash_ram_tree')} value={`${sys.tree_rss_mb} MB`} /><Stat label={t('perf_limit')} value={`${LIMIT_MB} MB`} /><Stat label="max concurrent builds" value={sys.max_concurrent_builds_seen} /></div>}
        <Spark data={series} max={max} />
        <p className="muted">{t('perf_note')}</p>
      </Card>
      <Card title={t('perf_runs')}>
        <div className="tablewrap">
          <table>
            <thead><tr><th>kind</th><th>{t('perf_time')}</th><th>{t('perf_before')}</th><th>{t('perf_peak')}</th><th>{t('perf_after')}</th><th>{t('perf_blender')}</th><th>{t('perf_tris')}</th><th>{t('elements_rebuilt')}</th></tr></thead>
            <tbody>{runs.map((r, i) => (
              <tr key={i}><td>{r.kind}</td><td>{r.seconds}{t('seconds')}</td><td>{Math.round(r.geometry.rss_before_mb)}</td><td>{Math.round(r.geometry.rss_peak_mb)}</td><td>{Math.round(r.geometry.rss_after_mb)}</td>
                <td>{r.blender_peak_mb ?? '—'}</td><td>{r.triangles ? r.triangles.visual : '—'}</td><td>{r.rebuilt}/{r.rebuilt + r.cached}</td></tr>))}</tbody>
          </table>
        </div>
      </Card>
    </div>
  )
}
