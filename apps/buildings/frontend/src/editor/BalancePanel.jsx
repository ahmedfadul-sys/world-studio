import { useState } from 'react'
import { useApp } from '../store.jsx'
import { clampOpenings, dist, fmtLen } from '../model.js'
import { Card, Field, NumField } from '../ui.jsx'
import { applyOverrides, balanceChain, divideWall, setWallLength, wallChain } from '../plan.js'

/** Lengths of the selected walls: type an exact length, split into equal parts, or equalise a whole chain. */
export default function BalancePanel() {
  const app = useApp()
  const { project, selection, t } = app
  const unit = project.units.name
  const [parts, setParts] = useState(2)
  const els = selection.map((id) => project.elements.find((e) => e.id === id)).filter(Boolean)
  if (!els.length || els.some((e) => e.type !== 'wall')) return null
  const chain = els.length > 1 ? wallChain(project.elements, selection) : null
  const commit = (fn, msg) => { app.edit((p) => ({ ...p, ...fn(p.elements, p) })); if (msg) app.toast(msg, 'info') }
  const fix = (els2, walls) => { let r = els2; for (const w of new Set(walls)) r = clampOpenings(r, w); return r }
  const one = els.length === 1 ? els[0] : null
  const lens = (chain ? chain.walls : els).map((w) => dist(w.a, w.b))
  const total = lens.reduce((s, v) => s + v, 0)
  const spread = lens.length > 1 ? Math.max(...lens) - Math.min(...lens) : 0

  return (
    <Card title={t('bal_title')} fold="balance">
      <div className="small" data-testid="bal-lens">
        {lens.map((l, i) => <span key={i} className="chip">{fmtLen(l, unit)}</span>)}
        {lens.length > 1 && <p className="muted">{t('bal_total')}: <b>{fmtLen(total, unit)}</b> · {t('bal_spread')}: {fmtLen(spread, unit)}</p>}
      </div>
      {one && (
        <>
          <Field label={`${t('f_length')} (${unit})`}>
            <NumField value={Math.round(dist(one.a, one.b) * 1e4) / 1e4} min={0.0001} onChange={(v) => commit((els2) => { const o = setWallLength(els2, one.id, v); const r = applyOverrides(els2, o); return { elements: fix(r, Object.keys(o).filter((k) => r.find((e) => e.id === k)?.type === 'wall')) } })} />
          </Field>
          <p className="muted small">{t('bal_len_hint')}</p>
          <Field label={t('bal_divide')}>
            <div className="row">
              <NumField value={parts} min={2} max={50} step={1} onChange={(v) => setParts(Math.round(v))} />
              <button type="button" className="btn small primary" data-testid="bal-divide" onClick={() => commit((els2) => ({ elements: divideWall(els2, one.id, parts) }), `${t('bal_done')}: ${fmtLen(dist(one.a, one.b) / parts, unit)} × ${parts}`)}>{t('bal_divide_go')}</button>
            </div>
          </Field>
        </>
      )}
      {chain && (
        <div className="row">
          <button type="button" className="btn small primary" data-testid="bal-equal" disabled={spread < 1e-6} onClick={() => commit((els2) => { const o = balanceChain(els2, selection); const r = applyOverrides(els2, o); return { elements: fix(r, chain.walls.map((w) => w.id)) } }, `${t('bal_done')}: ${fmtLen(total / chain.walls.length, unit)} × ${chain.walls.length}`)}>{t('bal_equal')}</button>
        </div>
      )}
      {els.length > 1 && !chain && <p className="muted small">{t('bal_need_chain')}</p>}
    </Card>
  )
}
