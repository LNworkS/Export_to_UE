import bpy
import os

from ..i18n import t, is_chinese
from ..core.export import do_export, classify_objects
from ..core.validation import validate_export_list, STATUS_ICON, CheckResult


# ============================================================
# Module-level storage
# ============================================================
_VALIDATION_DATA = None
_EXPORT_SETTINGS = None
_EXPORT_CONTEXT = None
_DIALOG_VISIBLE = False
_ACTION_COMPLETED = False


def _count_group_errors(group):
    """Count errors and warnings in a group."""
    error_count = 0
    warn_count = 0
    for results in group['mesh_results'].values():
        for r in results:
            if r.status == 'error':
                error_count += 1
            elif r.status == 'warn':
                warn_count += 1
    for results in group['collision_results'].values():
        for r in results:
            if r.status == 'error':
                error_count += 1
            elif r.status == 'warn':
                warn_count += 1
    for results in group['lod_results'].values():
        for r in results:
            if r.status == 'error':
                error_count += 1
            elif r.status == 'warn':
                warn_count += 1
    for r in group['group_results']:
        if r.status == 'error':
            error_count += 1
        elif r.status == 'warn':
            warn_count += 1
    return error_count, warn_count


def _count_error_groups(validation_data):
    """Count groups that have errors."""
    count = 0
    for g in validation_data['groups']:
        error_count, _ = _count_group_errors(g)
        if error_count > 0:
            count += 1
    return count


def _count_total_errors(validation_data):
    """Count total number of errors across all groups."""
    total = 0
    for g in validation_data['groups']:
        error_count, _ = _count_group_errors(g)
        total += error_count
    return total


def _count_total_warnings(validation_data):
    """Count total number of warnings across all groups."""
    total = 0
    for g in validation_data['groups']:
        _, warn_count = _count_group_errors(g)
        total += warn_count
    return total


def _draw_results(layout, results):
    """Draw a list of CheckResult items with status styling.
    
    Text uses normal contrast (default). Only error rows get alert=True (red text).
    The emoji icons (✅❌⚠️) already provide green/red/yellow color distinction.
    """
    for r in results:
        icon = STATUS_ICON.get(r.status, '?')
        text = f"{icon} {r.label}"
        if r.detail:
            text += f": {r.detail}"
        row = layout.row()
        # Only use alert for errors (red text); ok/warn use default normal contrast
        if r.status == 'error':
            row.alert = True
        row.label(text=text)


def _draw_group_checks(layout, group):
    """Draw all check results for a group."""
    if group['group_results']:
        box = layout.box()
        box.label(text=t("Group Checks"), icon='GROUP')
        _draw_results(box, group['group_results'])

    for obj_name, results in group['mesh_results'].items():
        box = layout.box()
        box.label(text=f"{t('Mesh')}: {obj_name}", icon='MESH_DATA')
        _draw_results(box, results)

    for obj_name, results in group['collision_results'].items():
        box = layout.box()
        box.label(text=f"{t('Collision')}: {obj_name}", icon='MESH_ICOSPHERE')
        _draw_results(box, results)

    for obj_name, results in group['lod_results'].items():
        box = layout.box()
        box.label(text=f"LOD: {obj_name}", icon='MOD_LATTICE')
        _draw_results(box, results)


# ============================================================
# Export Operator
# ============================================================

