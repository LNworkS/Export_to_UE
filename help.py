"""Plugin help/documentation module (independent from the Update panel).

Why a separate module instead of reusing the Update panel:
- The Update panel's job is version checking (dynamic, temporary);
  documentation is static, long-lived content. Mixing them makes the
  docs harder to discover and couples two unrelated lifecycles.
- A dedicated module is easy to extend later (per-version docs, FAQ...).

Provided:
- VIEW3D_PT_plugin_help : collapsible panel in the Export_To_UE tab.
- WM_OT_export_ue_help  : popup dialog with the full documentation.
"""

import bpy

from .i18n import t


# ============================================================
# Help dialog (popup)
# ============================================================

class WM_OT_export_ue_help(bpy.types.Operator):
    """Show the full plugin documentation in a popup dialog"""
    bl_idname = "wm.export_ue_help"
    bl_label = "Export To UE Help"

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = False

        # --- Overview ---
        head = layout.row()
        head.label(text=t("Export To UE - Help"), icon='INFO')
        layout.separator()

        # --- 1. Export to UE ---
        b1 = layout.box()
        b1.label(text=t("1. Export to UE (FBX)"), icon='EXPORT')
        b1.label(text=t("HELP_E2E_1"))
        b1.label(text=t("HELP_E2E_2"))
        b1.label(text=t("HELP_E2E_3"))

        # --- 2. Save as .Max ---
        b2 = layout.box()
        b2.label(text=t("2. Save as .Max (archive)"), icon='FILE_FOLDER')
        b2.label(text=t("HELP_SAVE_1"))
        b2.label(text=t("HELP_SAVE_2"))
        b2.label(text=t("HELP_SAVE_3"))

        # --- 3. Import Max with Units ---
        b3 = layout.box()
        b3.label(text=t("3. Import Max with Units"), icon='IMPORT')
        b3.label(text=t("HELP_IMPORT_1"))
        b3.label(text=t("HELP_IMPORT_2"))
        b3.label(text=t("HELP_IMPORT_3"))
        b3.label(text=t("HELP_IMPORT_4"))
        b3.label(text=t("HELP_IMPORT_5"))

        # --- 4. Update ---
        b4 = layout.box()
        b4.label(text=t("4. Plugin Update"), icon='WORLD')
        b4.label(text=t("HELP_UPDATE_1"))

        # --- FAQ ---
        faq = layout.box()
        faq.label(text=t("FAQ"), icon='QUESTION')
        faq.label(text=t("HELP_FAQ_1"))
        faq.label(text=t("HELP_FAQ_2"))
        faq.label(text=t("HELP_FAQ_3"))

    def invoke(self, context, event):
        return context.window_manager.invoke_popup(self, width=560)


# ============================================================
# Help panel (collapsible, next to the other panels)
# ============================================================

class VIEW3D_PT_plugin_help(bpy.types.Panel):
    """Plugin Help panel - quick access to the documentation."""
    bl_label = "Help"
    bl_idname = "VIEW3D_PT_plugin_help"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Export_To_UE"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        box = layout.box()
        box.label(text=t("Documentation"), icon='INFO')
        box.operator("wm.export_ue_help", text=t("Open Help"), icon='HELP')
        box.separator()
        box.label(text=t("Shortcuts:"), icon='KEYINGSET')
        box.label(text=t("HELP_QUICK_1"))
        box.label(text=t("HELP_QUICK_2"))


classes = (
    WM_OT_export_ue_help,
    VIEW3D_PT_plugin_help,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass
