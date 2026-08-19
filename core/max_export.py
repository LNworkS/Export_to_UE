import bpy
import os
import re
import subprocess
import tempfile
import shutil
import threading

from ..i18n import t


# ============================================================
# Background conversion queue (3ds Max batch)
# ============================================================
#
# Design notes (why background queue instead of blocking):
# - The FBX export step (bpy.ops.export_scene.fbx) MUST run on the main
#   thread, so it stays synchronous: clicking "Save as .MAX" immediately
#   snapshots the current scene into an FBX (what you see is what you get).
# - The 3dsmaxbatch.exe conversion (10-300s) runs on a single background
#   worker thread, so Blender's UI stays responsive while converting.
# - Tasks are processed strictly one at a time (serial queue). Each task
#   snapshots the 3ds Max executable path & version at enqueue time, so a
#   running/queued task is never affected by later settings changes and the
#   .max file's origin version is always traceable.
# - Background threads NEVER touch bpy data. Results are pushed into a
#   thread-safe queue and applied to the UI by a main-thread timer.
# ============================================================

_MAX_TASK_QUEUE = []          # list of task dicts (main thread writes)
_MAX_TASK_LOCK = threading.Lock()
_MAX_RESULT_QUEUE = []        # list of result dicts (worker writes)
_MAX_RESULT_LOCK = threading.Lock()
_MAX_WORKER = None            # the single background worker thread


def _max_version_from_path(exe_path):
    """Extract a human-readable version tag from a 3dsmaxbatch.exe path.

    Examples:
        G:\\...\\3ds Max 2019\\3dsmaxbatch.exe  ->  "3ds Max 2019"
        ...\\3ds Max 2024\\...                  ->  "3ds Max 2024"
        anything else                           ->  "3ds Max"
    """
    m = re.search(r'3ds\s*Max\s*(\d{4})', exe_path, re.IGNORECASE)
    if m:
        return f"3ds Max {m.group(1)}"
    return "3ds Max"


def _run_task(task):
    """Execute one conversion task on the worker thread (no bpy access!).

    Returns a result dict.
    """
    exe_path = task['max_exe_path']
    script_path = task['script_path']
    log_path = task['log_path']
    output_path = task['output_path']
    tmp_dir = task['tmp_dir']
    max_version = task['max_version']

    ret_code, stdout, stderr = _run_3dsmax(exe_path, script_path, log_path)

    print(f"Save to .MAX: 3ds Max exit code: {ret_code} ({max_version})")
    if stdout:
        print(f"  stdout: {stdout[:1000]}")
    if stderr:
        print(f"  stderr: {stderr[:1000]}")

    if not os.path.isfile(output_path):
        # Keep temp dir on failure so user can inspect log + script.
        return {
            'success': False,
            'message': f"3ds Max conversion failed (exit={ret_code}, {max_version}). {t('See log for details')}: {log_path}",
            'tmp_dir': tmp_dir,
            'max_version': max_version,
            'output': output_path,
        }

    # Success: clean up temp files.
    try:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        print(f"Save to .MAX: Cleaned up temp dir: {tmp_dir}")
    except Exception as e:
        print(f"Save to .MAX: Warning - could not clean temp dir: {e}")

    return {
        'success': True,
        'message': f"{t('Saved: ')}{output_path} ({max_version})",
        'tmp_dir': tmp_dir,
        'max_version': max_version,
        'output': output_path,
    }


def _max_worker_loop():
    """Background worker: process queued conversion tasks one by one."""
    while True:
        with _MAX_TASK_LOCK:
            if not _MAX_TASK_QUEUE:
                break
            task = _MAX_TASK_QUEUE.pop(0)
        try:
            result = _run_task(task)
        except Exception as e:
            print(f"Save to .MAX: task crashed: {e}")
            result = {
                'success': False,
                'message': f"Save to .MAX error: {e}",
                'tmp_dir': task.get('tmp_dir', ''),
                'max_version': task.get('max_version', ''),
                'output': task.get('output_path', ''),
            }
        with _MAX_RESULT_LOCK:
            _MAX_RESULT_QUEUE.append(result)


