import re
import bmesh
import bpy
from mathutils import Vector

from ..i18n import t, is_chinese


# ============================================================
# Status constants
# ============================================================
OK = 'ok'        # ✅
ERROR = 'error'  # ❌
WARN = 'warn'    # ⚠️

STATUS_ICON = {
    OK: '✅',
    ERROR: '❌',
    WARN: '⚠️',
}


class CheckResult:
    """Single check result item."""

    def __init__(self, status, label, detail=''):
        self.status = status
        self.label = label
        self.detail = detail

    def __str__(self):
        icon = STATUS_ICON.get(self.status, '?')
        text = f"{icon} {self.label}"
        if self.detail:
            text += f": {self.detail}"
        return text


# ============================================================
# Mesh checks (2.1)
# ============================================================

# Naming: sm_ + [letters/digits/underscore] + XX (two digits at end, no underscore before digits)
# Default regex - can be overridden by user via check settings
_DEFAULT_MODEL_NAME_REGEX = r'^sm_[a-zA-Z0-9_]*[a-zA-Z0-9]\d{2}$'
_RE_MODEL_NAME = re.compile(_DEFAULT_MODEL_NAME_REGEX)
# Material multi-suffix: mi_ + model_middle + <suffix>
# Accepts both M2-spec letter suffixes (mi_xxx01a/b/c) and the legacy
# numeric underscore suffixes (mi_xxx01_01/_02).
_RE_MATERIAL_SUFFIX = re.compile(r'([a-z]|_\d{2})$', re.IGNORECASE)


def check_mesh_naming(obj, regex_pattern=None):
    """2.1.1 Model naming: validated against user-configurable regex.
    For LOD models, strip _LODx suffix before checking.

    Args:
        obj: the mesh object
        regex_pattern: custom regex string. If None or empty, uses default.
    """
    name = obj.name
    # Strip _LODx suffix for LOD models
    check_name = re.sub(r'_LOD\d+$', '', name, flags=re.IGNORECASE)

    # Use custom regex if provided, otherwise default
    if regex_pattern:
        try:
            pattern = re.compile(regex_pattern)
        except re.error:
            # Invalid regex - fall back to default and warn
            if is_chinese():
                return CheckResult(ERROR, t("Model Naming"), f"正则表达式无效: {regex_pattern}")
            return CheckResult(ERROR, t("Model Naming"), f"Invalid regex: {regex_pattern}")
    else:
        pattern = _RE_MODEL_NAME

    if pattern.match(check_name):
        return CheckResult(OK, t("Model Naming"), name)
    if is_chinese():
        return CheckResult(ERROR, t("Model Naming"), f"'{name}' 不符合命名规则")
    return CheckResult(ERROR, t("Model Naming"), f"'{name}' does not match naming rule")


def check_material_naming(obj):
    """2.2.2 Material naming: mi_ prefix, single=match model, multi=_XX suffix.
    For LOD models, strip _LODx suffix before extracting model middle.
    """
    model_name = obj.name
    # Strip _LODx suffix for LOD models
    check_name = re.sub(r'_LOD\d+$', '', model_name, flags=re.IGNORECASE)
    model_middle = _get_model_middle(check_name)
    if model_middle is None:
        return CheckResult(ERROR, t("Material Naming"), t("Model name invalid, cannot verify"))

    slots = [s for s in obj.material_slots if s.material]
    if not slots:
        return CheckResult(ERROR, t("Material Naming"), t("No materials"))

    errors = []
    for slot in slots:
        mat_name = slot.material.name
        if not mat_name.lower().startswith('mi_'):
            errors.append(f"'{mat_name}' {t('does not start with mi_')}")
            continue
        mat_middle = mat_name[3:]  # remove 'mi_'
        if len(slots) == 1:
            if mat_middle == model_middle:
                continue
            else:
                if is_chinese():
                    errors.append(f"'{mat_name}'应为'mi_{model_middle}'")
                else:
                    errors.append(f"'{mat_name}' should be 'mi_{model_middle}'")
        else:
            m = _RE_MATERIAL_SUFFIX.search(mat_middle)
            if not m:
                errors.append(f"'{mat_name}' {t('missing _XX suffix')}")
                continue
            mat_base = mat_middle[:m.start()]
            if mat_base == model_middle:
                continue
            else:
                if is_chinese():
                    errors.append(f"'{mat_name}'基础部分应为'mi_{model_middle}'")
                else:
                    errors.append(f"'{mat_name}' base should be 'mi_{model_middle}'")

    if errors:
        return CheckResult(ERROR, t("Material Naming"), "、".join(errors))
    return CheckResult(OK, t("Material Naming"))


