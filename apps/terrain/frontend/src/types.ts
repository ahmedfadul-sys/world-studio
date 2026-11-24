export type PointKind = "mountain" | "hill" | "plateau" | "mesa" | "volcano" | "island" | "atoll" | "terraces" | "scree" | "delta"
  | "crater" | "basin" | "lake" | "sinkhole" | "cave" | "marsh" | "dune";
export type LineKind = "river" | "road" | "valley" | "ridge" | "cliff";
export type XY = [number, number];

export interface CellSpec { col: number; row: number; elevation_m: number; rise_m: number; run_m: number; aspect_deg: number }
export interface PointFeature {
  id: string; kind: PointKind; x_m: number; y_m: number; diameter_m: number; high_m: number; low_m: number;
  shape: "cone" | "dome" | "rugged"; inner_ratio: number; depth_ratio: number; amplitude_m: number; wavelength_m: number;
  direction_deg: number; steps: number; roughness: number; seed: number;
  mat_low: string | null; mat_mid: string | null; mat_high: string | null;
}
export interface Fall { at: number; height_m: number; length_m: number }
export interface LineFeature {
  id: string; kind: LineKind; points: XY[]; width_m: number; width_end_m: number | null; depth_m: number; depth_end_m: number | null;
  profile: "v" | "u"; max_grade: number; shoulder_m: number; min_slope: number; enforce_descent: boolean; grade_mode: "regrade" | "carve"; grade_width_m: number;
  falls: Fall[]; roughness: number; seed: number; mat_main: string | null; mat_edge: string | null;
  floor_m: number | null; top_m: number | null;
}
export interface Biome {
  id: string; name: string; polygon: XY[]; base_elevation_m: number; noise_amplitude_m: number; noise_scale_m: number; octaves: number;
  blend_m: number; min_elev_m: number | null; max_elev_m: number | null; clamp: boolean; mat_base: string | null;
}
export type SiteKind = "village" | "town" | "city" | "castle" | "ruins" | "farm" | "industrial" | "power_plant" | "mine" | "camp" | "tower" | "temple";
export type ZoneLayer = "grass" | "shrubs" | "forest" | "flowers" | "reeds" | "rocks" | "farmland" | "hummocks" | "rocky";
export interface Site {
  id: string; kind: SiteKind; name: string; x_m: number; y_m: number; shape: "circle" | "rect"; diameter_m: number; width_m: number; length_m: number;
  rotation_deg: number; level_mode: "mean" | "min" | "max" | "fixed"; level_m: number; level_offset_m: number; blend_m: number; strength: number;
  mat_ground: string | null; density: number; seed: number; bim_project?: string | null;
}
export interface Zone {
  id: string; name: string; layer: ZoneLayer; polygon: XY[]; density: number; falloff_m: number; max_slope_deg: number;
  min_elev_m: number | null; max_elev_m: number | null; patchiness: number; amplitude_m: number; wavelength_m: number; seed: number; mat_main: string | null;
}
export type PoiKind = "poi" | "landmark" | "player_start" | "boss" | "story" | "quest" | "dungeon" | "resource" | "fast_travel";
export interface Poi {
  id: string; kind: PoiKind; name: string; x_m: number; y_m: number; radius_m: number; order: number; difficulty: number; level_min: number; level_max: number;
  dwell_min: number; landmark_height_m: number; flatten: boolean; blend_m: number; notes: string;
}
export interface PlayerModel { speed_mps: number; eye_height_m: number; max_slope_deg: number; view_distance_m: number; can_swim: boolean }
export type DetailKind = "soil" | "rock" | "sand" | "gravel";
export interface Material { id: string; name: string; color: string; albedo: string | null; normal: string | null; roughness: string | null; height: string | null; pack: string | null; roughness_value: number; tile_m: number; detail_amp_m: number | null; detail_kind: DetailKind | null }
export type KitRole = "house" | "main" | "wall" | "gate" | "tower" | "prop";
export interface KitPiece { id: string; name: string; role: KitRole; collection: string | null; width_m: number; length_m: number; height_m: number; weight: number; site_kinds: string[] }
export interface Kit { enabled: boolean; pieces: KitPiece[]; face_road: boolean; road_snap_m: number; walls: boolean; wall_kinds: string[]; gate_width_m: number; props_per_lot: number; seed: number }
export const defaultKit = (): Kit => ({ enabled: true, pieces: [], face_road: true, road_snap_m: 40, walls: true, wall_kinds: ["castle"], gate_width_m: 10, props_per_lot: 0.5, seed: 1 });
export const KIT_ROLES: [KitRole, string][] = [["house", "بيت"], ["main", "مبنى رئيسي"], ["wall", "سور"], ["gate", "بوابة"], ["tower", "برج"], ["prop", "زينة"]];
export const newKitPiece = (id: string, role: KitRole): KitPiece => ({ id, name: id, role, collection: null, weight: 1, site_kinds: [],
  width_m: role === "main" ? 20 : role === "wall" ? 1.5 : role === "gate" ? 2 : role === "tower" ? 6 : role === "prop" ? 2 : 8,
  length_m: role === "main" ? 20 : role === "wall" ? 6 : role === "gate" ? 10 : role === "tower" ? 6 : role === "prop" ? 2 : 10,
  height_m: role === "main" ? 14 : role === "wall" ? 5 : role === "gate" ? 7 : role === "tower" ? 12 : role === "prop" ? 1.2 : 6 });