class OBJECT_OT_export_to_ue(bpy.types.Operator):
    """Export selected objects to Unreal Engine with proper coordinate conversion"""
    bl_idname = "object.export_to_ue"
    bl_label = "Export to UE"
    bl_options = {'REGISTER'}

    def execute(self, context):
        global _VALIDATION_DATA, _EXPORT_SETTINGS, _EXPORT_CONTEXT
        settings = context.scene.export_to_ue_settings

        if not settings.use_fixed_path and not settings.export_path:
            self.report({'ERROR'}, t("Please select an export path or enable Fixed Path."))
            return {'CANCELLED'}

        if context.active_object and context.active_object.mode == 'EDIT':
            bpy.ops.object.mode_set(mode='OBJECT')

        success, message = do_export(settings, context)

        if success:
            self.report({'INFO'}, message)
        else:
            self.report({'ERROR'}, message)
            return {'CANCELLED'}

        _VALIDATION_DATA = None
        _EXPORT_SETTINGS = None
        _EXPORT_CONTEXT = None
        return {'FINISHED'}

    def invoke(self, context, event):
        global _VALIDATION_DATA, _EXPORT_SETTINGS, _EXPORT_CONTEXT, _DIALOG_VISIBLE, _ACTION_COMPLETED
        settings = context.scene.export_to_ue_settings

        if not settings.use_fixed_path and not settings.export_path:
            self.report({'ERROR'}, t("Please select an export path or enable Fixed Path."))
            return {'CANCELLED'}

        if context.active_object and context.active_object.mode == 'EDIT':
            bpy.ops.object.mode_set(mode='OBJECT')

        if settings.check_before_export:
            success, msg, export_list = classify_objects(
                settings.selected_only, settings.independent_lod
            )
            if not success:
                self.report({'ERROR'}, msg)
                return {'CANCELLED'}

            if not export_list:
                self.report({'ERROR'}, t("No objects to export."))
                return {'CANCELLED'}

            _VALIDATION_DATA = validate_export_list(export_list, settings.get_check_settings(), settings.independent_lod)
            _EXPORT_SETTINGS = settings
            _EXPORT_CONTEXT = context
            _DIALOG_VISIBLE = True
            _ACTION_COMPLETED = False

            # Show the popup dialog
            return context.window_manager.invoke_popup(self, width=500)

        return self.execute(context)

    def draw(self, context):
        global _VALIDATION_DATA, _ACTION_COMPLETED
        layout = self.layout
        data = _VALIDATION_DATA

        # If action completed, don't draw anything
        if _ACTION_COMPLETED:
            return

        if not data:
            return

        total_groups = len(data['groups'])
        error_group_count = _count_error_groups(data)
        total_errors = _count_total_errors(data)
        total_warnings = _count_total_warnings(data)

        # Title
        box = layout.box()
        box.label(text=t("Export Check Results"), icon='CHECKBOX_HLT')

        # Summary - use alert only for error summary (red text)
        if total_errors > 0:
            if is_chinese():
                summary = f"发现{total_errors}{t('error(s) in')}{error_group_count}{t('group(s) - review before export')}"
            else:
                summary = f"Found {total_errors} {t('error(s) in')} {error_group_count} {t('group(s) - review before export')}"
            row = layout.row()
            row.alert = True
            row.label(text=summary, icon='ERROR')
        elif total_warnings > 0:
            if is_chinese():
                summary = f"发现{total_warnings}{t('warning(s) in')}{total_groups}{t('group(s)')}"
            else:
                summary = f"Found {total_warnings} {t('warning(s) in')} {total_groups} {t('group(s)')}"
            layout.label(text=summary, icon='INFO')
        else:
            if is_chinese():
                summary = f"{t('All')}{total_groups}{t('group(s) passed checks')}"
            else:
                summary = f"{t('All')} {total_groups} {t('group(s) passed checks')}"
            layout.label(text=summary, icon='CHECKBOX_HLT')

        # Export and Cancel buttons - Export left, Cancel right
        # No errors: Export highlighted (normal), Cancel gray (dimmed)
        # Has errors: Export gray (dimmed), Cancel red highlight (alert)
        # Note: Blender API only supports red highlight (alert=True) and gray dimming
        # (active=False). Green highlight is not available; Export uses normal style
        # to stand out against the dimmed Cancel button.
        row = layout.row(align=True)
        row.scale_y = 1.5

        if total_errors == 0:
            # No errors: Export normal (highlighted), Cancel dimmed
            row.operator("object.export_check_action", text=t("Export"), icon='EXPORT').action = 'EXPORT'
            cancel_row = row.row()
            cancel_row.active = False
            cancel_row.operator("object.export_check_action", text=t("Cancel"), icon='X').action = 'CANCEL'
        else:
            # Has errors: Export dimmed, Cancel red highlight
            export_row = row.row()
            export_row.active = False
            export_row.operator("object.export_check_action", text=t("Export"), icon='EXPORT').action = 'EXPORT'
            cancel_row = row.row()
            cancel_row.alert = True
            cancel_row.operator("object.export_check_action", text=t("Cancel"), icon='X').action = 'CANCEL'

        layout.separator()

        if total_groups == 1:
            group = data['groups'][0]
            _draw_group_checks(layout, group)
        else:
            for group in data['groups']:
                error_count, warn_count = _count_group_errors(group)
                if error_count > 0:
                    status_icon = "❌"
                elif warn_count > 0:
                    status_icon = "⚠️"
                else:
                    status_icon = "✅"
                box = layout.box()
                box.label(text=f"{status_icon} {group['name']}")
                _draw_group_checks(box, group)