def check_transform_zero(obj):
    """2.1.2 Transform zeroed: location/rotation/scale must all be zeroed"""
    loc = obj.location
    rot = obj.rotation_euler
    scale = obj.scale
    issues = []
    if is_chinese():
        if abs(loc.x) > 1e-6 or abs(loc.y) > 1e-6 or abs(loc.z) > 1e-6:
            issues.append(f"位置({loc.x:.4f},{loc.y:.4f},{loc.z:.4f})")
        if abs(rot.x) > 1e-6 or abs(rot.y) > 1e-6 or abs(rot.z) > 1e-6:
            issues.append(f"旋转({rot.x:.4f},{rot.y:.4f},{rot.z:.4f})")
        if abs(scale.x - 1.0) > 1e-6 or abs(scale.y - 1.0) > 1e-6 or abs(scale.z - 1.0) > 1e-6:
            issues.append(f"缩放({scale.x:.4f},{scale.y:.4f},{scale.z:.4f})")
    else:
        if abs(loc.x) > 1e-6 or abs(loc.y) > 1e-6 or abs(loc.z) > 1e-6:
            issues.append(f"Location({loc.x:.4f},{loc.y:.4f},{loc.z:.4f})")
        if abs(rot.x) > 1e-6 or abs(rot.y) > 1e-6 or abs(rot.z) > 1e-6:
            issues.append(f"Rotation({rot.x:.4f},{rot.y:.4f},{rot.z:.4f})")
        if abs(scale.x - 1.0) > 1e-6 or abs(scale.y - 1.0) > 1e-6 or abs(scale.z - 1.0) > 1e-6:
            issues.append(f"Scale({scale.x:.4f},{scale.y:.4f},{scale.z:.4f})")
    if issues:
        return CheckResult(ERROR, t("Transform Zeroed"), "、".join(issues))
    return CheckResult(OK, t("Transform Zeroed"))


def check_loose_geometry(obj):
    """2.1.3 Loose geometry: >=1 is error"""
    if obj.type != 'MESH' or not obj.data:
        return CheckResult(OK, t("Loose Geometry"), t("Not a mesh object"))
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    loose_verts = sum(1 for v in bm.verts if not v.link_edges)
    loose_edges = sum(1 for e in bm.edges if len(e.link_faces) == 0)
    bm.free()
    count = loose_verts + loose_edges
    if count > 0:
        if is_chinese():
            return CheckResult(ERROR, t("Loose Geometry"), f"{count}个 (点:{loose_verts}, 线:{loose_edges})")
        return CheckResult(ERROR, t("Loose Geometry"), f"{count} (verts:{loose_verts}, edges:{loose_edges})")
    return CheckResult(OK, t("Loose Geometry"), "0")


def check_overlapping_faces(obj):
    """2.1.4 Overlapping faces: >=1 is error"""
    if obj.type != 'MESH' or not obj.data:
        return CheckResult(OK, t("Overlapping Faces"), t("Not a mesh object"))
    mesh = obj.data
    face_centers = {}
    overlap_count = 0
    for poly in mesh.polygons:
        center = tuple(round(c, 5) for c in poly.center)
        if center in face_centers:
            overlap_count += 1
        else:
            face_centers[center] = True
    if overlap_count > 0:
        if is_chinese():
            return CheckResult(ERROR, t("Overlapping Faces"), f"{overlap_count}个")
        return CheckResult(ERROR, t("Overlapping Faces"), f"{overlap_count}")
    return CheckResult(OK, t("Overlapping Faces"), "0")


def check_ngons(obj, threshold=4):
    """2.1.5 Ngons (>N verts): >=1 is error. N is configurable."""
    if is_chinese():
        label = f"大于{threshold}个点的面"
    else:
        label = f"Ngons (>{threshold} verts)"
    if obj.type != 'MESH' or not obj.data:
        return CheckResult(OK, label, t("Not a mesh object"))
    count = sum(1 for p in obj.data.polygons if len(p.vertices) > threshold)
    if count > 0:
        if is_chinese():
            return CheckResult(ERROR, label, f"{count}个")
        return CheckResult(ERROR, label, f"{count}")
    return CheckResult(OK, label, "0")