def enqueue_max_task(fbx_path, script_path, log_path, tmp_dir, max_exe_path, output_path):
    """Enqueue a conversion task (call from main thread only).

    Snapshots the 3ds Max executable path + version tag at enqueue time so
    the task is independent of later settings changes.

    Returns:
        dict with 'max_version' and 'pending_count'.
    """
    global _MAX_WORKER
    task = {
        'fbx_path': fbx_path,
        'script_path': script_path,
        'log_path': log_path,
        'tmp_dir': tmp_dir,
        'max_exe_path': max_exe_path,
        'max_version': _max_version_from_path(max_exe_path),
        'output_path': output_path,
    }
    with _MAX_TASK_LOCK:
        _MAX_TASK_QUEUE.append(task)
        pending = len(_MAX_TASK_QUEUE)
        running = _MAX_WORKER is not None and _MAX_WORKER.is_alive()

    if not running:
        _MAX_WORKER = threading.Thread(
            target=_max_worker_loop,
            name="ExportToUE-MaxConverter",
            daemon=True,
        )
        _MAX_WORKER.start()

    return {
        'max_version': task['max_version'],
        'pending_count': pending,
    }


def drain_max_results():
    """Pop all finished results (call from the main-thread timer).

    Returns list of result dicts.
    """
    with _MAX_RESULT_LOCK:
        results = list(_MAX_RESULT_QUEUE)
        _MAX_RESULT_QUEUE.clear()
    return results


def get_max_queue_snapshot():
    """Return (state, pending_count, current_desc) for UI display.

    Call from the main thread. state is one of 'IDLE'/'RUNNING'/'QUEUED'.
    """
    with _MAX_TASK_LOCK:
        pending = len(_MAX_TASK_QUEUE)
        first = _MAX_TASK_QUEUE[0] if _MAX_TASK_QUEUE else None
    if pending == 0:
        return 'IDLE', 0, ""
    desc = os.path.basename(first['output_path'])
    return ('RUNNING' if pending == 1 else 'QUEUED'), max(0, pending - 1), desc


# ============================================================
# Object collection
# ============================================================

def _collect_export_objects(selected_only):
    """Collect mesh objects to export.

    Args:
        selected_only: bool - if True, only selected objects; else all scene objects

    Returns:
        list of MESH objects
    """
    if selected_only:
        objects = list(bpy.context.selected_objects)
    else:
        objects = list(bpy.data.objects)

    # Filter mesh objects (collisions are kept for completeness)
    return [obj for obj in objects if obj.type == 'MESH']


# ============================================================
# FBX intermediate export
# ============================================================

def _export_fbx_intermediate(objects, output_dir):
    """Export objects as intermediate FBX for 3ds Max import.

    Uses fixed FBX settings suitable for 3ds Max import:
    - Y forward, Z up (Blender default; no rotation applied, the .max file
      keeps the same orientation as the Blender file)
    - Apply unit scale (FBX carries unit info, Max reads it on import)
    - Include meshes only (no cameras, lights, animations)

    Args:
        objects: list of MESH objects to export
        output_dir: directory for the FBX file

    Returns:
        str: path to the FBX file, or None on failure
    """
    os.makedirs(output_dir, exist_ok=True)

    blend_name = bpy.path.basename(bpy.data.filepath) if bpy.data.filepath else "untitled.blend"
    base_name = os.path.splitext(blend_name)[0] or "blender_export"
    fbx_path = os.path.join(output_dir, f"{base_name}.fbx")

    # Save current selection state
    old_selection = [obj for obj in bpy.context.scene.objects if obj.select_get()]
    old_active = bpy.context.view_layer.objects.active

    try:
        bpy.ops.object.select_all(action='DESELECT')
        for obj in objects:
            obj.select_set(True)

        if objects:
            bpy.context.view_layer.objects.active = objects[0]

        bpy.ops.export_scene.fbx(
            filepath=fbx_path,
            use_selection=True,
            object_types={'MESH'},
            use_custom_props=True,
            mesh_smooth_type='OFF',  # 3ds Max will decide smoothing on import
            use_mesh_modifiers=True,
            add_leaf_bones=False,
            bake_anim=False,
            axis_forward='Y',
            axis_up='Z',
            use_space_transform=True,
            global_scale=1.0,
            apply_scale_options='FBX_SCALE_ALL',
        )
    finally:
        bpy.ops.object.select_all(action='DESELECT')
        for obj in old_selection:
            try:
                obj.select_set(True)
            except Exception:
                pass
        if old_active:
            try:
                bpy.context.view_layer.objects.active = old_active
            except Exception:
                pass

    return fbx_path if os.path.isfile(fbx_path) else None


