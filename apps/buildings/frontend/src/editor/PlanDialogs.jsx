import { useMemo, useRef, useState } from 'react'
import { useApp } from '../store.jsx'
import { Field, NumField, Select, Toggle } from '../ui.jsx'
import { fromM, UNITS } from '../model.js'
import { arrayLinear, arrayPolar, centroid } from '../plan.js'
import { DxfError, dxfToWalls, parseDxf } from '../dxf.js'
import { bbox, uid } from '../model.js'
import { centredUnderlay } from '../plan.js'
import { clearDebris, ruinElements } from '../ruin.js'
import { buildPlaza, PLAZA_SHAPES } from '../plaza.js'
import { autoFloors, buildVilla, levelsFor, planVilla } from '../villa.js'
import { openPdf, prepareImage, uploadUnderlay } from '../underlay.js'

export function Dialog({ title, onClose, children, testid }) {
  const { t } = useApp()
  return (
    <div className="dlg-overlay" role="dialog" aria-modal="true" aria-label={title} data-testid={testid} onMouseDown={(e) => { if (e.target === e.currentTarget) onClose() }}>
      <div className="dlg">
        <header className="dlg-h"><h3>{title}</h3><button type="button" className="btn small" onClick={onClose}>{t('close')}</button></header>
        <div className="dlg-b">{children}</div>
      </div>
    </div>
  )
}

/** Linear or circular array of the current selection. */
export function ArrayDialog({ onClose }) {
  const app = useApp()
  const { t, project, selection, levelId } = app
  const unit = project.units.name
  const c0 = useMemo(() => centroid(project.elements, selection), []) // eslint-disable-line react-hooks/exhaustive-deps
  const [mode, setMode] = useState('linear')
  const [n, setN] = useState(3)
  const [dx, setDx] = useState(fromM(3, unit))
  const [dy, setDy] = useState(0)
  const [total, setTotal] = useState(6)
  const [ang, setAng] = useState(360)
  const [cx, setCx] = useState(c0[0])
  const [cy, setCy] = useState(c0[1])
  const [rot, setRot] = useState(true)
  const preview = () => (mode === 'linear' ? arrayLinear(project.elements, selection, { count: n, dx, dy, levelId }) : arrayPolar(project.elements, selection, { count: total, center: [cx, cy], totalDeg: ang, rotateCopies: rot }))
  const count = useMemo(() => { try { return preview().length } catch { return 0 } }, [mode, n, dx, dy, total, ang, cx, cy, rot, selection]) // eslint-disable-line react-hooks/exhaustive-deps
  const apply = () => {
    const made = preview()
    app.edit((p) => ({ ...p, elements: [...p.elements, ...made] }))
    app.select(made.filter((e) => !e.wall_id).map((e) => e.id))
    app.toast(`${t('pt_done')}: ${made.length}`, 'info')
    onClose()
  }
  return (
    <Dialog title={t('ay_title')} onClose={onClose} testid="array-dialog">
      <div className="row wrap">
        <button type="button" className={`btn small ${mode === 'linear' ? 'primary' : ''}`} onClick={() => setMode('linear')}>{t('ay_linear')}</button>
        <button type="button" className={`btn small ${mode === 'polar' ? 'primary' : ''}`} data-testid="ay-polar" onClick={() => setMode('polar')}>{t('ay_polar')}</button>
      </div>
      {mode === 'linear' ? (
        <>
          <Field label={t('ay_count')}><NumField value={n} min={1} max={100} step={1} onChange={(v) => setN(Math.round(v))} /></Field>
          <Field label={`${t('ay_dx')} (${unit})`}><NumField value={dx} min={-1e6} onChange={setDx} /></Field>
          <Field label={`${t('ay_dy')} (${unit})`}><NumField value={dy} min={-1e6} onChange={setDy} /></Field>
        </>
      ) : (
        <>
          <Field label={t('ay_total')}><NumField value={total} min={2} max={100} step={1} onChange={(v) => setTotal(Math.round(v))} /></Field>
          <Field label={t('ay_angle')}><NumField value={ang} min={1} max={360} onChange={setAng} /></Field>
          <Field label={`${t('ay_cx')} (${unit})`}><NumField value={cx} min={-1e6} onChange={setCx} /></Field>
          <Field label={`${t('ay_cy')} (${unit})`}><NumField value={cy} min={-1e6} onChange={setCy} /></Field>
          <Toggle checked={rot} label={t('ay_rotate')} onChange={setRot} />
        </>
      )}
      <p className="muted">{t('ay_adds')}: {count}</p>
      <button type="button" className="btn primary" data-testid="ay-apply" disabled={!count} onClick={apply}>{t('ay_apply')}</button>
    </Dialog>
  )
}