export interface Roads {
  enabled: boolean; dust_width_m: number; dust_color: string; track_gauge_m: number; track_width_m: number; track_wear: number; track_depth_m: number; surface_variation: number;
}
export const defaultRoads = (): Roads => ({ enabled: true, dust_width_m: 3, dust_color: "#b59a72", track_gauge_m: 1.8, track_width_m: 0.45, track_wear: 0.6, track_depth_m: 0.04, surface_variation: 0.35 });
export interface Water {
  enabled: boolean; shore_width_m: number; foam_width_m: number; rapids_slope_deg: number; foam_amount: number;
  shallow_color: string; deep_color: string; absorption_depth_m: number; roughness: number; ior: number; wave_height_m: number; wave_scale_m: number; wave_speed: number;
}
export const defaultWater = (): Water => ({ enabled: true, shore_width_m: 6, foam_width_m: 3, rapids_slope_deg: 6, foam_amount: 1, shallow_color: "#3f9aa0", deep_color: "#0a2f4a",
  absorption_depth_m: 6, roughness: 0.04, ior: 1.333, wave_height_m: 0.15, wave_scale_m: 12, wave_speed: 0.5 });
export interface Detail { enabled: boolean; wavelength_max_m: number; slope_gain: number; seed: number }
export const defaultDetail = (): Detail => ({ enabled: false, wavelength_max_m: 24, slope_gain: 1, seed: 1 });
export type ScatterKind = "tree" | "bush" | "rock" | "grass" | "prop";
export type ScatterLayer = "grass" | "shrubs" | "forest" | "flowers" | "reeds" | "rocks" | "farmland";
export interface ScatterSpecies {
  id: string; name: string; kind: ScatterKind; layer: ScatterLayer; min_dist_m: number; scale_min: number; scale_max: number;
  max_slope_deg: number; min_elev_m: number | null; max_elev_m: number | null; align_to_normal: number; max_count: number; seed: number; asset: string | null;
}
export interface Scatter { enabled: boolean; species: ScatterSpecies[] }
export const defaultSpecies = (id: string, kind: ScatterKind = "tree"): ScatterSpecies => ({
  id, name: id, kind, layer: kind === "rock" ? "rocks" : kind === "bush" ? "shrubs" : kind === "grass" ? "grass" : "forest",
  min_dist_m: kind === "tree" ? 8 : kind === "rock" ? 6 : kind === "bush" ? 3 : 0.8, scale_min: 0.8, scale_max: 1.3, max_slope_deg: kind === "rock" ? 60 : 35,
  min_elev_m: null, max_elev_m: null, align_to_normal: kind === "rock" ? 0.7 : 0, max_count: 50000, seed: Math.floor(Math.random() * 100000) + 1, asset: null,
});
export interface Derived {
  enabled: boolean; curvature_scale_m: number; cavity_radius_m: number; stream_area_m2: number; slope_classes_deg: number[];
  convex_material: string | null; convex_amount: number; convex_min_slope_deg: number;
  hollow_material: string | null; hollow_amount: number; wet_material: string | null; wet_amount: number; wet_threshold: number;
}
export const defaultDerived = (): Derived => ({ enabled: true, curvature_scale_m: 8, cavity_radius_m: 12, stream_area_m2: 20000, slope_classes_deg: [5, 15, 30],
  convex_material: null, convex_amount: 0.7, convex_min_slope_deg: 10, hollow_material: null, hollow_amount: 0.7, wet_material: null, wet_amount: 0.7, wet_threshold: 0.65 });
export interface Surface {
  triplanar: boolean; triplanar_blend: number; break_tiling: boolean; break_strength: number; break_scale_m: number;
  height_blend: boolean; height_contrast: number; relief_m: number; normal_strength: number; normal_convention: "GL" | "DX"; cavity_strength: number; wet_darken: number; wet_gloss: number;
}
export const defaultSurface = (): Surface => ({ triplanar: true, triplanar_blend: 0.2, break_tiling: true, break_strength: 0.6, break_scale_m: 80, height_blend: true, height_contrast: 0.35, relief_m: 0.15, normal_strength: 1, normal_convention: "GL", cavity_strength: 0.5, wet_darken: 0.3, wet_gloss: 0.4 });
export interface PaintRules {
  default_material: string; slope_material: string | null; slope_start_deg: number; slope_full_deg: number;
  snow_material: string | null; snow_elev_m: number; snow_blend_m: number; beach_material: string | null; beach_height_m: number;
}
export interface Erosion { enabled: boolean; resolution: 257 | 513 | 1025; iterations: number; max_depth_m: number; deposition: number; thermal: boolean; talus_deg: number; smooth: number;
  mode: "stylized" | "sediment"; erodibility: number; deposition_rate: number; fans: boolean; fan_spread_m: number; gullies: boolean; gully_depth_m: number; gully_spacing_m: number;
  gully_length_cells: number; gully_min_slope_deg: number; gully_max_slope_deg: number; seed: number }
export interface Atmosphere {
  enabled: boolean; engine: "EEVEE" | "CYCLES"; view_transform: "AgX" | "Filmic" | "Standard"; exposure: number;
  sun_elevation: number; sun_azimuth: number; sun_energy: number; sun_size_deg: number;
  air_density: number; dust_density: number; ozone_density: number; sky_altitude_m: number | null;
  fog: boolean; fog_density: number | null; fog_anisotropy: number;
  camera: boolean; camera_azimuth: number; camera_distance_factor: number; camera_height_above_peak_m: number | null;
  focal_length_mm: number; sensor_width_mm: number; dof: boolean; f_stop: number;
}
export const defaultAtmosphere = (): Atmosphere => ({
  enabled: true, engine: "EEVEE", view_transform: "AgX", exposure: 0, sun_elevation: 28, sun_azimuth: 300, sun_energy: 4, sun_size_deg: 0.545,
  air_density: 1, dust_density: 1, ozone_density: 1, sky_altitude_m: null, fog: true, fog_density: null, fog_anisotropy: 0.35,
  camera: true, camera_azimuth: 225, camera_distance_factor: 0.6, camera_height_above_peak_m: null, focal_length_mm: 35, sensor_width_mm: 36, dof: true, f_stop: 4,
});
export interface Project {
  version: number; name: string;
  world: { size_x_m: number; size_y_m: number; cell_size_m: number; chunk_size_m: number; seed: number; sea_level_m: number };
  base: { elevation_m: number; noise_amplitude_m: number; noise_scale_m: number; octaves: number; noise_mode: "off" | "amplitude" | "range"; noise_min_m: number; noise_max_m: number; noise_bias: number; cell_blend: number; cell_detail: number };
  biomes: Biome[]; cells: CellSpec[]; points: PointFeature[]; lines: LineFeature[]; sites: Site[]; zones: Zone[]; pois: Poi[]; player: PlayerModel; materials: Material[]; paint: PaintRules; erosion: Erosion; kit: Kit; roads: Roads; water: Water; detail: Detail; scatter: Scatter; derived: Derived; surface: Surface; atmosphere: Atmosphere;
  export: { resolution: 513 | 1025 | 2049 | 4097; tile_px: 513 | 1025 | 2049; mask_px: 513 | 1025 | 2049; mode: "auto" | "fixed"; zmin_m: number; zmax_m: number; glb_resolution: 257 | 513 | 1025 | 2049; glb_texture_px: 1024 | 2048 | 4096 };
}
export interface LinearInfo { id: string; kind: LineKind; length_m: number; s: number[]; ground: number[]; design: number[] | null; x: number[]; y: number[] }
export interface Preview { color?: Uint8Array; nx: number; ny: number; zmin: number; zmax: number; u16: Uint16Array; errors: string[]; warnings: string[]; linear: LinearInfo[] }

