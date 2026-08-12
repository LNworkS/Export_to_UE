import bpy
import os

from .i18n import t
from .core.config import save_export_path, get_saved_export_path, load_config, save_config


def get_default_export_path():
    """Get the default export path based on current blend file location."""
    if bpy.data.filepath:
        return os.path.join(os.path.dirname(bpy.data.filepath), "BlenderExport")
    return os.path.join(os.path.expanduser("~"), "BlenderExport")


def update_use_fixed_path(self, context):
    """Callback when use_fixed_path toggles off - fill with saved config path."""
    if not self.use_fixed_path and not self.export_path:
        saved_path = get_saved_export_path()
        if saved_path:
            self.export_path = saved_path


def update_export_path(self, context):
    """Callback when export_path changes - saves to config file if not empty."""
    if self.export_path:
        save_export_path(self.export_path)


def _save_check_settings(self, context):
    """Callback to persist check settings to config file."""
    config = load_config()
    config['check_settings'] = {
        'mesh_naming': self.chk_mesh_naming,
        'mesh_naming_regex': self.mesh_naming_regex,
        'transform_zero': self.chk_transform_zero,
        'loose_geometry': self.chk_loose_geometry,
        'overlapping_faces': self.chk_overlapping_faces,
        'ngons': self.chk_ngons,
        'ngon_threshold': self.ngon_threshold,
        'vertex_color': self.chk_vertex_color,
        'uv_count': self.chk_uv_count,
        'uv_count_operator': self.uv_count_operator,
        'uv_count_value': self.uv_count_value,
        'animation': self.chk_animation,
        'material_count': self.chk_material_count,
        'material_naming': self.chk_material_naming,
        'unused_materials': self.chk_unused_materials,
        'collision_matching': self.chk_collision_matching,
        'lod_matching': self.chk_lod_matching,
    }
    save_config(config)


# UV count operator enum items
_UV_OPERATOR_ITEMS = [
    ('<', '<', ''),
    ('<=', '<=', ''),
    ('==', '==', ''),
    ('>=', '>=', ''),
    ('>', '>', ''),
]


