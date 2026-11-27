"""مخطط المشروع v7 — يُحفظ كما هو في JSON. المتر هو الوحدة الوحيدة، وy للأعلى (شمال)."""
from __future__ import annotations
from typing import List, Literal, Optional, Tuple
from pydantic import BaseModel, Field, field_validator, model_validator

SCHEMA_VERSION = 7
PointKind = Literal["mountain", "hill", "plateau", "mesa", "volcano", "island", "atoll", "terraces", "scree", "delta",
                    "crater", "basin", "lake", "sinkhole", "cave", "marsh", "dune"]
MountainShape = Literal["cone", "dome", "rugged"]
LineKind = Literal["river", "road", "valley", "ridge", "cliff"]


class World(BaseModel):
    size_x_m: float = Field(10000, gt=0, le=204800)
    size_y_m: float = Field(10000, gt=0, le=204800)
    cell_size_m: float = Field(100, gt=0)
    chunk_size_m: float = Field(2000, gt=0)                   # المنطقة المحمّلة = حجم المربع عند تصدير Tiles
    seed: int = 1
    sea_level_m: float = 0.0


class Base(BaseModel):
    """الأرض الافتراضية (خارج أي منطقة) + إعدادات الخلايا."""
    elevation_m: float = 50.0
    noise_amplitude_m: float = Field(30.0, ge=0)
    noise_scale_m: float = Field(1500.0, gt=0)
    octaves: int = Field(5, ge=1, le=8)
    # off: عالم مستوٍ تماماً عند elevation_m | amplitude: ضوضاء حول elevation_m | range: ضوضاء بين min وmax منسجمة مع المعالم
    noise_mode: Literal["off", "amplitude", "range"] = "amplitude"
    noise_min_m: float = 200.0
    noise_max_m: float = 250.0
    noise_bias: float = Field(0.6, ge=0, le=1)                # قوة تأثير المعالم على الضوضاء (0 = ضوضاء حرة، 1 = تتبع المعالم)
    cell_blend: float = Field(0.25, ge=0.05, le=0.5)          # نصف عرض التنعيم عند حدود الخلايا (نسبة من الخلية)
    cell_detail: float = Field(0.2, ge=0, le=1)               # نسبة التفصيل الطبيعي داخل الخلايا المعدّلة


class CellSpec(BaseModel):
    """مستوى مائل: الارتفاع عند المركز + (rise لكل run) باتجاه aspect. row=0 شمال."""
    col: int = Field(ge=0)
    row: int = Field(ge=0)
    elevation_m: float
    rise_m: float = 0.0
    run_m: float = Field(50.0, gt=0)
    aspect_deg: float = 0.0                                   # اتجاه الصعود: 0=شمال، 90=شرق


class PointFeature(BaseModel):
    """تضاريس نقطية ببصمة دائرية قطرها diameter_m بالضبط.
    موجبة: high=القمة/السطح، low=السفح.  سالبة: high=الحافة/منسوب الماء، low=القاع.
    dune: تستخدم amplitude_m فقط."""
    id: str
    kind: PointKind = "mountain"
    x_m: float
    y_m: float
    diameter_m: float = Field(2000, gt=0)
    high_m: float = 600.0
    low_m: float = 50.0
    shape: MountainShape = "cone"
    inner_ratio: float = Field(0.35, ge=0, le=0.9)
    depth_ratio: float = Field(0.25, ge=0, le=0.9)
    amplitude_m: float = Field(10.0, ge=0)                    # كثبان: ارتفاع | دلتا: عمق القنوات
    wavelength_m: float = Field(120.0, gt=0)                  # كثبان: طول الموجة | دلتا: عرض القناة
    direction_deg: float = 0.0                                # كثبان: اتجاه الرياح | دلتا: اتجاه المصب
    steps: int = Field(6, ge=1, le=40)                        # مدرجات: العدد | دلتا: عدد القنوات
    roughness: float = Field(0.5, ge=0, le=1)
    seed: int = 1
    mat_low: Optional[str] = None                             # سفح/قاع (السالبة: القاع)
    mat_mid: Optional[str] = None
    mat_high: Optional[str] = None                            # قمة (السالبة: الحافة)


