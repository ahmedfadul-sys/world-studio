"""تقسيم العالم إلى مراحل وتصديرها لـ Godot: ZIP فيه مجلد لكل مرحلة (Level1/Level1.tscn + terrain.glb + level.gd).

العالم واحد، والمرحلة مستطيل منه. كل مرحلة تُخبز من العالم نفسه بالإحداثيات المطلقة فتتطابق الحواف بين المراحل المتجاورة،
وملف world_levels.json يحمل موضع كل مرحلة في العالم لإعادة ضمّها في اللعبة عند الحاجة.
"""
from __future__ import annotations
import json, re, zipfile
from typing import Callable
from . import glb as glb_mod

ROOT = "World_Game"

_GD = '''extends Node3D
## يُنشئ تصادماً لتضاريس المرحلة عند التشغيل. المرحلة تبدأ عند (0,0,0) وأبعادها في level.json.
func _ready() -> void:
	for n in find_children("Terrain*", "MeshInstance3D", true, false):
		(n as MeshInstance3D).create_trimesh_collision()
'''


def level_folder(i: int) -> str:
    return f"Level{i + 1}"


def validate_levels(project) -> list[str]:
    errs, w = [], project.world
    ids = set()
    for i, lv in enumerate(project.levels):
        if lv.id in ids:
            errs.append(f"معرّف مكرر: {lv.id}")
        ids.add(lv.id)
        if lv.x_m + lv.w_m > w.size_x_m + 1e-6 or lv.y_m + lv.h_m > w.size_y_m + 1e-6:
            errs.append(f"المرحلة {i + 1} تخرج عن حدود العالم")
    return errs


def tscn(name: str, size_x: float, size_z: float, zmid: float) -> str:
    cx, cz = size_x / 2, -size_z / 2
    return f'''[gd_scene load_steps=5 format=3]

[ext_resource type="PackedScene" path="res://{ROOT}/{name}/terrain.glb" id="1_terrain"]
[ext_resource type="Script" path="res://{ROOT}/{name}/level.gd" id="2_script"]

[sub_resource type="ProceduralSkyMaterial" id="sky_mat"]

[sub_resource type="Sky" id="sky"]
sky_material = SubResource("sky_mat")

[sub_resource type="Environment" id="env"]
background_mode = 2
sky = SubResource("sky")
ambient_light_source = 3
tonemap_mode = 2

[node name="{name}" type="Node3D"]
script = ExtResource("2_script")
metadata/size_m = Vector2({size_x:.3f}, {size_z:.3f})

[node name="Terrain" parent="." instance=ExtResource("1_terrain")]

[node name="Sun" type="DirectionalLight3D" parent="."]
transform = Transform3D(0.866, -0.354, 0.354, 0, 0.707, 0.707, -0.5, -0.612, 0.612, {cx:.1f}, {zmid + 400:.1f}, {cz:.1f})
shadow_enabled = true
directional_shadow_max_distance = 600.0

[node name="WorldEnvironment" type="WorldEnvironment" parent="."]
environment = SubResource("env")

[node name="PlayerStart" type="Marker3D" parent="."]
transform = Transform3D(1, 0, 0, 0, 1, 0, 0, 0, 1, {cx:.1f}, {zmid + 5:.1f}, {cz:.1f})
'''


def export_levels(project, out_path: str, resolution: int = 513, tex_px: int = 2048,
                  progress: Callable[[str, float], None] = lambda s, f: None) -> dict:
    errs = validate_levels(project)
    if errs:
        raise ValueError("؛ ".join(errs))
    if not project.levels:
        raise ValueError("لا توجد مراحل: ارسم مرحلة واحدة على الأقل.")
    n, meta = len(project.levels), []
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as z:
        for i, lv in enumerate(project.levels):
            folder = level_folder(i)
            reg = (lv.x_m, lv.y_m, lv.x_m + lv.w_m, lv.y_m + lv.h_m)
            data, rep = glb_mod.build_glb(project, resolution, tex_px, jpeg_quality=88, region=reg,
                                          progress=lambda s, f, i=i: progress(f"المرحلة {i + 1}/{n}: {s}", (i + f) / n))
            z.writestr(f"{ROOT}/{folder}/terrain.glb", data)
            zmin = zmax = 0.0
            # الارتفاع الأوسط لموضع الشمس/اللاعب من تقرير الملف نفسه
            try:
                import struct
                jl = struct.unpack("<I", data[12:16])[0]
                ex = json.loads(data[20:20 + jl])["asset"]["extras"]
                zmin, zmax = ex["z_min_m"], ex["z_max_m"]
            except Exception:  # noqa: BLE001
                pass
            z.writestr(f"{ROOT}/{folder}/{folder}.tscn", tscn(folder, lv.w_m, lv.h_m, (zmin + zmax) / 2))
            z.writestr(f"{ROOT}/{folder}/level.gd", _GD)
            info = {"folder": folder, "id": lv.id, "name": lv.name or folder, "origin_m": [lv.x_m, lv.y_m], "size_m": [lv.w_m, lv.h_m],
                    "z_min_m": zmin, "z_max_m": zmax, "vertices": rep["vertices"], "triangles": rep["triangles"]}
            z.writestr(f"{ROOT}/{folder}/level.json", json.dumps(info, ensure_ascii=False, indent=2))
            meta.append(info)
        z.writestr(f"{ROOT}/world_levels.json", json.dumps({"world_size_m": [project.world.size_x_m, project.world.size_y_m], "levels": meta}, ensure_ascii=False, indent=2))
        z.writestr(f"{ROOT}/README.txt", "انسخ مجلد World_Game إلى مشروع Godot 4 (بجوار project.godot) ثم افتح LevelN/LevelN.tscn.\n"
                   "كل مرحلة تبدأ من (0,0,0): X شرقاً و -Z شمالاً. موضعها في العالم الواحد في world_levels.json.\n")
    return {"levels": meta}
