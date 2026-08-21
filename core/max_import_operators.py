"""Import Autodesk Max (.max) with automatic unit conversion.

Why this exists:
- Blender's builtin "Import Autodesk Max (.max)" importer ignores the
  file's unit scale, so a 100 cm model (1 unit = 1 cm in 3ds Max) comes
  in as 100 Blender units (1 BU = 1 m) - 100x too large.
- This operator reads the .max file's system units via 3dsmaxbatch.exe
  (loadMaxFile ... useFileUnits:true), compares them with the Blender
  scene unit settings, computes a scale factor and passes it to the
  builtin importer's `scale_objects` argument (which bakes the scale into
  the mesh data via the apply-matrix path).

Flow (two-stage):
1. execute #1 - read the file units (synchronous subprocess, cursor WAIT),
   then show a confirmation dialog with the detected unit, the Blender
   scene unit and the computed factor. The user can override the unit.
2. execute #2 (dialog OK) - compute the final factor and call the builtin
   import_scene.max with scale_objects=factor.
"""

import os

import bpy
from bpy_extras.io_utils import ImportHelper, orientation_helper
from bpy.props import (
    BoolProperty,
    CollectionProperty,
    EnumProperty,
    StringProperty,
)

from ..i18n import t
from .max_units import (
    blender_meters_per_unit,
    compute_scale_factor,
    find_3dsmaxbatch,
    meters_per_unit_from_type,
    read_max_file_units,
    unit_label,
)
from .max_version import (
    detect_installed_max_versions,
    pick_3dsmax_for_file,
    read_max_file_version,
)

# Unit choices shown in the confirmation dialog. 'AUTO' means "use the
# automatically detected file unit" (only valid when detection succeeded).
_UNIT_ITEMS = [
    ('AUTO', "Auto (detected)", ""),
    ('millimeters', "Millimeters", ""),
    ('centimeters', "Centimeters", ""),
    ('meters', "Meters", ""),
    ('kilometers', "Kilometers", ""),
    ('inches', "Inches", ""),
    ('feet', "Feet", ""),
    ('miles', "Miles", ""),
]

_OBJECT_FILTER_ITEMS = [
    ('MATERIAL', "Material", "", 'MATERIAL_DATA', 0x1),
    ('UV', "UV Maps", "", 'UV_DATA', 0x2),
    ('PRIMITIVE', "Primitive", "", 'CUBE', 0x4),
    ('EMPTY', "Empty", "", 'EMPTY_AXIS', 0x8),
    ('ARMATURE', "Armature", "", 'ARMATURE_DATA', 0x10),
]


@orientation_helper(axis_forward='Y', axis_up='Z')
def effective_meters_per_unit(unit_choice, unit_info):
    """Meters per 1 unit of the .max file (None when unknown).

    Args:
        unit_choice: the unit_choice enum value ('AUTO' or a unit type)
        unit_info: result dict from read_max_file_units()
    """
    if unit_choice == 'AUTO':
        if unit_info and unit_info.get('ok'):
            return unit_info.get('meters_per_unit')
        return None
    return meters_per_unit_from_type(unit_choice, 1.0)