SiteKind = Literal["village", "town", "city", "castle", "ruins", "farm", "industrial", "power_plant", "mine", "camp", "tower", "temple"]
ZoneLayer = Literal["grass", "shrubs", "forest", "flowers", "reeds", "rocks", "farmland", "hummocks", "rocky"]


class Material(BaseModel):
    """مادة سطح: لون دائماً، وصور Albedo/Normal اختيارية (مسارات فقط؛ الصور يوفرها المستخدم)."""
    id: str
    name: str = ""
    color: str = "#808080"
    albedo: Optional[str] = None
    normal: Optional[str] = None
    roughness: Optional[str] = None                           # خريطة الخشونة (Roughness)
    height: Optional[str] = None                              # خريطة الارتفاع/الإزاحة (Displacement): للمزج بالارتفاع والتفصيل البارز
    pack: Optional[str] = None                                # مجلد حزمة خامات (ambientCG/Poly Haven): تُكتشف الخرائط الناقصة من أسماء الملفات
    roughness_value: float = Field(0.9, ge=0, le=1)           # خشونة ثابتة عند غياب خريطة الخشونة
    tile_m: float = Field(10.0, gt=0)                         # طول تكرار صورة الخامة بالمتر
    detail_amp_m: Optional[float] = Field(None, ge=0, le=20)  # سعة التفاصيل الدقيقة بالمتر؛ None = الافتراضي حسب المادة
    detail_kind: Optional[Literal["soil", "rock", "sand", "gravel"]] = None


class Surface(BaseModel):
    """سطح الأرض في Blender (PBR): إسقاط ثلاثي المحاور، كسر التكرار، المزج بالارتفاع. لا يغيّر الارتفاعات ولا أقنعة التوزيع."""
    triplanar: bool = True
    triplanar_blend: float = Field(0.2, ge=0, le=1)
    break_tiling: bool = True
    break_strength: float = Field(0.6, ge=0, le=1)
    break_scale_m: float = Field(80.0, ge=1, le=5000)
    height_blend: bool = True
    height_contrast: float = Field(0.35, ge=0, le=1)
    relief_m: float = Field(0.15, ge=0, le=5)                 # عمق التفصيل البارز (0 = بلا)
    normal_strength: float = Field(1.0, ge=0, le=5)
    normal_convention: Literal["GL", "DX"] = "GL"             # اصطلاح خرائط Normal التي توفرها: OpenGL أو DirectX
    cavity_strength: float = Field(0.5, ge=0, le=1)           # تغميق التجاويف بقناع cavity
    wet_darken: float = Field(0.3, ge=0, le=1)                # تغميق الأرض الرطبة بقناع wetness
    wet_gloss: float = Field(0.4, ge=0, le=1)                 # خفض الخشونة (لمعان) في الأرض الرطبة


_SITE_KINDS = ("village", "town", "city", "castle", "ruins", "farm", "industrial", "power_plant", "mine", "camp", "tower", "temple")


class KitPiece(BaseModel):
    """قطعة من وحدات القرى/المباني. الواجهة = المحور +X المحلي؛ width_m على X وlength_m على Y (للأسوار: length_m طول المقطع على المحيط)."""
    id: str
    name: str = "قطعة"
    role: Literal["house", "main", "wall", "gate", "tower", "prop"] = "house"
    collection: Optional[str] = None                          # Collection في Blender (الافتراضي TF_Kit_<id>)
    width_m: float = Field(8.0, ge=0.1, le=500)
    length_m: float = Field(10.0, ge=0.1, le=500)
    height_m: float = Field(6.0, ge=0.1, le=500)
    weight: float = Field(1.0, ge=0, le=100)                  # احتمال الاختيار بين قطع الدور نفسه
    site_kinds: List[str] = []                                # فارغ = كل أنواع المواقع

    @field_validator("site_kinds")
    @classmethod
    def _kinds(cls, v):
        bad = [k for k in v if k not in _SITE_KINDS]
        if bad:
            raise ValueError(f"أنواع مواقع غير معروفة: {bad}")
        return v


class Kit(BaseModel):
    enabled: bool = True
    pieces: List[KitPiece] = []
    face_road: bool = True                                    # تتجه البيوت القريبة من طريق نحوه
    road_snap_m: float = Field(40.0, ge=0, le=500)
    walls: bool = True
    wall_kinds: List[str] = ["castle"]                        # أنواع المواقع التي يُسوَّر محيطها
    gate_width_m: float = Field(10.0, ge=1, le=100)           # عرض فتحة البوابة حيث يقطع طريق السور
    props_per_lot: float = Field(0.5, ge=0, le=5)             # متوسط عدد الزينة حول كل قطعة بيت
    seed: int = 1