const MAX_BYTES = 25 * 1024 * 1024

/** Import an ASCII DXF as walls on the current level. */
export function DxfImport({ onClose }) {
  const app = useApp()
  const { t, project, levelId } = app
  const unit = project.units.name
  const [parsed, setParsed] = useState(null)
  const [err, setErr] = useState('')
  const [layers, setLayers] = useState(new Set())
  const [from, setFrom] = useState('m')
  const [thick, setThick] = useState(fromM(0.2, unit))
  const [minLen, setMinLen] = useState(fromM(0.05, unit))
  const [snap, setSnap] = useState(fromM(0.02, unit))
  const [origin, setOrigin] = useState(true)

  const onFile = async (file) => {
    setErr(''); setParsed(null)
    if (!file) return
    if (/\.dwg$/i.test(file.name)) { setErr(t('dxf_err_dwg')); return }
    if (file.size > MAX_BYTES) { setErr(t('dxf_err_big')); return }
    try {
      const p = parseDxf(await file.text())
      setParsed(p); setLayers(new Set(Object.keys(p.layers))); setFrom(p.units || 'm')
    } catch (e) {
      setErr(e instanceof DxfError ? t(e.message === 'binary' ? 'dxf_err_binary' : 'dxf_err_empty') : String(e.message || e))
    }
  }
  const res = useMemo(() => (parsed ? dxfToWalls(parsed, { layers, fromUnit: from, levelId, unit, thickness: thick, minLen, snap, origin }) : null), [parsed, layers, from, levelId, unit, thick, minLen, snap, origin])
  const size = useMemo(() => {
    if (!res || !res.walls.length) return null
    const xs = res.walls.flatMap((w) => [w.a[0], w.b[0]]), ys = res.walls.flatMap((w) => [w.a[1], w.b[1]])
    return [Math.max(...xs) - Math.min(...xs), Math.max(...ys) - Math.min(...ys)].map((v) => Math.round(v * 100) / 100)
  }, [res])
  const toggle = (name) => { const s = new Set(layers); if (s.has(name)) s.delete(name); else s.add(name); setLayers(s) }
  const go = () => {
    if (!res?.walls.length) return
    app.edit((p) => ({ ...p, elements: [...p.elements, ...res.walls] }))
    app.select(res.walls.map((w) => w.id))
    app.set({ view: null })
    app.toast(`${t('pt_done')}: ${res.walls.length}`, 'info')
    onClose()
  }
  return (
    <Dialog title={t('dxf_title')} onClose={onClose} testid="dxf-dialog">
      <Field label={t('dxf_file')}><input type="file" accept=".dxf,.dwg" data-testid="dxf-file" onChange={(e) => onFile(e.target.files?.[0])} /></Field>
      {err && <div className="errbox" role="alert">{err}</div>}
      {parsed && (
        <>
          <div className="dxf-layers" role="group" aria-label={t('dxf_layers')}>
            <b>{t('dxf_layers')}</b>
            {Object.entries(parsed.layers).sort().map(([name, n]) => <Toggle key={name} checked={layers.has(name)} label={`${name} (${n})`} onChange={() => toggle(name)} />)}
          </div>
          <Select label={t('dxf_units')} value={from} onChange={setFrom} options={Object.keys(UNITS).map((u) => ({ value: u, label: u }))} />
          <Field label={`${t('dxf_thick')} (${unit})`}><NumField value={thick} min={0.0001} onChange={setThick} /></Field>
          <Field label={`${t('dxf_min')} (${unit})`}><NumField value={minLen} min={0} onChange={setMinLen} /></Field>
          <Field label={`${t('dxf_snap')} (${unit})`}><NumField value={snap} min={0} onChange={setSnap} /></Field>
          <Toggle checked={origin} label={t('dxf_origin')} onChange={setOrigin} />
          {Object.keys(parsed.skipped).length > 0 && <p className="muted small">{t('dxf_skipped')}: {Object.entries(parsed.skipped).map(([k, v]) => `${k} ×${v}`).join(', ')}</p>}
          {res?.tooMany ? <p className="errbox">{t('dxf_err_many')}</p> : <p className="muted" data-testid="dxf-result">{t('dxf_result')}: {res?.walls.length || 0} {t('dxf_walls')}{size ? ` · ${t('dxf_size')} ${size[0]} × ${size[1]} ${unit}` : ''}</p>}
          <button type="button" className="btn primary" data-testid="dxf-go" disabled={!res?.walls.length} onClick={go}>{t('dxf_import')}</button>
        </>
      )}
    </Dialog>
  )
}

