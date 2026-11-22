import { useCallback, useEffect, useRef, useState } from 'react'
import * as THREE from 'three'
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js'
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js'
import { useApp, useJob } from '../store.jsx'
import { api, formatError } from '../api.js'
import { initLook, applyLook } from '../godotLook.js'
import { Card, ErrorBox, JobBox, NeedProject, Select, Toggle } from '../ui.jsx'
import { toM } from '../model.js'
import { wallSide } from '../faceTools.js'
import WallFace from '../editor/WallFace.jsx'

const isCollision = (n) => /-(conv)?colonly$/.test(n)
const isLod = (n) => /_LOD\d+$/.test(n)

export default function Preview3D() {
  const app = useApp()
  const { project, t, theme } = app
  const job = useJob()
  const mount = useRef(null)
  const three = useRef(null)
  const [src, setSrc] = useState('exports/preview/preview.glb')
  const [info, setInfo] = useState(null)
  const [err, setErr] = useState(null)
  const [opts, setOpts] = useState({ col: false, lod: false, wire: false })
  const [stamp, setStamp] = useState(0)
  const [walk, setWalk] = useState(false)
  const [carve, setCarve] = useState(false)
  const [carveMsg, setCarveMsg] = useState('')
  const [walkLevel, setWalkLevel] = useState(null)
  const [collide, setCollide] = useState(true)
  const [godot, setGodot] = useState(false)
  const [sun, setSun] = useState({ elev: 50, az: 45 })
  const W = useRef({ yaw: 0, pitch: 0, keys: new Set(), eye: 1.65, collide: true, saved: null, dpad: { f: 0, s: 0 } })

  // one renderer for the lifetime of the tab; everything disposed on unmount (RAM-friendly)
  useEffect(() => {
    const el = mount.current
    if (!el) return undefined
    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false, powerPreference: 'low-power' })
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2))
    el.appendChild(renderer.domElement)
    const scene = new THREE.Scene()
    const cam = new THREE.PerspectiveCamera(50, 1, 0.05, 2000)
    cam.position.set(14, 10, 14)
    const controls = new OrbitControls(cam, renderer.domElement)
    controls.enableDamping = false
    const hemi = new THREE.HemisphereLight(0xffffff, 0x555566, 1.4); scene.add(hemi)
    const sunL = new THREE.DirectionalLight(0xffffff, 2.2); sunL.position.set(8, 14, 6); scene.add(sunL, sunL.target)
    const grid = new THREE.GridHelper(60, 60, 0x667788, 0x334455); scene.add(grid)
    const state = { renderer, scene, cam, controls, model: null, grid, raf: 0, hemi, sun: sunL }
    three.current = state
    renderer.domElement.__bim = state   // test hook (camera inspection in e2e)
    const draw = () => { state.raf = 0; renderer.render(scene, cam) }
    const request = () => { if (!state.raf) state.raf = requestAnimationFrame(draw) }
    state.request = request
    initLook(state)
    controls.addEventListener('change', request)
    const ro = new ResizeObserver(() => {
      const w = el.clientWidth || 300, h = el.clientHeight || 300
      renderer.setSize(w, h, false); cam.aspect = w / h; cam.updateProjectionMatrix(); request()
    })
    ro.observe(el)
    return () => {
      ro.disconnect(); controls.dispose(); cancelAnimationFrame(state.raf)
      scene.traverse((o) => { if (o.geometry) o.geometry.dispose(); if (o.material) [].concat(o.material).forEach((m) => { Object.values(m).forEach((v) => v && v.isTexture && v.dispose()); m.dispose() }) })
      renderer.dispose(); renderer.forceContextLoss(); el.removeChild(renderer.domElement); three.current = null
    }
  }, [])

  useEffect(() => {
    const s = three.current
    if (!s) return
    applyLook(s, godot, sun, theme)
  }, [theme, godot, sun, info])   // `info` changes whenever a model finished loading

  const applyVisibility = useCallback(() => {
    const s = three.current
    if (!s || !s.model) return
    s.model.traverse((o) => {
      if (!o.isMesh) return
      let n = o; let hide = false
      while (n && n !== s.model) { if (isCollision(n.name)) hide = hide || !opts.col; if (isLod(n.name)) hide = hide || !opts.lod; n = n.parent }
      o.visible = !hide
      ;[].concat(o.material).forEach((m) => { m.wireframe = opts.wire })
    })
    s.request()
  }, [opts])

  const load = useCallback(async () => {
    const s = three.current
    if (!s || !project) return
    setErr(null)
    if (src === 'exports/preview/preview.glb' && !project.build_history.some((h) => h.kind === 'preview' && h.status === 'succeeded')) { setInfo(null); return } // nothing built yet: avoid a pointless 404
    try {
      const res = await fetch(`${api.fileUrl(project.id, src)}?t=${Date.now()}`)
      if (res.status === 404) { setInfo(null); return }
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const buf = await res.arrayBuffer()
      const gltf = await new GLTFLoader().parseAsync(buf, '')
      if (!three.current) return
      if (s.model) { s.scene.remove(s.model); s.model.traverse((o) => { if (o.geometry) o.geometry.dispose(); if (o.material) [].concat(o.material).forEach((m) => m.dispose()) }) }
      s.model = gltf.scene
      s.scene.add(gltf.scene)
      const box = new THREE.Box3().setFromObject(gltf.scene)
      const size = box.getSize(new THREE.Vector3()), c = box.getCenter(new THREE.Vector3())
      const r = Math.max(size.x, size.y, size.z, 1)
      s.controls.target.copy(c)
      s.cam.position.set(c.x + r * 1.1, c.y + r * 0.8, c.z + r * 1.1)
      s.cam.near = r / 500; s.cam.far = r * 50; s.cam.updateProjectionMatrix()
      s.grid.position.y = box.min.y
      let tris = 0, meshes = 0
      gltf.scene.traverse((o) => { if (o.isMesh) { meshes++; tris += (o.geometry.index ? o.geometry.index.count : o.geometry.attributes.position.count) / 3 } })
      setInfo({ tris: Math.round(tris), meshes, size: size.toArray().map((v) => Math.round(v * 100) / 100) })
      applyVisibility()
    } catch (e) { setErr(e.info ? formatError(e) : { what: 'Cannot display this model', where: src, why: String(e.message || e), fix: 'Rebuild the preview' }) }
  }, [project, src, applyVisibility])

  useEffect(() => { load() }, [src, stamp, project?.id]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { applyVisibility() }, [applyVisibility])

  const autoRan = useRef(false)
  useEffect(() => {   // the preview is fast now: build it automatically the first time the tab opens
    if (autoRan.current || !project || !project.elements.length) return
    autoRan.current = true
    if (!project.build_history.some((h) => h.kind === 'preview' && h.status === 'succeeded')) {
      job.run('/api/build/preview', {}).then((r) => { if (r) { setSrc('exports/preview/preview.glb'); setStamp((x) => x + 1) } })
    }
  }, [project?.id]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { W.current.collide = collide }, [collide])

  // ---- first-person walkthrough: WASD / arrows move, drag looks, Q/E turn, R/F up/down, Shift runs -------------------
  const levelBase = useCallback((lid) => {
    const lv = project?.levels.find((l) => l.id === lid) || project?.levels[0]
    return lv ? lv.elevation * toM(1, project.units.name) : 0
  }, [project])
  const placeCamera = useCallback((lid) => {
    const s = three.current; if (!s || !s.model) return
    const box = new THREE.Box3().setFromObject(s.model)
    const c = box.getCenter(new THREE.Vector3())
    const minElev = Math.min(...project.levels.map((l) => l.elevation * toM(1, project.units.name)))
    // the model's lowest point is the base of the lowest level's slab (~0.2 m below its walking surface)
    const y = box.min.y + 0.2 + (levelBase(lid) - minElev) + W.current.eye
    // pick the first candidate that is not buried inside a wall and has a floor under it
    const mats = new Set(); s.model.traverse((o) => { if (o.isMesh) [].concat(o.material).forEach((m) => mats.add(m)) })
    const sides = [...mats].map((m) => [m, m.side]); sides.forEach(([m]) => { m.side = THREE.DoubleSide })
    const rc = new THREE.Raycaster(); const dirs = [[1, 0, 0], [-1, 0, 0], [0, 0, 1], [0, 0, -1]].map((v) => new THREE.Vector3(...v))
    const size = box.getSize(new THREE.Vector3())
    const fr = [[0, 0], [-0.25, 0], [0.25, 0], [0, -0.25], [0, 0.25], [-0.25, -0.25], [0.25, 0.25], [-0.25, 0.25], [0.25, -0.25], [-0.12, 0.12], [0.12, -0.12]]
    let pick = [c.x, c.z]
    for (const [fx, fz] of fr) {
      const p = new THREE.Vector3(c.x + fx * size.x, y, c.z + fz * size.z)
      rc.set(p, new THREE.Vector3(0, -1, 0)); rc.far = W.current.eye + 0.6
      if (!rc.intersectObject(s.model, true).length) continue
      let buried = false
      for (const d of dirs) { rc.set(p, d); rc.far = 0.6; const h = rc.intersectObject(s.model, true)[0]; if (h && h.face && h.face.normal.clone().transformDirection(h.object.matrixWorld).dot(d) > 0) buried = true }
      if (!buried) { pick = [p.x, p.z]; break }
    }
    sides.forEach(([m, sd]) => { m.side = sd })
    s.cam.position.set(pick[0], y, pick[1])
  }, [project, levelBase])

  useEffect(() => {
    const s = three.current
    if (!s) return undefined
    if (!walk || !s.model) { if (!walk) { s.controls.enabled = true } return undefined }
    const w = W.current
    const el = s.renderer.domElement
    w.saved = { pos: s.cam.position.clone(), target: s.controls.target.clone(), fov: s.cam.fov, near: s.cam.near }
    s.controls.enabled = false
    s.cam.fov = 70; s.cam.near = 0.05; s.cam.rotation.order = 'YXZ'; s.cam.updateProjectionMatrix()
    w.yaw = Math.PI * 0.15; w.pitch = 0
    placeCamera(walkLevel)
    const rc = new THREE.Raycaster()
    const dir = new THREE.Vector3(), nrm = new THREE.Vector3(), org = new THREE.Vector3()
    const blocked = (d) => {   // first wall hit along d at knee and waist height, or null
      const len = d.length(); if (len < 1e-6) return null
      dir.copy(d).normalize()
      for (const h of [1.1, 0.5]) {
        org.set(s.cam.position.x, s.cam.position.y - h, s.cam.position.z)
        rc.set(org, dir); rc.far = len + 0.3
        const hit = rc.intersectObject(s.model, true).find((x) => x.object.visible)
        if (hit && hit.face) { return nrm.copy(hit.face.normal).transformDirection(hit.object.matrixWorld).clone() }
      }
      return null
    }
    const move = (d) => {
      if (w.collide) {
        const n = blocked(d)
        if (n) { n.y = 0; if (n.lengthSq() > 1e-6) { n.normalize(); d.addScaledVector(n, -d.dot(n)) } if (blocked(d)) return }
      }
      s.cam.position.add(d)
    }
    let last = performance.now(), raf = 0
    const tick = (now) => {
      const dt = Math.min(0.1, (now - last) / 1000); last = now
      const k = w.keys, fast = k.has('shift') ? 2.5 : 1
      const f = (k.has('w') || k.has('arrowup') ? 1 : 0) - (k.has('s') || k.has('arrowdown') ? 1 : 0) + w.dpad.f
      const r = (k.has('d') || k.has('arrowright') ? 1 : 0) - (k.has('a') || k.has('arrowleft') ? 1 : 0) + w.dpad.s
      const turn = (k.has('q') ? 1 : 0) - (k.has('e') ? 1 : 0)
      const up = (k.has('r') ? 1 : 0) - (k.has('f') ? 1 : 0)
      if (turn) w.yaw += turn * 1.6 * dt
      if (up) { s.cam.position.y += up * 2 * dt }
      if (f || r) {
        const sp = 2.6 * fast * dt, fy = -Math.cos(w.yaw), fx = -Math.sin(w.yaw)
        const d = new THREE.Vector3((fx * f + Math.cos(w.yaw) * r) * sp, 0, (fy * f - Math.sin(w.yaw) * r) * sp)
        move(d)
      }
      s.cam.rotation.set(w.pitch, w.yaw, 0)
      s.renderer.render(s.scene, s.cam)
      raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    const typing = () => { const a = document.activeElement; return a && ['INPUT', 'TEXTAREA', 'SELECT'].includes(a.tagName) }
    const kd = (e) => { if (typing()) return; const key = e.key.toLowerCase(); if (key === 'escape') { setWalk(false); return } if (['w', 'a', 's', 'd', 'q', 'e', 'r', 'f', 'shift', 'arrowup', 'arrowdown', 'arrowleft', 'arrowright'].includes(key)) { w.keys.add(key); e.preventDefault() } }
    const ku = (e) => { w.keys.delete(e.key.toLowerCase()) }
    let drag = null
    const pd = (e) => { drag = { x: e.clientX, y: e.clientY }; el.setPointerCapture?.(e.pointerId) }
    const pm = (e) => { if (!drag) return; w.yaw -= (e.clientX - drag.x) * 0.005; w.pitch = Math.max(-1.45, Math.min(1.45, w.pitch - (e.clientY - drag.y) * 0.005)); drag = { x: e.clientX, y: e.clientY } }
    const pu = () => { drag = null }
    const tp = (e) => {   // double-click a floor to stand there
      const r = el.getBoundingClientRect()
      rc.setFromCamera(new THREE.Vector2(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1), s.cam); rc.far = 200
      const h = rc.intersectObject(s.model, true).find((x) => x.face && x.face.normal.clone().transformDirection(x.object.matrixWorld).y > 0.6)
      if (h) s.cam.position.set(h.point.x, h.point.y + w.eye, h.point.z)
    }
    el.addEventListener('dblclick', tp)
    window.addEventListener('keydown', kd); window.addEventListener('keyup', ku)
    el.addEventListener('pointerdown', pd); el.addEventListener('pointermove', pm); el.addEventListener('pointerup', pu); el.addEventListener('pointercancel', pu)
    el.style.touchAction = 'none'
    return () => {
      cancelAnimationFrame(raf)
      window.removeEventListener('keydown', kd); window.removeEventListener('keyup', ku)
      el.removeEventListener('dblclick', tp); el.removeEventListener('pointerdown', pd); el.removeEventListener('pointermove', pm); el.removeEventListener('pointerup', pu); el.removeEventListener('pointercancel', pu)
      w.keys.clear(); w.dpad = { f: 0, s: 0 }
      el.style.touchAction = ''
      s.cam.rotation.order = 'XYZ'; s.cam.fov = w.saved.fov; s.cam.near = w.saved.near; s.cam.updateProjectionMatrix()
      s.cam.position.copy(w.saved.pos); s.controls.target.copy(w.saved.target); s.controls.enabled = true; s.controls.update()
      s.request()
    }
  }, [walk, info]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (walk) placeCamera(walkLevel) }, [walkLevel]) // eslint-disable-line react-hooks/exhaustive-deps
  const dpad = (f, s2) => ({
    onPointerDown: (e) => { e.preventDefault(); W.current.dpad = { f, s: s2 } },
    onPointerUp: () => { W.current.dpad = { f: 0, s: 0 } }, onPointerLeave: () => { W.current.dpad = { f: 0, s: 0 } }, onPointerCancel: () => { W.current.dpad = { f: 0, s: 0 } },
  })

  // ---- carve mode: click a wall in the 3D view → its carving window opens (then the preview is rebuilt when it closes)
  const wasOpen = useRef(false)
  useEffect(() => {
    const s = three.current
    if (!carve || walk || !s || !project) return undefined
    const el = s.renderer.domElement, rc = new THREE.Raycaster()
    let down = null
    const pd = (e) => { down = { x: e.clientX, y: e.clientY } }
    const pu = (e) => {
      if (!down || Math.hypot(e.clientX - down.x, e.clientY - down.y) > 5 || !s.model) { down = null; return }
      down = null
      const r = el.getBoundingClientRect()
      rc.setFromCamera(new THREE.Vector2(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1), s.cam); rc.far = 1e4
      const hit = rc.intersectObject(s.model, true).find((x) => x.object.visible && x.face)
      if (!hit) { setCarveMsg(t('pv_carve_none')); return }
      const n = hit.face.normal.clone().transformDirection(hit.object.matrixWorld)
      let o = hit.object, id = null
      while (o && !id) { id = o.userData && o.userData.bim_id; o = o.parent }      // the fast preview tags every node with its element id
      const wall = id && app.project.elements.find((x) => x.id === id && x.type === 'wall')
      if (!wall) { setCarveMsg(t('pv_carve_none')); return }
      const pk = { wallId: wall.id, side: wallSide(wall, n) }
      setCarveMsg('')
      app.select([pk.wallId]); app.set({ faceWall: pk.wallId, faceSide: pk.side })
    }
    el.addEventListener('pointerdown', pd); el.addEventListener('pointerup', pu)
    el.style.cursor = 'crosshair'
    return () => { el.removeEventListener('pointerdown', pd); el.removeEventListener('pointerup', pu); el.style.cursor = '' }
  }, [carve, walk, info, project?.id, app.project]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (app.faceWall) { wasOpen.current = true; return }
    if (wasOpen.current && carve) { wasOpen.current = false; job.run('/api/build/preview', {}).then((r) => { if (r) { setSrc('exports/preview/preview.glb'); setStamp((x) => x + 1) } }) }
  }, [app.faceWall]) // eslint-disable-line react-hooks/exhaustive-deps

  if (!project) return <NeedProject />
  const builds = project.build_history.filter((h) => h.output && /\.glb$/.test(h.output)).reverse()
  const build = async () => {
    const r = await job.run('/api/build/preview', {})
    if (r) { setSrc('exports/preview/preview.glb'); setStamp((x) => x + 1) }
  }
  const g = job.result?.geometry

  return (
    <div className="page full">
      <div className="pv-bar">
        <h2>{t('pv_title')}</h2>
        <div className="row wrap">
          <button type="button" className="btn primary" disabled={job.busy} onClick={build}>{job.busy ? t('running') : t('pv_build')}</button>
          <Select value={src} onChange={(v) => setSrc(v)} options={[{ value: 'exports/preview/preview.glb', label: 'preview' }, ...builds.map((b) => ({ value: b.output, label: `${b.kind} · ${b.output.split('/').slice(-2).join('/')}` }))]} />
          <button type="button" className={`btn ${carve ? 'primary' : ''}`} data-testid="carve-toggle" disabled={!info || walk} aria-pressed={carve} onClick={() => { setCarve(!carve); setCarveMsg('') }}>⛏ {t('pv_carve')}</button>
          <button type="button" className={`btn ${walk ? 'primary' : ''}`} data-testid="walk-toggle" disabled={!info} aria-pressed={walk} onClick={() => { if (!walk && !walkLevel) setWalkLevel(project.levels[0]?.id); setWalk(!walk) }}>{walk ? t('pv_walk_exit') : t('pv_walk')}</button>
          {walk && project.levels.length > 1 && <Select value={walkLevel} onChange={setWalkLevel} options={project.levels.map((l) => ({ value: l.id, label: l.name }))} />}
          {walk && <Toggle checked={collide} label={t('pv_walk_collide')} onChange={setCollide} />}
          <Toggle checked={godot} label={t('pv_godot')} onChange={setGodot} />
          {godot && <><label className="small">{t('pv_sun_elev')} {sun.elev}°<input type="range" min={5} max={90} value={sun.elev} data-testid="sun-elev" onChange={(e) => setSun({ ...sun, elev: +e.target.value })} /></label><label className="small">{t('pv_sun_az')} {sun.az}°<input type="range" min={0} max={360} value={sun.az} onChange={(e) => setSun({ ...sun, az: +e.target.value })} /></label></>}
          <Toggle checked={opts.wire} label={t('pv_wire')} onChange={(v) => setOpts({ ...opts, wire: v })} />
          <Toggle checked={opts.col} label={t('pv_collision')} onChange={(v) => setOpts({ ...opts, col: v })} />
          <Toggle checked={opts.lod} label={t('pv_lod')} onChange={(v) => setOpts({ ...opts, lod: v })} />
        </div>
      </div>
      <JobBox job={job} />
      <ErrorBox error={err} />
      <div className="pv-wrap">
        <div ref={mount} className="pv-canvas" data-testid="preview-canvas" />
        {!info && !job.busy && <div className="pv-empty">{t('pv_none')}</div>}
        {carve && !walk && <div className="pv-walkhint" data-testid="carve-hint">{carveMsg || t('pv_carve_hint')}</div>}
        {walk && <div className="pv-walkhint" data-testid="walk-hint">{t('pv_walk_hint')}</div>}
        {walk && (
          <div className="pv-dpad" aria-label={t('pv_walk')}>
            <button type="button" className="btn" {...dpad(1, 0)} aria-label="forward">▲</button>
            <div className="row"><button type="button" className="btn" {...dpad(0, -1)} aria-label="left">◀</button><button type="button" className="btn" {...dpad(-1, 0)} aria-label="back">▼</button><button type="button" className="btn" {...dpad(0, 1)} aria-label="right">▶</button></div>
          </div>
        )}
        <div className="pv-info">
          {info && <span>{info.tris} ▲ · {info.meshes} meshes · {info.size.join(' × ')} m</span>}
          {g && <span> · {g.rebuilt} {t('pv_rebuilt')} / {g.cached} {t('pv_cached')}</span>}
        </div>
      </div>
      {app.faceWall && <WallFace />}
      <p className="muted">{t('pv_note')} {t('pv_incremental')}</p>
    </div>
  )
}
