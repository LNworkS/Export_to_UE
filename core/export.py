import bpy
import os
import json
import math
import mathutils

from .coordinate import apply_transform_to_ue, sanitize_vector
from .texture_export import get_ue_parent_material


def _get_base_name(obj_name):
    """Get base name for grouping and matching.

    For collision objects (UCX_ prefix):
    - Strip UCX_ prefix
    - Strip Blender's auto-suffix .XXX (e.g., .001, .002)
    - Do NOT strip _XX or _XXX (these are part of the model name being matched,
      per strict matching requirement)

    For mesh objects:
    - Strip _LODx suffix (case-insensitive)

    Examples:
        sm_com_cube01 -> sm_com_cube01
        sm_com_cube01_LOD0 -> sm_com_cube01
        sm_com_cube01_LOD1 -> sm_com_cube01
        UCX_sm_com_cube01 -> sm_com_cube01
        UCX_sm_com_cube01_01 -> sm_com_cube01_01  (kept! strict matching)
        UCX_sm_com_cube01.001 -> sm_com_cube01  (Blender auto-suffix stripped)
    """
    import re
    name = obj_name.lower()
    is_collision = name.startswith('ucx_')
    if is_collision:
        name = name[4:]
        # Only strip Blender's auto-generated .XXX suffix (not _XX or _XXX)
        name = re.sub(r'\.\d{3}$', '', name)
    else:
        # Strip LOD suffix for mesh objects
        name = re.sub(r'_lod\d+$', '', name)
    return name


def _is_lod_mesh(obj):
    """Check if obj name has _LODx suffix (case-insensitive)."""
    import re
    return bool(re.search(r'_lod\d+$', obj.name.lower()))


def _strip_lod_suffix(name):
    """Strip _LODx suffix from name (case-insensitive)."""
    import re
    return re.sub(r'_lod\d+$', '', name, flags=re.IGNORECASE)