/** Import a scanned plan (PNG / JPG / one page of a PDF) as an underlay to trace over. */
export function UnderlayImport({ onClose }) {
  const app = useApp()
  const { t, project, levelId } = app
  const unit = project.units.name
  const [file, setFile] = useState(null)
  const [pdf, setPdf] = useState(null)
  const [page, setPage] = useState(1)
  const [width, setWidth] = useState(fromM(20, unit))
  const [scope, setScope] = useState('this')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const onFile = async (f) => {
    setErr(''); setPdf(null); setFile(f || null); setPage(1)
    if (!f) return
    if (/\.pdf$/i.test(f.name) || f.type === 'application/pdf') {
      try { setPdf(await openPdf(f)) } catch (e) { setErr(`${t('ul_err')}: ${e.message || e}`); setFile(null) }
    }
  }
  const go = async () => {
    if (!file) return
    setBusy(true); setErr('')
    try {
      const img = pdf ? await pdf.render(page) : await prepareImage(file)
      const id = uid('ul')
      const ext = img.blob.type === 'image/png' ? 'png' : 'jpg'
      const name = `${id}.${ext}`
      await uploadUnderlay(project.id, name, img.blob)
      const bb = bbox(project.elements, levelId)
      const centre = bb ? [(bb.x0 + bb.x1) / 2, (bb.y0 + bb.y1) / 2] : [width / 2, 0]
      const pos = centredUnderlay(centre, width, img.w, img.h)
      const u = { id, name: file.name.replace(/\.[^.]+$/, '').slice(0, 100) + (pdf && pdf.pages > 1 ? ` p${page}` : ''), file: name, level_id: scope === 'this' ? levelId : null, ...pos, width, px_w: img.w, px_h: img.h, rotation_deg: 0, opacity: 0.55, visible: true, locked: false }
      app.edit((p) => ({ ...p, underlays: [...(p.underlays || []), u] }))
      app.set({ view: null, calib: { id, pts: [] }, tool: 'select' })
      app.toast(t('ul_first'), 'info')
      onClose()
    } catch (e) { setErr(`${t('ul_err')}: ${e.message || e}`) } finally { setBusy(false) }
  }
  return (
    <Dialog title={t('ul_import')} onClose={onClose} testid="underlay-dialog">
      <Field label={t('ul_file')}><input type="file" accept="image/png,image/jpeg,application/pdf,.pdf" data-testid="ul-file" onChange={(e) => onFile(e.target.files?.[0])} /></Field>
      {pdf && pdf.pages > 1 && <Field label={`${t('ul_page')} (1–${pdf.pages})`}><NumField value={page} min={1} max={pdf.pages} step={1} onChange={(v) => setPage(Math.round(v))} /></Field>}
      <Field label={`${t('ul_guess')} (${unit})`}><NumField value={width} min={0.01} onChange={setWidth} /></Field>
      <Select label={t('ul_level')} value={scope} onChange={setScope} options={[{ value: 'this', label: t('ul_this') }, { value: 'all', label: t('ul_all') }]} />
      {err && <div className="errbox" role="alert">{err}</div>}
      {busy && <p className="muted">{t('ul_loading')}</p>}
      <button type="button" className="btn primary" data-testid="ul-go" disabled={!file || busy} onClick={go}>{t('ul_go')}</button>
    </Dialog>
  )
}

