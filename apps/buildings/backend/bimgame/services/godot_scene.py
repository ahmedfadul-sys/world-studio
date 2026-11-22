"""Godot 4 scene export: building GLB (collision via -colonly hints) + .tscn with openable doors, a test player and physics props.

The doors are NOT part of the GLB in this mode: each one becomes a small node (door.gd) with its hinge at the right place,
a physics leaf (AnimatableBody3D) and a proximity zone; the player presses E (action "interact") to open/close it.
"""
from __future__ import annotations

import math
import re
from pathlib import Path

from ..schema import Project, SceneOptions

DOOR_GD = '''extends Node3D
## BIM Builder door. The hinge is this node's origin; the leaf extends along local +X.
## Press the "interact" action (E) while standing close to open / close it.
@export var width := 0.86
@export var height := 2.1
@export var thickness := 0.045
@export var open_deg := 100.0
@export var swing := 1.0          # +1 / -1: which way the leaf swings
@export var color := Color(0.55, 0.38, 0.22)
@export var speed := 0.55
var is_open := false
var _leaf: AnimatableBody3D
var _label: Label3D
var _near := 0
var _tween: Tween

func _ready() -> void:
	if not InputMap.has_action("interact"):
		InputMap.add_action("interact")
		var ev := InputEventKey.new()
		ev.physical_keycode = KEY_E
		InputMap.action_add_event("interact", ev)
	_leaf = AnimatableBody3D.new()
	_leaf.name = "Leaf"
	add_child(_leaf)
	var box := BoxMesh.new()
	box.size = Vector3(width, height, thickness)
	var mat := StandardMaterial3D.new()
	mat.albedo_color = color
	box.material = mat
	var mi := MeshInstance3D.new()
	mi.mesh = box
	mi.position = Vector3(width / 2.0, height / 2.0, 0.0)
	_leaf.add_child(mi)
	var cs := CollisionShape3D.new()
	var bs := BoxShape3D.new()
	bs.size = box.size
	cs.shape = bs
	cs.position = mi.position
	_leaf.add_child(cs)
	var zone := Area3D.new()
	zone.name = "Zone"
	var zs := CollisionShape3D.new()
	var sp := SphereShape3D.new()
	sp.radius = maxf(width, 1.0) * 1.4
	zs.shape = sp
	zone.position = Vector3(width / 2.0, height / 2.0, 0.0)
	zone.add_child(zs)
	add_child(zone)
	zone.body_entered.connect(_on_enter)
	zone.body_exited.connect(_on_exit)
	_label = Label3D.new()
	_label.text = "[E]"
	_label.billboard = BaseMaterial3D.BILLBOARD_ENABLED
	_label.no_depth_test = true
	_label.pixel_size = 0.004
	_label.position = Vector3(width / 2.0, height + 0.2, 0.0)
	_label.visible = false
	add_child(_label)

func _on_enter(body: Node3D) -> void:
	if body.is_in_group("player"):
		_near += 1
		_label.visible = true

func _on_exit(body: Node3D) -> void:
	if body.is_in_group("player"):
		_near = maxi(0, _near - 1)
		_label.visible = _near > 0

func _unhandled_input(event: InputEvent) -> void:
	if _near > 0 and event.is_action_pressed("interact"):
		toggle()

func toggle() -> void:
	is_open = not is_open
	if _tween:
		_tween.kill()
	_tween = create_tween()
	var target := deg_to_rad(open_deg) * swing if is_open else 0.0
	_tween.tween_property(_leaf, "rotation:y", target, speed).set_trans(Tween.TRANS_SINE)
'''