class Roads(BaseModel):
    """طرق واقعية: أقنعة سطح/كتف/حافة مغبرّة تُصدَّر، وإعدادات مسارات الإطارات والغبار في ظل Blender (إجرائياً بالأمتار)."""
    enabled: bool = True
    dust_width_m: float = Field(3.0, ge=0, le=50)             # عرض الحافة المغبرّة خارج السطح (يتغير بضوضاء)
    dust_color: str = Field("#b59a72", pattern=r"^#[0-9a-fA-F]{6}$")
    track_gauge_m: float = Field(1.8, ge=0.5, le=4)           # المسافة بين العجلتين (مركز لمركز)
    track_width_m: float = Field(0.45, ge=0.1, le=2)
    track_wear: float = Field(0.6, ge=0, le=1)                # قوة تغميق/تلميع أثر الإطارات
    track_depth_m: float = Field(0.04, ge=0, le=0.5)          # عمق الأثر البارز (Bump)
    surface_variation: float = Field(0.35, ge=0, le=1)        # تفاوت لون السطح بالبقع


class Water(BaseModel):
    """ماء واقعي: خرائط عمق/شاطئ/رغوة/تدفق تُصدَّر، وإعدادات ظلال الماء في Blender (امتصاص بالعمق، رغوة، تموّج يتبع التدفق)."""
    enabled: bool = True
    shore_width_m: float = Field(6.0, ge=0.5, le=200)         # عرض نطاق الشاطئ الرطب على اليابسة
    foam_width_m: float = Field(3.0, ge=0.2, le=100)          # عرض رغوة الحافة داخل الماء
    rapids_slope_deg: float = Field(6.0, ge=0.5, le=60)       # ميل قاع النهر الذي تبدأ عنده رغوة المنحدرات
    foam_amount: float = Field(1.0, ge=0, le=1)
    shallow_color: str = Field("#3f9aa0", pattern=r"^#[0-9a-fA-F]{6}$")
    deep_color: str = Field("#0a2f4a", pattern=r"^#[0-9a-fA-F]{6}$")
    absorption_depth_m: float = Field(6.0, ge=0.2, le=200)    # العمق الذي يبلغ عنده اللون العميق
    roughness: float = Field(0.04, ge=0, le=1)
    ior: float = Field(1.333, ge=1, le=2)
    wave_height_m: float = Field(0.15, ge=0, le=5)
    wave_scale_m: float = Field(12.0, ge=0.5, le=500)
    wave_speed: float = Field(0.5, ge=0, le=10)               # سرعة تحريك التموّج (يتبع اتجاه التدفق في الأنهار)


class Detail(BaseModel):
    """تفاصيل ارتفاع دقيقة تُضاف عند تصدير المربعات فقط، بحسب المادة والميل (حقول مطلقة الإحداثيات: لا شقوق بين المربعات)."""
    enabled: bool = False
    wavelength_max_m: float = Field(24.0, ge=2, le=500)       # أطول طول موجة للتفاصيل
    slope_gain: float = Field(1.0, ge=0, le=5)                # تضخيم تفاصيل الصخر/الحصى على المنحدرات
    seed: int = 1


class Derived(BaseModel):
    """طبقات مشتقة من الارتفاعات (انحناء، تجويف، تدفق، رطوبة، ميل) تُصدَّر كأقنعة وتُستعمل في التلوين وفي سطح Blender."""
    enabled: bool = True
    curvature_scale_m: float = Field(8.0, ge=1, le=500)       # حجم الشكل الذي يُقاس انحناؤه
    cavity_radius_m: float = Field(12.0, ge=2, le=500)        # نصف قطر التجويف (انسداد محيطي)
    stream_area_m2: float = Field(20000.0, ge=100, le=1e8)    # أصغر مساحة مغذية تُعدّ مجرى
    slope_classes_deg: List[float] = [5.0, 15.0, 30.0]        # حدود فئات الميل (حتى 7 حدود)
    convex_material: Optional[str] = None                     # صخر/مادة على الحواف المحدبة
    convex_amount: float = Field(0.7, ge=0, le=1)
    convex_min_slope_deg: float = Field(10.0, ge=0, le=89)
    hollow_material: Optional[str] = None                     # طين/تراب في المنخفضات المقعرة
    hollow_amount: float = Field(0.7, ge=0, le=1)
    wet_material: Optional[str] = None                        # مادة رطبة قرب المجاري ومناطق التجمّع
    wet_amount: float = Field(0.7, ge=0, le=1)
    wet_threshold: float = Field(0.65, ge=0, le=1)

    @field_validator("slope_classes_deg")
    @classmethod
    def _limits(cls, v):
        if len(v) > 7 or any(not (0 < x < 90) for x in v):
            raise ValueError("حتى 7 حدود بين 0 و90 درجة")
        return sorted(v)