def check_vertex_color(obj):
    """2.1.6 Vertex color: none is OK, has is warning"""
    if obj.type != 'MESH' or not obj.data:
        return CheckResult(OK, t("Vertex Color"), t("Not a mesh object"))
    layers = obj.data.color_attributes
    if layers and len(layers) > 0:
        if is_chinese():
            return CheckResult(WARN, t("Vertex Color"), f"{len(layers)}个层")
        return CheckResult(WARN, t("Vertex Color"), f"{len(layers)} layer(s)")
    return CheckResult(OK, t("Vertex Color"), t("None"))


def check_uv_count(obj, operator='<=', value=2):
    """2.1.7 UV count: configurable comparison. Condition met = OK, not met = WARN."""
    if obj.type != 'MESH' or not obj.data:
        return CheckResult(OK, t("UV Count"), t("Not a mesh object"))
    count = len(obj.data.uv_layers)

    # Evaluate condition
    if operator == '<':
        condition_met = count < value
    elif operator == '<=':
        condition_met = count <= value
    elif operator == '==':
        condition_met = count == value
    elif operator == '>=':
        condition_met = count >= value
    elif operator == '>':
        condition_met = count > value
    else:
        condition_met = count <= value  # fallback

    if is_chinese():
        detail = f"{count}个 ({operator}{value})"
    else:
        detail = f"{count} ({operator}{value})"
    return CheckResult(OK if condition_met else WARN, t("UV Count"), detail)


def check_animation(obj):
    """2.1.8 Animation data: has animation or armature binding is error"""
    issues = []
    if obj.animation_data and obj.animation_data.action:
        issues.append(t("Has animation Action"))
    if obj.animation_data and obj.animation_data.nla_tracks and len(obj.animation_data.nla_tracks) > 0:
        issues.append(t("Has NLA tracks"))
    for mod in obj.modifiers:
        if mod.type == 'ARMATURE' and mod.object:
            if is_chinese():
                issues.append(f"绑定骨骼({mod.object.name})")
            else:
                issues.append(f"Bound to armature ({mod.object.name})")
    if issues:
        return CheckResult(ERROR, t("Animation Data"), "、".join(issues))
    return CheckResult(OK, t("Animation Data"), t("None"))


def check_non_manifold(obj):
    """2.1.9 Non-manifold geometry: edges shared by >2 faces, or coincident vertices.

    Loose geometry (isolated verts/edges) is handled separately by
    check_loose_geometry. This check targets the remaining non-manifold
    cases that break UV/import quality:
        - non-manifold edges (connected to more than 2 faces)
        - duplicated vertices at the same position (mesh must be welded)
    """
    if obj.type != 'MESH' or not obj.data:
        return CheckResult(OK, t("Non-Manifold"), t("Not a mesh object"))
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    nm_edges = sum(1 for e in bm.edges if len(e.link_faces) > 2)
    seen_pos = {}
    dup_verts = 0
    for v in bm.verts:
        key = (round(v.co.x, 4), round(v.co.y, 4), round(v.co.z, 4))
        if key in seen_pos:
            dup_verts += 1
        else:
            seen_pos[key] = True
    bm.free()
    if nm_edges > 0 or dup_verts > 0:
        if is_chinese():
            return CheckResult(ERROR, t("Non-Manifold"),
                               f"非流形边{nm_edges}条, 重合顶点{dup_verts}个 (需合并顶点)")
        return CheckResult(ERROR, t("Non-Manifold"),
                           f"{nm_edges} non-manifold edge(s), {dup_verts} duplicated vert(s) (weld required)")
    return CheckResult(OK, t("Non-Manifold"), "0")


def check_smooth_shading(obj):
    """2.7 Smooth groups: model must have smooth shading set before export.

    Blender equivalent of the M2 spec's "设置光滑组" (Mark Sharp /
    Smooth Shading). Warns when every face is flat-shaded, i.e. no
    smoothing was ever assigned.
    """
    if obj.type != 'MESH' or not obj.data:
        return CheckResult(OK, t("Smooth Shading"), t("Not a mesh object"))
    mesh = obj.data
    total = len(mesh.polygons)
    if total == 0:
        return CheckResult(OK, t("Smooth Shading"), "0")
    smooth = sum(1 for p in mesh.polygons if p.use_smooth)
    if smooth == 0:
        if is_chinese():
            return CheckResult(WARN, t("Smooth Shading"),
                               f"全部 {total} 个面均为平直着色, 未设置光滑组")
        return CheckResult(WARN, t("Smooth Shading"),
                           f"all {total} faces flat-shaded, no smooth groups set")
    return CheckResult(OK, t("Smooth Shading"), f"{smooth}/{total}")