PLAYER_GD = '''extends CharacterBody3D
## Simple first-person test player: WASD / arrows, Shift = run, Space = jump, mouse look, Esc = release mouse.
@export var speed := 4.5
@export var run_factor := 1.8
@export var jump_speed := 4.5
@export var mouse_sens := 0.0025
var _pitch := 0.0
var _gravity: float = ProjectSettings.get_setting("physics/3d/default_gravity")
@onready var cam: Camera3D = $Camera3D

func _ready() -> void:
	add_to_group("player")
	_bind("move_forward", KEY_W, KEY_UP)
	_bind("move_back", KEY_S, KEY_DOWN)
	_bind("move_left", KEY_A, KEY_LEFT)
	_bind("move_right", KEY_D, KEY_RIGHT)
	_bind("jump", KEY_SPACE)
	_bind("run", KEY_SHIFT)
	_bind("interact", KEY_E)
	Input.mouse_mode = Input.MOUSE_MODE_CAPTURED

func _bind(action: String, k1: Key, k2: Key = KEY_NONE) -> void:
	if InputMap.has_action(action):
		return
	InputMap.add_action(action)
	for k in [k1, k2]:
		if k != KEY_NONE:
			var ev := InputEventKey.new()
			ev.physical_keycode = k
			InputMap.action_add_event(action, ev)

func _unhandled_input(event: InputEvent) -> void:
	if event is InputEventMouseMotion and Input.mouse_mode == Input.MOUSE_MODE_CAPTURED:
		rotate_y(-event.relative.x * mouse_sens)
		_pitch = clampf(_pitch - event.relative.y * mouse_sens, -1.5, 1.5)
		cam.rotation.x = _pitch
	elif event is InputEventKey and event.pressed and event.keycode == KEY_ESCAPE:
		Input.mouse_mode = Input.MOUSE_MODE_VISIBLE
	elif event is InputEventMouseButton and event.pressed:
		Input.mouse_mode = Input.MOUSE_MODE_CAPTURED

func _physics_process(delta: float) -> void:
	if not is_on_floor():
		velocity.y -= _gravity * delta
	elif Input.is_action_just_pressed("jump"):
		velocity.y = jump_speed
	var d := Input.get_vector("move_left", "move_right", "move_forward", "move_back")
	var dir := (transform.basis * Vector3(d.x, 0.0, d.y)).normalized()
	var sp := speed * (run_factor if Input.is_action_pressed("run") else 1.0)
	velocity.x = dir.x * sp
	velocity.z = dir.z * sp
	move_and_slide()
'''


def _f(v: float) -> str:
    return f"{v:.5f}".rstrip("0").rstrip(".") if abs(v) > 1e-9 else "0"


def _slug(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9_]+", "_", s).strip("_") or "x"


class _Xf:
    """The worker's final transform: p' = scale * Rz(rot) * Mirror * (p - pivot), then glTF Y-up: (x, z, -y)."""

    def __init__(self, pivot, scale: float, rot_deg: float, mirror: bool):
        self.piv, self.s, self.mirror = pivot, scale, mirror
        r = math.radians(rot_deg)
        self.c, self.sn = math.cos(r), math.sin(r)

    def vec(self, x: float, y: float) -> tuple[float, float]:        # direction (no translation)
        if self.mirror:
            x = -x
        return self.c * x - self.sn * y, self.sn * x + self.c * y

    def pt(self, x: float, y: float, z: float) -> tuple[float, float, float]:
        dx, dy = self.vec(x - self.piv[0], y - self.piv[1])
        return self.s * dx, self.s * (z - self.piv[2]), -self.s * dy   # Godot (x, y, z)


def collect_doors(p: Project, xf: _Xf, open_deg: float) -> list[dict]:
    k = p.units.to_meters
    lv = {l.id: l for l in p.levels}
    walls = {e.id: e for e in p.elements if e.type == "wall"}
    out = []
    for e in p.elements:
        if e.type != "door" or e.wall_id not in walls:
            continue
        w = walls[e.wall_id]
        ax, ay, bx, by = w.a[0] * k, w.a[1] * k, w.b[0] * k, w.b[1] * k
        L = math.hypot(bx - ax, by - ay)
        if L < 1e-6:
            continue
        dx, dy = (bx - ax) / L, (by - ay) / L
        width, height = e.width * k, e.height * k
        leaf_w = max(0.3, width - 0.04)
        sign = 1.0 if e.hinge == "left" else -1.0                    # leaf direction along (+) / against (-) the wall
        hu = e.offset * k - sign * width / 2.0 + sign * 0.02         # hinge position along the wall
        hx, hy = ax + dx * hu, ay + dy * hu
        z = lv[w.level_id].elevation * k + e.sill * k
        origin = xf.pt(hx, hy, z)
        lx, ly = xf.vec(dx * sign, dy * sign)                         # leaf direction in output plan coords
        n = math.hypot(lx, ly) or 1.0
        X = (lx / n, 0.0, -ly / n)                                    # Godot axes
        Z = (-X[2], 0.0, X[0])                                        # X x Y with Y = up
        # which way does +open_deg turn the leaf?  local +X rotated by +90 deg about Y points at -Z
        nl = xf.vec(-dy, dx)                                          # plan "left" normal of the wall
        left = (nl[0], 0.0, -nl[1])
        want_left = e.swing == "left"
        turn = (-Z[0] * left[0] + -Z[2] * left[2])
        swing = (1.0 if (turn > 0) == want_left else -1.0)
        out.append({"id": e.id, "origin": origin, "X": X, "Z": Z, "width": leaf_w * xf.s, "height": height * xf.s - 0.02,
                    "swing": swing, "open_deg": open_deg, "name": e.name})
    return out


def write_scene(p: Project, out_dir: Path, stem: str, glb_name: str, pivot_report: dict, settings: dict, opts: SceneOptions) -> dict:
    """Write door.gd, player.gd and <stem>.tscn next to the GLB. Returns {files, doors, spawn}."""
    res = opts.res_dir or f"res://bim/{stem}/"
    if not res.endswith("/"):
        res += "/"
    xf = _Xf(pivot_report["offset_applied"], float(settings["scale"]), float(settings.get("rotate_deg", 0)), bool(settings.get("mirror_x", False)))
    doors = collect_doors(p, xf, opts.door_open_deg)
    lo, hi = pivot_report["bbox_min"], pivot_report["bbox_max"]       # output plan coords (x, y, z-up)
    cx = (lo[0] + hi[0]) / 2
    spawn = (cx, lo[2] + 0.12, -lo[1] + 4.0)                          # in front of the building's south side, looking at it
    (out_dir / "door.gd").write_text(DOOR_GD, encoding="utf-8")
    (out_dir / "player.gd").write_text(PLAYER_GD, encoding="utf-8")

    ext = [("PackedScene", res + glb_name, "bld"), ("Script", res + "door.gd", "door")]
    if opts.player:
        ext.append(("Script", res + "player.gd", "player"))
    sub: list[str] = []
    nodes: list[str] = []
    if opts.lights:
        sub += ['[sub_resource type="ProceduralSkyMaterial" id="skymat"]', "",
                '[sub_resource type="Sky" id="sky"]', 'sky_material = SubResource("skymat")', "",
                '[sub_resource type="Environment" id="env"]', "background_mode = 2", 'sky = SubResource("sky")', "tonemap_mode = 3", ""]
        nodes += ['[node name="WorldEnvironment" type="WorldEnvironment" parent="."]', 'environment = SubResource("env")', "",
                  '[node name="Sun" type="DirectionalLight3D" parent="."]',
                  "transform = Transform3D(0.866, -0.321, 0.383, 0, 0.766, 0.643, -0.5, -0.557, 0.663, 0, 20, 0)", "shadow_enabled = true", ""]
    nodes += ['[node name="Building" parent="." instance=ExtResource("bld")]', ""]
    if opts.ground:
        gy = lo[2] - 0.02
        sub += ['[sub_resource type="BoxShape3D" id="gshape"]', "size = Vector3(600, 0.2, 600)", "",
                '[sub_resource type="StandardMaterial3D" id="gmat"]', "albedo_color = Color(0.36, 0.40, 0.30, 1)", "",
                '[sub_resource type="PlaneMesh" id="gmesh"]', 'material = SubResource("gmat")', "size = Vector2(600, 600)", ""]
        nodes += [f'[node name="Ground" type="StaticBody3D" parent="."]', f"transform = Transform3D(1, 0, 0, 0, 1, 0, 0, 0, 1, {_f(cx)}, {_f(gy - 0.1)}, {_f(-(lo[1] + hi[1]) / 2)})", "",
                  '[node name="Shape" type="CollisionShape3D" parent="Ground"]', 'shape = SubResource("gshape")', "",
                  '[node name="Mesh" type="MeshInstance3D" parent="Ground"]', 'mesh = SubResource("gmesh")', "transform = Transform3D(1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0.1, 0)", ""]
    if doors:
        nodes += ['[node name="Doors" type="Node3D" parent="."]', ""]
    for i, d in enumerate(doors):
        X, Z, o = d["X"], d["Z"], d["origin"]
        nm = f"Door_{i + 1}_{_slug(d['id'])}"[:60]
        nodes += [f'[node name="{nm}" type="Node3D" parent="Doors"]',
                  f"transform = Transform3D({_f(X[0])}, 0, {_f(Z[0])}, {_f(X[1])}, 1, {_f(Z[1])}, {_f(X[2])}, 0, {_f(Z[2])}, {_f(o[0])}, {_f(o[1])}, {_f(o[2])})",
                  'script = ExtResource("door")', f"width = {_f(d['width'])}", f"height = {_f(d['height'])}",
                  f"open_deg = {_f(d['open_deg'])}", f"swing = {_f(d['swing'])}", f'metadata/bim_id = "{d["id"]}"', ""]
    if opts.player:
        sub += ['[sub_resource type="CapsuleShape3D" id="cap"]', "radius = 0.3", "height = 1.7", ""]
        nodes += ['[node name="Player" type="CharacterBody3D" parent="."]', f"transform = Transform3D(1, 0, 0, 0, 1, 0, 0, 0, 1, {_f(spawn[0])}, {_f(spawn[1])}, {_f(spawn[2])})",
                  'script = ExtResource("player")', "",
                  '[node name="Body" type="CollisionShape3D" parent="Player"]', 'shape = SubResource("cap")', "transform = Transform3D(1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0.85, 0)", "",
                  '[node name="Camera3D" type="Camera3D" parent="Player"]', "transform = Transform3D(1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 1.6, 0)", "current = true", ""]
    if opts.props:
        sub += ['[sub_resource type="BoxShape3D" id="crate_s"]', "size = Vector3(0.5, 0.5, 0.5)", "",
                '[sub_resource type="BoxMesh" id="crate_m"]', "size = Vector3(0.5, 0.5, 0.5)", ""]
        for j, dx in enumerate((-1.2, 0.0, 1.2)):
            nodes += [f'[node name="Crate{j + 1}" type="RigidBody3D" parent="."]', "mass = 8.0",
                      f"transform = Transform3D(1, 0, 0, 0, 1, 0, 0, 0, 1, {_f(spawn[0] + dx)}, {_f(spawn[1] + 0.35)}, {_f(spawn[2] - 2.5)})", "",
                      f'[node name="Shape" type="CollisionShape3D" parent="Crate{j + 1}"]', 'shape = SubResource("crate_s")', "",
                      f'[node name="Mesh" type="MeshInstance3D" parent="Crate{j + 1}"]', 'mesh = SubResource("crate_m")', ""]
    head = [f"[gd_scene load_steps={len(ext) + len(sub) // 3 + 1} format=3]", ""]
    head += [f'[ext_resource type="{t}" path="{path}" id="{i}"]' for t, path, i in ext] + [""]
    text = "\n".join(head + sub + ['[node name="' + _slug(stem) + '" type="Node3D"]', ""] + nodes).rstrip() + "\n"
    (out_dir / f"{stem}.tscn").write_text(text, encoding="utf-8")
    readme = (f"Godot scene export - {p.name}\n\n1. Copy this whole folder into your Godot 4 project at: {res}\n"
              f"2. Open {stem}.tscn (Godot imports {glb_name} first; collision shapes come from the '-colonly' / '-convcolonly' meshes).\n"
              "3. Run the scene (F6). WASD move, Shift run, Space jump, mouse look, Esc release mouse, E open/close a door.\n"
              "If you put the folder somewhere else, use Scene > Reload or edit the res:// paths at the top of the .tscn.\n")
    (out_dir / "README_godot.txt").write_text(readme, encoding="utf-8")
    files = [glb_name, f"{stem}.tscn", "door.gd", "player.gd", "README_godot.txt"]
    return {"files": files, "doors": len(doors), "spawn": [round(v, 3) for v in spawn], "res_dir": res}