class ScatterSpecies(BaseModel):
    """نوع يُنثر (شجر/شجيرة/صخر/عشب) بمواضع Poisson-disk حتمية داخل أقنعة كثافة طبقة نباتات."""
    id: str
    name: str = "نوع جديد"
    kind: Literal["tree", "bush", "rock", "grass", "prop"] = "tree"
    layer: Literal["grass", "shrubs", "forest", "flowers", "reeds", "rocks", "farmland"] = "forest"   # من أي طبقة مناطق تأتي الكثافة
    min_dist_m: float = Field(8.0, ge=0.3, le=500)            # أدنى مسافة بين نسختين
    scale_min: float = Field(0.8, gt=0, le=20)
    scale_max: float = Field(1.3, gt=0, le=20)
    max_slope_deg: float = Field(35.0, ge=0, le=90)
    min_elev_m: Optional[float] = None
    max_elev_m: Optional[float] = None
    align_to_normal: float = Field(0.0, ge=0, le=1)           # 0 = قائم دائماً، 1 = عمودي على السطح
    max_count: int = Field(50000, ge=10, le=500000)
    seed: int = 1
    asset: Optional[str] = None                               # اسم Collection في Blender (أو معرّف prefab في المحرك)

    @model_validator(mode="after")
    def _scale_order(self):
        if self.scale_max < self.scale_min:
            raise ValueError("scale_max يجب ألا يقل عن scale_min")
        return self


class Scatter(BaseModel):
    enabled: bool = True
    species: List[ScatterSpecies] = []


class PaintRules(BaseModel):
    """قواعد تلقائية تُطبَّق قبل مواد المعالم (مواد المعالم تتغلب عليها)."""
    default_material: str = "grass"
    slope_material: Optional[str] = "rock"
    slope_start_deg: float = Field(30.0, ge=0, le=89)
    slope_full_deg: float = Field(48.0, ge=1, le=90)
    snow_material: Optional[str] = None
    snow_elev_m: float = 1500.0
    snow_blend_m: float = Field(150.0, gt=0)
    beach_material: Optional[str] = "sand"
    beach_height_m: float = Field(3.0, gt=0)


PoiKind = Literal["poi", "landmark", "player_start", "boss", "story", "quest", "dungeon", "resource", "fast_travel"]


class Poi(BaseModel):
    """نقطة/منطقة اهتمام للعب. radius_m=0 نقطة، وأكبر من 0 منطقة دائرية (منطقة زعيم/قصة...)."""
    id: str
    kind: PoiKind = "poi"
    name: str = ""
    x_m: float
    y_m: float
    radius_m: float = Field(0.0, ge=0)
    order: int = Field(0, ge=0)                               # ترتيب المرور المتوقع للاعب (0 = خارج المسار)
    difficulty: int = Field(1, ge=1, le=10)
    level_min: int = Field(1, ge=1)
    level_max: int = Field(1, ge=1)
    dwell_min: float = Field(2.0, ge=0)                       # دقائق متوقعة هناك
    landmark_height_m: float = Field(0.0, ge=0)               # ارتفاع المعلم المرئي (برج، شجرة ضخمة…) لتحليل الرؤية
    flatten: bool = False                                     # تسوية الأرض داخل المنطقة (حلبة زعيم…)
    blend_m: float = Field(30.0, ge=1)
    notes: str = ""