/** Villa / palace generator: total built area → a complete multi-level plan that can be edited afterwards. */
export function VillaDialog({ onClose }) {
  const app = useApp()
  const { t, project } = app
  const unit = project.units.name
  const [area, setArea] = useState(2000)
  const [style, setStyle] = useState('villa')
  const [floors, setFloors] = useState(0)
  const [aspect, setAspect] = useState(1.5)
  const [replace, setReplace] = useState(true)
  const plan = useMemo(() => { try { return area >= 60 && area <= 40000 ? planVilla({ area, style, floors, aspect }) : null } catch { return null } }, [area, style, floors, aspect])
  const apply = () => {
    if (!plan) return
    if (replace && project.elements.length && !window.confirm(t('vl_confirm'))) return
    const levels = levelsFor(plan, replace ? project.levels : project.levels, unit)
    const label = (ty) => t('rt_' + ty)
    const res = buildVilla(plan, levels.map((l) => l.id), unit, { label })
    app.edit((p) => {
      const keep = replace ? [] : p.elements.filter((e) => levels.every((l) => l.id !== e.level_id))
      const extra = p.levels.filter((l) => !levels.some((n) => n.id === l.id))
      return { ...p, levels: [...levels, ...(replace ? [] : extra)], elements: [...keep, ...res.elements] }
    })
    app.set({ levelId: levels[0].id })
    app.select([])
    app.toast(`${t('vl_done')}: ${res.stats.rooms} ${t('vl_rooms')}, ${res.stats.walls} ${t('vl_walls')}`, 'info')
    onClose()
  }
  return (
    <Dialog title={t('vl_title')} onClose={onClose} testid="villa-dialog">
      <p className="muted small">{t('vl_hint')}</p>
      <Field label={t('vl_area')}><NumField value={area} min={60} max={40000} step={50} onChange={(v) => setArea(Math.round(v))} /></Field>
      <div className="row wrap">
        <button type="button" className={`btn small ${area === 2000 ? 'primary' : ''}`} onClick={() => setArea(2000)}>2000 m²</button>
        <button type="button" className={`btn small ${area === 5000 ? 'primary' : ''}`} data-testid="vl-5000" onClick={() => { setArea(5000); setStyle('palace') }}>5000 m²</button>
      </div>
      <Select label={t('vl_style')} value={style} onChange={setStyle} options={[{ value: 'villa', label: t('vl_villa') }, { value: 'palace', label: t('vl_palace') }]} />
      <Select label={t('vl_floors')} value={String(floors)} onChange={(v) => setFloors(Number(v))} options={[{ value: '0', label: `${t('vl_auto')} (${autoFloors(area, style)})` }, ...[1, 2, 3, 4].map((n) => ({ value: String(n), label: String(n) }))]} />
      <Field label={t('vl_aspect')}><NumField value={aspect} min={1} max={3} step={0.1} onChange={setAspect} /></Field>
      <Toggle checked={replace} label={t('vl_replace')} onChange={setReplace} />
      {plan && <p className="vl-sum" data-testid="vl-summary">{t('vl_result')}: <b>{plan.W} × {plan.D} m</b> · {plan.floors} {t('vl_levels')} · <b>{plan.total} m²</b> ({plan.perLevel.toFixed(0)} m² / {t('vl_level')})</p>}
      <div className="row"><button type="button" className="btn primary" data-testid="vl-go" disabled={!plan} onClick={apply}>{t('vl_generate')}</button></div>
    </Dialog>
  )
}