def classify_objects(selected_only, include_lod):
    """Classify selected objects into export groups.

    Grouping logic:
    - include_lod=True (LOD grouping mode):
      * Meshes WITHOUT _LODx suffix: each becomes its own independent group.
      * Meshes WITH _LODx suffix: grouped by base name (e.g., sm_com_cube01_LOD0
        and sm_com_cube01_LOD1 form one LOD group).
      * Single-LOD groups (only 1 _LODx mesh) are flagged for error reporting.
    - include_lod=False (independent mode):
      * Every mesh becomes its own group, no LOD grouping.

    Collision matching (strict):
      UCX_sm_com_cube01 matches sm_com_cube01 (or LOD group base sm_com_cube01).
      UCX_sm_com_cube01_01 only matches sm_com_cube01_01 (NOT sm_com_cube01).
      UCX_sm_com_cube01.001 matches sm_com_cube01 (Blender auto-suffix stripped).

    Args:
        selected_only: bool - Export only selected objects
        include_lod: bool - True=LOD grouping mode, False=independent mode

    Returns:
        tuple: (success: bool, message: str, export_list: list)
    """
    if not selected_only:
        bpy.ops.object.select_all(action='SELECT')

    selected_objects = bpy.context.selected_objects

    if not selected_objects:
        return (False, "No objects selected for export.", None)

    # Phase 1: Separate objects by type
    meshes = []
    collisions = []
    empties = []

    for obj in selected_objects:
        if obj.type == 'MESH':
            if len(obj.name) >= 3 and obj.name[0:3].lower() == 'ucx':
                collisions.append(obj)
            else:
                meshes.append(obj)
        elif obj.type == 'EMPTY':
            empties.append(obj)

    # Phase 2: Create export groups for meshes
    export_list = []

    if include_lod:
        # LOD grouping mode: separate LOD meshes from regular meshes
        lod_meshes = [m for m in meshes if _is_lod_mesh(m)]
        regular_meshes = [m for m in meshes if not _is_lod_mesh(m)]

        # Regular meshes (no _LODx suffix): each is its own independent group
        for mesh in regular_meshes:
            export_list.append({
                'mesh': [mesh],
                'active': [mesh],
                'collision': [],
                '_is_lod_group': False,
            })

        # LOD meshes: group by base name
        lod_groups = {}
        for mesh in lod_meshes:
            base = _get_base_name(mesh.name)
            if base not in lod_groups:
                lod_groups[base] = []
            lod_groups[base].append(mesh)

        for base, group_meshes in lod_groups.items():
            # Sort by name to ensure consistent LOD ordering (LOD0, LOD1, ...)
            group_meshes.sort(key=lambda m: m.name.lower())
            export_list.append({
                'mesh': group_meshes,
                'active': [group_meshes[0]],  # temporary; will be replaced by empty
                'collision': [],
                '_is_lod_group': True,
                '_lod_base_name': base,
            })
    else:
        # Independent mode: every mesh is its own group
        for mesh in meshes:
            export_list.append({
                'mesh': [mesh],
                'active': [mesh],
                'collision': [],
                '_is_lod_group': False,
            })

    # Phase 3: Match collision objects to mesh groups (strict matching)
    for col_obj in collisions:
        col_base = _get_base_name(col_obj.name)

        matched = False
        for export_dict in export_list:
            if not export_dict.get('mesh'):
                continue
            mesh_base = _get_base_name(export_dict['mesh'][0].name)
            if col_base == mesh_base:
                export_dict['collision'].append(col_obj)
                matched = True
                break

        if not matched:
            # Orphan collision - create its own group
            export_list.append({
                'mesh': [],
                'active': [],
                'collision': [col_obj],
                '_is_lod_group': False,
            })

    # Phase 4: Handle empty objects (match by name to LOD group base)
    for empty_obj in empties:
        matched = False
        for export_dict in export_list:
            if export_dict.get('_is_lod_group') and export_dict.get('mesh'):
                mesh_base = _get_base_name(export_dict['mesh'][0].name)
                if empty_obj.name.lower() == mesh_base:
                    # User-provided empty for LOD group - use as active
                    export_dict['active'] = [empty_obj]
                    export_dict['_user_empty'] = True
                    matched = True
                    break
            elif export_dict.get('mesh'):
                mesh_base = _get_base_name(export_dict['mesh'][0].name)
                if empty_obj.name.lower() == mesh_base:
                    if not export_dict.get('active'):
                        export_dict['active'] = [empty_obj]
                    matched = True
                    break

        if not matched:
            # Standalone empty - create its own group
            export_list.append({
                'mesh': [],
                'active': [empty_obj],
                'collision': [],
                '_is_lod_group': False,
            })

    # Phase 5: Ensure each group has an active object
    for export_dict in export_list:
        if not export_dict.get('active'):
            if len(export_dict.get('mesh', [])) == 1:
                export_dict['active'] = [export_dict['mesh'][0]]
            elif export_dict.get('_is_lod_group'):
                # LOD group without empty - will be created in setup_lod_groups()
                # Keep temporary active as mesh[0] for now
                if export_dict.get('mesh'):
                    export_dict['active'] = [export_dict['mesh'][0]]
            elif export_dict.get('collision'):
                export_dict['active'] = [export_dict['collision'][0]]

    return (True, f"Classified {len(export_list)} export groups.", export_list)