# ============================================================
# Material checks (2.2)
# ============================================================

def check_material_count(obj):
    """2.2.1 Material count: 0 is error"""
    count = len(obj.material_slots)
    if count == 0:
        return CheckResult(ERROR, t("Material Count"), "0")
    if is_chinese():
        return CheckResult(OK, t("Material Count"), f"{count}个")
    return CheckResult(OK, t("Material Count"), f"{count}")


def _get_model_middle(model_name):
    """Extract middle part of model name: sm_XXXNN -> XXXNN (include trailing digits)

    Example: sm_com_cube01 -> com_cube01
    For old format (sm_XXX_NN), it would return XXX
    """
    if not model_name.lower().startswith('sm_'):
        return None

    # Check if name matches new format (sm_XXXNN where NN is part of the name)
    if _RE_MODEL_NAME.match(model_name):
        # New format: keep the trailing digits as part of the middle
        rest = model_name[3:]  # remove 'sm_'
        return rest

    # Old format fallback: sm_XXX_NN -> remove _NN suffix
    rest = model_name[3:]  # remove 'sm_'
    m = re.search(r'_\d{2}$', rest)
    if m:
        rest = rest[:m.start()]
    return rest


def check_unused_materials(obj):
    """2.2.3 Unused materials: material slot exists but no face uses it"""
    if obj.type != 'MESH' or not obj.data:
        return CheckResult(OK, t("Unused Materials"), t("Not a mesh object"))
    mesh = obj.data
    used_indices = set()
    for poly in mesh.polygons:
        used_indices.add(poly.material_index)
    unused = []
    for i, slot in enumerate(obj.material_slots):
        if slot.material and i not in used_indices:
            unused.append(slot.material.name)
    if unused:
        if is_chinese():
            return CheckResult(ERROR, t("Unused Materials"), f"{len(unused)}个: {', '.join(unused)}")
        return CheckResult(ERROR, t("Unused Materials"), f"{len(unused)}: {', '.join(unused)}")
    return CheckResult(OK, t("Unused Materials"), "0")


# Blend methods that always produce transparency (excludes OPAQUE and CLIP:
# CLIP/masked materials are supported by Nanite and are not treated as
# translucent for the separation check). Union of Blender 4.x and 5.x enums;
# values absent from the current Blender version simply never occur.
#
# NOTE: HASHED is intentionally NOT in this set. Blender 5.2 changed the
# default blend_method of freshly created materials from OPAQUE to HASHED,
# so a bare unconfigured material must not count as translucent. HASHED is
# treated as translucent only when the material actually configures alpha
# (static value < 1 or linked input), see _is_translucent().
_TRANSLUCENT_BLEND_METHODS = {'BLEND', 'BLEND_ALPHA', 'ADD', 'MULTIPLY', 'SUBTRACT', 'SOFTLIGHT'}


def _mat_has_alpha(mat):
    """True when the material's Principled BSDF alpha is linked or static < 1."""
    if not mat.node_tree:
        return False
    for node in mat.node_tree.nodes:
        if node.type == 'BSDF_PRINCIPLED':
            inp = node.inputs.get('Alpha')
            if inp is None:
                return False
            if inp.is_linked:
                return True
            try:
                return float(inp.default_value) < 0.999
            except (TypeError, ValueError):
                return False
    return False


def _is_translucent(mat):
    """True when a material uses transparency.

    - BLEND-family blend methods are always translucent.
    - HASHED is translucent only when alpha is actually configured (linked
      input or static value < 1); a fresh Blender 5.2 material defaults to
      HASHED with alpha 1.0 and is effectively opaque.
    - OPAQUE / CLIP (masked) are not translucent (Nanite supports masked).
    """
    if mat.blend_method in _TRANSLUCENT_BLEND_METHODS:
        return True
    if mat.blend_method == 'HASHED':
        return _mat_has_alpha(mat)
    return False


