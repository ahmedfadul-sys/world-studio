"""يعمل داخل Blender (bpy): يبني المشهد الكامل من build.json بواسطة import_build.py ثم يحفظه ملف .blend واحداً.

الاستعمال (يستدعيه backend/app/blendexport.py):
    python export_blend.py <build.json> <out.blend>                      # بايثون فيه وحدة bpy
    blender -b --factory-startup -P export_blend.py -- <build.json> <out.blend>
import_build.py يجب أن يكون بجوار build.json (يضعه التصدير هناك) — لا تعديل عليه: هو مرجع التحسينات.
"""
import os
import sys
import traceback


def main():
    args = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
    if len(args) < 2:
        raise SystemExit("usage: export_blend.py <build.json> <out.blend>")
    build, out = os.path.abspath(args[0]), os.path.abspath(args[1])
    sys.path.insert(0, os.path.dirname(build))
    import bpy
    bpy.ops.wm.read_factory_settings(use_empty=True)
    import import_build
    import_build.main(build)
    try:
        bpy.ops.file.pack_all()                      # يضمّن الصور (الأقنعة والخامات) فيصير الملف مكتفياً بذاته
    except Exception:                                # noqa: BLE001
        print("WARNING: pack_all failed — textures stay external:\n" + traceback.format_exc())
    bpy.ops.wm.save_as_mainfile(filepath=out, compress=True)
    print(f"TF_BLEND_SAVED {out} {os.path.getsize(out)}")


if __name__ == "__main__":
    main()