class PlayerModel(BaseModel):
    """اللاعب المتوقع: يحدد زمن الوصول والرؤية والعوائق."""
    speed_mps: float = Field(5.0, gt=0)                       # سرعة الجري على أرض مستوية
    eye_height_m: float = Field(1.7, ge=0)
    max_slope_deg: float = Field(40.0, ge=5, le=80)           # لا يتسلق أكثر من هذا
    view_distance_m: float = Field(2000.0, gt=0)
    can_swim: bool = False


class Erosion(BaseModel):
    """تعرية أسلوبية (ليست معايَرة بمعدلات حقيقية): مائية (قدرة المجرى) + حرارية (زاوية الركام) + تنعيم.
    تُحسب على شبكة عالمية بدقة resolution ثم تُضاف كفرق ناعم فتتطابق حواف المربعات."""
    enabled: bool = False
    resolution: Literal[257, 513, 1025] = 513
    iterations: int = Field(30, ge=1, le=200)
    max_depth_m: float = Field(15.0, ge=0)
    deposition: float = Field(0.3, ge=0, le=0.9)
    thermal: bool = True
    talus_deg: float = Field(38.0, ge=5, le=80)
    smooth: float = Field(0.2, ge=0, le=1)
    # ── وضع نقل الرواسب (الأحدث) ──
    mode: Literal["stylized", "sediment"] = "sediment"        # stylized: القديم (لا يحفظ الكتلة) | sediment: نقل رواسب بالسعة يحفظ الكتلة
    erodibility: float = Field(0.6, ge=0, le=1)               # سرعة التعرية عندما تزيد السعة عن الحمل
    deposition_rate: float = Field(0.5, ge=0, le=1)           # سرعة الترسيب عندما يزيد الحمل عن السعة
    fans: bool = True                                         # مراوح ركامية: ينتشر الترسيب جانبياً
    fan_spread_m: float = Field(150.0, ge=20, le=3000)
    gullies: bool = True                                      # أخاديد باتجاه خط الانحدار
    gully_depth_m: float = Field(2.0, ge=0, le=30)
    gully_spacing_m: float = Field(40.0, ge=5, le=500)
    gully_length_cells: int = Field(18, ge=4, le=60)
    gully_min_slope_deg: float = Field(8.0, ge=0, le=80)
    gully_max_slope_deg: float = Field(50.0, ge=10, le=89)
    seed: int = 1


class Site(BaseModel):
    """موقع منشآت: تُسوّى الأرض داخل بصمته إلى منسوب واحد وتُنعَّم حوله على مسافة blend_m."""
    id: str
    kind: SiteKind = "village"
    name: str = ""
    x_m: float
    y_m: float
    shape: Literal["circle", "rect"] = "circle"
    diameter_m: float = Field(300, gt=0)
    width_m: float = Field(300, gt=0)
    length_m: float = Field(200, gt=0)
    rotation_deg: float = 0.0
    level_mode: Literal["mean", "min", "max", "fixed"] = "mean"
    level_m: float = 0.0
    level_offset_m: float = 0.0                               # منجم: سالب
    blend_m: float = Field(40.0, ge=1)
    strength: float = Field(1.0, ge=0, le=1)                  # أطلال: أقل من 1
    mat_ground: Optional[str] = None
    density: float = Field(0.6, ge=0, le=1)                   # كثافة اقتراح المباني
    seed: int = 1
    bim_project: Optional[str] = None                         # مشروع BIM Builder الذي يحوي مباني هذه المنشأة (World Studio)


class Zone(BaseModel):
    """grass..farmland تنتج قناع كثافة؛ hummocks/rocky تضيف تضاريس صغيرة للارتفاع."""
    id: str
    name: str = "منطقة نباتات"
    layer: ZoneLayer = "grass"
    polygon: List[Tuple[float, float]] = Field(min_length=3)
    density: float = Field(0.8, ge=0, le=1)
    falloff_m: float = Field(30.0, ge=0)
    max_slope_deg: float = Field(30.0, ge=0, le=90)
    min_elev_m: Optional[float] = None
    max_elev_m: Optional[float] = None
    patchiness: float = Field(0.3, ge=0, le=1)
    amplitude_m: float = Field(1.5, ge=0)
    wavelength_m: float = Field(20.0, gt=0)
    seed: int = 1
    mat_main: Optional[str] = None


class Fall(BaseModel):
    at: float = Field(0.5, ge=0, le=1)                        # موضع الشلال على النهر (0=منبع، 1=مصب)
    height_m: float = Field(10, gt=0)
    length_m: float = Field(10, gt=0)