interface PointMeta {
  label: string; neg: boolean; dia: number; rel: number; hi: string; lo: string; group: "pos" | "neg" | "special";
  inner?: [string, number]; depth?: boolean; shape?: boolean; noHL?: boolean;
  amp?: string; wave?: string; dir?: string; steps?: string; note?: string;
}
export const POINT_META: Record<PointKind, PointMeta> = {
  mountain: { label: "جبل", group: "pos", neg: false, dia: 0.2, rel: 0.06, shape: true, hi: "أعلى قمة (م)", lo: "أدنى نقطة (م)" },
  hill: { label: "تلّة", group: "pos", neg: false, dia: 0.1, rel: 0.012, hi: "أعلى نقطة (م)", lo: "أدنى نقطة (م)" },
  plateau: { label: "هضبة", group: "pos", neg: false, dia: 0.2, rel: 0.03, inner: ["نسبة السطح المستوي", 0.5], hi: "ارتفاع السطح (م)", lo: "أدنى نقطة (م)" },
  mesa: { label: "مصطبة (جروف)", group: "pos", neg: false, dia: 0.1, rel: 0.03, inner: ["نسبة السطح المستوي", 0.5], hi: "ارتفاع السطح (م)", lo: "أدنى نقطة (م)" },
  volcano: { label: "بركان", group: "pos", neg: false, dia: 0.2, rel: 0.07, inner: ["نسبة الفوهة", 0.15], depth: true, hi: "حافة الفوهة (م)", lo: "أدنى نقطة (م)" },
  island: { label: "جزيرة", group: "pos", neg: false, dia: 0.2, rel: 0.015, hi: "أعلى نقطة (م)", lo: "قاع البحر (م)" },
  atoll: { label: "أتول (مرجان حلقي)", group: "pos", neg: false, dia: 0.15, rel: 0.004, inner: ["نصف قطر الحلقة", 0.7], hi: "قمة الحلقة (م)", lo: "قاع البحر (م)" },
  terraces: { label: "مدرجات", group: "pos", neg: false, dia: 0.1, rel: 0.02, steps: "عدد المدرجات", hi: "أعلى مدرج (م)", lo: "أدنى نقطة (م)" },
  scree: { label: "منحدر صخري", group: "pos", neg: false, dia: 0.06, rel: 0.02, hi: "أعلى نقطة (م)", lo: "أدنى نقطة (م)" },
  delta: { label: "دلتا نهرية", group: "pos", neg: false, dia: 0.1, rel: 0.002, steps: "عدد القنوات", amp: "عمق القنوات (م)", wave: "عرض القناة (م)", dir: "اتجاه المصب (°)", hi: "سطح الدلتا (م)", lo: "قاع البحر (م)" },
  crater: { label: "فوهة ارتطام", group: "neg", neg: true, dia: 0.08, rel: 0.006, inner: ["نسبة القاع المستوي", 0.35], hi: "ارتفاع الحافة (م)", lo: "قاع الفوهة (م)" },
  basin: { label: "منخفض / حوض", group: "neg", neg: true, dia: 0.15, rel: 0.008, hi: "مستوى الحافة (م)", lo: "أخفض نقطة (م)" },
  lake: { label: "بحيرة", group: "neg", neg: true, dia: 0.1, rel: 0.006, inner: ["نسبة القاع المستوي", 0.3], hi: "منسوب الماء (م)", lo: "قاع البحيرة (م)" },
  sinkhole: { label: "حفرة انهيارية", group: "neg", neg: true, dia: 0.03, rel: 0.01, inner: ["نسبة القاع المستوي", 0.4], hi: "مستوى الحافة (م)", lo: "قاع الحفرة (م)" },
  cave: { label: "مدخل كهف", group: "neg", neg: true, dia: 0.006, rel: 0.003, inner: ["نسبة المدخل", 0.3], hi: "مستوى الحافة (م)", lo: "قاع المدخل (م)", note: "علامة + حفرة: الـ Height Map لا يحمل تجاويف، فيُنمذَج الداخل ثلاثياً (الموضع في metadata)." },
  marsh: { label: "مستنقع", group: "special", neg: true, dia: 0.08, rel: 0.002, hi: "مستوى المستنقع (م)", lo: "قاع البرك (م)" },
  dune: { label: "حقل كثبان", group: "special", neg: false, dia: 0.12, rel: 0, noHL: true, amp: "ارتفاع الكثبان (م)", wave: "طول الموجة (م)", dir: "اتجاه الرياح (°)", hi: "", lo: "" },
};
export const LINE_META: Record<LineKind, { label: string; color: string; depth?: string; widthLabel: string }> = {
  river: { label: "نهر", color: "#4aa3ff", depth: "عمق القناة (م)", widthLabel: "العرض (م)" },
  road: { label: "طريق", color: "#f2e3b3", widthLabel: "العرض (م)" },
  valley: { label: "وادٍ", color: "#c98b55", depth: "عمق الوادي (م)", widthLabel: "العرض (م)" },
  ridge: { label: "سلسلة جبلية", color: "#ff7a59", depth: "ارتفاع السلسلة (م)", widthLabel: "العرض (م)" },
  cliff: { label: "جرف", color: "#d8a8ff", depth: "ارتفاع الجرف (م)", widthLabel: "عرض الانتقال (م)" },
};
export const BIOME_PRESETS: { label: string; base: number; amp: number; scale: number; min?: number; max?: number; mat?: string }[] = [
  { label: "سهول", base: 100, amp: 15, scale: 2500, max: 300 , mat: "grass" },
  { label: "صحراء", base: 150, amp: 25, scale: 1800, max: 300 , mat: "sand" },
  { label: "جبال", base: 900, amp: 300, scale: 3000, min: 500 , mat: "rock" },
  { label: "غابات وتلال", base: 300, amp: 60, scale: 1500 , mat: "forest_floor" },
  { label: "مستنقعات", base: 5, amp: 2, scale: 800, max: 40 , mat: "mud" },
  { label: "محيط", base: -300, amp: 30, scale: 2500, max: -50 , mat: "sand" },
];