def separate_collision(export_list):
    """Separate collision objects into individual pieces before export.

    For each collision object:
    1. Save original name and reference
    2. Separate by loose parts
    3. Rename each piece to UCX_<base>_<NNN>
    4. Track which pieces belong to which original for correct merging

    Args:
        export_list: List of export dicts

    Returns:
        list: Modified export_list with separated collision meshes.
              Piece mapping saved in export_dict['_collision_pieces_map'].
              Original names saved in export_dict['_collision_original_names'].
    """
    for export_dict in export_list:
        collision_objs = export_dict.get('collision', [])
        if not collision_objs:
            continue

        # Save original names for restoration during merge
        original_names = [obj.name for obj in collision_objs]
        export_dict['_collision_original_names'] = original_names

        # Determine base name for renaming (use _get_base_name for LOD/UCX stripping)
        active_objs = export_dict.get('active', [])
        if active_objs:
            base_name = _get_base_name(active_objs[0].name)
        elif collision_objs:
            base_name = _get_base_name(collision_objs[0].name)
        else:
            base_name = 'collision'

        # Track pieces per original collision object
        pieces_map = {}
        new_collision_list = []
        global_idx = 0

        for obj in collision_objs:
            bpy.ops.object.select_all(action='DESELECT')
            obj.select_set(True)
            bpy.context.view_layer.objects.active = obj

            if obj.type == 'MESH' and len(obj.data.polygons) > 0:
                bpy.ops.object.mode_set(mode='EDIT')
                bpy.ops.mesh.separate(type='LOOSE')
                bpy.ops.object.mode_set(mode='OBJECT')

                separated = [o for o in bpy.context.selected_objects if o.type == 'MESH']
            else:
                separated = [obj]

            # Store piece mapping: original_name -> [pieces]
            pieces_map[obj.name] = separated

            # Rename pieces with global index
            for piece in separated:
                global_idx += 1
                piece.name = f"UCX_{base_name}_{global_idx:03d}"

            new_collision_list.extend(separated)
            bpy.ops.object.select_all(action='DESELECT')

        export_dict['_collision_pieces_map'] = pieces_map
        export_dict['collision'] = new_collision_list
        bpy.ops.object.select_all(action='DESELECT')

    return export_list


def merge_collision(export_list):
    """Merge separated collision objects back into single objects after export.

    For each original collision object, merges its pieces back into one object
    and restores the original name. Preserves independent collision structure.

    Args:
        export_list: List of export dicts with '_collision_original_names'
                     and '_collision_pieces_map'

    Returns:
        list: Modified export_list with merged collision meshes.
    """
    for export_dict in export_list:
        original_names = export_dict.get('_collision_original_names', [])
        pieces_map = export_dict.get('_collision_pieces_map', {})
        if not original_names or not pieces_map:
            continue

        merged_collision = []

        for orig_name in original_names:
            pieces = pieces_map.get(orig_name, [])
            mesh_pieces = [p for p in pieces if p.type == 'MESH']

            if len(mesh_pieces) == 0:
                continue
            elif len(mesh_pieces) == 1:
                mesh_pieces[0].name = orig_name
                merged_collision.append(mesh_pieces[0])
            else:
                bpy.ops.object.select_all(action='DESELECT')
                for p in mesh_pieces:
                    p.select_set(True)
                bpy.context.view_layer.objects.active = mesh_pieces[0]
                bpy.ops.object.join()
                merged = bpy.context.active_object
                merged.name = orig_name
                merged_collision.append(merged)

        export_dict['collision'] = merged_collision
        export_dict.pop('_collision_original_names', None)
        export_dict.pop('_collision_pieces_map', None)
        bpy.ops.object.select_all(action='DESELECT')

    return export_list


def setup_lod_groups(export_list):
    """Create Empty parents for LOD groups and set parent relationships.

    For each LOD group (export_dict with '_is_lod_group'=True):
    1. Skip if user already provided an empty (_user_empty flag)
    2. Create an Empty named after the base name (e.g., sm_com_cube01)
    3. Set custom property fbx_type = "LodGroup" (String type)
    4. Parent all LOD meshes and collisions to the Empty
    5. Preserve world transforms using matrix_parent_inverse
    6. Save original parent and matrix_world for restoration in cleanup

    Args:
        export_list: list of export dicts

    Returns:
        list: Modified export_list with LOD empties created.
    """
    for export_dict in export_list:
        if not export_dict.get('_is_lod_group'):
            continue

        # Skip if user already provided an empty
        if export_dict.get('_user_empty'):
            # Still need to parent meshes to the user-provided empty
            empty_obj = export_dict['active'][0]
            _parent_to_empty(export_dict, empty_obj)
            continue

        mesh_objects = export_dict.get('mesh', [])
        if not mesh_objects:
            continue

        # Determine base name for empty
        base_name = _get_base_name(mesh_objects[0].name)

        # Create Empty
        bpy.ops.object.select_all(action='DESELECT')
        bpy.ops.object.empty_add(type='PLAIN_AXES', location=(0, 0, 0))
        empty_obj = bpy.context.object
        empty_obj.name = base_name

        # Set custom property fbx_type = LodGroup (String type)
        empty_obj['fbx_type'] = 'LodGroup'

        # Replace active with empty
        export_dict['active'] = [empty_obj]
        export_dict['_lod_empty'] = empty_obj

        # Parent meshes and collisions to empty
        _parent_to_empty(export_dict, empty_obj)

    return export_list


