# BIM Builder – Game Edition / منشئ المباني – نسخة الألعاب

محرر 2D للمباني ← نموذج BIM (debim) ← Blender ← تصدير GLB/glTF/FBX إلى Godot.

2D building editor → debim BIM model → Blender → GLB/glTF/FBX export for Godot.

---

## المتطلبات / Requirements

- Python 3.13 (الخلفية / backend)
- Python 3.11 (فقط لوحدة `bpy` الخاصة بـ Blender) أو ملف Blender تنفيذي
- Node.js 20+

---

## التشغيل السريع / Quick start (Linux / macOS)

```bash
cd bim-builder
scripts/install.sh      # مرة واحدة: بيئات بايثون + مكتبات + بناء الواجهة
scripts/start.sh        # تشغيل كل شيء
```

ثم افتح / then open: **http://127.0.0.1:8000**

---

## التشغيل اليدوي / Manual run

### 1) الخلفية / Backend

```bash
cd bim-builder
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

cd backend
../.venv/bin/python -m uvicorn bimgame.api.app:app --port 8000
```

Windows:
```
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
cd backend
..\.venv\Scripts\python.exe -m uvicorn bimgame.api.app:app --port 8000
```
(Windows لم يُختبر / not tested)

التحقق / check: http://127.0.0.1:8000/api/health — الوثائق التفاعلية / API docs: http://127.0.0.1:8000/docs

> لا تستخدم `--reload` أثناء مهام البناء الطويلة؛ إعادة التحميل تقطع المهمة الجارية.
> Do not use `--reload` during long builds; a reload kills the running job.

### 2) الواجهة / Frontend

