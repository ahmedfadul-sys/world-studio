import * as THREE from 'three'

// Approximation of Godot 4's default look: ProceduralSky ambient + sun with soft shadows + ACES tonemapping.
const SKY = { top: 0x6073a0, horizon: 0xb8c0cc, ground: 0x2a2018 }   // Godot ProceduralSky defaults, roughly (sRGB)

function skyDome() {
  const mat = new THREE.ShaderMaterial({
    side: THREE.BackSide, depthWrite: false, toneMapped: false,
    uniforms: { top: { value: new THREE.Color(SKY.top) }, hor: { value: new THREE.Color(SKY.horizon) }, gnd: { value: new THREE.Color(SKY.ground) } },
    vertexShader: 'varying vec3 vP; void main(){ vP = normalize(position); gl_Position = projectionMatrix * modelViewMatrix * vec4(position,1.0); }',
    fragmentShader: 'uniform vec3 top; uniform vec3 hor; uniform vec3 gnd; varying vec3 vP; void main(){ float h = vP.y; vec3 c = h > 0.0 ? mix(hor, top, pow(h, 0.55)) : mix(hor, gnd, pow(-h, 0.4)); gl_FragColor = vec4(c, 1.0); }',
  })
  const m = new THREE.Mesh(new THREE.SphereGeometry(1, 24, 16), mat)
  m.frustumCulled = false; m.renderOrder = -1
  m.onBeforeRender = (_r, _s, cam) => { m.position.copy(cam.position); m.scale.setScalar(cam.far * 0.5) }   // always inside the far plane
  return m
}

/** Sun direction from elevation / azimuth in degrees. */
export const sunVector = (elev, az, r = 1) => {
  const e = (elev * Math.PI) / 180, a = (az * Math.PI) / 180
  return new THREE.Vector3(Math.cos(e) * Math.sin(a) * r, Math.sin(e) * r, Math.cos(e) * Math.cos(a) * r)
}

/** One-time additions to the three.js state: sky dome + environment map. Returns objects to dispose on unmount. */
export function initLook(state) {
  const sky = skyDome(); sky.visible = false; state.scene.add(sky); state.sky = sky
  const pm = new THREE.PMREMGenerator(state.renderer)
  const envScene = new THREE.Scene(); envScene.add(skyDome())
  state.envTex = pm.fromScene(envScene, 0.02).texture
  pm.dispose()
}

/** Switch between the plain editor lighting and the Godot-like look; `sun` = {elev, az}. */
export function applyLook(state, godot, sun, theme) {
  const { renderer, scene, model } = state
  if (!state.sky) return
  state.sky.visible = godot
  state.hemi.visible = !godot
  scene.environment = godot ? state.envTex : null
  scene.environmentIntensity = 0.85
  scene.background = godot ? null : new THREE.Color(theme === 'dark' ? 0x14171c : 0xeae6dc)
  state.grid.visible = !godot
  renderer.toneMapping = godot ? THREE.ACESFilmicToneMapping : THREE.NoToneMapping
  renderer.toneMappingExposure = 1
  renderer.shadowMap.enabled = godot
  renderer.shadowMap.type = THREE.PCFSoftShadowMap
  const s = state.sun
  s.castShadow = godot
  s.intensity = godot ? 3.0 : 2.2
  let centre = new THREE.Vector3(), radius = 20
  if (model) {
    const box = new THREE.Box3().setFromObject(model)
    if (!box.isEmpty()) { box.getCenter(centre); radius = Math.max(4, box.getSize(new THREE.Vector3()).length() / 2) }
    model.traverse((o) => { if (o.isMesh) { o.castShadow = godot; o.receiveShadow = godot; [].concat(o.material).forEach((m) => { m.needsUpdate = true }) } })
  }
  if (godot) {
    s.position.copy(centre).add(sunVector(sun.elev, sun.az, radius * 3))
    s.target.position.copy(centre); s.target.updateMatrixWorld()
    const c = s.shadow.camera
    c.left = c.bottom = -radius * 1.2; c.right = c.top = radius * 1.2; c.near = 0.5; c.far = radius * 7
    c.updateProjectionMatrix()
    s.shadow.mapSize.set(2048, 2048); s.shadow.bias = -0.0004; s.shadow.normalBias = 0.03
    if (s.shadow.map) { s.shadow.map.dispose(); s.shadow.map = null }
  } else s.position.set(8, 14, 6)
  state.request()
}