# ============================================================
# MAXScript generation
# ============================================================

def _build_maxscript(fbx_path, max_save_path, blend_name):
    """Build a MAXScript that imports FBX, standardizes scene, saves .max.

    Standardization steps:
    1. Reset scene to empty
    2. Set units to centimeters (matches Blender default unit scale)
    3. Import FBX (let Max read unit/axis info from file)
    4. Reset XForm on all meshes (apply transform to mesh data)
    5. Normalize material names (lowercase, underscores)
    6. Delete unused materials
    7. Garbage collect
    8. Save .max file
    9. Quit

    Note: FBX importer options are kept minimal to avoid version-specific
    parameter name mismatches. The FBX file itself carries unit and axis
    info which Max reads on import. No rotation is applied: the .max file
    keeps the same orientation as the Blender file.
    """
    # Use forward slashes for MaxScript paths (more portable than escaped backslashes)
    fbx_path_ms = fbx_path.replace('\\', '/')
    max_save_path_ms = max_save_path.replace('\\', '/')

    script = f"""-- Auto-generated MAXScript for Save to .MAX conversion
-- Source blend: {blend_name}

-- Step 1: Reset scene to empty
resetMaxFile #noPrompt

-- Step 2: Configure unit system (centimeters, matches Blender default)
units.SystemType = #centimeters
units.DisplayType = #Metric
units.MetricType = #Centimeters

-- Step 3: Import FBX file
-- FBX file carries unit and axis info; Max reads it automatically.
-- #noPrompt suppresses the FBX import options dialog.
importFile "{fbx_path_ms}" #noPrompt

-- Step 4: Reset XForm on all mesh objects (apply transform to mesh data)
for obj in Geometry do (
    if isValidNode obj do (
        try (
            ResetXForm obj
            collapseStack obj
        ) catch ()
    )
)

-- Step 5: Normalize material names (lowercase, underscores for spaces/dashes/dots)
for m in sceneMaterials do (
    if m != undefined and m.name != undefined do (
        newName = m.name
        newName = substituteString newName " " "_"
        newName = substituteString newName "-" "_"
        newName = substituteString newName "." "_"
        newName = toLower newName
        if newName != "" and newName != m.name do (
            try ( m.name = newName ) catch ()
        )
    )
)

-- Step 6: Delete unused materials (not referenced by any Geometry object)
usedMats = #()
for obj in Geometry do (
    if isValidNode obj and obj.material != undefined do (
        appendIfUnique usedMats obj.material
    )
)
-- Collect materials to delete first (avoid modifying sceneMaterials while iterating)
matsToDelete = #()
for m in sceneMaterials do (
    if m != undefined and (findItem usedMats m) == 0 do (
        appendIfUnique matsToDelete m
    )
)
for m in matsToDelete do (
    try ( delete m ) catch ()
)

-- Step 7: Garbage collection
gc()

-- Step 8: Save .max file (use default version for max compatibility)
saveMaxFile "{max_save_path_ms}" quiet:true

-- Exit silently
quitMax #noPrompt
"""
    return script