export const DEFAULT_MATERIALS: Material[] = [
  { id: "grass", name: "عشب", color: "#5c8a3c", albedo: null, normal: null, roughness: null, height: null, pack: null, roughness_value: 0.9, tile_m: 10, detail_amp_m: null, detail_kind: null },
  { id: "forest_floor", name: "أرض غابة", color: "#3d5a2a", albedo: null, normal: null, roughness: null, height: null, pack: null, roughness_value: 0.9, tile_m: 10, detail_amp_m: null, detail_kind: null },
  { id: "rock", name: "صخر", color: "#7b7468", albedo: null, normal: null, roughness: null, height: null, pack: null, roughness_value: 0.9, tile_m: 10, detail_amp_m: null, detail_kind: null },
  { id: "snow", name: "ثلج", color: "#f2f5f7", albedo: null, normal: null, roughness: null, height: null, pack: null, roughness_value: 0.9, tile_m: 10, detail_amp_m: null, detail_kind: null },
  { id: "sand", name: "رمل", color: "#d8c690", albedo: null, normal: null, roughness: null, height: null, pack: null, roughness_value: 0.9, tile_m: 10, detail_amp_m: null, detail_kind: null },
  { id: "mud", name: "طين", color: "#6b5338", albedo: null, normal: null, roughness: null, height: null, pack: null, roughness_value: 0.9, tile_m: 10, detail_amp_m: null, detail_kind: null },
  { id: "dirt", name: "تراب", color: "#8b7355", albedo: null, normal: null, roughness: null, height: null, pack: null, roughness_value: 0.9, tile_m: 10, detail_amp_m: null, detail_kind: null },
  { id: "pavement", name: "رصف", color: "#8a8a8a", albedo: null, normal: null, roughness: null, height: null, pack: null, roughness_value: 0.9, tile_m: 10, detail_amp_m: null, detail_kind: null },
  { id: "farmland", name: "أرض زراعية", color: "#b09a4a", albedo: null, normal: null, roughness: null, height: null, pack: null, roughness_value: 0.9, tile_m: 10, detail_amp_m: null, detail_kind: null },
  { id: "gravel", name: "حصى", color: "#9a9488", albedo: null, normal: null, roughness: null, height: null, pack: null, roughness_value: 0.9, tile_m: 10, detail_amp_m: null, detail_kind: null },
];
type M3 = [string | null, string | null, string | null];
/** مواد افتراضية (قاع/وسط/قمة؛ للسالبة: قاع/جدار/حافة). */
export const POINT_MATS: Partial<Record<PointKind, M3>> = {
  mountain: ["grass", "rock", "snow"], volcano: ["forest_floor", "rock", "rock"], plateau: ["grass", "rock", "grass"], mesa: ["gravel", "rock", "dirt"],
  island: ["sand", "grass", "grass"], atoll: ["sand", "sand", "sand"], dune: ["sand", null, null], scree: ["rock", "gravel", "rock"],
  delta: ["mud", "sand", "grass"], crater: ["rock", "dirt", "rock"], basin: ["mud", "dirt", "grass"], lake: ["mud", "sand", "sand"],
  sinkhole: ["rock", "rock", "dirt"], cave: ["rock", "rock", "rock"], marsh: ["mud", "mud", "forest_floor"],
};
export const LINE_MATS: Record<LineKind, [string | null, string | null]> = { river: ["mud", "sand"], road: ["dirt", "gravel"], valley: [null, null], ridge: ["rock", null], cliff: ["rock", null] };
export const SITE_MATS: Record<SiteKind, string> = { village: "dirt", town: "pavement", city: "pavement", castle: "gravel", ruins: "gravel", farm: "farmland", industrial: "pavement", power_plant: "pavement", mine: "rock", camp: "dirt", tower: "gravel", temple: "pavement" };
export const ZONE_MATS: Record<ZoneLayer, string | null> = { grass: "grass", shrubs: "forest_floor", forest: "forest_floor", flowers: "grass", reeds: "mud", rocks: "rock", farmland: "farmland", hummocks: null, rocky: "rock" };

// ── التداخل المنطقي (نسخة من NEST في الخلفية؛ الخلفية هي المرجع) ──
const HIGH: PointKind[] = ["hill", "mountain", "volcano", "mesa", "lake", "basin", "crater", "sinkhole", "marsh", "dune", "scree", "terraces", "cave"];
export const NEST: Record<PointKind, PointKind[]> = {
  plateau: HIGH, mesa: HIGH,
  mountain: ["lake", "basin", "hill", "scree", "terraces", "cave"], volcano: ["lake", "hill", "scree", "cave"],
  hill: ["lake", "sinkhole", "cave", "scree"], terraces: ["lake", "hill"], scree: ["cave"],
  island: ["hill", "mountain", "lake", "volcano", "marsh", "dune", "cave"], atoll: ["island", "lake", "hill", "marsh"],
  basin: ["lake", "hill", "mountain", "mesa", "plateau", "sinkhole", "marsh", "dune", "island", "cave"],
  crater: ["hill", "mountain", "lake", "basin", "sinkhole", "cave"],
  lake: ["island", "hill", "mountain", "plateau", "mesa", "atoll", "volcano"],
  sinkhole: ["lake", "cave"], marsh: ["lake", "hill", "island"], dune: ["lake", "marsh", "hill"], delta: ["lake", "marsh", "island", "hill"], cave: [],
};
/** يعيد سبب الرفض أو null. تلامس مسموح؛ تداخل كامل مسموح فقط إن كان منطقياً؛ التداخل الجزئي ممنوع. */
export function conflict(points: PointFeature[], c: PointFeature): string | null {
  for (const q of points) {
    if (q.id === c.id) continue;
    const d = Math.hypot(q.x_m - c.x_m, q.y_m - c.y_m), ra = c.diameter_m / 2, rb = q.diameter_m / 2;
    if (d >= ra + rb - 1e-6) continue;
    let host = q, child = c;
    if (d + ra <= rb + 1e-6) { /* c داخل q */ } else if (d + rb <= ra + 1e-6) { host = c; child = q; } else return `تداخل جزئي مع ${q.id} (يُسمح بالتلامس أو الاحتواء الكامل المنطقي فقط).`;
    if (!NEST[host.kind].includes(child.kind)) return `غير منطقي: ${POINT_META[child.kind].label} داخل ${POINT_META[host.kind].label} (${host.id}).`;
  }
  return null;
}

