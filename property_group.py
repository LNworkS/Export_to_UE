import bpy
import os

from .i18n import t
from .core.config import (
    save_export_path, get_saved_export_path, load_config, save_config,
)


def get_default_export_path():
    if bpy.data.filepath:
        return os.path.join(os.path.dirname(bpy.data.filepath), "BlenderExport")
    return os.path.join(os.path.expanduser("~"), "BlenderExport")


def update_use_fixed_path(self, context):
    if not self.use_fixed_path and not self.export_path:
        saved_path = get_saved_export_path()
        if saved_path:
            self.export_path = saved_path


def update_export_path(self, context):
    if self.export_path:
        save_export_path(self.export_path)


# Flag set True while load_check_settings_from_config() runs, so the update
# callbacks do not persist intermediate/empty values over saved ones.
_LOADING_CHECK_SETTINGS = False


def _save_check_settings(self, context):
    if _LOADING_CHECK_SETTINGS:
        return
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


_UV_OPERATOR_ITEMS = [
    ('<', '<', ''),
    ('<=', '<=', ''),
    ('==', '==', ''),
    ('>=', '>=', ''),
    ('>', '>', ''),
]


class ExportToUEPropertyGroup(bpy.types.PropertyGroup):
    """Property group for Export to UE settings."""

    # ---- Object Selection ----
    selected_only: bpy.props.BoolProperty(
        name="Selected Objects",
        description=t("Export only selected objects"),
        default=True,
    )
    independent_lod: bpy.props.BoolProperty(
        name="Independent LOD",
        description=t("Handle LOD groups separately"),
        default=False,
    )

    # ---- Export Path ----
    use_fixed_path: bpy.props.BoolProperty(
        name="Fixed Path",
        description=t("Use default path (filepath\BlenderExport). When disabled, path is saved in plugin config."),
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

    # ---- Check Settings ----
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
    chk_material_count: bpy.props.BoolProperty(name="Material Count", default=True, update=_save_check_settings)
    chk_material_naming: bpy.props.BoolProperty(name="Material Naming", default=True, update=_save_check_settings)
    chk_unused_materials: bpy.props.BoolProperty(name="Unused Materials", default=True, update=_save_check_settings)
    chk_collision_matching: bpy.props.BoolProperty(name="Collision Matching", default=True, update=_save_check_settings)
    chk_lod_matching: bpy.props.BoolProperty(name="LOD Matching", default=True, update=_save_check_settings)

    # ---- Hidden export settings ----
    combine_meshes: bpy.props.BoolProperty(default=True)
    smooth_meshes: bpy.props.BoolProperty(default=True)
    import_materials: bpy.props.BoolProperty(default=True)
    import_textures: bpy.props.BoolProperty(default=True)
    # Independent of material import: controls whether FBX carries custom props.
    use_custom_props: bpy.props.BoolProperty(default=True)

    def get_check_settings(self):
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
        global _LOADING_CHECK_SETTINGS
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
        _LOADING_CHECK_SETTINGS = True
        try:
            for cfg_key, prop_name in mapping.items():
                if cfg_key in check_cfg:
                    setattr(settings, prop_name, check_cfg[cfg_key])
        finally:
            _LOADING_CHECK_SETTINGS = False


# ============================================================
# Plugin Update Property Group (independent panel)
# ============================================================

class UpdatePropertyGroup(bpy.types.PropertyGroup):
    """Property group holding plugin update-check state."""

    update_available: bpy.props.BoolProperty(
        name="Update Available",
        description="True when a newer version is available on GitHub.",
        default=False,
    )
    update_latest_version: bpy.props.StringProperty(name="Latest Version", default="")
    update_download_url: bpy.props.StringProperty(
        name="Update Download URL", default="", subtype="FILE_PATH"
    )
    update_current_version: bpy.props.StringProperty(name="Current Version", default="")
    update_error: bpy.props.StringProperty(name="Update Check Error", default="")
    update_checking: bpy.props.BoolProperty(
        name="Checking",
        description="True while an update check is in progress.",
        default=False,
    )
    update_source: bpy.props.StringProperty(
        name="Update Source",
        description="Where the latest version info came from (release or manifest).",
        default="",
    )


# ============================================================
# Save to .MAX Property Group
# ============================================================

def _save_max_settings(self, context):
    """Update callback: persist max settings to config.json.

    Only the 3ds Max executable path and the "selected only" flag are
    plugin-level preferences (shared across .blend files).

    The save path and the custom file name are NOT persisted here:
    they live in the .blend file (Scene ID properties), so each blend
    starts with whatever the user chose for that file.

    Skipped while loading config to avoid overwriting saved values with
    in-progress defaults.
    """
    if _LOADING_MAX_SETTINGS:
        return
    config = load_config()
    config['max_settings'] = {
        'max_exe_path': self.max_exe_path,
        'max_selected_only': self.max_selected_only,
    }
    save_config(config)


# Flag set True while load_max_settings_from_config() runs, so the update
# callback does not persist intermediate/empty values over saved ones.
_LOADING_MAX_SETTINGS = False

# Max conversion queue states (kept in sync by the UI timer, not persisted).
MAX_QUEUE_STATE_ITEMS = [
    ('IDLE', "Idle", ""),
    ('RUNNING', "Running", ""),
    ('QUEUED', "Queued", ""),
]


def _default_max_file_name():
    """Current blend file name (without extension); empty when unsaved."""
    blend_path = bpy.data.filepath
    if blend_path:
        blend_name = bpy.path.basename(blend_path)
        name = os.path.splitext(blend_name)[0]
        if name:
            return name
    return ""


# ---- Dynamic file name (get/set) ----
# When "Use Blender File Name" is checked the property reads the current
# blend file name live (updates after Save As, disabled in the UI).
# When unchecked it reads the user-typed custom name, which is stored as a
# Scene ID property and therefore travels with the .blend file.

def _get_max_file_name(self):
    if self.get("use_blend_file_name", True):
        return _default_max_file_name()
    return self.get("max_file_name_custom", "")


def _set_max_file_name(self, value):
    self["max_file_name_custom"] = value


class SaveToMaxPropertyGroup(bpy.types.PropertyGroup):
    """Property group for Save to .MAX settings."""

    max_exe_path: bpy.props.StringProperty(
        name="3ds Max Executable",
        description=t("Path to 3dsmaxbatch.exe, e.g. C:\\Program Files\\Autodesk\\3ds Max 2024\\3dsmaxbatch.exe"),
        subtype="FILE_PATH",
        default="",
        update=_save_max_settings,
    )

    max_save_path: bpy.props.StringProperty(
        name="Save Path",
        description=t("Directory to save .max files. Chosen per .blend file; not filled in by default."),
        subtype="DIR_PATH",
        default="",
    )

    use_blend_file_name: bpy.props.BoolProperty(
        name="Use Blender File Name",
        description=t("When checked, the .max file name always follows the current blend file name. Uncheck to type a custom name (saved with the .blend file)."),
        default=True,
    )

    max_file_name: bpy.props.StringProperty(
        name="File Name",
        description=t("Name of the .max file (without extension). When 'Use Blender File Name' is checked this shows the current blend file name; otherwise type a custom name, saved with the .blend file."),
        default="",
        get=_get_max_file_name,
        set=_set_max_file_name,
    )

    max_selected_only: bpy.props.BoolProperty(
        name="Selected Objects",
        description=t("Export only selected objects"),
        default=True,
        update=_save_max_settings,
    )

    # ---- Background queue state (updated by UI timer; not persisted) ----
    max_queue_state: bpy.props.EnumProperty(
        name="Queue State",
        items=MAX_QUEUE_STATE_ITEMS,
        default='IDLE',
    )
    max_queue_info: bpy.props.StringProperty(
        name="Queue Info",
        description="Current 3ds Max conversion queue status.",
        default="",
    )
    max_last_result: bpy.props.StringProperty(
        name="Last Result",
        description="Result of the most recent .max conversion.",
        default="",
    )

    @staticmethod
    def load_max_settings_from_config():
        """Load max settings from config.json (called by register / load_post).

        Only plugin-level preferences are restored (3ds Max executable path
        and the "selected only" flag). The save path and the custom file
        name are per-.blend values: they are stored as Scene properties and
        come back automatically when the .blend file is opened — they are
        deliberately NOT restored from the plugin config so a new scene
        starts with empty fields the user must fill in.
        """
        global _LOADING_MAX_SETTINGS
        _LOADING_MAX_SETTINGS = True
        try:
            config = load_config()
            max_cfg = config.get('max_settings', {})
            if not max_cfg:
                # Legacy config layout (pre-0.2.0): flat keys.
                max_cfg = {
                    'max_exe_path': config.get('max_exe_path', ''),
                    'max_selected_only': config.get('max_selected_only', True),
                }
            settings = bpy.context.scene.save_to_max_settings
            if 'max_exe_path' in max_cfg:
                settings.max_exe_path = max_cfg['max_exe_path']
            if 'max_selected_only' in max_cfg:
                settings.max_selected_only = bool(max_cfg['max_selected_only'])
        finally:
            _LOADING_MAX_SETTINGS = False
