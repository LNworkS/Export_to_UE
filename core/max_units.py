"""Read unit settings from a .max file via 3dsmaxbatch.exe.

Why 3dsmaxbatch instead of binary parsing:
- The .max binary format stores the File Unit Scale but not as readable
  text; two reference parsers (builtin io_scene_max and Importer3D) do not
  read units at all.
- 3dsmaxbatch.exe + MaxScript CAN read it reliably: loading with
  `loadMaxFile <file> quiet:true useFileUnits:true` adopts the file's
  system units, after which `units.SystemType` / `units.SystemScale`
  report exactly what the file was created with (verified by experiment).
- `useFileUnits:true` also skips the "Units Mismatch" dialog that the
  interactive 3ds Max shows, so batch runs are fully automatic.

Unit model:
- 3ds Max "System Unit" = the physical size of 1 generic unit.
  SystemType: millimeters/centimeters/meters/kilometers/inches/feet/miles
  SystemScale: multiplier for the base type (1.0 for standard types).
- Blender: 1 Blender unit = scene.unit_settings.scale_length meters.
- Import scale factor = max_meters_per_unit / blender_meters_per_unit,
  passed to the builtin importer's `scale_objects` argument.
"""

import os
import re
import shutil
import subprocess
import tempfile

from ..i18n import t
from .max_version import detect_installed_max_versions


# Base meters for each 3ds Max System Unit type (1 unit = X meters).
_MAX_BASE_METERS = {
    'millimeters': 0.001,
    'centimeters': 0.01,
    'meters': 1.0,
    'kilometers': 1000.0,
    'inches': 0.0254,
    'feet': 0.3048,
    'miles': 1609.344,
}

# Human-readable labels for the unit choice dropdown / reports.
_UNIT_LABELS = {
    'millimeters': "Millimeters",
    'centimeters': "Centimeters",
    'meters': "Meters",
    'kilometers': "Kilometers",
    'inches': "Inches",
    'feet': "Feet",
    'miles': "Miles",
}


def unit_label(unit_type):
    """English label for a Max unit type (used in reports/UI)."""
    return _UNIT_LABELS.get(unit_type, unit_type or "?")


def meters_per_unit_from_type(system_type, system_scale=1.0):
    """Meters per 1 system unit for a Max unit type, or None if unknown."""
    base = _MAX_BASE_METERS.get(system_type)
    if base is None:
        return None
    try:
        return base * float(system_scale)
    except (TypeError, ValueError):
        return base


def _is_valid_exe(path):
    """True when the path is an existing, non-empty executable file."""
    try:
        return bool(path) and os.path.isfile(path) and os.path.getsize(path) > 0
    except OSError:
        return False


def find_3dsmaxbatch():
    """Locate a usable 3dsmaxbatch.exe.

    Priority:
    1. The path configured in the Save as .Max panel (plugin settings).
       A configured path that is missing or empty (0 bytes, e.g. a stale
       placeholder) is ignored and falls through to auto-detection.
    2. Auto-detected installs, choosing the NEWEST version (multiple 3ds
       Max installs are common; an older exe cannot open newer .max files).

    Returns an absolute path string, or None when not found.
    """
    # 1) User-configured path (plugin settings / config.json)
    try:
        import bpy
        scene = bpy.context.scene
        if scene is not None and hasattr(scene, 'save_to_max_settings'):
            cfg = scene.save_to_max_settings.max_exe_path
            if cfg:
                abs_path = bpy.path.abspath(cfg)
                if _is_valid_exe(abs_path):
                    return abs_path
                if _is_valid_exe(cfg):
                    return cfg
    except Exception:
        pass

    # 2) Auto-detect: newest installed version (read-only probe).
    installed = detect_installed_max_versions()
    if installed:
        return installed[-1]['path']
    return None


def find_all_3dsmaxbatch():
    """All usable 3dsmaxbatch.exe installs, best first.

    The user-configured path (when valid) comes first, then every
    auto-detected install sorted newest to oldest. Each entry is a dict:
        {'path': <exe>, 'year': <int>, 'version': <int>}
    Returns an empty list when nothing is usable.
    """
    entries = []
    seen = set()
    try:
        import bpy
        scene = bpy.context.scene
        if scene is not None and hasattr(scene, 'save_to_max_settings'):
            cfg = scene.save_to_max_settings.max_exe_path
            for candidate in (bpy.path.abspath(cfg) if cfg else '', cfg or ''):
                if candidate and _is_valid_exe(candidate):
                    entries.append({'path': candidate, 'year': 0, 'version': 0})
                    seen.add(candidate)
                    break
    except Exception:
        pass
    for entry in reversed(detect_installed_max_versions()):
        if entry['path'] not in seen:
            entries.append(entry)
    return entries