def check_transparency_separation(mesh_objs):
    """3.4 Translucent material separation (group/Actor level).

    Translucent materials (glass, translucent plastic, soap bubbles...)
    must not be merged with opaque materials on the same Actor, otherwise
    Nanite cannot be enabled. Runs once per export group.
    """
    translucent = []
    opaque = []
    for obj in mesh_objs:
        if obj.type != 'MESH' or not obj.data:
            continue
        for slot in obj.material_slots:
            mat = slot.material
            if not mat:
                continue
            if _is_translucent(mat):
                if mat.name not in translucent:
                    translucent.append(mat.name)
            elif mat.name not in opaque:
                opaque.append(mat.name)
    if translucent and opaque:
        if is_chinese():
            return CheckResult(ERROR, t("Transparency Separation"),
                               f"半透明材质 [{', '.join(translucent)}] 与不透明材质混用, 需分离为独立Actor")
        return CheckResult(ERROR, t("Transparency Separation"),
                           f"translucent [{', '.join(translucent)}] mixed with opaque materials, separate them")
    return CheckResult(OK, t("Transparency Separation"))


# ============================================================
# Collision checks (2.3)
# ============================================================

def check_collision_matching(collision_objs, mesh_objs):
    """2.3 Collision matching: UCX_ prefix must match a model name (strict).

    Strict matching rules:
        UCX_sm_com_cube01       -> matches sm_com_cube01 (or sm_com_cube01_LOD0 etc.)
        UCX_sm_com_cube01_01    -> only matches sm_com_cube01_01 (NOT sm_com_cube01)
        UCX_sm_com_cube01.001   -> matches sm_com_cube01 (Blender auto-suffix stripped)

    For LOD meshes, the _LODx suffix is stripped before comparison, so
    UCX_sm_com_cube01 matches sm_com_cube01_LOD0 (base name match).

    Args:
        collision_objs: list of collision mesh objects
        mesh_objs: list of all mesh objects (including LOD meshes)
    """
    # Build set of mesh base names (strip _LODx suffix for LOD meshes)
    mesh_base_names = set()
    for obj in mesh_objs:
        base = re.sub(r'_LOD\d+$', '', obj.name, flags=re.IGNORECASE)
        mesh_base_names.add(base.lower())

    issues = []
    for col in collision_objs:
        col_name = col.name
        if not col_name.lower().startswith('ucx_'):
            issues.append(f"'{col_name}' {t('does not start with UCX_')}")
            continue
        body = col_name[4:]  # remove 'UCX_'

        # Direct match (case-insensitive)
        if body.lower() in mesh_base_names:
            continue

        # Try removing Blender auto-suffix .XXX only (NOT _XX or _XXX)
        body_stripped = re.sub(r'\.\d{3}$', '', body)
        if body_stripped.lower() in mesh_base_names:
            continue

        issues.append(f"'{col_name}' {t('no matching model')}")

    if issues:
        return CheckResult(WARN, t("Collision Matching"), "、".join(issues))
    return CheckResult(OK, t("Collision Matching"))


# ============================================================
# LOD checks (2.4)
# ============================================================

def check_lod_matching(lod_objs, mesh_objs, independent_lod=False):
    """2.4 LOD group completeness check.

    - When independent_lod=False (LOD grouping mode, default): each _LODx mesh must belong
      to a LOD group with >= 2 members of the same base name. A single LOD
      mesh reports ERROR: "XXX 没有找到对应的LOD组".
    - When independent_lod=True (independent mode): no check (each LOD is
      exported independently, no grouping required).

    Args:
        lod_objs: list of LOD mesh objects (with _LODx suffix)
        mesh_objs: list of all mesh objects (for reference)
        independent_lod: bool, True=independent mode, False=LOD grouping mode
    """
    if independent_lod:
        # Independent mode: no LOD group check needed
        return CheckResult(OK, t("LOD Matching"), t("Independent LOD mode"))

    # Group LOD meshes by base name (case-insensitive)
    lod_groups = {}
    for lod in lod_objs:
        lod_name = lod.name
        m = re.search(r'_LOD\d+$', lod_name, re.IGNORECASE)
        if not m:
            if is_chinese():
                return CheckResult(ERROR, t("LOD Matching"), f"'{lod_name}' 不符合_LODx格式")
            return CheckResult(ERROR, t("LOD Matching"), f"'{lod_name}' {t('invalid _LODx format')}")
        base = lod_name[:m.start()].lower()
        if base not in lod_groups:
            lod_groups[base] = []
        lod_groups[base].append(lod)

    # Check each LOD group has >= 2 members
    issues = []
    for base, lods in lod_groups.items():
        if len(lods) < 2:
            for lod in lods:
                if is_chinese():
                    issues.append(f"'{lod.name}' 没有找到对应的LOD组")
                else:
                    issues.append(f"'{lod.name}' no matching LOD group")

    if issues:
        return CheckResult(ERROR, t("LOD Matching"), "、".join(issues))
    return CheckResult(OK, t("LOD Matching"))