class LinearFeature(BaseModel):
    """river/road/valley/ridge/cliff. جرف: الجهة اليسرى من اتجاه الرسم هي المرتفعة."""
    id: str
    kind: LineKind = "river"
    points: List[Tuple[float, float]] = Field(min_length=2)
    width_m: float = Field(30, gt=0)
    width_end_m: Optional[float] = None
    depth_m: float = Field(5, ge=0)                           # عمق/ارتفاع (جرف: ارتفاع الجرف)
    depth_end_m: Optional[float] = None
    profile: Literal["v", "u"] = "u"
    max_grade: float = Field(0.08, gt=0, le=1)
    shoulder_m: float = Field(20, ge=0)                       # طريق: الجسر | جرف: عرض الحافة المرتفعة
    min_slope: float = Field(0.0005, ge=0)
    enforce_descent: bool = True                              # وضع carve فقط
    grade_mode: Literal["regrade", "carve"] = "regrade"       # regrade: تعديل مناسيب الأرض ليلائم النهر | carve: حفر خندق
    grade_width_m: float = Field(100.0, ge=0)                 # عرض التدرج الجانبي لتسوية الأرض حول النهر
    falls: List[Fall] = []
    roughness: float = Field(0.4, ge=0, le=1)
    seed: int = 1
    floor_m: Optional[float] = None                           # وادٍ: منسوب القاع المطلق (تنخفض الأرض إليه)
    top_m: Optional[float] = None                             # سلسلة: منسوب القمة المطلق
    mat_main: Optional[str] = None                            # مجرى/سطح الطريق/قاع الوادي/قمة السلسلة
    mat_edge: Optional[str] = None                            # ضفاف/كتف


class Biome(BaseModel):
    id: str
    name: str = "منطقة"
    polygon: List[Tuple[float, float]] = Field(min_length=3)
    base_elevation_m: float = 50.0
    noise_amplitude_m: float = Field(30.0, ge=0)
    noise_scale_m: float = Field(1500.0, gt=0)
    octaves: int = Field(5, ge=1, le=8)
    blend_m: float = Field(300.0, gt=0)                       # عرض الانتقال بين المناطق
    min_elev_m: Optional[float] = None                        # حدود الارتفاع المسموحة في المنطقة
    max_elev_m: Optional[float] = None
    clamp: bool = False                                       # قصّ تلقائي بدل الخطأ
    mat_base: Optional[str] = None


class Atmosphere(BaseModel):
    """الجو والإضاءة والكاميرا: لا تؤثر في الارتفاعات، تُصدَّر في build.json ويطبّقها import_build.py في Blender.
    الزوايا بالدرجات. السمت اتجاه بوصلة: 0 = شمال، 90 = شرق. None = يُشتق من حجم العالم."""
    enabled: bool = True
    engine: Literal["EEVEE", "CYCLES"] = "EEVEE"
    view_transform: Literal["AgX", "Filmic", "Standard"] = "AgX"
    exposure: float = Field(0.0, ge=-10, le=10)
    sun_elevation: float = Field(28.0, ge=0, le=90)
    sun_azimuth: float = Field(300.0, ge=0, le=360)
    sun_energy: float = Field(4.0, ge=0, le=100)              # مصباح الشمس (EEVEE فقط)
    sun_size_deg: float = Field(0.545, gt=0, le=20)
    air_density: float = Field(1.0, ge=0, le=10)
    dust_density: float = Field(1.0, ge=0, le=10)
    ozone_density: float = Field(1.0, ge=0, le=10)
    sky_altitude_m: Optional[float] = Field(None, ge=0, le=60000)
    fog: bool = True
    fog_density: Optional[float] = Field(None, gt=0, le=1)    # لكل متر؛ None = 3 / حجم العالم
    fog_anisotropy: float = Field(0.35, ge=-0.95, le=0.95)
    camera: bool = True
    camera_azimuth: float = Field(225.0, ge=0, le=360)        # موضع الكاميرا بالنسبة لمركز العالم
    camera_distance_factor: float = Field(0.6, gt=0, le=5)    # × أكبر ضلع للعالم
    camera_height_above_peak_m: Optional[float] = Field(None, ge=0)   # None = 8% من حجم العالم
    focal_length_mm: float = Field(35.0, ge=8, le=300)
    sensor_width_mm: float = Field(36.0, gt=0, le=100)
    dof: bool = True
    f_stop: float = Field(4.0, ge=0.5, le=32)