export const minSide = (p: Project) => Math.min(p.world.size_x_m, p.world.size_y_m);
const rnd = () => Math.floor(Math.random() * 9999) + 1;

/** القيم الافتراضية نسبة إلى ارتفاع الأرض عند موضع النقر (ground)، فيصحّ الوضع فوق الهضاب والجبال. */
export function newPoint(kind: PointKind, x: number, y: number, id: string, p: Project, ground: number): PointFeature {
  const m = POINT_META[kind], L = minSide(p), g = Math.round(ground), up = Math.max(1, Math.round(L * m.rel));
  const dia = Math.max(p.world.cell_size_m, Math.round((L * m.dia) / 10) * 10);
  let high = m.neg ? (kind === "crater" ? g + Math.max(1, Math.round(L * 0.002)) : g) : g + up, low = m.neg ? g - up : g;
  if (kind === "island") high = Math.max(high, p.world.sea_level_m + Math.max(2, Math.round(up * 0.3)));
  return {
    id, kind, x_m: Math.round(x), y_m: Math.round(y), diameter_m: dia, high_m: high, low_m: low, shape: "cone",
    inner_ratio: m.inner ? m.inner[1] : 0.35, depth_ratio: 0.25,
    amplitude_m: kind === "dune" ? Math.max(3, Math.round(L * 0.002)) : kind === "delta" ? Math.max(2, Math.round(L * 0.0004)) : 10,
    wavelength_m: kind === "dune" ? Math.max(20, Math.round(L * 0.012)) : kind === "delta" ? Math.max(5, Math.round(dia * 0.03)) : 120,
    direction_deg: kind === "delta" ? 180 : 0, steps: kind === "delta" ? 4 : 6, roughness: 0.5, seed: rnd(),
    mat_low: POINT_MATS[kind]?.[0] ?? null, mat_mid: POINT_MATS[kind]?.[1] ?? null, mat_high: POINT_MATS[kind]?.[2] ?? null,
  };
}
export function newLine(kind: LineKind, points: XY[], id: string, p: Project): LineFeature {
  const L = minSide(p);
  const w = { river: Math.max(5, Math.round(L * 0.003)), road: Math.max(4, Math.round(L * 0.001)), valley: Math.round(L * 0.04), ridge: Math.round(L * 0.05), cliff: Math.max(10, Math.round(L * 0.002)) }[kind];
  const dep = { river: Math.max(2, Math.round(L * 0.0005)), road: 0, valley: Math.round(L * 0.003), ridge: Math.round(L * 0.015), cliff: Math.round(L * 0.01) }[kind];
  return { id, kind, points, width_m: w, width_end_m: null, depth_m: dep, depth_end_m: null, profile: "u", max_grade: 0.08, shoulder_m: kind === "cliff" ? Math.round(L * 0.03) : w * 2, min_slope: 0.0005, enforce_descent: true, grade_mode: "regrade", grade_width_m: 100, falls: [], roughness: 0.4, seed: rnd(), mat_main: LINE_MATS[kind][0], mat_edge: LINE_MATS[kind][1], floor_m: null, top_m: null };
}
export function newBiome(id: string, name: string, polygon: XY[], preset: (typeof BIOME_PRESETS)[number], blend: number): Biome {
  return { id, name, polygon, base_elevation_m: preset.base, noise_amplitude_m: preset.amp, noise_scale_m: preset.scale, octaves: 5, blend_m: blend, min_elev_m: preset.min ?? null, max_elev_m: preset.max ?? null, clamp: false, mat_base: preset.mat ?? null };
}

/** تقسيم مستطيل العالم إلى مناطق بمساحات مطلوبة بالضبط (قطع متتالٍ على الضلع الأطول). */
export function sliceAndDice(areas: number[], x0: number, y0: number, w: number, h: number): XY[][] {
  if (areas.length === 1) return [[[x0, y0], [x0 + w, y0], [x0 + w, y0 + h], [x0, y0 + h]]];
  const total = areas.reduce((a, b) => a + b, 0);
  let acc = 0, k = 1, best = Infinity;
  for (let i = 1; i < areas.length; i++) { acc += areas[i - 1]; const d = Math.abs(acc - total / 2); if (d < best) { best = d; k = i; } }
  const frac = areas.slice(0, k).reduce((a, b) => a + b, 0) / total;
  if (w >= h) return [...sliceAndDice(areas.slice(0, k), x0, y0, w * frac, h), ...sliceAndDice(areas.slice(k), x0 + w * frac, y0, w * (1 - frac), h)];
  return [...sliceAndDice(areas.slice(0, k), x0, y0, w, h * frac), ...sliceAndDice(areas.slice(k), x0, y0 + h * frac, w, h * (1 - frac))];
}
export const polyArea = (P: XY[]) => { let s = 0; P.forEach(([x, y], i) => { const [x2, y2] = P[(i + 1) % P.length]; s += x * y2 - x2 * y; }); return Math.abs(s) / 2; };