# ============================================================
# 3ds Max batch invocation
# ============================================================

def _validate_3dsmaxbatch(max_exe_path):
    """Validate the user-configured 3dsmaxbatch.exe path.

    No auto-detection is performed: the 3ds Max version is a project
    requirement and is explicitly specified by the user in the settings.

    Args:
        max_exe_path: str - user-configured path to 3dsmaxbatch.exe

    Returns:
        str: validated absolute path, or None if not found/not configured
    """
    if not max_exe_path:
        return None
    # Resolve Blender relative paths (e.g. //foo, //../bar)
    abs_path = bpy.path.abspath(max_exe_path)
    if os.path.isfile(abs_path):
        return abs_path
    # Try as-is (already absolute)
    if os.path.isfile(max_exe_path):
        return max_exe_path
    return None


def _run_3dsmax(max_exe_path, script_path, log_path=None, timeout_sec=300):
    """Run 3dsmaxbatch.exe with the given script.

    3dsmaxbatch.exe syntax: 3dsmaxbatch.exe <script_file> [options]
    - script_file is a REQUIRED positional argument (not -script)
    - -log writes the 3ds Max system log (script errors/exceptions)
    - -v 5 enables debug-level logging for diagnostics

    Note: -safescene option is only available in 3ds Max 2022+. It is NOT
    passed here so the command works across all versions (2018+). The script
    uses only standard FBX import / ResetXForm / saveMaxFile commands which
    are not blocked by Safe Scene Script Execution.

    Args:
        max_exe_path: path to 3dsmaxbatch.exe
        script_path: path to MAXScript file (.ms)
        log_path: optional path for log output
        timeout_sec: timeout in seconds (default 300 = 5 minutes)

    Returns:
        tuple: (returncode: int, stdout: str, stderr: str)
    """
    cmd = [max_exe_path, script_path, '-v', '5']
    if log_path:
        cmd.extend(['-log', log_path])

    print(f"Save to .MAX: Running: {' '.join(cmd)}")

    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout_sec,
            shell=False,
        )
        return result.returncode, result.stdout or '', result.stderr or ''
    except subprocess.TimeoutExpired:
        return -1, '', f'Timeout after {timeout_sec}s'
    except FileNotFoundError:
        return -1, '', '3dsmaxbatch.exe not found'
    except Exception as e:
        return -1, '', str(e)


# ============================================================
# Path resolution
# ============================================================

def resolve_max_save_path(max_settings):
    """Compute the full .max output path from settings.

    Used by the operator's invoke() to check for file-overwrite before
    actually running the conversion.

    File-name rules:
    - "Use Blender File Name" checked  -> current blend file name
      (falls back to "untitled" when the blend is not saved yet).
    - unchecked -> the user-typed custom name (returns "" when it is
      empty; the operator validates this before calling).

    Args:
        max_settings: SaveToMaxPropertyGroup

    Returns:
        str: absolute path to the target .max file, or empty string if
             save_path is not configured / custom name is empty.
    """
    if not max_settings.max_save_path:
        return ""

    save_dir = bpy.path.abspath(max_settings.max_save_path)

    if getattr(max_settings, "use_blend_file_name", True):
        blend_path = bpy.data.filepath
        blend_name = bpy.path.basename(blend_path) if blend_path else "untitled.blend"
        file_name = os.path.splitext(blend_name)[0] or "blender_export"
    else:
        file_name = (max_settings.max_file_name or "").strip()
        if not file_name:
            return ""
    # Strip any extension the user may have typed (we add .max ourselves)
    file_name = os.path.splitext(file_name)[0]
    if not file_name:
        file_name = "blender_export"

    return os.path.join(save_dir, f"{file_name}.max")


# ============================================================
# Main entry point
# ============================================================