# ============================================================
# MaxScript execution
# ============================================================

def _build_script(max_file_ascii, result_file):
    """MaxScript that loads the .max with file units and writes the units.

    Notes:
    - Top-level `local` is illegal under 3dsmaxbatch (scripts run via
      filein), so everything is wrapped in a (...) block.
    - The .max path must be ASCII (Chinese paths break GBK parsing), the
      caller copies the file to a temp dir.
    - Results go to a file, not stdout (format writes to the Listener and
      the batch stdout is UTF-16/noisy).
    - useFileUnits:true adopts the file's system units and skips the
      "Units Mismatch" dialog.
    """
    return r'''(
    local maxFile = @"{max_file}"
    local resFile = @"{result_file}"
    local ok = loadMaxFile maxFile quiet:true useFileUnits:true
    local f = createfile resFile
    if ok then (
        format "OK SystemType=% SystemScale=% DisplayType=%\n" (units.SystemType as string) (units.SystemScale as string) (units.DisplayType as string) to:f
        -- meters per unit, computed by 3ds Max itself (cross-check)
        local mpu = -1.0
        try (
            mpu = ((100.0 as system) as meters) / 100.0
        ) catch (
            mpu = -1.0
        )
        format "MetersPerUnit=%\n" mpu to:f
    ) else (
        format "FAILED\n" to:f
    )
    close f
    quitMAX #noPrompt
)
'''.format(max_file=max_file_ascii, result_file=result_file)


def _run_3dsmax(max_exe, script_path, timeout_sec=120):
    """Run 3dsmaxbatch.exe with the given script; returns (rc, out, err)."""
    cmd = [max_exe, script_path, '-v', '5']
    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout_sec,
            shell=False,
        )
        return result.returncode, (result.stdout or b''), (result.stderr or b'')
    except subprocess.TimeoutExpired:
        return -1, b'', f"Timeout after {timeout_sec}s".encode()
    except FileNotFoundError:
        return -1, b'', b'3dsmaxbatch.exe not found'
    except Exception as e:
        return -1, b'', str(e).encode('utf-8', errors='replace')


def _parse_result(text):
    """Parse the result file written by the MaxScript.

    Returns a dict:
        ok              bool
        system_type     str ('centimeters', ...) or ''
        system_scale    float
        display_type    str or ''
        meters_per_unit float or None (None when unknown/custom)
        error           str
    """
    info = {
        'ok': False,
        'system_type': '',
        'system_scale': 1.0,
        'display_type': '',
        'meters_per_unit': None,
        'error': '',
    }
    if 'FAILED' in text and 'OK SystemType=' not in text:
        info['error'] = t("Failed to load the .max file")
        return info
    m = re.search(
        r'OK SystemType=(\S+)\s+SystemScale=([\d.eE+-]+)\s+DisplayType=(\S+)',
        text,
    )
    if not m:
        info['error'] = t("Unexpected MaxScript output")
        return info
    info['ok'] = True
    info['system_type'] = m.group(1).lower()
    try:
        info['system_scale'] = float(m.group(2))
    except ValueError:
        info['system_scale'] = 1.0
    info['display_type'] = m.group(3)
    mm = re.search(r'MetersPerUnit=([\d.eE+-]+)', text)
    if mm:
        try:
            val = float(mm.group(1))
            if val > 0:
                info['meters_per_unit'] = val
        except ValueError:
            pass
    if info['meters_per_unit'] is None:
        info['meters_per_unit'] = meters_per_unit_from_type(
            info['system_type'], info['system_scale']
        )
    if info['meters_per_unit'] is None:
        info['error'] = t("Unsupported unit type")
    return info


def read_max_file_units(max_file, max_exe=None, timeout_sec=120):
    """Read the system units stored in a .max file.

    Args:
        max_file: absolute path to the .max file
        max_exe: optional 3dsmaxbatch.exe path (auto-detected when None)
        timeout_sec: subprocess timeout

    Returns:
        dict as _parse_result(); when 3dsmaxbatch is unavailable, returns
        {'ok': False, 'error': <message>, ...}.
    """
    if not os.path.isfile(max_file):
        return {
            'ok': False, 'system_type': '', 'system_scale': 1.0,
            'display_type': '', 'meters_per_unit': None,
            'error': t("File not found"),
        }
    if max_exe is None:
        max_exe = find_3dsmaxbatch()
    if not max_exe or not os.path.isfile(max_exe):
        return {
            'ok': False, 'system_type': '', 'system_scale': 1.0,
            'display_type': '', 'meters_per_unit': None,
            'error': t("3ds Max not found. Please select the unit manually."),
        }

    tmp_dir = tempfile.mkdtemp(prefix='etue_maxunits_')
    try:
        # Chinese paths break the GBK-encoded MaxScript; copy to ASCII temp.
        ext = os.path.splitext(max_file)[1] or '.max'
        ascii_max = os.path.join(tmp_dir, 'input' + ext)
        shutil.copy2(max_file, ascii_max)
        result_file = os.path.join(tmp_dir, 'units_result.txt')
        script_path = os.path.join(tmp_dir, 'read_units.ms')
        script = _build_script(ascii_max, result_file)
        with open(script_path, 'w', encoding='gbk') as f:
            f.write(script)

        rc, out, err = _run_3dsmax(max_exe, script_path, timeout_sec)
        print(f"Import MAX: unit probe exit={rc}")
        if not os.path.isfile(result_file):
            return {
                'ok': False, 'system_type': '', 'system_scale': 1.0,
                'display_type': '', 'meters_per_unit': None,
                'error': t("3ds Max failed to read the file"),
            }
        with open(result_file, 'r', encoding='utf-8', errors='replace') as f:
            text = f.read()
        return _parse_result(text)
    except Exception as e:
        return {
            'ok': False, 'system_type': '', 'system_scale': 1.0,
            'display_type': '', 'meters_per_unit': None,
            'error': str(e),
        }
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def read_max_file_units_best(max_file, candidates=None, timeout_sec=120):
    """Read units, trying several 3dsmaxbatch.exe installs in order.

    Each candidate is tried until one reports a valid unit. When a
    candidate fails to load the file (e.g. the .max file is newer than
    that 3ds Max), the next one is attempted instead of giving up.

    Args:
        max_file: absolute path to the .max file
        candidates: ordered list of exe paths (default: every detected
            install, newest first; user-configured path first when valid)
        timeout_sec: per-attempt subprocess timeout

    Returns:
        dict as _parse_result(). `ok` True on the first success. When all
        candidates fail, the LAST result is returned with `error` appended
        a note about how many installs were tried.
    """
    if not candidates:
        candidates = [e['path'] for e in find_all_3dsmaxbatch()]
    if not candidates:
        return {
            'ok': False, 'system_type': '', 'system_scale': 1.0,
            'display_type': '', 'meters_per_unit': None,
            'error': t("3ds Max not found. Please select the unit manually."),
        }
    last = None
    for exe in candidates:
        last = read_max_file_units(max_file, exe, timeout_sec)
        if last.get('ok'):
            return last
    if last is None:
        last = {
            'ok': False, 'system_type': '', 'system_scale': 1.0,
            'display_type': '', 'meters_per_unit': None,
            'error': t("Failed to read the .max file"),
        }
    elif len(candidates) > 1:
        note = t("Tried {n} 3ds Max install(s)").format(n=len(candidates))
        last['error'] = f"{last.get('error', '')} ({note})".strip()
    return last


# ============================================================
# Scale computation
# ============================================================

def blender_meters_per_unit(scene):
    """Meters per 1 Blender unit for a scene (1 BU = scale_length m)."""
    try:
        return float(scene.unit_settings.scale_length)
    except Exception:
        return 1.0


def compute_scale_factor(max_meters_per_unit, blender_meters_per_unit_):
    """Import scale factor: max units -> blender units.

    factor = max_meters_per_unit / blender_meters_per_unit
    Example: max file in cm (0.01 m/unit), Blender in m (1.0 m/unit)
        -> factor = 0.01 (a 100 cm model becomes 1.0 Blender unit).
    """
    if not max_meters_per_unit or max_meters_per_unit <= 0:
        return 1.0
    if not blender_meters_per_unit_ or blender_meters_per_unit_ <= 0:
        return 1.0
    return max_meters_per_unit / blender_meters_per_unit_
