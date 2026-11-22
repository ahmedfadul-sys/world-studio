import { useApp, useJob } from '../store.jsx'
import { Card, Field, JobBox, NeedProject, NumField, Select, Stat, Toggle } from '../ui.jsx'

const setExport = (app, patch, key) => app.edit((p) => ({ ...p, export: { ...p.export, ...patch } }), key)

function Run({ job, onRun, label }) {
  const { t } = useApp()
  return <button type="button" className="btn primary" disabled={job.busy} onClick={onRun}>{job.busy ? t('running') : label || t('run')}</button>
}

export default function AssetTool({ kind }) {
  const app = useApp()
  const { project, t } = app
  const job = useJob()
  if (!project) return <NeedProject />
  const ex = project.export
  const rep = job.result?.blender?.report
  const run = () => job.run(`/api/assets/${kind}`, {})

  let body = null
  if (kind === 'optimize') {
    body = (
      <>
        <Select label={t('opt_preset')} value={ex.poly_preset} onChange={(v) => setExport(app, { poly_preset: v })} options={['low', 'medium', 'high'].map((v) => ({ value: v, label: t('opt_' + v) }))} />
        <Toggle checked={ex.triangulate} label={t('opt_tri')} onChange={(v) => setExport(app, { triangulate: v })} />
        <p className="muted">{t('opt_note')}</p>
      </>
    )
  } else if (kind === 'collision') {
    body = (
      <>
        <Select label={t('col_mode')} value={ex.collision} onChange={(v) => setExport(app, { collision: v })} options={[['none', 'col_none'], ['box', 'col_box'], ['convex', 'col_convex'], ['simplified', 'col_simple']].map(([v, k]) => ({ value: v, label: t(k) }))} />
        <p className="muted">{t('col_note')}</p>
      </>
    )
  } else if (kind === 'lod') {
    const lv = ex.lod_levels
    const upd = (arr) => setExport(app, { lod_levels: [...arr].sort((a, b) => b - a) })
    body = (
      <>
        <h4>{t('lod_levels')}</h4>
        {lv.map((r, i) => (
          <div className="row" key={i}>
            <b>LOD{i + 1}</b>
            <NumField value={r} min={0.02} max={0.98} onChange={(v) => upd(lv.map((x, j) => (j === i ? v : x)))} />
            <button type="button" className="btn small" onClick={() => upd(lv.filter((_, j) => j !== i))} aria-label={t('remove')}>✕</button>
          </div>
        ))}
        <button type="button" className="btn small" disabled={lv.length >= 6} onClick={() => upd([...lv, Math.max(0.05, +(lv[lv.length - 1] / 2 || 0.5).toFixed(3))])}>{t('lod_add')}</button>
        <NumField label={t('lod_min')} value={ex.lod_min_triangles} min={0} step={1} onChange={(v) => setExport(app, { lod_min_triangles: Math.round(v) })} />
        <p className="muted">{t('lod_note')}</p>
      </>
    )
  } else if (kind === 'uv') {
    body = (
      <>
        <Select label={t('uv_mode')} value={ex.uv} onChange={(v) => setExport(app, { uv: v })} options={[['box', 'uv_box'], ['smart', 'uv_smart'], ['none', 'uv_none']].map(([v, k]) => ({ value: v, label: t(k) }))} />
        <p className="muted">{t('uv_note')}</p>
      </>
    )
  }

  let res = null
  if (rep) {
    if (kind === 'optimize') res = <div className="stats"><Stat label={t('opt_before')} value={rep.triangles.after_cleanup} /><Stat label={t('opt_after')} value={rep.triangles.after_optimize} /><Stat label={t('triangles')} value={rep.final_triangles.visual} /></div>
    if (kind === 'collision') res = <div className="stats"><Stat label={t('col_objects')} value={rep.collision.objects} /><Stat label={t('col_tris')} value={rep.collision.triangles} /><Stat label={t('triangles')} value={rep.final_triangles.visual} /></div>
    if (kind === 'lod') res = <div className="stats"><Stat label={t('lod_objects')} value={rep.lod.objects} />{Object.entries(rep.lod.triangles_by_level).map(([k, v]) => <Stat key={k} label={`LOD${k}`} value={v} />)}<Stat label="LOD0" value={rep.final_triangles.visual} /></div>
    if (kind === 'uv') res = (
      <div>
        <div className="stats"><Stat label={t('uv_objects')} value={rep.uv.objects} /><Stat label={t('uv_valid')} value={rep.uv.mode === 'none' ? '—' : rep.uv.ok ? '✔' : '✖'} /><Stat label={t('uv_invalid')} value={rep.uv.invalid.length} /></div>
        {rep.uv.invalid.map((x) => <div key={x.object} className="muted">{x.object}: {x.degenerate_faces} degenerate</div>)}
      </div>
    )
  }

  return (
    <div className="page narrow">
      <h2>{t(`${{ optimize: 'opt', collision: 'col', lod: 'lod', uv: 'uv' }[kind]}_title`)}</h2>
      <Card>{body}<div className="row"><Run job={job} onRun={run} /></div></Card>
      <JobBox job={job} />
      {res && <Card title={t('result')}>{res}<p className="muted">{job.result.seconds}{t('seconds')} · {job.result.geometry.rebuilt} {t('elements_rebuilt')} · {job.result.geometry.cached} {t('elements_reused')}</p></Card>}
    </div>
  )
}