/** Ruin tool: cut the building along a jagged line, break the walls near the cut, drop slabs / roofs, scatter debris. Re-applies from the original each time. */
export function RuinDialog({ onClose }) {
  const app = useApp()
  const { t, project, selection, levelId } = app
  const unit = project.units.name
  const orig = useRef(project.elements)
  const [P, setP] = useState({ severity: 0.6, seed: 1, angle: 0, randomAngle: true, offset: 0.15, jag: 0.5, debris: 0.7, scope: 'all' })
  const [stats, setStats] = useState(null)
  const up = (o) => setP((x) => ({ ...x, ...o }))
  const apply = (q = P) => {
    const ids = q.scope === 'selection' && selection.length ? new Set(selection) : null
    const r = ruinElements(orig.current, { unit, levels: project.levels, seed: q.seed, severity: q.severity, cutAngle: q.randomAngle ? null : q.angle, cutOffset: q.offset, jag: q.jag, debris: q.debris, ids, levelIds: q.scope === 'level' ? [levelId] : null })
    app.edit((p) => ({ ...p, elements: r.elements }))
    setStats(r.stats)
  }
  const reroll = () => { const q = { ...P, seed: Math.floor(Math.random() * 100000) }; setP(q); apply(q) }
  const restore = () => { app.edit((p) => ({ ...p, elements: orig.current })); setStats(null) }
  return (
    <Dialog title={t('ru_title')} onClose={onClose} testid="ruin-dialog">
      <p className="muted small">{t('ru_hint')}</p>
      <Select label={t('ru_scope')} value={P.scope} onChange={(v) => up({ scope: v })} options={[{ value: 'all', label: t('ru_all') }, { value: 'level', label: t('ru_level') }, ...(selection.length ? [{ value: 'selection', label: `${t('ru_sel')} (${selection.length})` }] : [])]} />
      <Field label={`${t('ru_sev')}: ${Math.round(P.severity * 100)}%`}><input type="range" min={0.1} max={1} step={0.05} value={P.severity} onChange={(e) => up({ severity: +e.target.value })} /></Field>
      <Field label={`${t('ru_jag')}: ${Math.round(P.jag * 100)}%`}><input type="range" min={0} max={1} step={0.05} value={P.jag} onChange={(e) => up({ jag: +e.target.value })} /></Field>
      <Field label={`${t('ru_cutpos')}: ${Math.round(P.offset * 100)}%`}><input type="range" min={-0.5} max={0.5} step={0.05} value={P.offset} onChange={(e) => up({ offset: +e.target.value })} /></Field>
      <Toggle checked={P.randomAngle} label={t('ru_randang')} onChange={(v) => up({ randomAngle: v })} />
      {!P.randomAngle && <Field label={`${t('ru_angle')}: ${P.angle}°`}><input type="range" min={0} max={359} step={5} value={P.angle} onChange={(e) => up({ angle: +e.target.value })} /></Field>}
      <Field label={`${t('ru_debris')}: ${Math.round(P.debris * 100)}%`}><input type="range" min={0} max={1.5} step={0.05} value={P.debris} onChange={(e) => up({ debris: +e.target.value })} /></Field>
      <div className="row wrap">
        <button type="button" className="btn primary" data-testid="ru-apply" onClick={() => apply()}>{t('ru_apply')}</button>
        <button type="button" className="btn" data-testid="ru-reroll" onClick={reroll}>🎲 {t('ru_reroll')}</button>
        <button type="button" className="btn small" onClick={restore}>{t('ru_restore')}</button>
      </div>
      {stats && <p className="vl-sum" data-testid="ru-stats">{t('ru_result')}: {stats.removedWalls} {t('ru_walls_gone')} · {stats.loweredWalls} {t('ru_walls_low')} · {stats.debris} {t('ru_debris_n')}</p>}
    </Dialog>
  )
}