# ============================================================
# Per-object validation
# ============================================================

def validate_object(obj, all_mesh_objs, cs):
    """Run all checks on a single mesh object.

    Args:
        obj: the mesh object to check
        all_mesh_objs: list of all mesh objects in export (for collision/LOD matching)
        cs: check settings dict

    Returns:
        list of CheckResult
    """
    results = []

    # 2.1 Mesh checks - only run enabled checks
    if cs.get('mesh_naming', True):
        results.append(check_mesh_naming(obj, cs.get('mesh_naming_regex', '')))
    if cs.get('transform_zero', True):
        results.append(check_transform_zero(obj))
    if cs.get('loose_geometry', True):
        results.append(check_loose_geometry(obj))
    if cs.get('overlapping_faces', True):
        results.append(check_overlapping_faces(obj))
    if cs.get('ngons', True):
        results.append(check_ngons(obj, cs.get('ngon_threshold', 4)))
    if cs.get('vertex_color', True):
        results.append(check_vertex_color(obj))
    if cs.get('uv_count', True):
        results.append(check_uv_count(obj, cs.get('uv_count_operator', '<='), cs.get('uv_count_value', 2)))
    if cs.get('animation', True):
        results.append(check_animation(obj))
    if cs.get('non_manifold', True):
        results.append(check_non_manifold(obj))
    if cs.get('smooth_shading', True):
        results.append(check_smooth_shading(obj))

    # 2.2 Material checks
    if cs.get('material_count', True):
        results.append(check_material_count(obj))
    if cs.get('material_naming', True):
        results.append(check_material_naming(obj))
    if cs.get('unused_materials', True):
        results.append(check_unused_materials(obj))

    return results


def validate_collision(obj, collision_objs, mesh_objs, cs):
    """Validate a collision object."""
    results = []
    if cs.get('collision_matching', True):
        result = check_collision_matching([obj], mesh_objs)
        results.append(result)
    if cs.get('transform_zero', True):
        results.append(check_transform_zero(obj))
    if cs.get('loose_geometry', True):
        results.append(check_loose_geometry(obj))
    if cs.get('ngons', True):
        results.append(check_ngons(obj, cs.get('ngon_threshold', 4)))
    return results


def validate_lod(obj, lod_objs, mesh_objs, cs, independent_lod=False):
    """Validate a LOD object.

    Note: LOD group matching (check_lod_matching) is intentionally NOT run
    here per LOD mesh — it is evaluated once at group level in
    validate_export_list(). Running it per member would duplicate the same
    error for every LOD mesh.

    In LOD grouping mode (independent_lod=False) the LOD meshes are parented
    under a group Empty during export, so their local transform offsets are
    legitimate and Transform Zeroed would report false positives. The check is
    therefore only applied when independent_lod=True (each LOD exported alone).
    """
    results = []
    if cs.get('mesh_naming', True):
        results.append(check_mesh_naming(obj, cs.get('mesh_naming_regex', '')))
    if independent_lod and cs.get('transform_zero', True):
        results.append(check_transform_zero(obj))
    if cs.get('loose_geometry', True):
        results.append(check_loose_geometry(obj))
    if cs.get('non_manifold', True):
        results.append(check_non_manifold(obj))
    if cs.get('ngons', True):
        results.append(check_ngons(obj, cs.get('ngon_threshold', 4)))
    if cs.get('smooth_shading', True):
        results.append(check_smooth_shading(obj))
    if cs.get('material_count', True):
        results.append(check_material_count(obj))
    return results