وضع التطوير / dev mode (الخلفية يجب أن تعمل على 8000):
```bash
cd bim-builder/frontend
npm install
npm run dev
```
افتح الرابط الذي يطبعه Vite (غالباً http://localhost:5173). طلبات `/api` تُحوَّل تلقائياً إلى الخلفية.

بناء الإنتاج / production build (تخدمه الخلفية نفسها على :8000):
```bash
npm run build
```

### 3) Blender (للتصدير وأدوات التحسين / for export and asset tools)

بدون Blender تعمل الواجهة والمعاينة ثلاثية الأبعاد، لكن التصدير وأدوات (Optimize, Collision, LOD, UV) تحتاجه.
Without Blender the editor and 3D preview work, but export and the asset tools need it.

الخيار أ / Option A — وحدة bpy:
```bash
python3.11 -m venv .venv-blender
.venv-blender/bin/pip install -r requirements-blender.txt
```

الخيار ب / Option B — Blender مثبّت / installed Blender:
```bash
export BIM_BLENDER_CMD=/path/to/blender
```

---

## متغيرات البيئة / Environment variables

| المتغير | الوصف |
|---|---|
| `BIM_DATA_DIR` | مكان حفظ المشاريع (الافتراضي `data/`) |
| `BIM_BLENDER_CMD` | مسار ملف Blender التنفيذي |
| `BIM_BLENDER_PYTHON` | مفسر بايثون الخاص بـ bpy |
| `BIM_BLENDER_TIMEOUT` | مهلة Blender بالثواني (300) |
| `BIM_BLENDER_MAX_RSS_MB` | حد ذاكرة Blender (3500) |
| `BIM_FRONTEND_DIST` | مجلد الواجهة المبنية |
| `BIM_PREVIEW_BLENDER` | `1` = بناء المعاينة عبر Blender بدل الكاتب السريع داخل العملية |

---

## الاستخدام / Usage

1. **Projects** → أنشئ مشروعاً / create a project.
2. **2D Editor** → ارسم جدراناً وأبواباً ونوافذ؛ الالتقاط: نهايات الجدران ثم خطوطها ثم الشبكة. Delete للحذف، وتراجع/إعادة من الشريط.
   - **جدران دائرية / Circle walls** (مفتاح `Q`): انقر المركز ثم نصف القطر. **جدران منحنية / Curved walls** (مفتاح `A`): انقر البداية ثم نقطة على المنحنى ثم النهاية. تُنشأ كسلسلة جدران مستقيمة قصيرة (≤ 1.5 م) بزوايا مائلة مضبوطة؛ الأبواب والنوافذ تُوضع على قطعة واحدة. / Drawn as short straight segments (≤ 1.5 m) with exact mitred joints; doors/windows sit on one segment. الأرضية والسقف: ارسم مضلعاً يتبع الدائرة.
   - **أرضية/سقف/غرفة**: شريط أعلى المحرر لاختيار الشكل (مضلع / مستطيل / دائرة). السقف يدعم: مسطح، مائل، جملوني، رباعي (hip)، **مخروطي/هرمي، قبة، قبو أسطواني**؛ غيّره من لوحة الخصائص. / Floor/roof/room tools have a shape bar (polygon / rectangle / circle). Roof kinds: flat, shed, gable, hip, **cone/pyramid, dome, barrel vault** (change in Properties).
   - **وجه الجدار / Wall face (2D sculpting)**: حدّد جداراً ثم اضغط «تحرير وجه الجدار» (أو انقر عليه مرتين) لتفتح لوحة الواجهة الأمامية للجدار. ارسم مستطيلاً أو دائرة أو قوساً أو مثلثاً أو نجمة أو مضلعاً حراً، واختر نوعه: **قص كامل** (فتحة)، **تجويف** (كوّة بعمق)، **نتوء** (بارز بعمق) على الوجه الأيمن أو الأيسر. اسحب لتنقل، واسحب المقابض لتغيّر الحجم. قوالب جاهزة: شرفات وإطار بارز. / Select a wall, click *Edit wall face* (or double-click it): draw shapes on the wall elevation as through-cuts, recesses or reliefs; presets: battlements, frame moulding. Needs `manifold3d` (in requirements.txt).
   - **معالج الغرف / Room wizard** (مفتاح `T`): اختر النوع (صالة، قاعة، مجلس، غرفة نوم، مطبخ، حمام، ممر…) واكتب العرض×العمق والاسم، ثم انقر على المخطط: تُنشأ 4 جدران + أرضية + باب + عنصر غرفة باسمها ومساحتها. الغرف المتجاورة تتشارك الجدران المطابقة تماماً. / Pick a type, type W×D and a name, click: walls + floor + door + named room are created; identical neighbouring walls are shared.
   - **التعديل بعد الرسم / Editing afterwards**: «زوايا مترابطة» (مفعّل افتراضياً): اسحب مربع الزاوية أو معيّن الضلع فتتحرك معه الجدران والأرضية والغرفة المتصلة. وفي الخصائص حقلا العرض والعمق لتغيير حجم أي غرفة مستطيلة (مواضع الأبواب تبقى نسبية). زر «إنشاء الجدران/الأرضية الناقصة» لغرفة رُسمت كمحيط فقط. / *Linked corners* drags walls, floor and room together; width/depth fields resize rectangular rooms.
   - **الكتابة بالأبعاد / Typed dimensions**: أثناء رسم جدار أو عارضة أو دائرة أو مستطيل اكتب الرقم مباشرة ثم Enter: `4.5` (باتجاه المؤشر) · `4.5<30` (بزاوية 30°) · `4x3` (مستطيل). / Type `4.5`, `4.5<30` or `4x3` then Enter.
   - **نسخ ولصق / Copy-paste**: Ctrl+C / Ctrl+V (الأول عند المؤشر) / Ctrl+D للتكرار. **مصفوفة / Array** (من «أدوات المخطط»): خطية أو حول نقطة مع تدوير النسخ. **نسخ إلى طابق** أو نسخ الطابق كاملاً. الأبواب والنوافذ تُنسخ مع جدرانها.
   - **السلالم / Stairs**: يُضبط عدد الدرجات تلقائياً على ارتفاع الطابق؛ أزرار «ضبط الدرجات» وتحويل إلى درج **L** أو **U** (مرحلتان وبسطة).
   - **صورة مخطط خلفية / Plan image underlay**: «أدوات المخطط ← استيراد صورة مخطط / PDF» (PNG وJPG أو صفحة من PDF؛ يُحوَّل داخل المتصفح). بعد الاستيراد انقر نقطتين على الصورة تعرف المسافة الحقيقية بينهما (مثلاً عرض الصالة) واكتبها فيُضبط المقياس، مع خيار تعديل ميلان المسح. تتحكم بالشفافية والإظهار والموضع والدوران من لوحة «صورة المخطط»، ثم ارسم الجدران فوقها. لا تُصدَّر مع النموذج. / Import a scan or one PDF page, click two points of known distance to calibrate (optionally straighten), then trace over it; never exported.
   - **استيراد DXF**: «أدوات المخطط ← استيراد DXF» (ملف ASCII فقط): LINE وLWPOLYLINE (مع الأقواس) وPOLYLINE وCIRCLE وARC تتحول إلى جدران؛ اختيار الطبقات والوحدة والسماكة وربط النهايات. لا يُقرأ: DWG، DXF الثنائي، الكتل (INSERT)، الخطوط المزدوجة للجدران (كل خط يصبح جداراً). / ASCII DXF only; DWG, binary DXF and blocks are not read; double-line walls become two walls.
   - **تطبيق على الكل / Apply to all**: حدّد جداراً (أو عموداً…) في لوحة الخصائص؛ زر ⇉ بجانب كل حقل يطبّقه على كل العناصر من نفس النوع (مثلاً نفس الارتفاع والسماكة لكل الجدران مع بقاء الأطوال مختلفة، أو نفس القطر لكل الأعمدة)، وزر «تطبيق الكل» يطبّق كل المواصفات؛ النطاق: المشروع كله أو الطابق الحالي. / ⇉ next to a field applies it to every element of that type; length/position are never overwritten.
3. **3D Preview** → معاينة سريعة (تُبنى تلقائياً عند فتح التبويب، دون تشغيل Blender)؛ تُعاد معالجة العناصر المتغيّرة فقط.
   - **وضع المشي / Walk mode**: زر «Walk inside». W A S D أو الأسهم للحركة، السحب للنظر، Q/E للدوران، R/F أعلى/أسفل، Shift للركض، نقر مزدوج على أرضية للانتقال إليها، Esc للخروج؛ خيار «Collide with walls» ومحدّد الطابق. / First-person walkthrough with wall collision and level picker.
4. **Godot Export** → ملف GLB مع عقد التصادم (`-convcolonly`) وLOD (`_LOD1…`). خيارا **Rotate (0/90/180/270)** و**Mirror X** لتصحيح اتجاه النموذج في Godot إن ظهر مقلوباً. / Rotate and Mirror-X options fix orientation if the model appears flipped in Godot.

مشروع تجريبي / demo: `examples/demo_house.json` (والناتج المصدَّر `examples/demo_house.glb`).

---

### القوالب / Templates
- في المحرر اختر أداة (جدار، باب، نافذة، عمود، كمرة، أرضية، سقف، درج) فتظهر بطاقة **القوالب** في الجانب: قوالب جاهزة (جدار خارجي 30 سم، سور، باب مزدوج، نافذة عريضة...) وقوالبك الخاصة.
- اضغط قالباً ليُستخدم لكل عنصر جديد من هذا النوع (والغرف من معالج الغرف تستخدم قالب الجدار)، واضغطه مرة أخرى لإيقافه.
- حدد عناصر من نفس النوع واضغط «تطبيق على المحدد». لحفظ قالب خاص: حدد عنصراً واحداً (مثلاً جدار سمكه 0.3 وارتفاعه 3.2)، اكتب اسماً واضغط «حفظ القالب». القوالب تُحفظ داخل المشروع (`templates`) وتُحوَّل أطوالها لوحدات المشروع.

### مختبر الخامات / Material Lab
- في لوحة **Materials** اختر خامة ثم من بطاقة «مختبر الخامات» اختر النوع (طوب، خرسانة، لياسة، خشب، بلاط، رخام، حجر، معدن، أسفلت)، عدّل الألوان والخشونة والبروز والتباين و«حجم الوحدة» (الحجم الحقيقي بالمتر لتكرار واحد) واضغط **Generate with Blender**.
- يبني Blender (في الخلفية) شبكة عقد إجرائية ثم يخبز ثلاث خرائط قابلة للتكرار بلا حدود ظاهرة: اللون، Normal، والخشونة/المعدنية (صيغة glTF). تظهر فوراً في معاينة ثلاثية الأبعاد وتُصدَّر في GLB/glTF/FBX.
- يحتاج Blender. معاينة الموقع السريعة تعرض الألوان فقط؛ الخرائط تظهر في التصدير الكامل.

### النسخ الاحتياطية / Backups
- الإعدادات ← **Backups**: نسخ مؤرَّخة للمشروع تُؤخذ تلقائياً (حوالي كل 5 دقائق أثناء الحفظ، وآخر 30 نسخة) ويدوياً بزر «Back up now». الاسترجاع يحفظ الحالة الحالية أولاً فيمكن التراجع. تُحفظ في `<project>/backups/`.

### مظهر Godot في المعاينة / Godot look
- في **3D Preview** فعّل «Godot look»: سماء متدرجة وإضاءة محيطة وشمس بظلال ناعمة وتحويل ألوان ACES (تقريب لمظهر Godot 4 الافتراضي) مع مزلقَي ارتفاع الشمس واتجاهها. هو تقريب في المتصفح وليس Godot نفسه.

### مشهد Godot (.tscn) / Godot scene export
- **Export ← «مشهد Godot»** يصدّر: `<name>.glb` + `<name>.tscn` + `door.gd` + `player.gd` + `README_godot.txt`. انسخ المجلد كاملاً إلى مشروع Godot 4 في المسار المكتوب في الحقل (`res://...`).
- التصادم من أجسام `-colonly/-convcolonly` داخل الـGLB (يولّدها Godot عند الاستيراد). الأبواب **ليست** داخل الـGLB: كل باب عقدة منفصلة بمفصلة وجسم `AnimatableBody3D` ومنطقة اقتراب؛ اللاعب يضغط **E** قربه ليفتح/يغلق. حقلا الباب «جهة المفصلة» و«يُفتح نحو» في المحرر.
- المشهد يحتوي سماء وشمساً بظلال، أرضية بتصادم، لاعباً تجريبياً (WASD، Shift، Space، الفأرة) وثلاثة صناديق `RigidBody3D` لتجربة الفيزياء. لم يُختبر داخل Godot نفسه (اختُبرت الرياضيات وبنية الملف فقط).

### مولّد الفلل والقصور / Villa & palace generator
- Plan tools ← **Villa / palace from area**: اكتب مساحة البناء الكلية (مثل 2000 أو 5000 م²، مجموع كل الأدوار) فيُرسم مخطط كامل: غرف بأسمائها، ممر، مدخل بدرج U، أبواب، نوافذ، سقف، على أدوار منفصلة (تلقائي أو 1–4). المساحة الناتجة تطابق المطلوب بدقة ~0.02%. كل شيء قابل للتعديل (الزوايا مربوطة).

### الأطوال والموازنة / Lengths & balance
- عند سحب زاوية جدار تظهر أطوال الجدران المتأثرة مع التغيّر (+/−)، وتُجذب النقطة إلى موضع التساوي عندما يلتقي جداران (تظهر علامة «=»، مثلاً 200 | 200).
- بطاقة **الأطوال والموازنة**: كتابة طول دقيق لجدار، «قسّم إلى أجزاء متساوية»، و«وازن الأطوال» لسلسلة جدران متصلة (مع المجموع والفرق).

## الاختبارات / Tests

```bash
scripts/test.sh
# أو / or:
cd backend && ../.venv/bin/python -m pytest -q      # 72 اختباراً
cd frontend && npx vitest run                        # 58 اختباراً
```

---

## حل المشاكل / Troubleshooting

- `No module named uvicorn` → لم تُثبَّت المكتبات: `.venv/bin/pip install -r requirements.txt`
- `No module named bimgame` → شغّل الأمر من داخل مجلد `backend`
- `address already in use` → غيّر المنفذ `--port 8001` (وعدّل `frontend/vite.config.js` في وضع التطوير)
- `Blender is not available` → ثبّت `.venv-blender` أو اضبط `BIM_BLENDER_CMD`

---

## الوثائق / Docs

`docs/01` الجدوى وdebim · `02` البنية والـ API · `03` التثبيت · `04` دليل المستخدم · `05` الأداء · `06` ما تم التحقق منه وما لم يتم

**غير مُتحقَّق منه / not verified:** الاستيراد داخل Godot (`godot_test/` لم يُشغَّل)، ملف Blender التنفيذي الحقيقي، إعادة استيراد FBX، سكربتات Windows.

**Blender 5.2:** الكود يتجنب الواجهات المحذوفة ويفحص خصائص التصدير ديناميكياً، لكن لم أستطع تجربة 5.2 (الإصدار الأحدث المتاح لي 5.0.1). / Not testable here (latest available: 5.0.1).

## Ruins (destroyed buildings)
Plan tools → **Ruin / destroy building…** cuts the building along a jagged line (random or chosen angle/position), breaks and lowers walls near the cut, drops slabs/roofs, fits or removes openings that no longer fit, and scatters rubble boxes (`decor`, `props.debris`) near the building. Scope: whole drawing, current level or selection. Damage, jaggedness and rubble amount are adjustable; **Another result** re-rolls the seed; **Back to the original** restores; **Clear debris** removes only the rubble. Everything is undoable.

## Plaza (square for leaders)
Plan tools → **Plaza**: circle, ellipse, square, rectangle, hexagon, octagon or cross; width/depth, height, number and width of steps around it, an optional central dais (for the leader) and an optional ring of columns. Built from raised floors (`z_offset` = thickness = height), so it exports to GLB/Godot with collision like any slab.

## Room editing
Select a room (or click it – its floor selects the room): **Rooms** card in the inspector.
- Two rooms selected → **Merge**: shared walls and their doors/windows are removed, polygons and floors are united.
- One room → **Split** with a new interior wall + door at a chosen direction/position; boundary walls are split at the cut and floors are cut too.
Room type is changed in the same inspector.

## Carving (wall-face editor) – improvements
- **Open it from 3D:** in *3D Preview* press **⛏ Carve**, then click any wall; its carving window opens on the side you clicked. When you press *Done* the preview is rebuilt automatically. (2D: double-click a wall, as before.)
- **Shapes:** rectangle, rounded rectangle, circle, ellipse, semicircle/dome, arch, pointed (gothic) arch, triangle, trapezoid, diamond, hexagon, octagon, cross, star, free polygon, and a **slanted bar** (click start, click end – any angle, width adjustable). Overlapping shapes combine, so most drawings can be assembled from these.
- **Snapping:** shapes snap to wall edges/centre, door & window edges, and the edges/centres/vertices of other shapes (pink guide lines), to the same width/height as another shape (orange guides), and to the grid. Hold **Alt** for free placement. Moving a shape snaps its edges and centre.
- **Angle:** draw new shapes at an angle (slider), rotate the selection by ±15/45/90° or any value, mirror, centre on the wall, and repeat (array) with spacing.

## Housekeeping & limits (stability)
- Only the newest **6** export folders per project are kept (`BIM_KEEP_EXPORTS`); the preview folder and the latest build are never deleted.
- Finished jobs in SQLite are trimmed to the newest 300; `profile.jsonl` rotates at 512 KB; project saves are fsynced before the atomic rename.
- A wall holds at most 300 carved shapes (the editor stops adding beyond that instead of failing to save).
- Measured (headless, CPU-only): 40 000 m² palace (675 elements) → scene export 8 s, Blender peak 424 MB; fast preview 0.2 s; 2D editor 60 fps; JS heap < 30 MB.