class ExportToUEPropertyGroup(bpy.types.PropertyGroup):
    """Property group for Export to UE settings.

    export_path is persisted in plugin config file (not .blend file)
    so it can be shared across multiple .blend files.
    """

    # ---- Object Selection ----
    selected_only: bpy.props.BoolProperty(
        name="Selected Objects",
        description=t("Export only selected objects"),
        default=True,
    )
    include_lod: bpy.props.BoolProperty(
        name="Independent LOD",
        description=t("Handle LOD groups separately"),
        default=False,
    )

    # ---- Export Path (persisted in plugin config file, not .blend) ----
    use_fixed_path: bpy.props.BoolProperty(
        name="Fixed Path",
        description=t("Use default path (filepath\\BlenderExport). When disabled, path is saved in plugin config."),
        default=True,
        update=update_use_fixed_path,
    )
    export_path: bpy.props.StringProperty(
        name="Export Path",
        description=t("Directory to export FBX files. Saved in plugin config for reuse across .blend files."),
        subtype="DIR_PATH",
        default="",
        update=update_export_path,
    )

    # ---- +90° on Z ----
    adapt_ue_rotation: bpy.props.BoolProperty(
        name="+90° on Z",
        description=t("Apply +90° Z rotation before export, then restore. Matches Unreal Engine coordinate system."),
        default=True,
    )

    # ---- Check before export ----
    check_before_export: bpy.props.BoolProperty(
        name="Check",
        description=t("Run validation checks before export. Show results in a dialog."),
        default=True,
    )

    # ---- Check Settings (persisted in config file) ----
    # Mesh checks
    chk_mesh_naming: bpy.props.BoolProperty(name="Model Naming", default=True, update=_save_check_settings)
    mesh_naming_regex: bpy.props.StringProperty(
        name="Model Naming Regex",
        description=t("Regular expression for model naming validation"),
        default=r"^sm_[a-zA-Z0-9_]*[a-zA-Z0-9]\d{2}$",
        update=_save_check_settings,
    )
    chk_transform_zero: bpy.props.BoolProperty(name="Transform Zeroed", default=True, update=_save_check_settings)
    chk_loose_geometry: bpy.props.BoolProperty(name="Loose Geometry", default=True, update=_save_check_settings)
    chk_overlapping_faces: bpy.props.BoolProperty(name="Overlapping Faces", default=True, update=_save_check_settings)
    chk_ngons: bpy.props.BoolProperty(name="Ngons (>N verts)", default=True, update=_save_check_settings)
    ngon_threshold: bpy.props.IntProperty(
        name="N=", description="N value for ngon check", default=4, min=3, update=_save_check_settings
    )
    chk_vertex_color: bpy.props.BoolProperty(name="Vertex Color", default=True, update=_save_check_settings)
    chk_uv_count: bpy.props.BoolProperty(name="UV Count", default=True, update=_save_check_settings)
    uv_count_operator: bpy.props.EnumProperty(
        name="UV Operator", items=_UV_OPERATOR_ITEMS, default='<=', update=_save_check_settings
    )
    uv_count_value: bpy.props.IntProperty(
        name="UV Value", description="Value for UV count comparison", default=2, min=0, update=_save_check_settings
    )
    chk_animation: bpy.props.BoolProperty(name="Animation Data", default=True, update=_save_check_settings)

    # Material checks
    chk_material_count: bpy.props.BoolProperty(name="Material Count", default=True, update=_save_check_settings)
    chk_material_naming: bpy.props.BoolProperty(name="Material Naming", default=True, update=_save_check_settings)
    chk_unused_materials: bpy.props.BoolProperty(name="Unused Materials", default=True, update=_save_check_settings)

    # Group checks
    chk_collision_matching: bpy.props.BoolProperty(name="Collision Matching", default=True, update=_save_check_settings)
    chk_lod_matching: bpy.props.BoolProperty(name="LOD Matching", default=True, update=_save_check_settings)

    # ---- Hidden export settings (used by export logic, not shown in UI) ----
    combine_meshes: bpy.props.BoolProperty(default=True)
    smooth_meshes: bpy.props.BoolProperty(default=True)
    import_materials: bpy.props.BoolProperty(default=True)
    import_textures: bpy.props.BoolProperty(default=True)

    def get_check_settings(self):
        """Build a dict of check settings for validation functions."""
        return {
            'mesh_naming': self.chk_mesh_naming,
            'mesh_naming_regex': self.mesh_naming_regex,
            'transform_zero': self.chk_transform_zero,
            'loose_geometry': self.chk_loose_geometry,
            'overlapping_faces': self.chk_overlapping_faces,
            'ngons': self.chk_ngons,
            'ngon_threshold': self.ngon_threshold,
            'vertex_color': self.chk_vertex_color,
            'uv_count': self.chk_uv_count,
            'uv_count_operator': self.uv_count_operator,
            'uv_count_value': self.uv_count_value,
            'animation': self.chk_animation,
            'material_count': self.chk_material_count,
            'material_naming': self.chk_material_naming,
            'unused_materials': self.chk_unused_materials,
            'collision_matching': self.chk_collision_matching,
            'lod_matching': self.chk_lod_matching,
        }

    @staticmethod
    def load_check_settings_from_config():
        """Load check settings from config file and apply to scene settings."""
        config = load_config()
        check_cfg = config.get('check_settings', {})
        if not check_cfg:
            return
        settings = bpy.context.scene.export_to_ue_settings
        mapping = {
            'mesh_naming': 'chk_mesh_naming',
            'mesh_naming_regex': 'mesh_naming_regex',
            'transform_zero': 'chk_transform_zero',
            'loose_geometry': 'chk_loose_geometry',
            'overlapping_faces': 'chk_overlapping_faces',
            'ngons': 'chk_ngons',
            'ngon_threshold': 'ngon_threshold',
            'vertex_color': 'chk_vertex_color',
            'uv_count': 'chk_uv_count',
            'uv_count_operator': 'uv_count_operator',
            'uv_count_value': 'uv_count_value',
            'animation': 'chk_animation',
            'material_count': 'chk_material_count',
            'material_naming': 'chk_material_naming',
            'unused_materials': 'chk_unused_materials',
            'collision_matching': 'chk_collision_matching',
            'lod_matching': 'chk_lod_matching',
        }
        for cfg_key, prop_name in mapping.items():
            if cfg_key in check_cfg:
                setattr(settings, prop_name, check_cfg[cfg_key])