def validate_export_list(export_list, check_settings=None, independent_lod=False):
    """Validate all objects in the export list.

    Args:
        export_list: list of export dicts with 'mesh', 'collision', 'active'
        check_settings: dict of check settings (enables, thresholds)
        independent_lod: bool, True=independent mode, False=LOD grouping mode

    Returns:
        dict: {
            'groups': [
                {
                    'name': group_name,
                    'mesh_results': {obj_name: [CheckResult]},
                    'collision_results': {obj_name: [CheckResult]},
                    'lod_results': {obj_name: [CheckResult]},
                    'group_results': [CheckResult],  # collision/LOD matching at group level
                },
                ...
            ],
            'has_errors': bool,
            'has_warnings': bool,
        }
    """
    # Default check settings if none provided
    if check_settings is None:
        check_settings = {
            'mesh_naming': True, 'transform_zero': True, 'loose_geometry': True,
            'overlapping_faces': True, 'ngons': True, 'ngon_threshold': 4,
            'non_manifold': True, 'smooth_shading': True,
            'vertex_color': True, 'uv_count': True, 'uv_count_operator': '<=',
            'uv_count_value': 2, 'animation': True, 'material_count': True,
            'material_naming': True, 'unused_materials': True,
            'collision_matching': True, 'lod_matching': True,
            'transparency_separation': True,
        }

    cs = check_settings

    # Collect all mesh objects across all groups for matching checks
    all_mesh_objs = []
    for export_dict in export_list:
        all_mesh_objs.extend(export_dict.get('mesh', []))

    groups = []
    has_errors = False
    has_warnings = False

    for export_dict in export_list:
        mesh_objs = export_dict.get('mesh', [])
        collision_objs = export_dict.get('collision', [])
        active_objs = export_dict.get('active', [])

        # Determine group name
        if active_objs:
            group_name = active_objs[0].name
        elif mesh_objs:
            group_name = mesh_objs[0].name
        elif collision_objs:
            group_name = collision_objs[0].name
        else:
            continue

        group_data = {
            'name': group_name,
            'mesh_results': {},
            'collision_results': {},
            'lod_results': {},
            'group_results': [],
        }

        # Separate LOD meshes from regular meshes
        regular_meshes = []
        lod_meshes = []
        for obj in mesh_objs:
            if re.search(r'_LOD\d+$', obj.name, re.IGNORECASE):
                lod_meshes.append(obj)
            else:
                regular_meshes.append(obj)

        # 2.1 + 2.2: Check each regular mesh (skip LOD meshes here)
        for obj in regular_meshes:
            results = validate_object(obj, all_mesh_objs, cs)
            group_data['mesh_results'][obj.name] = results
            for r in results:
                if r.status == ERROR:
                    has_errors = True
                elif r.status == WARN:
                    has_warnings = True

        # 2.3: Check collision matching at group level
        if collision_objs:
            if cs.get('collision_matching', True):
                col_result = check_collision_matching(collision_objs, all_mesh_objs)
                group_data['group_results'].append(col_result)
                if col_result.status == ERROR:
                    has_errors = True
                elif col_result.status == WARN:
                    has_warnings = True

            # Individual collision checks (no mesh naming check for collision)
            for obj in collision_objs:
                results = validate_collision(obj, collision_objs, all_mesh_objs, cs)
                group_data['collision_results'][obj.name] = results
                for r in results:
                    if r.status == ERROR:
                        has_errors = True
                    elif r.status == WARN:
                        has_warnings = True

        # 2.4: Check LOD matching at group level
        if lod_meshes:
            if cs.get('lod_matching', True):
                lod_result = check_lod_matching(lod_meshes, all_mesh_objs, independent_lod=independent_lod)
                group_data['group_results'].append(lod_result)
                if lod_result.status == ERROR:
                    has_errors = True
                elif lod_result.status == WARN:
                    has_warnings = True

            # Individual LOD checks (full mesh checks + LOD matching)
            for obj in lod_meshes:
                results = validate_lod(obj, lod_meshes, all_mesh_objs, cs, independent_lod=independent_lod)
                group_data['lod_results'][obj.name] = results
                for r in results:
                    if r.status == ERROR:
                        has_errors = True
                    elif r.status == WARN:
                        has_warnings = True

        # 3.4: Translucent material separation at group level (regular + LOD meshes)
        group_meshes = regular_meshes + lod_meshes
        if group_meshes and cs.get('transparency_separation', True):
            trans_result = check_transparency_separation(group_meshes)
            group_data['group_results'].append(trans_result)
            if trans_result.status == ERROR:
                has_errors = True
            elif trans_result.status == WARN:
                has_warnings = True

        groups.append(group_data)

    return {
        'groups': groups,
        'has_errors': has_errors,
        'has_warnings': has_warnings,
    }