def _parent_to_empty(export_dict, empty_obj):
    """Parent all meshes and collisions in a group to the empty.

    Saves original parent and matrix_world for restoration.
    Preserves world transform via matrix_parent_inverse.

    Args:
        export_dict: dict with 'mesh' and 'collision' lists
        empty_obj: the empty to parent to
    """
    mesh_objects = export_dict.get('mesh', [])
    collision_objects = export_dict.get('collision', [])
    all_children = mesh_objects + collision_objects

    original_states = []
    for obj in all_children:
        original_states.append({
            'obj': obj,
            'parent': obj.parent,
            'matrix_world': obj.matrix_world.copy(),
        })

    # Parent objects to empty (preserving world transform)
    for obj in all_children:
        obj.parent = empty_obj
        # matrix_parent_inverse compensates for parent's transform
        # so that world transform is preserved
        obj.matrix_parent_inverse = empty_obj.matrix_world.inverted()

    export_dict['_lod_original_states'] = original_states


def cleanup_lod_groups(export_list):
    """Remove LOD group empties and restore original parent relationships.

    For each LOD group with a created empty:
    1. Restore original parent and matrix_world for all child objects
    2. Delete the created empty (not user-provided empties)

    Args:
        export_list: list of export dicts
    """
    for export_dict in export_list:
        if not export_dict.get('_is_lod_group'):
            continue

        original_states = export_dict.get('_lod_original_states', [])
        empty_obj = export_dict.get('_lod_empty')

        # Restore original parent and world matrix
        for state in original_states:
            obj = state['obj']
            if obj is None:
                continue
            # Restore parent first, then world transform
            obj.parent = state['parent']
            obj.matrix_world = state['matrix_world']

        # Delete the created empty (not user-provided empties)
        if empty_obj is not None:
            try:
                bpy.ops.object.select_all(action='DESELECT')
                empty_obj.select_set(True)
                bpy.context.view_layer.objects.active = empty_obj
                bpy.ops.object.delete()
            except Exception as e:
                print(f"  Warning: could not delete LOD empty: {e}")

        # Clean up export_dict
        export_dict.pop('_lod_empty', None)
        export_dict.pop('_lod_original_states', None)

    bpy.ops.object.select_all(action='DESELECT')
    return export_list


