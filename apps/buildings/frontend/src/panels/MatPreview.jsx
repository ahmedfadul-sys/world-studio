import { useEffect, useRef } from 'react'
import * as THREE from 'three'
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js'
import { RoomEnvironment } from 'three/examples/jsm/environments/RoomEnvironment.js'

/** Small PBR preview (sphere + slab) of a material's baked maps; tile size in metres sets the texture repeat. */
export default function MatPreview({ pid, mat }) {
  const host = useRef(null)
  const st = useRef(null)
  useEffect(() => {
    const el = host.current
    let renderer
    try { renderer = new THREE.WebGLRenderer({ antialias: true }) } catch { return undefined }
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2))
    renderer.setSize(el.clientWidth, el.clientHeight)
    el.appendChild(renderer.domElement)
    const scene = new THREE.Scene()
    scene.background = new THREE.Color(0x1d2126)
    const pm = new THREE.PMREMGenerator(renderer)
    scene.environment = pm.fromScene(new RoomEnvironment(), 0.04).texture
    const cam = new THREE.PerspectiveCamera(35, el.clientWidth / el.clientHeight, 0.1, 50)
    cam.position.set(0, 1.1, 5.2)
    const sun = new THREE.DirectionalLight(0xffffff, 1.6); sun.position.set(3, 4, 5); scene.add(sun)
    const ctl = new OrbitControls(cam, renderer.domElement)
    ctl.enableDamping = true; ctl.enablePan = false; ctl.minDistance = 3; ctl.maxDistance = 9
    const material = new THREE.MeshStandardMaterial({ color: 0xb8b2a7, roughness: 0.8, metalness: 0 })
    const sphere = new THREE.Mesh(new THREE.SphereGeometry(1.15, 64, 48), material); sphere.position.x = -1.35; scene.add(sphere)
    const slab = new THREE.Mesh(new THREE.BoxGeometry(2.3, 2.3, 0.35), material); slab.position.x = 1.35; scene.add(slab)
    for (const g of [sphere.geometry, slab.geometry]) g.setAttribute('uv2', g.attributes.uv)
    let raf = 0, alive = true
    let lastT = 0
    const loop = (now = 0) => {        // ~30 fps, and nothing at all while the tab is hidden (saves GPU/CPU on small machines)
      if (!alive) return
      raf = requestAnimationFrame(loop)
      if (document.hidden || now - lastT < 33) return
      lastT = now; ctl.update(); sphere.rotation.y += 0.008; renderer.render(scene, cam)
    }
    loop()
    const ro = new ResizeObserver(() => { renderer.setSize(el.clientWidth, el.clientHeight); cam.aspect = el.clientWidth / el.clientHeight; cam.updateProjectionMatrix() })
    ro.observe(el)
    st.current = { material, textures: [] }
    return () => {
      alive = false; cancelAnimationFrame(raf); ro.disconnect(); ctl.dispose()
      st.current.textures.forEach((x) => x.dispose()); material.dispose(); sphere.geometry.dispose(); slab.geometry.dispose(); pm.dispose(); renderer.dispose(); renderer.forceContextLoss()
      el.removeChild(renderer.domElement)
    }
  }, [])

  useEffect(() => {
    const s = st.current
    if (!s) return undefined
    const m = s.material
    s.textures.forEach((x) => x.dispose()); s.textures = []
    m.map = m.normalMap = m.roughnessMap = m.metalnessMap = null
    m.color.set(mat.color); m.roughness = mat.roughness; m.metalness = mat.metallic
    const loader = new THREE.TextureLoader()
    // sphere / slab are ~2.3 units wide; a texture tile is `tile` metres, so a 2.3 m object shows 2.3/tile repeats
    const rep = Math.max(0.5, 2.3 * (mat.uv_scale || 1))
    const load = (name, srgb, apply) => {
      if (!name) return
      loader.load(`/api/projects/${pid}/files/textures/${encodeURIComponent(name)}`, (t) => {
        t.wrapS = t.wrapT = THREE.RepeatWrapping; t.repeat.set(rep, rep); t.anisotropy = 8
        t.colorSpace = srgb ? THREE.SRGBColorSpace : THREE.NoColorSpace
        s.textures.push(t); apply(t); m.needsUpdate = true
      })
    }
    load(mat.texture, true, (t) => { m.map = t; m.color.set('#ffffff') })
    load(mat.normal_texture, false, (t) => { m.normalMap = t; m.normalScale.set(1, 1) })
    load(mat.rough_texture, false, (t) => { m.roughnessMap = t; m.metalnessMap = t; m.roughness = 1; m.metalness = 1 })
    return undefined
  }, [pid, mat.texture, mat.normal_texture, mat.rough_texture, mat.color, mat.roughness, mat.metallic, mat.uv_scale])

  return <div ref={host} className="mat-preview" data-testid="mat-preview" role="img" aria-label="material preview" />
}
