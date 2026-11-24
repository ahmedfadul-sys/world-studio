# User guide / دليل المستخدم

**EN** — Create a project (Projects). In *2D Editor* pick a tool on the left: wall (click points, double-click/Esc ends), door/window/arch (click a wall), column, beam, floor, roof, stair, room, decor. Snapping: endpoints > wall lines > grid. Select + drag handles to edit; Delete removes; undo/redo in the toolbar. *Building* sets levels, *Materials* colours/textures, *Modules* reusable parameters (editing a field on an element protects it from the module). *3D Preview* builds a fast low-poly preview (only changed elements rebuilt). *Optimize / Collision / LOD / UV* run Blender steps; *Godot Export* writes GLB/glTF/FBX with collision (`-convcolonly`) and LOD (`_LOD1…`) nodes. *Performance* shows RAM and build history. Language/theme switch in the header (Arabic is RTL).

**AR** — أنشئ مشروعاً من «المشاريع». في «المحرر ثنائي الأبعاد» اختر أداة (جدار، باب، نافذة، عمود، أرضية، سقف، درج…). الالتقاط: نهايات الجدران ثم خطوطها ثم الشبكة. اسحب المقابض للتعديل، Delete للحذف، وتراجع/إعادة من الشريط. «المعاينة ثلاثية الأبعاد» تبني نموذجاً خفيفاً وتعيد بناء العناصر المتغيّرة فقط. أدوات التحسين والتصادم وLOD وUV تعمل عبر Blender، و«تصدير Godot» ينتج GLB/glTF/FBX. تبديل اللغة والمظهر من الشريط العلوي.

## الطرق وأعمدة الإنارة ومخطط المدينة والبرج الدائري

- **طريق (P):** اختر أداة «طريق»، حدّد نوع السطح (أسفلت / ترابي / حجري / حصى / مبلّط / خرسانة / رملي) والعرض وعرض الرصيف في اللوحة العائمة، ثم انقر نقاط خط المنتصف؛ نقر مزدوج أو Enter للإنهاء. تعديل الطريق لاحقًا من المفتّش أو بسحب نقاطه.
- **عمود إنارة (L):** انقر لوضع عمود واحد، أو حدّد طريقًا واضغط «إضافة أعمدة إنارة على طول هذا الطريق» (المسافة والجانب). لكل عمود ضوء حقيقي (نقطي) يظهر في معاينة GLB وGodot/Blender.
- **مخطط المدينة:** لوحة «City plan» في المفتّش: شبكة هندسية، خطوط متوازية، شعاعي، أو خط مفرد (أداة I). تظهر في المحرر ثنائي الأبعاد فقط، ولا تدخل البناء ولا المعاينة ولا التصدير؛ وتلتصق بها العناصر عند تفعيل الالتصاق.
- **برج دائري:** زر «برج دائري» في أدوات المخطط: عدد الطوابق ونصف القطر وسلّم لولبي وشبابيك وسقف (مخروطي/قبة/مسطح) وموضع X/Y. السلّم اللولبي متاح أيضًا لأي درج (النوع: لولبي).
- **فيلا/قصر/ساحة:** تُوضع الآن يمين المباني الموجودة تلقائيًا ويمكن تحديد X/Y؛ بعد الإنشاء تكون محددة فيمكن سحبها كمجموعة. نوافذ الحوار صارت قابلة للتمرير داخل النافذة.