def export_fbx(export_dict, export_path, settings):
    """Export a single FBX file for one export group.

    LOD group export (Plan A):
    - Include Empty (with fbx_type=LodGroup) + all LOD meshes + collisions
    - object_types={'EMPTY', 'MESH'}, use_custom_props=True
    - Rotation: only rotate the Empty (parent), children inherit via hierarchy

    Regular export:
    - Include meshes + collisions (+ optional empty)
    - Rotation: rotate all objects individually

    When adapt_ue_rotation is enabled:
    - Before export: rotate +90° around Z axis
    - After export: restore original transforms

    Args:
        export_dict: dict with 'mesh', 'active', 'collision' lists
        export_path: str - output directory
        settings: ExportToUEPropertyGroup - export settings

    Returns:
        tuple: (success, filepath)
    """
    os.makedirs(export_path, exist_ok=True)

    mesh_objects = export_dict.get('mesh', [])
    collision_objects = export_dict.get('collision', [])
    active_objects = export_dict.get('active', [])

    filepath = os.path.join(export_path, f"{active_objects[0].name if active_objects else 'export'}.fbx")

    is_lod_group = export_dict.get('_is_lod_group', False)

    # ---- Select objects for export ----
    bpy.ops.object.select_all(action='DESELECT')

    if is_lod_group:
        # LOD group export (Plan A): include empty + meshes + collisions
        # Empty has fbx_type=LodGroup custom property for UE LOD group import
        for obj in active_objects:  # The empty (or user-provided empty)
            obj.select_set(True)
        for obj in mesh_objects:
            obj.select_set(True)
        for obj in collision_objects:
            obj.select_set(True)
        object_types = {'EMPTY', 'MESH'}
        use_custom_props = True  # Required for fbx_type custom property
    else:
        # Regular export: include empties (parents) + meshes + collision
        for obj in collision_objects:
            obj.select_set(True)
        for obj in active_objects:
            obj.select_set(True)
        for obj in mesh_objects:
            obj.select_set(True)
        object_types = {'EMPTY', 'MESH'}
        use_custom_props = settings.import_materials

    # Set active object
    active_target = (active_objects + mesh_objects)[0] if (active_objects or mesh_objects) else None
    if active_target:
        bpy.context.view_layer.objects.active = active_target

    # ---- Determine which objects need rotation ----
    # For LOD groups: only rotate the Empty (parent). Children inherit rotation
    # via parent hierarchy, avoiding double rotation.
    # For regular groups: rotate all objects individually (no parent hierarchy).
    all_export_objects = list(set(mesh_objects + collision_objects + active_objects))

    if is_lod_group and active_objects:
        # LOD group: only rotate the empty (parent), children follow via hierarchy
        rotation_objects = active_objects
    else:
        # Regular: rotate all objects
        rotation_objects = all_export_objects

    # ---- Apply +90° Z rotation if adapt_ue_rotation is enabled ----
    original_matrices = {}
    if settings.adapt_ue_rotation:
        # Save original world matrices (most reliable for restoration)
        for obj in all_export_objects:
            original_matrices[obj.name] = obj.matrix_world.copy()

        # Apply +90° Z rotation only to rotation_objects
        for obj in rotation_objects:
            obj.rotation_euler.z += math.radians(90)

        # Force view layer update to apply transformations
        bpy.context.view_layer.update()
        print("  Applied +90° Z rotation for UE adaptation")

    # ---- Export FBX ----
    bpy.ops.export_scene.fbx(
        filepath=filepath,
        use_selection=True,
        object_types=object_types,
        use_custom_props=use_custom_props,
        mesh_smooth_type='FACE' if settings.smooth_meshes else 'OFF',
        use_mesh_modifiers=True,
        add_leaf_bones=False,
        bake_anim=False,
        axis_forward='Y',
        axis_up='Z',
        use_space_transform=True,
        global_scale=1.0,
        apply_scale_options='FBX_SCALE_ALL',
    )

    # ---- Restore original transforms after export ----
    if settings.adapt_ue_rotation and original_matrices:
        for obj in all_export_objects:
            if obj.name in original_matrices:
                obj.matrix_world = original_matrices[obj.name]
        bpy.context.view_layer.update()
        print("  Restored original transforms")

    bpy.ops.object.select_all(action='DESELECT')
    print(f"  Exported: {filepath}")
    return (True, filepath)


