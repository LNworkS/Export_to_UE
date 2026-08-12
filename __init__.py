bl_info = {
    "name": "Export_To_UE",
    "author": "BI1MCS",
    "version": (0, 1, 1),
    "blender": (4, 2, 0),
    "location": "View3D > Export_To_UE",
    "description": "Export models to Unreal Engine with proper FBX settings.",
    "category": "Generic",
}

import bpy
import os

from .i18n import t
from .property_group import ExportToUEPropertyGroup, get_default_export_path
from .core.operators import (
    OBJECT_OT_export_to_ue,
    OBJECT_OT_export_check_dialog,
    OBJECT_OT_export_check_action,
    OBJECT_OT_check_settings,
)
from .core.config import get_saved_export_path


class VIEW3D_PT_export_to_ue(bpy.types.Panel):
    """Export to Unreal Engine panel in the Generic sidebar."""
    bl_label = "Export to Unreal Engine"
    bl_idname = "VIEW3D_PT_export_to_ue"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Export_To_UE"

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        settings = scene.export_to_ue_settings

        # ---- FBX Export ----
        path_box = layout.box()
        path_box.label(text=t("FBX Export"), icon="FILE_FOLDER")

        path_box.prop(settings, "selected_only", text=t("Selected Objects"))
        path_box.prop(settings, "include_lod", text=t("Independent LOD"))
        path_box.prop(settings, "adapt_ue_rotation", text=t("+90° on Z"))

        # Check with conditional settings button
        check_row = path_box.row(align=True)
        check_row.prop(settings, "check_before_export", text=t("Check"))
        if settings.check_before_export:
            check_row.operator("object.check_settings", text="", icon="PREFERENCES")

        path_box.prop(settings, "use_fixed_path", text=t("Fixed Path"))
        if settings.use_fixed_path:
            path_box.label(text=f"  {get_default_export_path()}")
        else:
            path_box.prop(settings, "export_path", text="")

        # ---- Export Button ----
        layout.separator()
        row = layout.row(align=True)
        row.scale_y = 1.5
        row.operator("object.export_to_ue", text=t("Export to UE"), icon="EXPORT")


classes = (
    ExportToUEPropertyGroup,
    VIEW3D_PT_export_to_ue,
    OBJECT_OT_export_to_ue,
    OBJECT_OT_export_check_dialog,
    OBJECT_OT_export_check_action,
    OBJECT_OT_check_settings,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)

    bpy.types.Scene.export_to_ue_settings = bpy.props.PointerProperty(
        type=ExportToUEPropertyGroup
    )

    # Load saved settings from config file
    def load_saved_settings():
        if hasattr(bpy.context, 'scene'):
            saved_path = get_saved_export_path()
            if saved_path:
                bpy.context.scene.export_to_ue_settings.export_path = saved_path
            # Load check settings from config
            ExportToUEPropertyGroup.load_check_settings_from_config()

    # Register handler for loading when .blend file is opened
    bpy.app.handlers.load_post.append(load_saved_settings)

    # Also load immediately after registration
    load_saved_settings()


def unregister():
    # Remove load handler
    for handler in bpy.app.handlers.load_post:
        if handler.__name__ == 'load_saved_settings':
            bpy.app.handlers.load_post.remove(handler)
            break

    del bpy.types.Scene.export_to_ue_settings

    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()