# ============================================================
# Dialog Action Operator
# ============================================================

class OBJECT_OT_export_check_action(bpy.types.Operator):
    """Action button in validation dialog"""
    bl_idname = "object.export_check_action"
    bl_label = "Dialog Action"
    bl_options = {'REGISTER', 'INTERNAL'}

    action: bpy.props.EnumProperty(
        items=[('EXPORT', 'Export', ''), ('CANCEL', 'Cancel', '')],
        default='EXPORT',
    )

    def execute(self, context):
        global _VALIDATION_DATA, _EXPORT_SETTINGS, _EXPORT_CONTEXT, _DIALOG_VISIBLE, _ACTION_COMPLETED

        if self.action == 'EXPORT':
            if _EXPORT_SETTINGS and _EXPORT_CONTEXT:
                success, message = do_export(_EXPORT_SETTINGS, _EXPORT_CONTEXT)
                if success:
                    self.report({'INFO'}, message)
                else:
                    self.report({'ERROR'}, message)
        elif self.action == 'CANCEL':
            self.report({'INFO'}, t("Export cancelled"))

        # Mark action as completed to prevent redraw
        _ACTION_COMPLETED = True
        _VALIDATION_DATA = None
        _EXPORT_SETTINGS = None
        _EXPORT_CONTEXT = None
        _DIALOG_VISIBLE = False

        return {'FINISHED'}


# ============================================================
# Check Settings Dialog Operator
# ============================================================

class OBJECT_OT_check_settings(bpy.types.Operator):
    """Open check settings dialog to configure which checks to run."""
    bl_idname = "object.check_settings"
    bl_label = "Check Settings"
    bl_options = {'REGISTER', 'INTERNAL'}

    def execute(self, context):
        return {'FINISHED'}

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=400)

    def draw(self, context):
        settings = context.scene.export_to_ue_settings
        layout = self.layout

        # ---- Mesh checks ----
        box = layout.box()
        box.label(text=t("Mesh Checks"), icon='MESH_DATA')

        # Model Naming with regex input
        row = box.row(align=True)
        row.prop(settings, "chk_mesh_naming", text=t("Model Naming"))
        row.prop(settings, "mesh_naming_regex", text="", icon="SYNTAX_ON")

        box.prop(settings, "chk_transform_zero", text=t("Transform Zeroed"))
        box.prop(settings, "chk_loose_geometry", text=t("Loose Geometry"))
        box.prop(settings, "chk_overlapping_faces", text=t("Overlapping Faces"))

        # Ngons with N input
        row = box.row(align=True)
        row.prop(settings, "chk_ngons", text=t("Ngons (>N verts)"))
        row.label(text="N=")
        row.prop(settings, "ngon_threshold", text="")

        box.prop(settings, "chk_vertex_color", text=t("Vertex Color"))

        # UV count with operator dropdown and value input
        row = box.row(align=True)
        row.prop(settings, "chk_uv_count", text=t("UV Count"))
        row.prop(settings, "uv_count_operator", text="")
        row.prop(settings, "uv_count_value", text="")

        box.prop(settings, "chk_animation", text=t("Animation Data"))

        # ---- Material checks ----
        box = layout.box()
        box.label(text=t("Material Checks"), icon='MATERIAL')
        box.prop(settings, "chk_material_count", text=t("Material Count"))
        box.prop(settings, "chk_material_naming", text=t("Material Naming"))
        box.prop(settings, "chk_unused_materials", text=t("Unused Materials"))

        # ---- Group checks ----
        box = layout.box()
        box.label(text=t("Group Checks"), icon='GROUP')
        box.prop(settings, "chk_collision_matching", text=t("Collision Matching"))
        box.prop(settings, "chk_lod_matching", text=t("LOD Matching"))

