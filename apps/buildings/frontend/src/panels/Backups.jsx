import { useCallback, useEffect, useState } from 'react'
import { useApp } from '../store.jsx'
import { api, formatError } from '../api.js'
import { Card, ErrorBox } from '../ui.jsx'

/** Dated project snapshots: automatic (every ~5 min while saving) and manual; restoring first snapshots the current state. */
export default function Backups() {
  const app = useApp()
  const { project, t } = app
  const [list, setList] = useState(null)
  const [err, setErr] = useState(null)
  const [busy, setBusy] = useState(false)
  const pid = project.id
  const load = useCallback(() => api.backups(pid).then((r) => { setList(r.backups); setErr(null) }).catch((e) => setErr(formatError(e))), [pid])
  useEffect(() => { load() }, [load])
  const run = async (fn) => { setBusy(true); try { await fn() } catch (e) { setErr(formatError(e)) } finally { setBusy(false) } }
  const make = () => run(async () => { if (!(await app.save())) return; await api.makeBackup(pid); await load(); app.toast(t('bk_made'), 'info') })
  const restore = (b) => {
    if (!window.confirm(`${t('bk_confirm')}\n${new Date(b.modified * 1000).toLocaleString()}`)) return
    run(async () => { if (!(await app.save())) return; const p = await api.restoreBackup(pid, b.name); app.open(p, 'settings'); await load(); app.toast(t('bk_restored'), 'info') })
  }
  const del = (b) => run(async () => { await api.deleteBackup(pid, b.name); await load() })
  return (
    <Card title={t('bk_title')} actions={<button type="button" className="btn small" data-testid="bk-make" disabled={busy} onClick={make}>{t('bk_make')}</button>}>
      <p className="muted small">{t('bk_hint')}</p>
      <ErrorBox error={err} />
      {list && !list.length && <p className="muted">{t('bk_empty')}</p>}
      <ul className="tpl-list" data-testid="bk-list">
        {(list || []).map((b) => (
          <li key={b.name} className="tpl">
            <div className="tpl-pick" style={{ cursor: 'default' }}>
              <b>{new Date(b.modified * 1000).toLocaleString()}</b>
              <span className="muted small">{b.manual ? t('bk_manual') : t('bk_auto')} · {b.elements ?? '?'} {t('elements')}</span>
            </div>
            <button type="button" className="btn small" data-bk-restore={b.name} disabled={busy} onClick={() => restore(b)}>{t('bk_restore')}</button>
            <button type="button" className="btn small" aria-label={t('delete')} disabled={busy} onClick={() => del(b)}>✕</button>
          </li>
        ))}
      </ul>
    </Card>
  )
}
