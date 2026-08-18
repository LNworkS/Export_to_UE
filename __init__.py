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
import threading

from .i18n import t
from .property_group import ExportToUEPropertyGroup, get_default_export_path
from .core.operators import (
    OBJECT_OT_export_to_ue,
    OBJECT_OT_export_check_dialog,
    OBJECT_OT_export_check_action,
    OBJECT_OT_check_settings,
)
from .core.update_operators import (
    OBJECT_OT_check_update,
    OBJECT_OT_perform_update,
)
from .core.config import get_saved_export_path
from .core.updater import check_for_update, get_current_version_str, get_cached_result


class VIEW3D_PT_export_to_ue(bpy.types.Panel):
    bl_label = "Export to Unreal Engine"
    bl_idname = "VIEW3D_PT_export_to_ue"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Export_To_UE"

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        settings = scene.export_to_ue_settings
        path_box = layout.box()
        path_box.label(text=t("FBX Export"), icon="FILE_FOLDER")
        path_box.prop(settings, "selected_only", text=t("Selected Objects"))
        path_box.prop(settings, "independent_lod", text=t("Independent LOD"))
        path_box.prop(settings, "adapt_ue_rotation", text=t("+90° on Z"))
        check_row = path_box.row(align=True)
        check_row.prop(settings, "check_before_export", text=t("Check"))
        if settings.check_before_export:
            check_row.operator("object.check_settings", text="", icon="PREFERENCES")
        path_box.prop(settings, "use_fixed_path", text=t("Fixed Path"))
        if settings.use_fixed_path:
            path_box.label(text=f"  {get_default_export_path()}")
        else:
            path_box.prop(settings, "export_path", text="")
        layout.separator()
        row = layout.row(align=True)
        row.scale_y = 1.5
        row.operator("object.export_to_ue", text=t("Export to UE"), icon="EXPORT")
        try:
            _draw_update_section(layout, settings)
        except Exception:
            import traceback as _tb
            print("[Export_To_UE] Plugin Update section draw() failed:")
            _tb.print_exc()
            layout.separator()
            safe_box = layout.box()
            safe_box.alert = True
            safe_box.label(text="Plugin Update error (see System Console)", icon="ERROR")
            try:
                safe_box.operator("object.check_update", text=t("Check for Updates"), icon="FILE_REFRESH")
            except Exception:
                pass


def _draw_update_section(layout, settings):
    layout.separator()
    upd_box = layout.box()
    upd_box.label(text=t("Plugin Update"), icon="WORLD")
    cur_ver = settings.update_current_version or get_current_version_str()
    upd_box.label(text=f"{t('Version')}: {cur_ver}", icon="INFO")
    if settings.update_checking:
        upd_box.label(text=t("Checking for updates..."), icon="RENDER_RESULT")
    elif settings.update_error:
        err_row = upd_box.row()
        err_row.alert = True
        err_row.label(text=t("Update check failed"), icon="ERROR")
        upd_box.operator("object.check_update", text=t("Retry Check"), icon="FILE_REFRESH")
    elif settings.update_available:
        new_row = upd_box.row()
        new_row.alert = True
        new_row.label(
            text=f"{t('New version available')}: {settings.update_latest_version}",
            icon="ERROR",
        )
        upd_box.operator("object.perform_update", text=t("Update Now"), icon="IMPORT")
        upd_box.operator("object.check_update", text=t("Check Again"), icon="FILE_REFRESH")
    else:
        if settings.update_current_version:
            upd_box.label(text=t("Already up to date"), icon="CHECKBOX_HLT")
        else:
            upd_box.label(text=t("Not checked yet"), icon="QUESTION")
        upd_box.operator("object.check_update", text=t("Check for Updates"), icon="FILE_REFRESH")


classes = (
    ExportToUEPropertyGroup,
    VIEW3D_PT_export_to_ue,
    OBJECT_OT_export_to_ue,
    OBJECT_OT_export_check_dialog,
    OBJECT_OT_export_check_action,
    OBJECT_OT_check_settings,
    OBJECT_OT_check_update,
    OBJECT_OT_perform_update,
)


