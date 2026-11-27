import { useCallback, useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { previewGlb } from "./api";
import type { Project } from "./types";

interface Scene3D {
  renderer: THREE.WebGLRenderer; scene: THREE.Scene; camera: THREE.PerspectiveCamera; controls: OrbitControls; sun: THREE.DirectionalLight;
  world: THREE.Group | null; markers: THREE.Group; terrain: THREE.Mesh | null; center: THREE.Vector3; span: number;
}

function disposeTree(o: THREE.Object3D) {
  o.traverse((n) => {
    const m = n as THREE.Mesh;
    if (m.geometry) m.geometry.dispose();
    const mats = Array.isArray(m.material) ? m.material : m.material ? [m.material] : [];
    for (const mt of mats) {
      for (const v of Object.values(mt as unknown as Record<string, unknown>)) if (v instanceof THREE.Texture) v.dispose();
      mt.dispose();
    }
  });
}

/** نافذة معاينة العالم ثلاثياً: تعرض نفس ملف GLB الذي سيُصدَّر (بدقة أخفّ) فما تراه هو ما تحصل عليه. */
export default function World3D({ project, onClose }: { project: Project; onClose: () => void }) {
  const host = useRef<HTMLDivElement>(null);
  const S = useRef<Scene3D | null>(null);
  const loaded = useRef<Project | null>(null);
  const abort = useRef<AbortController | null>(null);
  const [res, setRes] = useState(257);
  const [tex, setTex] = useState(1024);
  const [exag, setExag] = useState(1);
  const [az, setAz] = useState(135);
  const [el, setEl] = useState(40);
  const [sea, setSea] = useState(true);
  const [wire, setWire] = useState(false);
  const [marks, setMarks] = useState(true);
  const [status, setStatus] = useState<"idle" | "loading" | "ready" | "error">("idle");
  const [msg, setMsg] = useState<string | null>(null);
  const [info, setInfo] = useState<{ vertices: number; triangles: number } | null>(null);
  const [hover, setHover] = useState<string>("");
  const [stale, setStale] = useState(false);

  const placeSun = useCallback(() => {
    const s = S.current; if (!s) return;
    const a = (az * Math.PI) / 180, e = (el * Math.PI) / 180, r = s.span * 2;
    s.sun.position.set(s.center.x + r * Math.cos(e) * Math.sin(a), s.center.y + r * Math.sin(e), s.center.z - r * Math.cos(e) * Math.cos(a));
    s.sun.target.position.copy(s.center); s.sun.target.updateMatrixWorld();
  }, [az, el]);

  // ── إنشاء المشهد مرة واحدة ──
  useEffect(() => {
    const el0 = host.current!;
    const renderer = new THREE.WebGLRenderer({ antialias: true, preserveDrawingBuffer: false });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    el0.appendChild(renderer.domElement);
    const scene = new THREE.Scene();
    scene.background = new THREE.Color(0x9ec7ee);
    const camera = new THREE.PerspectiveCamera(50, 1, 1, 1000);
    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true; controls.maxPolarAngle = Math.PI / 2 - 0.02;
    scene.add(new THREE.HemisphereLight(0xdbeaff, 0x5a5040, 0.9));
    const sun = new THREE.DirectionalLight(0xfff2dd, 2.6);
    scene.add(sun, sun.target);
    const markers = new THREE.Group(); scene.add(markers);
    S.current = { renderer, scene, camera, controls, sun, world: null, markers, terrain: null, center: new THREE.Vector3(), span: 1000 };
    const fit = () => {
      const w = el0.clientWidth || 800, h = el0.clientHeight || 500;
      renderer.setSize(w, h); camera.aspect = w / h; camera.updateProjectionMatrix();
    };
    fit();
    const ro = new ResizeObserver(fit); ro.observe(el0);
    renderer.setAnimationLoop(() => { controls.update(); renderer.render(scene, camera); });
    const key = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", key);
    return () => {
      window.removeEventListener("keydown", key); ro.disconnect(); abort.current?.abort();
      renderer.setAnimationLoop(null); controls.dispose();
      if (S.current?.world) disposeTree(S.current.world);
      disposeTree(markers); renderer.dispose(); renderer.domElement.remove(); S.current = null;
    };
  }, []); // eslint-disable-line

  // ── تحميل/تحديث المعاينة ──
  const load = useCallback(async (first = false) => {
    const s = S.current; if (!s) return;
    abort.current?.abort(); const ac = new AbortController(); abort.current = ac;
    setStatus("loading"); setMsg(null);
    const snap = project;
    try {
      const r = await previewGlb(snap, res, tex, ac.signal);
      const gltf = await new GLTFLoader().parseAsync(r.data, "");
      if (ac.signal.aborted || S.current !== s) { disposeTree(gltf.scene); return; }
      if (s.world) { s.scene.remove(s.world); disposeTree(s.world); }
      disposeTree(s.markers); s.markers.clear();
      const world = gltf.scene as unknown as THREE.Group;
      s.world = world; s.scene.add(world);
      const maxAniso = s.renderer.capabilities.getMaxAnisotropy();
      let terrain: THREE.Mesh | null = null;
      world.traverse((n) => {
        const m = n as THREE.Mesh;
        if (m.isMesh && m.name === "Terrain") { terrain = m; const mt = m.material as THREE.MeshStandardMaterial; if (mt.map) mt.map.anisotropy = maxAniso; }
      });
      s.terrain = terrain;
      const box = new THREE.Box3().setFromObject(world), size = box.getSize(new THREE.Vector3());
      s.span = Math.max(size.x, size.z, 1); box.getCenter(s.center);
      // علامات المنشآت ونقاط الاهتمام (العقد الفارغة في الملف) كمخاريط ملوّنة بحجم يتناسب مع العالم
      const mk = world.getObjectByName("Markers");
      const cone = new THREE.ConeGeometry(s.span / 260, s.span / 90, 10);
      mk?.children.forEach((c) => {
        const extras = (c.userData ?? {}) as { type?: string };
        const m = new THREE.Mesh(cone, new THREE.MeshStandardMaterial({ color: extras.type === "poi" ? 0xff4fa3 : 0xffa11f }));
        const p = new THREE.Vector3(); c.getWorldPosition(p);
        m.userData.base = p.clone(); m.position.copy(p).setY(p.y * exag + s.span / 180); m.rotation.x = Math.PI; s.markers.add(m);
      });
      if (mk) mk.visible = false;
      if (first || !loaded.current) {
        s.camera.near = s.span / 4000; s.camera.far = s.span * 30; s.camera.updateProjectionMatrix();
        s.controls.minDistance = s.span / 300; s.controls.maxDistance = s.span * 6;
        s.camera.position.set(s.center.x + s.span * 0.75, s.center.y + s.span * 0.65, s.center.z + s.span * 0.95);
        s.controls.target.copy(s.center); s.controls.update();
      }
      loaded.current = snap; setStale(false); setInfo({ vertices: r.vertices, triangles: r.triangles }); setStatus("ready");
    } catch (e) {
      if (ac.signal.aborted) return;
      setStatus("error"); setMsg(String((e as Error).message));
    }
  }, [project, res, tex]); // eslint-disable-line

  useEffect(() => { void load(true); }, [res, tex]); // eslint-disable-line
  useEffect(() => { setStale(!!loaded.current && loaded.current !== project); }, [project]);
  useEffect(() => { // تحديث تلقائي بعد توقف التعديل: الخامات الجديدة تظهر دون ضغط «تحديث»
    if (!loaded.current || loaded.current === project) return;
    const h = setTimeout(() => { void load(false); }, 1200);
    return () => clearTimeout(h);
  }, [project]); // eslint-disable-line

  // ── تأثير الضوابط على المشهد ──
  useEffect(() => {
    const s = S.current; if (!s?.world) return;
    s.world.scale.y = exag; s.world.updateMatrixWorld(true);
    s.markers.children.forEach((m) => { const b = m.userData.base as THREE.Vector3; m.position.set(b.x, b.y * exag + s.span / 180, b.z); });
  }, [exag, status]);
  useEffect(() => { const s = S.current; if (!s?.world) return; for (const n of ["Sea", "Lakes", "Rivers"]) { const o = s.world.getObjectByName(n); if (o) o.visible = sea; } }, [sea, status]);
  useEffect(() => { const s = S.current; if (s?.terrain) (s.terrain.material as THREE.MeshStandardMaterial).wireframe = wire; }, [wire, status]);
  useEffect(() => { const s = S.current; if (s) s.markers.visible = marks; }, [marks, status]);
  useEffect(() => { placeSun(); }, [placeSun, status]);

  // ── إحداثيات تحت المؤشر ──
  const lastHover = useRef(0);
  const onMove = (e: React.PointerEvent) => {
    const s = S.current; if (!s?.terrain || performance.now() - lastHover.current < 120) return;
    lastHover.current = performance.now();
    const r = s.renderer.domElement.getBoundingClientRect();
    const ndc = new THREE.Vector2(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1);
    const rc = new THREE.Raycaster(); rc.setFromCamera(ndc, s.camera);
    const hit = rc.intersectObject(s.terrain, false)[0];
    setHover(hit ? `X ${hit.point.x.toFixed(0)} · Y ${(-hit.point.z).toFixed(0)} · Z ${(hit.point.y / exag).toFixed(1)}` : "");
  };

  const topView = () => { const s = S.current; if (!s) return; s.camera.position.set(s.center.x, s.center.y + s.span * 1.4, s.center.z + 0.01); s.controls.target.copy(s.center); s.controls.update(); };
  const reset = () => { const s = S.current; if (!s) return; s.camera.position.set(s.center.x + s.span * 0.75, s.center.y + s.span * 0.65, s.center.z + s.span * 0.95); s.controls.target.copy(s.center); s.controls.update(); };
  const shot = () => {
    const s = S.current; if (!s) return;
    s.renderer.render(s.scene, s.camera);
    const a = document.createElement("a"); a.href = s.renderer.domElement.toDataURL("image/png"); a.download = "world_preview.png"; a.click();
  };

  return (
    <div className="modal3d" role="dialog" aria-modal="true" aria-label="معاينة العالم ثلاثية الأبعاد">
      <div className="m3d-bar">
        <strong>معاينة العالم</strong>
        <label>الدقة <select value={res} onChange={(e) => setRes(Number(e.target.value))}>{[129, 257, 513].map((v) => <option key={v} value={v}>{v}</option>)}</select></label>
        <label>الخامة <select value={tex} onChange={(e) => setTex(Number(e.target.value))}>{[512, 1024, 2048].map((v) => <option key={v} value={v}>{v}</option>)}</select></label>
        <label>تضخيم الارتفاع ×{exag.toFixed(1)} <input type="range" min={1} max={6} step={0.1} value={exag} onChange={(e) => setExag(Number(e.target.value))} /></label>
        <label>اتجاه الشمس <input type="range" min={0} max={360} value={az} onChange={(e) => setAz(Number(e.target.value))} /></label>
        <label>ارتفاعها <input type="range" min={5} max={85} value={el} onChange={(e) => setEl(Number(e.target.value))} /></label>
        <label><input type="checkbox" checked={sea} onChange={(e) => setSea(e.target.checked)} /> الماء (بحر وبحيرات وأنهار)</label>
        <label><input type="checkbox" checked={marks} onChange={(e) => setMarks(e.target.checked)} /> العلامات</label>
        <label><input type="checkbox" checked={wire} onChange={(e) => setWire(e.target.checked)} /> شبكة</label>
        <button onClick={reset}>إعادة ضبط</button><button onClick={topView}>من الأعلى</button><button onClick={shot}>لقطة PNG</button>
        <button className="primary" disabled={status === "loading"} onClick={() => load(false)}>{stale ? "حدّث (المشروع تغيّر)" : "تحديث"}</button>
        <button className="danger" onClick={onClose} aria-label="إغلاق">✕</button>
      </div>
      <div className="m3d-stage" ref={host} onPointerMove={onMove} dir="ltr">
        {status === "loading" && <div className="m3d-note">جارٍ بناء المعاينة…</div>}
        {status === "error" && <div className="m3d-note error">{msg}</div>}
      </div>
      <div className="m3d-foot">
        <span dir="ltr">{hover}</span>
        {info && <span>{info.vertices.toLocaleString()} رأس · {info.triangles.toLocaleString()} مثلث</span>}
        <span>السحب: تدوير · العجلة: تقريب · زر الفأرة الأيمن: إزاحة</span>
      </div>
    </div>
  );
}