class ExportSettings(BaseModel):
    resolution: Literal[513, 1025, 2049, 4097] = 1025        # صورة واحدة: الضلع الأطول
    mask_px: Literal[513, 1025, 2049] = 1025                  # دقة أقنعة الغطاء النباتي
    tile_px: Literal[513, 1025, 2049] = 1025                  # Tiles: بكسلات كل مربع (حجمه = chunk_size_m)
    mode: Literal["auto", "fixed"] = "auto"
    zmin_m: float = 0.0
    zmax_m: float = 1000.0
    glb_resolution: Literal[257, 513, 1025, 2049] = 1025      # تصدير GLB: عدد رؤوس الضلع الأطول
    glb_texture_px: Literal[1024, 2048, 4096] = 2048          # تصدير GLB: دقة الخامة المخبوزة (الضلع الأطول)


class Level(BaseModel):
    """مرحلة لعبة = مستطيل من العالم الواحد (م). x_m,y_m = الزاوية الجنوبية الغربية."""
    id: str
    name: str = ""
    x_m: float = Field(0, ge=0)
    y_m: float = Field(0, ge=0)
    w_m: float = Field(1000, gt=0)
    h_m: float = Field(1000, gt=0)
    points: Optional[List[Tuple[float, float]]] = None          # حدود حرّة (م، إحداثيات العالم)؛ المستطيل أعلاه = صندوقها المحيط


class Project(BaseModel):
    version: int = SCHEMA_VERSION
    name: str = "عالم جديد"
    world: World = World()
    base: Base = Base()
    biomes: List[Biome] = []
    cells: List[CellSpec] = []
    points: List[PointFeature] = []
    lines: List[LinearFeature] = []
    sites: List[Site] = []
    zones: List[Zone] = []
    pois: List[Poi] = []
    player: PlayerModel = PlayerModel()
    materials: List[Material] = []
    paint: PaintRules = PaintRules()
    erosion: Erosion = Erosion()
    kit: Kit = Kit()                                          # اختياري في الملفات القديمة
    roads: Roads = Roads()                                    # اختياري في الملفات القديمة
    water: Water = Water()                                    # اختياري في الملفات القديمة
    detail: Detail = Detail()                                 # اختياري في الملفات القديمة
    scatter: Scatter = Scatter()                              # اختياري في الملفات القديمة
    derived: Derived = Derived()                              # اختياري في الملفات القديمة
    surface: Surface = Surface()                              # اختياري في الملفات القديمة
    atmosphere: Atmosphere = Atmosphere()                     # اختياري في الملفات القديمة (تُملأ بالقيم الافتراضية)
    levels: List[Level] = []                                  # اختياري في الملفات القديمة: تقسيم العالم إلى مراحل
    export: ExportSettings = ExportSettings()


class PreviewRequest(BaseModel):
    project: Project
    resolution: int = Field(513, ge=65, le=1025)
    colors: bool = False                                      # أعِد خريطة ألوان المواد


class ProfileRequest(BaseModel):
    project: Project
    p0: Tuple[float, float]
    p1: Tuple[float, float]
    samples: int = Field(400, ge=2, le=2000)


class RouteRequest(BaseModel):
    project: Project
    kind: Literal["road", "river"] = "road"
    points: List[Tuple[float, float]] = Field(min_length=1)   # طريق: نقطتان فأكثر. نهر: منبع (+ مصب اختياري)
    resolution: Literal[257, 513] = 257
    max_grade: float = Field(0.08, gt=0, le=1)


class SuggestRequest(BaseModel):
    project: Project
    kind: SiteKind = "village"
    diameter_m: float = Field(300, gt=0)
    count: int = Field(5, ge=1, le=12)
    resolution: Literal[257, 513] = 513


class LotsRequest(BaseModel):
    project: Project
    site_id: str


class SimRequest(BaseModel):
    project: Project
    resolution: Literal[257, 513] = 513


class ViewRequest(BaseModel):
    project: Project
    x_m: float
    y_m: float
    height_m: float = Field(1.7, ge=0)
    radius_m: float = Field(2000, gt=0)
    resolution: Literal[257, 513] = 513