def _apply_update_result(result):
    if not result:
        return
    ctx = bpy.context
    if not hasattr(ctx, 'scene') or ctx.scene is None:
        return
    if not hasattr(ctx.scene, 'export_to_ue_settings'):
        return
    settings = ctx.scene.export_to_ue_settings
    settings.update_available = bool(result.get('has_update'))
    settings.update_latest_version = result.get('latest_version') or ''
    settings.update_download_url = result.get('download_url') or ''
    settings.update_current_version = result.get('current_version') or get_current_version_str()
    settings.update_error = result.get('error') or ''
    settings.update_source = result.get('source') or ''
    settings.update_checking = False


def _apply_cached_update_state():
    cached = get_cached_result()
    if cached is not None:
        _apply_update_result(cached)


_BG_RESULT_QUEUE = []
_BG_RESULT_LOCK = threading.Lock()
_BG_THREAD = None


def _set_checking_flag(checking):
    try:
        if hasattr(bpy.context, 'scene') and hasattr(bpy.context.scene, 'export_to_ue_settings'):
            bpy.context.scene.export_to_ue_settings.update_checking = bool(checking)
    except Exception:
        pass


def _apply_bg_result_timer():
    with _BG_RESULT_LOCK:
        if not _BG_RESULT_QUEUE:
            return 0.5
        result = _BG_RESULT_QUEUE.pop(0)
    try:
        _apply_update_result(result)
    except Exception as e:
        print(f"Export to UE: failed to apply background update result: {e}")
    return None


def _bg_worker(force_check):
    try:
        result = check_for_update(force=force_check)
    except Exception as e:
        print(f"Export to UE: background update check failed: {e}")
        result = None
    with _BG_RESULT_LOCK:
        _BG_RESULT_QUEUE.append(result)
    try:
        _set_checking_flag(False)
    except Exception:
        pass


def start_background_update_check(force=False):
    global _BG_THREAD
    if _BG_THREAD and _BG_THREAD.is_alive():
        return
    try:
        _set_checking_flag(True)
        def run_and_queue():
            _bg_worker(force_check=force)
        _BG_THREAD = threading.Thread(
            target=run_and_queue,
            name="ExportToUE-UpdateCheck",
            daemon=True,
        )
        _BG_THREAD.start()
        try:
            if not bpy.app.timers.is_registered(_apply_bg_result_timer):
                bpy.app.timers.register(_apply_bg_result_timer, first_interval=0.5)
        except Exception as e:
            print(f"Export to UE: failed to register result timer: {e}")
    except Exception as e:
        print(f"Export to UE: failed to launch background update check: {e}")
        _set_checking_flag(False)


def _deferred_update_check():
    start_background_update_check(force=False)
    return None


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.export_to_ue_settings = bpy.props.PointerProperty(
        type=ExportToUEPropertyGroup
    )
    def load_saved_settings():
        if hasattr(bpy.context, 'scene'):
            saved_path = get_saved_export_path()
            if saved_path:
                bpy.context.scene.export_to_ue_settings.export_path = saved_path
            ExportToUEPropertyGroup.load_check_settings_from_config()
            _apply_cached_update_state()
    bpy.app.handlers.load_post.append(load_saved_settings)
    load_saved_settings()
    try:
        bpy.app.timers.register(_deferred_update_check, first_interval=5.0)
    except Exception as e:
        print(f"Export to UE: failed to schedule update check: {e}")


def unregister():
    for handler in bpy.app.handlers.load_post:
        if handler.__name__ == 'load_saved_settings':
            bpy.app.handlers.load_post.remove(handler)
            break
    try:
        if bpy.app.timers.is_registered(_deferred_update_check):
            bpy.app.timers.unregister(_deferred_update_check)
    except Exception:
        pass
    try:
        del bpy.types.Scene.export_to_ue_settings
    except Exception:
        pass
    for cls in reversed(classes):
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass


if __name__ == "__main__":
    register()