def do_save_to_max(max_settings, context):
    """Main entry: Blender objects -> FBX -> (background) 3ds Max -> .max file.

    Two-phase pipeline:
    Phase 1 (main thread, synchronous, fast):
      1. Validate settings (exe path, save path, objects to export)
      2. Export Blender objects as intermediate FBX to a temp dir — this
         snapshots the scene exactly as it is at click time.
      3. Generate MAXScript and enqueue the conversion with a snapshot of
         the 3ds Max executable path & version.
    Phase 2 (background worker thread, serial queue):
      4. Run 3dsmaxbatch.exe and verify the .max output.
      5. Clean up temp files on success (kept on failure for diagnosis).

    Because the FBX is exported synchronously and the conversion is queued
    per-click, repeated clicks while a conversion is running simply enqueue
    more tasks; each task converts its own FBX snapshot. The max version
    used by each task is the one configured at enqueue time and is reported
    in the task result.

    Args:
        max_settings: SaveToMaxPropertyGroup with max_exe_path, max_save_path,
                      max_file_name, max_selected_only
        context: bpy context

    Returns:
        tuple: (success: bool, message: str)
    """
    # ---- Validate 3ds Max executable (explicit user path, no auto-detect) ----
    max_exe_path = _validate_3dsmaxbatch(max_settings.max_exe_path)
    if not max_exe_path:
        return (False, t("3ds Max executable not found. Please configure 3dsmaxbatch.exe path in settings."))

    # ---- Validate save path ----
    if not max_settings.max_save_path:
        return (False, t("Please select a .max save path."))

    # ---- Validate file name (custom mode requires a non-empty name) ----
    if not getattr(max_settings, "use_blend_file_name", True):
        if not (max_settings.max_file_name or "").strip():
            return (False, t("Please enter a file name or enable Use Blender File Name."))

    save_dir = bpy.path.abspath(max_settings.max_save_path)
    try:
        os.makedirs(save_dir, exist_ok=True)
    except Exception as e:
        return (False, f"Cannot create save directory: {e}")

    max_save_path = resolve_max_save_path(max_settings)
    file_name = os.path.splitext(os.path.basename(max_save_path))[0]

    # ---- Collect objects ----
    objects = _collect_export_objects(max_settings.max_selected_only)
    if not objects:
        return (False, t("No objects to export."))

    print(f"Save to .MAX: Converting {len(objects)} object(s) to {file_name}.max")

    # ---- Phase 1: Export FBX to temp dir (main thread, synchronous snapshot) ----
    tmp_dir = tempfile.mkdtemp(prefix="blender_to_max_")
    print(f"Save to .MAX: Temp dir: {tmp_dir}")

    try:
        fbx_path = _export_fbx_intermediate(objects, tmp_dir)
        if not fbx_path:
            shutil.rmtree(tmp_dir, ignore_errors=True)
            return (False, t("FBX export failed."))

        print(f"Save to .MAX: FBX exported: {fbx_path}")

        # ---- Generate MAXScript ----
        script_path = os.path.join(tmp_dir, "convert_to_max.ms")
        script_content = _build_maxscript(fbx_path, max_save_path, file_name)
        with open(script_path, 'w', encoding='utf-8') as f:
            f.write(script_content)

        log_path = os.path.join(tmp_dir, "max_log.log")

        # ---- Enqueue conversion (background, serial queue) ----
        queued = enqueue_max_task(
            fbx_path=fbx_path,
            script_path=script_path,
            log_path=log_path,
            tmp_dir=tmp_dir,
            max_exe_path=max_exe_path,
            output_path=max_save_path,
        )

        return (True, t("Queued: ") + f"{file_name}.max ({queued['max_version']})")

    except Exception as e:
        # Unexpected error before enqueue - keep temp dir for diagnosis
        print(f"Save to .MAX: Unexpected error, temp dir kept: {tmp_dir}")
        return (False, f"Save to .MAX error: {e}. {t('See log for details')}: {tmp_dir}")