class IMPORT_OT_max_with_units(bpy.types.Operator, ImportHelper):
    """Import MAX with automatic unit conversion"""
    bl_idname = "import_scene.max_with_units"
    bl_label = "Import MAX with Units (.max)"
    bl_options = {'PRESET', 'UNDO'}

    filename_ext = ".max"
    filter_glob: StringProperty(default="*.max", options={'HIDDEN'})
    files: CollectionProperty(type=bpy.types.OperatorFileListElement,
                              options={'HIDDEN', 'SKIP_SAVE'})
    directory: StringProperty(subtype='DIR_PATH')

    # ---- Options passed through to the builtin importer ----
    use_image_search: BoolProperty(
        name="Image Search",
        description="Search subdirectories for any associated images "
                    "(Warning, may be slow)",
        default=True,
    )
    object_filter: EnumProperty(
        name="Object Filter", options={'ENUM_FLAG'},
        items=_OBJECT_FILTER_ITEMS,
        description="Object types to import",
        default={'MATERIAL', 'UV', 'EMPTY', 'PRIMITIVE', 'ARMATURE'},
    )
    use_collection: BoolProperty(
        name="Collection",
        description="Create a new collection",
        default=False,
    )
    use_apply_matrix: BoolProperty(
        name="Apply Matrix",
        description="Use matrix to transform the objects",
        default=True,
    )

    # ---- Unit confirmation ----
    unit_choice: EnumProperty(
        name="Max File Unit",
        description="System unit used by the .max file "
                    "(1 unit = how much). AUTO uses the detected value.",
        items=_UNIT_ITEMS,
        default='AUTO',
    )

    # Internal stage state (survives between the two execute calls).
    _unit_info = None      # result dict from read_max_file_units()
    _file_version_info = None  # dict from read_max_file_version()
    _stage = 0             # 0 = not confirmed, 1 = dialog confirmed

    # ============================================================
    # Stage 1 / 2
    # ============================================================

    def _target_paths(self):
        if self.files:
            return [os.path.join(self.directory, f.name) for f in self.files]
        return [self.filepath]

    def execute(self, context):
        if self._stage == 0:
            # ---- Stage 1: detect version, read units, confirm ----
            paths = self._target_paths()
            if not paths or not os.path.isfile(paths[0]):
                self.report({'ERROR'}, t("Please select a .max file."))
                return {'CANCELLED'}

            # Version detection is pure binary parsing (~1 ms, no 3ds Max
            # launch) and lets us pick a 3dsmaxbatch that can open the file.
            self._file_version_info = read_max_file_version(paths[0])
            info = self._read_units_with_version_match(paths[0])

            self._unit_info = info
            # Default the dropdown: AUTO when detected, centimeters otherwise.
            if info and info.get('ok'):
                self.unit_choice = 'AUTO'
            else:
                self.unit_choice = 'centimeters'
            self._stage = 1
            return context.window_manager.invoke_props_dialog(self, width=460)

        # ---- Stage 2: dialog confirmed -> import with scale factor ----
        factor = self._compute_factor(context)
        if factor is None:
            self.report(
                {'ERROR'},
                t("Could not determine the Max file unit. "
                  "Please re-import and select the unit manually."),
            )
            return {'CANCELLED'}
        return self._do_import(context, factor)

    def _read_units_with_version_match(self, max_file):
        """Read units, preferring a 3ds Max that can open this file.

        Strategy:
        1. Match the file's version against installed 3ds Max versions;
           use the closest install >= file version (older exes cannot open
           newer .max files).
        2. When every install is older than the file (or no version was
           detected), try the newest install anyway.
        3. On failure, re-scan the install registry (it may be stale) and
           retry every untried install.
        """
        context = bpy.context
        installed = detect_installed_max_versions()
        file_year = (self._file_version_info or {}).get('year')
        best = None
        tried = set()

        info = None
        context.window.cursor_set('WAIT')
        try:
            if not installed:
                return None

            if file_year:
                best = pick_3dsmax_for_file(installed, file_year)
                if best:
                    info = read_max_file_units(max_file, best['path'])
                    tried.add(best['path'])
                else:
                    # No install is new enough -> the newest still gets one
                    # attempt (defensive; 3ds Max may open it in practice).
                    newest = installed[-1]['path']
                    info = read_max_file_units(max_file, newest)
                    tried.add(newest)
            else:
                fallback_exe = find_3dsmaxbatch()
                if fallback_exe:
                    info = read_max_file_units(max_file, fallback_exe)
                    tried.add(fallback_exe)

            if not (info and info.get('ok')):
                # Fresh re-scan + retry every untried install.
                for entry in detect_installed_max_versions():
                    if entry['path'] in tried:
                        continue
                    attempt = read_max_file_units(max_file, entry['path'])
                    tried.add(entry['path'])
                    if attempt.get('ok'):
                        info = attempt
                        break
                    info = attempt
                # Last resort: the user-configured exe, which may live
                # outside the auto-detected install locations.
                cfg_exe = find_3dsmaxbatch()
                if (cfg_exe and cfg_exe not in tried
                        and not (info and info.get('ok'))):
                    attempt = read_max_file_units(max_file, cfg_exe)
                    tried.add(cfg_exe)
                    if attempt.get('ok'):
                        info = attempt
        finally:
            context.window.cursor_set('DEFAULT')

        if info is None:
            return None
        # Helpful note when the file is simply too new for this computer.
        if not info.get('ok') and file_year:
            required = self._file_version_info['version']
            info['error'] = t("The .max file needs 3ds Max {year} or newer "
                              "to read its units").format(year=file_year)
        return info

    # ============================================================
    # Scale factor
    # ============================================================

    def _effective_meters_per_unit(self):
        """Meters per 1 unit of the .max file (None when unknown)."""
        return effective_meters_per_unit(self.unit_choice, self._unit_info)

    def _compute_factor(self, context):
        max_mpu = self._effective_meters_per_unit()
        if max_mpu is None or max_mpu <= 0:
            return None
        blender_mpu = blender_meters_per_unit(context.scene)
        return compute_scale_factor(max_mpu, blender_mpu)

    # ============================================================
    # Import
    # ============================================================

    def _do_import(self, context, factor):
        paths = self._target_paths()
        first = paths[0]
        keywords = {
            'filepath': first,
            'files': self.files,
            'directory': self.directory,
            'scale_objects': factor,
            'use_image_search': self.use_image_search,
            'use_collection': self.use_collection,
            'use_apply_matrix': self.use_apply_matrix,
            'object_filter': set(self.object_filter),
            'axis_forward': self.axis_forward,
            'axis_up': self.axis_up,
        }
        try:
            result = bpy.ops.import_scene.max(**keywords)
        except TypeError as e:
            # Some Blender versions reject 'files'/'directory' keywords.
            self.report({'ERROR'}, f"import_scene.max: {e}")
            keywords.pop('files', None)
            keywords.pop('directory', None)
            try:
                result = bpy.ops.import_scene.max(**keywords)
            except Exception as e2:
                self.report({'ERROR'}, f"import_scene.max: {e2}")
                return {'CANCELLED'}

        if 'FINISHED' in result:
            unit_desc = self._unit_desc(context, factor)
            self.report({'INFO'}, t("Imported with unit conversion") + f": {unit_desc}")
            return {'FINISHED'}
        return result

    def _unit_desc(self, context, factor):
        max_mpu = self._effective_meters_per_unit()
        blender_mpu = blender_meters_per_unit(context.scene)
        unit_name = unit_label(self.unit_choice if self.unit_choice != 'AUTO'
                               else (self._unit_info or {}).get('system_type', ''))
        return (f"1 {unit_name} = {max_mpu:.4f} m, "
                f"Blender 1 unit = {blender_mpu:.4f} m, "
                f"scale {factor:.6f}")

    # ============================================================
    # Confirmation dialog
    # ============================================================

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False

        info = self._unit_info
        blender_mpu = blender_meters_per_unit(context.scene)

        box = layout.box()
        fv = self._file_version_info
        if fv and fv.get('year'):
            box.label(
                text=t("File saved by 3ds Max {year} (v{ver})").format(
                    year=fv['year'], ver=fv['version']),
                icon='FILE_TICK',
            )
        if info and info.get('ok'):
            row = box.row()
            row.label(text=t("Detected Max file unit"), icon='CHECKMARK')
            detected = (f"1 unit = 1 {unit_label(info.get('system_type', ''))}"
                        f" (scale {info.get('system_scale', 1.0):g})")
            box.label(text=detected)
        else:
            row = box.row()
            row.alert = True
            row.label(text=t("Could not detect Max file unit"), icon='ERROR')
            if info and info.get('error'):
                box.label(text=str(info.get('error'))[:120])
            box.label(text=t("Please select the unit manually below."))

        box.separator()
        box.prop(self, "unit_choice")

        # Live preview of the conversion result.
        box.separator()
        max_mpu = self._effective_meters_per_unit()
        if max_mpu:
            factor = compute_scale_factor(max_mpu, blender_mpu)
            box.label(text=f"{t('Blender scene unit')}: 1 unit = {blender_mpu:.4f} m")
            box.label(text=f"{t('Scale factor')}: {factor:.6f}")
        else:
            box.label(text=t("Blender scene unit") + f": 1 unit = {blender_mpu:.4f} m")
            box.label(text=t("Select a unit to compute the scale factor."))

        # Pass-through options (collapsible).
        header, body = layout.panel("MAX_import_include", default_closed=True)
        header.label(text=t("Include"))
        if body:
            body.prop(self, "use_image_search")
            body.prop(self, "object_filter")
            body.prop(self, "use_collection")

        header2, body2 = layout.panel("MAX_import_transform", default_closed=True)
        header2.label(text=t("Transform"))
        if body2:
            body2.prop(self, "use_apply_matrix")
            body2.prop(self, "axis_forward")
            body2.prop(self, "axis_up")


def menu_func_import(self, context):
    self.layout.operator(
        IMPORT_OT_max_with_units.bl_idname,
        text="Autodesk MAX (.max) with Units",
    )


classes = (
    IMPORT_OT_max_with_units,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.TOPBAR_MT_file_import.append(menu_func_import)


def unregister():
    bpy.types.TOPBAR_MT_file_import.remove(menu_func_import)
    for cls in reversed(classes):
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass
