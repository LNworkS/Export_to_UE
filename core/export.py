import bpy
import os
import json
import math
import mathutils

from .coordinate import apply_transform_to_ue, sanitize_vector
from .texture_export import get_ue_parent_material


def _get_base_name(obj_name):
    """Get base name without LOD suffix.
    
    Examples:
        sm_com_cube01 -> sm_com_cube01
        sm_com_cube01_lod0 -> sm_com_cube01
        sm_com_cube01_LOD1 -> sm_com_cube01
    """
    name = obj_name.lower()
    # Remove _lodN or _LODN suffix
    while '_lod' in name:
        idx = name.find('_lod')
        # Check if followed by a digit
        after = name[idx + 4:]
        if after and after[0].isdigit():
            name = name[:idx]
        else:
            break
    return name


def classify_objects(selected_only, include_lod):
    """Classify selected objects into export groups.

    Groups objects by LOD hierarchy (mesh + collision) for FBX export.
    Each independent mesh gets its own export group. LOD variants and
    collision objects are matched by base name.

    Args:
        selected_only: bool - Export only selected objects
        include_lod: bool - Handle LOD groups (combine LOD variants)

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

    # Phase 2: Create export groups for each mesh
    export_list = []
    
    if include_lod:
        # Group meshes by base name (LOD variants)
        mesh_groups = {}
        for mesh in meshes:
            base = _get_base_name(mesh.name)
            if base not in mesh_groups:
                mesh_groups[base] = []
            mesh_groups[base].append(mesh)

        for base, group_meshes in mesh_groups.items():
            # Sort by name to ensure consistent LOD ordering
            group_meshes.sort(key=lambda m: m.name.lower())
            export_list.append({
                'mesh': group_meshes,
                'active': [group_meshes[0]],
                'collision': [],
            })
    else:
        # Each mesh gets its own group (independent export)
        for mesh in meshes:
            export_list.append({
                'mesh': [mesh],
                'active': [mesh],
                'collision': [],
            })

    # Phase 3: Match collision objects to mesh groups
    for col_obj in collisions:
        col_base = _get_base_name(col_obj.name)
        
        # Try to find matching mesh group
        matched = False
        for export_dict in export_list:
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
            })

    # Phase 4: Handle empty objects
    for empty_obj in empties:
        # Try to match to existing group by name prefix
        matched = False
        for export_dict in export_list:
            if export_dict.get('mesh'):
                mesh_base = _get_base_name(export_dict['mesh'][0].name)
                if empty_obj.name.lower() == mesh_base:
                    export_dict['active'] = [empty_obj]
                    matched = True
                    break
        
        if not matched:
            # Standalone empty - create its own group
            export_list.append({
                'mesh': [],
                'active': [empty_obj],
                'collision': [],
            })

    # Phase 5: Ensure each group has an active (parent)
    for export_dict in export_list:
        if not export_dict.get('active'):
            if len(export_dict.get('mesh', [])) == 1:
                export_dict['active'] = [export_dict['mesh'][0]]
            elif len(export_dict.get('mesh', [])) > 1:
                # Create an empty as LOD group parent
                bpy.ops.object.empty_add(type='PLAIN_AXES', location=(0, 0, 0))
                empty_obj = bpy.context.object
                base_name = _get_base_name(export_dict['mesh'][0].name)
                empty_obj.name = base_name
                empty_obj['fbx_type'] = 'LodGroup'
                export_dict['active'] = [empty_obj]
            elif export_dict.get('collision'):
                export_dict['active'] = [export_dict['collision'][0]]

    # Phase 6: Set LOD hierarchy (parent LOD variants to active)
    for export_dict in export_list:
        mesh_objects = export_dict.get('mesh', [])
        is_lod = len(mesh_objects) > 1 or any('_lod' in m.name.lower() for m in mesh_objects)
        if is_lod and export_dict.get('active'):
            active_obj = export_dict['active'][0]
            for mesh_obj in mesh_objects:
                if mesh_obj != active_obj:
                    mesh_obj.parent = active_obj

    return (True, f"Classified {len(export_list)} export groups.", export_list)


def separate_collision(export_list):
    """Separate collision objects into individual pieces before export.

    For each collision object:
    1. Save original name
    2. Separate by loose parts
    3. Rename each piece to UCX_<base>_<NNN>

    Args:
        export_list: List of export dicts

    Returns:
        list: Modified export_list with separated collision meshes.
              Original names saved in export_dict['_collision_original_names'].
    """
    for export_dict in export_list:
        collision_objs = export_dict.get('collision', [])
        if not collision_objs:
            continue

        # Save original names for restoration during merge
        original_names = {obj.name: obj for obj in collision_objs}
        export_dict['_collision_original_names'] = list(original_names.keys())

        # Determine base name for renaming
        active_objs = export_dict.get('active', [])
        if active_objs:
            base_name = active_objs[0].name
            # Strip UCX_ prefix if present
            if base_name.lower().startswith('ucx_'):
                base_name = base_name[4:]
        elif collision_objs:
            base_name = collision_objs[0].name
            if base_name.lower().startswith('ucx_'):
                base_name = base_name[4:]
        else:
            base_name = 'collision'

        new_collision_list = []
        for obj in collision_objs:
            bpy.ops.object.select_all(action='DESELECT')
            obj.select_set(True)
            bpy.context.view_layer.objects.active = obj

            if obj.type == 'MESH' and len(obj.data.polygons) > 0:
                bpy.ops.object.mode_set(mode='EDIT')
                bpy.ops.mesh.separate(type='LOOSE')
                bpy.ops.object.mode_set(mode='OBJECT')

                # Collect all separated objects (original + new)
                separated = [o for o in bpy.context.selected_objects if o.type == 'MESH']
            else:
                separated = [obj]

            new_collision_list.extend(separated)
            bpy.ops.object.select_all(action='DESELECT')

        # Rename collision pieces sequentially
        for idx, obj in enumerate(new_collision_list, start=1):
            obj.name = f"UCX_{base_name}_{idx:03d}"

        export_dict['collision'] = new_collision_list
        bpy.ops.object.select_all(action='DESELECT')

    return export_list


def merge_collision(export_list):
    """Merge separated collision objects back into single objects after export.

    Restores original collision object names.

    Args:
        export_list: List of export dicts with '_collision_original_names'

    Returns:
        list: Modified export_list with merged collision meshes.
    """
    for export_dict in export_list:
        collision_objs = export_dict.get('collision', [])
        original_names = export_dict.get('_collision_original_names', [])
        if not collision_objs or not original_names:
            continue

        # If only one collision piece, just restore the name (no join needed)
        mesh_collision = [obj for obj in collision_objs if obj.type == 'MESH']
        if len(mesh_collision) <= 1:
            if mesh_collision:
                mesh_collision[0].name = original_names[0]
                export_dict['collision'] = [mesh_collision[0]]
            export_dict.pop('_collision_original_names', None)
            continue

        # Select all collision pieces and join
        bpy.ops.object.select_all(action='DESELECT')
        for obj in mesh_collision:
            obj.select_set(True)

        if not bpy.context.selected_objects:
            continue

        bpy.context.view_layer.objects.active = bpy.context.selected_objects[0]
        bpy.ops.object.join()

        merged = bpy.context.active_object
        # Restore original name
        merged.name = original_names[0]

        export_dict['collision'] = [merged]
        export_dict.pop('_collision_original_names', None)
        bpy.ops.object.select_all(action='DESELECT')

    return export_list


def export_fbx(export_dict, export_path, settings):
    """Export a single FBX file for one export group.

    When adapt_ue_rotation is enabled:
    - Before export: rotate all export objects +90° around Z axis
    - After export: restore original transforms
    - Uses axis_forward='Y' (Blender native axes)

    When disabled:
    - No rotation applied
    - Uses axis_forward='Y' (Blender native axes)

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

    is_lod = any('_lod' in obj.name.lower() for obj in mesh_objects)

    # ---- Select objects for export ----
    bpy.ops.object.select_all(action='DESELECT')

    if is_lod:
        # LOD export: only meshes, no empties
        for obj in mesh_objects:
            obj.select_set(True)
        object_types = {'MESH'}
        use_custom_props = False
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
    active_target = (mesh_objects + active_objects)[0] if (mesh_objects or active_objects) else None
    if active_target:
        bpy.context.view_layer.objects.active = active_target

    # ---- Collect all objects that need rotation (deduplicated) ----
    all_export_objects = list(set(mesh_objects + collision_objects + active_objects))

    # ---- Apply +90° Z rotation if adapt_ue_rotation is enabled ----
    original_matrices = {}
    if settings.adapt_ue_rotation:
        # Save original world matrices (most reliable for restoration)
        for obj in all_export_objects:
            original_matrices[obj.name] = obj.matrix_world.copy()
        
        # Apply +90° Z rotation to each object
        for obj in all_export_objects:
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

    if export_failed:
        return (False, f"Export completed with errors. {len(exported_files)} file(s) exported to: {export_path}")

    # ---- Report ----
    summary = f"Exported {len(exported_files)} FBX file(s) to: {export_path}"

    return (True, summary)
