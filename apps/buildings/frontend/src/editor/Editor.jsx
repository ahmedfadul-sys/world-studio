import { useState } from 'react'
import { useApp } from '../store.jsx'
import { Icon, Toggle } from '../ui.jsx'
import Canvas2D from './Canvas2D.jsx'
import Inspector from './Inspector.jsx'
import { RoadPanel } from './CityPanels.jsx'
import WallFace from './WallFace.jsx'
import { ArrayDialog, DxfImport, VillaDialog, RuinDialog, PlazaDialog, TowerDialog, UnderlayImport } from './PlanDialogs.jsx'

// أدوات المحرر مجمّعة: (مفتاح العنوان، الأدوات)
const TOOL_GROUPS = [
  ['tg_select', ['select', 'move', 'hand', 'delete']],
  ['tg_draw', ['wall', 'circle', 'arc']],
  ['tg_open', ['door', 'window', 'opening']],
  ['tg_struct', ['column', 'beam', 'floor', 'roof', 'stair', 'room', 'roomwiz', 'decor']],
  ['tg_city', ['road', 'lamp', 'guide']],
]

export default function Editor() {
  const app = useApp()
  const { project, levelId, tool, t } = app
  const [ghost, setGhost] = useState(true)
  const [notice, setNotice] = useState('')
  const [panel, setPanel] = useState(false)
  const flash = (m) => { setNotice(m); setTimeout(() => setNotice(''), 2500) }
  const ed = project.editor

  const addLevel = () => app.edit((p) => {
    const last = p.levels[p.levels.length - 1]
    const lv = { id: `lvl_${p.levels.length}_${Math.random().toString(36).slice(2, 5)}`, name: `Level ${p.levels.length}`, elevation: last.elevation + last.height, height: last.height }
    setTimeout(() => app.set({ levelId: lv.id }), 0)
    return { ...p, levels: [...p.levels, lv] }
  })

  return (
    <div className="editor">
      <div className="ed-top">
        <div className="tabs" role="tablist" aria-label={t('levels')}>
          {project.levels.map((l) => <button key={l.id} role="tab" aria-selected={l.id === levelId} className={`tab ${l.id === levelId ? 'on' : ''}`} type="button" onClick={() => app.set({ levelId: l.id, selection: [] })}>{l.name}</button>)}
          <button type="button" className="tab" onClick={addLevel} aria-label={t('bld_add_level')} title={t('bld_add_level')}>＋</button>
        </div>
        <div className="row wrap">
          <button type="button" className="icon-btn" onClick={app.undo} title={`${t('undo')} (Ctrl+Z)`} aria-label={t('undo')}><Icon name="undo" /><span>{t('undo')}</span></button>
          <button type="button" className="icon-btn" onClick={app.redo} title={`${t('redo')} (Ctrl+Y)`} aria-label={t('redo')}><Icon name="redo" /><span>{t('redo')}</span></button>
          <Toggle checked={ed.snap_enabled} label={t('snap')} onChange={(v) => app.edit((p) => ({ ...p, editor: { ...p.editor, snap_enabled: v } }))} />
          <Toggle checked={ed.show_dimensions} label={t('dims')} onChange={(v) => app.edit((p) => ({ ...p, editor: { ...p.editor, show_dimensions: v } }))} />
          <Toggle checked={ghost} label={t('ghost')} onChange={setGhost} />
          <span title={t('linked_tip')}><Toggle checked={app.linked !== false} label={t('linked')} onChange={(v) => app.set({ linked: v })} /></span>
          <button type="button" className="btn small mobile-only" onClick={() => setPanel(!panel)}>{t('insp_title')}</button>
        </div>
      </div>
      <div className="ed-body">
        <div className="toolbar" role="toolbar" aria-label="tools">
          {TOOL_GROUPS.map(([g, list]) => (
            <div className="tgroup" key={g} role="group" aria-label={t(g)}>
              <h6>{t(g)}</h6>
              <div className="tgrid">
                {list.map((k) => (
                  <button key={k} type="button" className={`tool ${tool === k ? 'on' : ''}`} onClick={() => app.set({ tool: k })} title={t('tool_' + k)} aria-label={t('tool_' + k)} aria-pressed={tool === k} data-tool={k}>
                    <Icon name={k} />
                  </button>
                ))}
              </div>
            </div>
          ))}
        </div>
        <div className="ed-canvas">
          {['floor', 'roof', 'room'].includes(tool) && (
            <div className="shape-bar opts" role="group" aria-label={t('shape')}>
              {['poly', 'rect', 'circle'].map((k) => <button key={k} type="button" className={`btn small ${(app.shape || 'poly') === k ? 'primary' : ''}`} aria-pressed={(app.shape || 'poly') === k} data-shape={k} onClick={() => app.set({ shape: k })}>{t('shape_' + k)}</button>)}
            </div>
          )}
          {tool === 'road' && <RoadPanel />}
          <Canvas2D showGhost={ghost} onNotice={flash} />
          {notice && <div className="notice" role="status">{notice}</div>}
        </div>
        <aside className={`ed-side ${panel ? 'open' : ''}`}><Inspector /></aside>
        {app.faceWall && <WallFace />}
        {app.dialog === 'array' && <ArrayDialog onClose={() => app.set({ dialog: null })} />}
        {app.dialog === 'underlay' && <UnderlayImport onClose={() => app.set({ dialog: null })} />}
        {app.dialog === 'plaza' && <PlazaDialog onClose={() => app.set({ dialog: null })} />}
        {app.dialog === 'tower' && <TowerDialog onClose={() => app.set({ dialog: null })} />}
        {app.dialog === 'ruin' && <RuinDialog onClose={() => app.set({ dialog: null })} />}
        {app.dialog === 'villa' && <VillaDialog onClose={() => app.set({ dialog: null })} />}
        {app.dialog === 'dxf' && <DxfImport onClose={() => app.set({ dialog: null })} />}
      </div>
    </div>
  )
}
