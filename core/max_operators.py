import os

import bpy

from ..i18n import t, is_chinese
from .max_export import do_save_to_max, resolve_max_save_path


# ============================================================
# Save to .MAX Operator (main save button)
# ============================================================

class OBJECT_OT_save_to_max(bpy.types.Operator):
    """Save Blender objects as .max file via 3ds Max batch conversion"""
    bl_idname = "object.save_to_max"
    bl_label = "Save as .MAX"
    bl_options = {'REGISTER'}

    # Internal flag: set True by the overwrite-confirm dialog so execute()
    # knows the user already approved overwriting an existing file.
    # Named without leading underscore (Blender RNA skips underscore-prefixed).
    overwrite_confirmed: bpy.props.BoolProperty(default=False, options={'HIDDEN', 'SKIP_SAVE'})

    def invoke(self, context, event):
        max_settings = context.scene.save_to_max_settings

        # ---- Basic validation before any dialog ----
        if not max_settings.max_save_path:
            self.report({'ERROR'}, t("Please select a .max save path."))
            return {'CANCELLED'}

        if not max_settings.use_blend_file_name and not (max_settings.max_file_name or "").strip():
            self.report({'ERROR'}, t("Please enter a file name or enable Use Blender File Name."))
            return {'CANCELLED'}

        if context.active_object and context.active_object.mode == 'EDIT':
            bpy.ops.object.mode_set(mode='OBJECT')

        # ---- Check for existing file -> ask to overwrite ----
        target_path = resolve_max_save_path(max_settings)
        if target_path and os.path.isfile(target_path) and not self.overwrite_confirmed:
            # Store target path so draw() can show it; render the confirm popup.
            self.target_path = target_path
            return context.window_manager.invoke_props_dialog(self, width=400)

        # No conflict (or already confirmed) -> run the conversion now.
        return self.execute(context)

    def draw(self, context):
        """Draws the overwrite-confirmation dialog body (only used by invoke)."""
        layout = self.layout
        target = getattr(self, "target_path", "")
        if is_chinese():
            layout.label(text="该文件已存在，是否覆盖？")
            layout.label(text=target)
        else:
            layout.label(text="File already exists. Overwrite?")
            layout.label(text=target)

    def execute(self, context):
        max_settings = context.scene.save_to_max_settings

        if not max_settings.max_save_path:
            self.report({'ERROR'}, t("Please select a .max save path."))
            return {'CANCELLED'}

        if not max_settings.use_blend_file_name and not (max_settings.max_file_name or "").strip():
            self.report({'ERROR'}, t("Please enter a file name or enable Use Blender File Name."))
            return {'CANCELLED'}

        # Non-blocking: FBX is exported synchronously (scene snapshot), then
        # the 3ds Max conversion runs on a background serial queue. The UI
        # stays responsive and the queue status is shown in the panel.
        success, message = do_save_to_max(max_settings, context)

        if success:
            self.report({'INFO'}, message)
            # A conversion task was enqueued: make sure the main-thread UI
            # timer polls the queue and updates the panel status.
            from .. import ensure_max_queue_polling
            ensure_max_queue_polling()
        else:
            self.report({'ERROR'}, message)
            return {'CANCELLED'}

        return {'FINISHED'}


# ============================================================
# Max Settings Dialog Operator (settings button)
# ============================================================

class OBJECT_OT_max_settings(bpy.types.Operator):
    """Configure 3ds Max executable path and export options"""
    bl_idname = "object.max_settings"
    bl_label = "Max Settings"
    bl_options = {'REGISTER', 'INTERNAL'}

    def execute(self, context):
        # Settings are persisted via property update callbacks; nothing to do here.
        return {'FINISHED'}

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=500)

    def draw(self, context):
        settings = context.scene.save_to_max_settings
        layout = self.layout

        box = layout.box()
        box.label(text=t("3ds Max Settings"), icon='SETTINGS')

        # 3dsmaxbatch.exe path (FILE_PATH subtype provides file browser)
        box.prop(settings, "max_exe_path", text=t("3ds Max Executable"), icon="FILE")

        # Selected objects checkbox (only export selected vs all objects)
        box.prop(settings, "max_selected_only", text=t("Selected Objects"))