def build_bridge_payload(export_dict, export_name, settings):
    """Build a payload for UE bridge connection.

    Args:
        export_dict: dict with object lists
        export_name: str - name of the export group
        settings: ExportToUEPropertyGroup

    Returns:
        dict - JSON-serializable payload
    """
    mesh_objects = export_dict.get('mesh', [])
    collision_objects = export_dict.get('collision', [])

    payload = {
        "type": "blender_export",
        "version": "1.0",
        "export_name": export_name,
        "timestamp": bpy.app.frame,
        "meshes": [],
        "collisions": [],
        "materials": {},
        "settings": {
            "combine_meshes": settings.combine_meshes,
            "smooth_shading": settings.smooth_meshes,
            "import_materials": settings.import_materials,
            "import_textures": settings.import_textures,
        }
    }

    # Add mesh data
    for obj in mesh_objects:
        if obj.type == 'MESH' and obj.data:
            loc, rot, scale = apply_transform_to_ue(obj)
            payload["meshes"].append({
                "name": obj.name,
                "location": [loc.x, loc.y, loc.z],
                "rotation": [rot.x, rot.y, rot.z],
                "scale": [scale.x, scale.y, scale.z],
                "vertex_count": len(obj.data.vertices),
                "material_slots": [ms.material.name if ms.material else "None"
                                    for ms in obj.material_slots],
            })

    # Add collision data
    for obj in collision_objects:
        if obj.type == 'MESH' and obj.data:
            loc, rot, scale = apply_transform_to_ue(obj)
            payload["collisions"].append({
                "name": obj.name,
                "location": [loc.x, loc.y, loc.z],
                "rotation": [rot.x, rot.y, rot.z],
                "scale": [scale.x, scale.y, scale.z],
                "vertex_count": len(obj.data.vertices),
            })

    # Add material mapping
    for obj in mesh_objects:
        if obj.type == 'MESH':
            for ms in obj.material_slots:
                mat = ms.material
                if mat and mat.name not in payload["materials"]:
                    ue_parent = get_ue_parent_material(mat)
                    payload["materials"][mat.name] = {
                        "ue_parent": ue_parent,
                        "textures": [],
                    }

    return payload


def do_export(settings, context):
    """Main export function.

    Args:
        settings: ExportToUEPropertyGroup
        context: bpy context

    Returns:
        tuple: (success: bool, message: str)
    """
    scene = context.scene

    # ---- Determine export path ----
    # Lazy import to avoid circular dependency at module load time
    from ..property_group import get_default_export_path

    if settings.use_fixed_path:
        export_path = get_default_export_path()
    else:
        export_path = settings.export_path
        if not export_path:
            return (False, "Please select an export path first (uncheck Fixed Path and browse).")

    # ---- Classify objects ----
    success, msg, export_list = classify_objects(
        settings.selected_only, settings.include_lod
    )
    if not success:
        return (False, msg)

    if not export_list:
        return (False, "No objects to export.")

    # ---- LOD group completeness check (only in LOD grouping mode) ----
    # When include_lod=True (LOD grouping mode), each LOD group must have >= 2
    # LOD meshes. A single _LODx mesh without a matching partner is an error.
    if settings.include_lod:
        for export_dict in export_list:
            if export_dict.get('_is_lod_group'):
                mesh_list = export_dict.get('mesh', [])
                if len(mesh_list) < 2:
                    mesh_name = mesh_list[0].name if mesh_list else "Unknown"
                    return (False, f"{mesh_name} 没有找到对应的LOD组")

    # ---- Setup LOD groups (create empties, set parent relationships) ----
    setup_lod_groups(export_list)

    # ---- Separate collision objects before export ----
    separate_collision(export_list)

    # ---- Process each export group ----
    exported_files = []
    export_failed = False

    for export_dict in export_list:
        if not export_dict.get('mesh') and not export_dict.get('collision'):
            continue

        # Export as FBX file
        success, filepath = export_fbx(export_dict, export_path, settings)
        if success:
            exported_files.append(filepath)
        else:
            export_failed = True

    # ---- Merge collision objects back after export ----
    merge_collision(export_list)

    # ---- Cleanup LOD groups (delete empties, restore parents) ----
    cleanup_lod_groups(export_list)

    if export_failed:
        return (False, f"Export completed with errors. {len(exported_files)} file(s) exported to: {export_path}")

    # ---- Report ----
    summary = f"Exported {len(exported_files)} FBX file(s) to: {export_path}"

    return (True, summary)