export const defaultProject = (): Project => ({
  version: 7, name: "عالم جديد",
  world: { size_x_m: 10000, size_y_m: 10000, cell_size_m: 100, chunk_size_m: 2000, seed: 1, sea_level_m: 0 },
  base: { elevation_m: 200, noise_amplitude_m: 30, noise_scale_m: 1500, octaves: 5, noise_mode: "off", noise_min_m: 200, noise_max_m: 250, noise_bias: 0.6, cell_blend: 0.25, cell_detail: 0.2 },
  biomes: [], cells: [], points: [], lines: [], sites: [], zones: [],
  pois: [], player: { speed_mps: 5, eye_height_m: 1.7, max_slope_deg: 40, view_distance_m: 2000, can_swim: false },
  materials: DEFAULT_MATERIALS.map((m) => ({ ...m })),
  paint: { default_material: "grass", slope_material: "rock", slope_start_deg: 30, slope_full_deg: 48, snow_material: null, snow_elev_m: 1500, snow_blend_m: 150, beach_material: "sand", beach_height_m: 3 },
  erosion: { enabled: false, resolution: 513, iterations: 30, max_depth_m: 15, deposition: 0.3, thermal: true, talus_deg: 38, smooth: 0.2,
    mode: "sediment", erodibility: 0.6, deposition_rate: 0.5, fans: true, fan_spread_m: 150, gullies: true, gully_depth_m: 2, gully_spacing_m: 40, gully_length_cells: 18, gully_min_slope_deg: 8, gully_max_slope_deg: 50, seed: 1 },
  kit: defaultKit(),
  roads: defaultRoads(),
  water: defaultWater(),
  detail: defaultDetail(),
  scatter: { enabled: true, species: [] },
  derived: defaultDerived(),
  surface: defaultSurface(),
  atmosphere: defaultAtmosphere(),
  export: { resolution: 1025, tile_px: 1025, mask_px: 1025, mode: "auto", zmin_m: 0, zmax_m: 1000, glb_resolution: 1025, glb_texture_px: 2048 },
});

export const SITE_META: Record<SiteKind, { label: string; icon: string; rect: boolean; w: number; l: number; blend: number; strength?: number; offset?: number }> = {
  village: { label: "قرية", icon: "⌂", rect: false, w: 0.03, l: 0.03, blend: 0.2 },
  town: { label: "بلدة", icon: "▣", rect: false, w: 0.06, l: 0.06, blend: 0.15 },
  city: { label: "مدينة", icon: "▦", rect: false, w: 0.12, l: 0.12, blend: 0.1 },
  castle: { label: "قلعة", icon: "♜", rect: false, w: 0.02, l: 0.02, blend: 0.3 },
  ruins: { label: "أطلال", icon: "⌘", rect: false, w: 0.025, l: 0.025, blend: 0.3, strength: 0.6 },
  farm: { label: "مزرعة", icon: "❖", rect: false, w: 0.015, l: 0.015, blend: 0.3 },
  industrial: { label: "منشأة صناعية", icon: "⚙", rect: true, w: 0.04, l: 0.025, blend: 0.15 },
  power_plant: { label: "محطة طاقة", icon: "⚡", rect: true, w: 0.035, l: 0.025, blend: 0.15 },
  mine: { label: "منجم (حفرة)", icon: "⛏", rect: false, w: 0.04, l: 0.04, blend: 0.05, offset: -0.003 },
  camp: { label: "معسكر", icon: "⛺", rect: false, w: 0.01, l: 0.01, blend: 0.3 },
  tower: { label: "برج مراقبة", icon: "♖", rect: false, w: 0.006, l: 0.006, blend: 0.4 },
  temple: { label: "معبد", icon: "⛩", rect: false, w: 0.012, l: 0.012, blend: 0.3 },
};
export const ZONE_META: Record<ZoneLayer, { label: string; color: string; relief: boolean }> = {
  grass: { label: "عشب", color: "#6fbf4a", relief: false },
  shrubs: { label: "شجيرات", color: "#4f8a3a", relief: false },
  forest: { label: "غابة", color: "#2f6b2f", relief: false },
  flowers: { label: "أزهار", color: "#e08adf", relief: false },
  reeds: { label: "قصب", color: "#9ab86a", relief: false },
  rocks: { label: "صخور متناثرة", color: "#9a9a9a", relief: false },
  farmland: { label: "أراضٍ زراعية", color: "#d8c060", relief: false },
  hummocks: { label: "نتوءات صغيرة (تضاريس)", color: "#b08a5a", relief: true },
  rocky: { label: "أرض صخرية (تضاريس)", color: "#7a6a5a", relief: true },
};
export function newSite(kind: SiteKind, x: number, y: number, id: string, p: Project): Site {
  const m = SITE_META[kind], L = minSide(p), r10 = (v: number) => Math.max(10, Math.round(v / 10) * 10);
  return {
    id, kind, name: `${m.label} ${id.split("-").pop()}`, x_m: Math.round(x), y_m: Math.round(y), shape: m.rect ? "rect" : "circle",
    diameter_m: r10(L * m.w), width_m: r10(L * m.w), length_m: r10(L * m.l), rotation_deg: 0, level_mode: "mean", level_m: 0,
    level_offset_m: m.offset ? Math.round(L * m.offset) : 0, blend_m: r10(L * m.w * m.blend), strength: m.strength ?? 1, mat_ground: SITE_MATS[kind], density: 0.6, seed: Math.floor(Math.random() * 9999) + 1,
  };
}
export function newZone(layer: ZoneLayer, polygon: XY[], id: string): Zone {
  return { id, name: ZONE_META[layer].label, layer, polygon, density: 0.8, falloff_m: 30, max_slope_deg: 30, min_elev_m: null, max_elev_m: null, patchiness: 0.3, amplitude_m: 1.5, wavelength_m: 20, seed: Math.floor(Math.random() * 9999) + 1, mat_main: ZONE_MATS[layer] };
}
/** مسافة مركز موقع إلى نصف قطره المكافئ (للتحقق من التداخل محلياً؛ الخلفية هي المرجع). */
export const siteExt = (s: Site) => (s.shape === "circle" ? s.diameter_m / 2 : Math.hypot(s.width_m, s.length_m) / 2);

