"""Operators for checking and applying plugin updates."""

import bpy

from ..i18n import t
from .updater import check_for_update, download_and_install, get_current_version_str


def _get_update_settings():
    """Return the scene's update property group (created by the package)."""
    scene = bpy.context.scene
    if not hasattr(scene, 'update_settings'):
        return None
    return scene.update_settings


def _apply_result_to_scene(result):
    """Apply a check_for_update() result dict to the scene's property group.

    Safe to call from operators running on the main thread.
    """
    settings = _get_update_settings()
    if settings is None:
        return
    settings.update_available = bool(result.get('has_update'))
    settings.update_latest_version = result.get('latest_version') or ''
    settings.update_download_url = result.get('download_url') or ''
    settings.update_current_version = result.get('current_version') or get_current_version_str()
    settings.update_error = result.get('error') or ''
    settings.update_source = result.get('source') or ''
    settings.update_checking = False


class OBJECT_OT_check_update(bpy.types.Operator):
    """Check GitHub for a newer version of the plugin (non-blocking).

    Launches the check on a background thread so Blender UI stays responsive,
    and uses a modal timer to detect completion, then reports to the user.
    """
    bl_idname = "object.check_update"
    bl_label = "Check for Updates"
    bl_description = "Check GitHub for a newer version of Export To UE"
    bl_options = {'REGISTER', 'INTERNAL'}

    _timer = None
    _last_state_checking = False
    _ticks = 0

    def invoke(self, context, event):
        # Lazy import to avoid circular import (package imports operators).
        from .. import start_background_update_check
        start_background_update_check(force=True)

        context.window_manager.modal_handler_add(self)
        self._timer = context.window_manager.event_timer_add(0.3, window=context.window)
        self._last_state_checking = True
        self._ticks = 0
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        if event.type != 'TIMER':
            return {'PASS_THROUGH'}

        self._ticks += 1
        settings = _get_update_settings()
        if settings is None:
            context.window_manager.event_timer_remove(self._timer)
            self._timer = None
            return {'FINISHED'}
        done = (not settings.update_checking) and (self._ticks > 2 or not self._last_state_checking)

        # Give UI a chance to show "Checking..." for at least ~1 tick.
        if settings.update_checking:
            self._last_state_checking = True
            return {'PASS_THROUGH'}

        if self._ticks < 2:
            # Wait a tiny bit longer so result-timer in __init__.py has a chance
            # to apply the scene state.
            return {'PASS_THROUGH'}

        # --- done ---
        context.window_manager.event_timer_remove(self._timer)
        self._timer = None

        if settings.update_error:
            self.report({'WARNING'}, f"{t('Update check failed')}: {settings.update_error}")
        elif settings.update_available:
            self.report({'INFO'}, f"{t('New version available')}: {settings.update_latest_version}")
        else:
            self.report({'INFO'}, t("Already up to date"))

        # Force the panel region to redraw.
        for area in context.screen.areas:
            if area.type == 'VIEW_3D':
                for region in area.regions:
                    region.tag_redraw()
                break

        return {'FINISHED'}

    def cancel(self, context):
        if self._timer is not None:
            try:
                context.window_manager.event_timer_remove(self._timer)
            except Exception:
                pass
            self._timer = None


class OBJECT_OT_perform_update(bpy.types.Operator):
    """Download and install the latest version from GitHub.

    Asks for confirmation before overwriting the current install.
    After successful install, the user is asked to restart Blender.
    """
    bl_idname = "object.perform_update"
    bl_label = "Update Now"
    bl_description = "Download the latest version from GitHub and install it (overwrites current install)"
    bl_options = {'REGISTER', 'INTERNAL'}

    @classmethod
    def poll(cls, context):
        settings = _get_update_settings()
        if settings is None:
            return False
        return bool(getattr(settings, 'update_download_url', ''))

    def invoke(self, context, event):
        # Confirmation dialog
        return context.window_manager.invoke_props_dialog(self, width=400)

    def draw(self, context):
        settings = _get_update_settings()
        layout = self.layout
        latest = settings.update_latest_version if settings else 'unknown'
        current = settings.update_current_version if settings else get_current_version_str()
        col = layout.column()
        col.label(text=t("Update Confirmation"), icon='WORLD')
        col.label(text=f"{t('Current version')}: {current}")
        col.label(text=f"{t('New version')}: {latest}")
        col.separator()
        col.label(text=t("This will download and overwrite the current installation."))
        col.label(text=t("Blender restart is recommended after update."))

    def execute(self, context):
        settings = _get_update_settings()
        if settings is None:
            self.report({'ERROR'}, t("No download URL available. Please check for updates first."))
            return {'CANCELLED'}
        url = settings.update_download_url
        if not url:
            self.report({'ERROR'}, t("No download URL available. Please check for updates first."))
            return {'CANCELLED'}

        # Show in-progress state
        self.report({'INFO'}, t("Downloading update..."))

        success, message = download_and_install(url)

        if success:
            self.report({'INFO'}, message)
            # Clear update state since we just installed
            settings.update_available = False
            # Note: current version won't be updated until modules are reloaded by Blender restart
        else:
            self.report({'ERROR'}, message)
            return {'CANCELLED'}
        return {'FINISHED'}


classes = (
    OBJECT_OT_check_update,
    OBJECT_OT_perform_update,
)