export const removeDebris = (app) => app.edit((p) => ({ ...p, elements: clearDebris(p.elements) }))

export function PlazaDialog({ onClose }) {
  const app = useApp()
  const { t, project, levelId } = app
  const unit = project.units.name
  const bb = project.elements.length ? bbox(project.elements) : null
  const k = UNITS[unit].toM
  const [P, setP] = useState(() => ({ shape: 'circle', width: 30, depth: 20, height: 0.6, tiers: 3, tierRun: 0.45, dais: true, daisFrac: 0.28, daisH: 0.5, colN: 0, colH: 5,
    cx: bb ? +(((bb.x0 + bb.x1) / 2) * k).toFixed(2) : 0, cy: bb ? +((bb.y0 * k) - 30).toFixed(2) : 0 }))
  const up = (o) => setP((x) => ({ ...x, ...o }))
  const rect = ['rect', 'ellipse', 'cross'].includes(P.shape)
  const apply = () => {
    const els = buildPlaza({ shape: P.shape, width: P.width, depth: rect ? P.depth : P.width, height: P.height, tiers: P.tiers, tierRun: P.tierRun,
      dais: { on: P.dais, frac: P.daisFrac, height: P.daisH }, columns: { n: P.colN, height: P.colH, frac: 0.9 } }, [fromM(P.cx, unit), fromM(P.cy, unit)], levelId, unit)
    app.edit((p) => ({ ...p, elements: [...p.elements, ...els] }))
    app.set({ selection: els.map((e) => e.id) })
    onClose()
  }
  const N = (label, key, min, max, step = 'any') => <NumField label={label} value={P[key]} min={min} max={max} step={step} onChange={(v) => up({ [key]: v })} />
  return (
    <Dialog title={t('pz_title')} onClose={onClose} testid="plaza-dialog">
      <p className="muted small">{t('pz_hint')}</p>
      <Select label={t('pz_shape')} value={P.shape} onChange={(v) => up({ shape: v })} options={PLAZA_SHAPES.filter((s) => s !== 'custom').map((s) => ({ value: s, label: t('pz_' + s) }))} />
      {N(t('pz_width') + ' (m)', 'width', 4, 400)}
      {rect && N(t('pz_depth') + ' (m)', 'depth', 4, 400)}
      {N(t('pz_height') + ' (m)', 'height', 0.1, 10)}
      {N(t('pz_tiers'), 'tiers', 0, 10, 1)}
      {N(t('pz_tierrun') + ' (m)', 'tierRun', 0.2, 3)}
      <Toggle checked={P.dais} label={t('pz_dais')} onChange={(v) => up({ dais: v })} />
      {P.dais && <>{N(t('pz_daisfrac'), 'daisFrac', 0.1, 0.7)}{N(t('pz_daish') + ' (m)', 'daisH', 0.1, 3)}</>}
      {N(t('pz_cols'), 'colN', 0, 64, 1)}
      {P.colN >= 3 && N(t('pz_colh') + ' (m)', 'colH', 1, 20)}
      <div className="row">{N('X (m)', 'cx')}{N('Y (m)', 'cy')}</div>
      <button type="button" className="btn primary" data-testid="pz-apply" onClick={apply}>{t('pz_apply')}</button>
    </Dialog>
  )
}