export const POI_META: Record<PoiKind, { label: string; icon: string; color: string; zone: number; note: string }> = {
  player_start: { label: "نقطة انطلاق اللاعب", icon: "▶", color: "#4cd964", zone: 0, note: "أول نقطة في المحاكاة" },
  poi: { label: "نقطة اهتمام", icon: "◆", color: "#ffd60a", zone: 0, note: "" },
  landmark: { label: "معلم بارز (Landmark)", icon: "⚑", color: "#ff9f0a", zone: 0, note: "يُرى من بعيد: حدد ارتفاعه لتحليل الرؤية" },
  boss: { label: "منطقة الزعيم", icon: "☠", color: "#ff453a", zone: 0.012, note: "منطقة دائرية؛ فعّل التسوية لحلبة مستوية" },
  story: { label: "منطقة القصة", icon: "✎", color: "#bf5af2", zone: 0.012, note: "منطقة دائرية لأحداث القصة" },
  quest: { label: "مهمة", icon: "!", color: "#64d2ff", zone: 0, note: "" },
  dungeon: { label: "مدخل زنزانة", icon: "⛫", color: "#a2845e", zone: 0, note: "" },
  resource: { label: "موارد", icon: "◈", color: "#30d158", zone: 0, note: "" },
  fast_travel: { label: "سفر سريع", icon: "✦", color: "#5e5ce6", zone: 0, note: "" },
};
export function newPoi(kind: PoiKind, x: number, y: number, id: string, p: Project): Poi {
  const m = POI_META[kind], L = minSide(p), nextOrder = Math.max(0, ...p.pois.map((q) => q.order)) + 1;
  return {
    id, kind, name: `${m.label} ${id.split("-").pop()}`, x_m: Math.round(x), y_m: Math.round(y), radius_m: m.zone ? Math.max(10, Math.round((L * m.zone) / 5) * 5) : 0,
    order: kind === "player_start" || kind === "landmark" || kind === "fast_travel" ? 0 : nextOrder, difficulty: kind === "boss" ? 7 : 1, level_min: 1, level_max: 1,
    dwell_min: kind === "boss" ? 8 : kind === "story" ? 5 : kind === "player_start" ? 0 : 2, landmark_height_m: kind === "landmark" ? 30 : 0,
    flatten: kind === "boss", blend_m: 30, notes: "",
  };
}
export interface Candidate { x_m: number; y_m: number; level_m: number; rms_m: number; cut_m3: number; fill_m3: number; max_cut_m: number; max_fill_m: number }
export interface Lot { x_m: number; y_m: number; width_m: number; length_m: number; rotation_deg: number; z_m: number; main: boolean }
export interface RouteResult { points: XY[]; length_m: number; max_grade: number; mean_grade: number; climb_m: number; descent_m: number; notes: string[] }
export interface SimLeg { from: string; to: string; reachable: boolean; distance_m?: number; walk_s?: number; climb_m?: number; descent_m?: number; max_slope_deg?: number; points?: XY[] }
export interface SimResult {
  legs: SimLeg[]; totals: { distance_m: number; walk_s: number; dwell_s: number; total_s: number; climb_m: number; descent_m: number; max_slope_deg: number };
  profile: { distance_m: number[]; z: number[] }; stops: { id: string; name: string; kind: PoiKind; difficulty: number; level_min: number; level_max: number; z: number }[];
  view: { observers: number; bands_m: number[] | null; mean_far_m?: number; pois_seen: { id: string; name: string; kind: PoiKind; first_seen_at_m: number | null; first_seen_distance_m: number | null; ever_seen: boolean }[] };
  warnings: string[]; suggested_lod_distances_m: number[] | null;
}
