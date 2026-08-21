"""Read the 3ds Max version embedded in a .max file and match it against
locally installed 3ds Max versions.

Why binary parsing instead of launching 3dsmaxbatch:
- A .max file is an OLE2 compound document. Its streams contain plain-ASCII
  markers ``3ds Max Version: <float>``, ``Saved As Version: <float>`` and
  ``Build: <x.y.z.w>`` that record the version that LAST saved the file.
  Verified experimentally: files re-saved by a newer 3ds Max carry the new
  version (e.g. the presets shipped with the 3ds Max 2024 install are
  v25 = saved by 3ds Max 2023, while the 2019 install ships the same-named
  presets at v16 = 3ds Max 2014; a file saved on this machine by 3ds Max
  2019 reads 21.00 / Build 21.0.0.845, matching the official product
  version string "3ds Max 2019 (21.0.0.845)").
- Launching 3dsmaxbatch costs 20+ seconds; parsing the binary is ~1 ms and
  needs no 3ds Max installation at all.

Version model:
- 3ds Max internal version N maps to year N + 1998 (21 -> 2019, 26 -> 2024).
- Compatibility: newer 3ds Max opens older .max files, but an older one
  cannot open a newer file. So for a file saved at version F we want the
  closest installed version with year >= F.year.
"""

import glob
import os
import re

# Path patterns probed for installed 3ds Max (same drives as max_units.py).
_MAX_DIR_PATTERNS = []
for drive in 'CDEFGH':
    _MAX_DIR_PATTERNS.extend([
        f"{drive}:\\Program Files\\Autodesk\\3ds Max *\\3dsmaxbatch.exe",
        f"{drive}:\\Program Files (x86)\\Autodesk\\3ds Max *\\3dsmaxbatch.exe",
        f"{drive}:\\3ds Max *\\3dsmaxbatch.exe",
        f"{drive}:\\Autodesk\\3ds Max *\\3dsmaxbatch.exe",
    ])

# Marker strings found as plain ASCII inside the OLE2 streams of .max files.
_MAX_VERSION_RE = re.compile(rb'3ds Max Version:\s*([0-9]+(?:\.[0-9]+)?)')
_SAVED_AS_RE = re.compile(rb'Saved As Version:\s*([0-9]+(?:\.[0-9]+)?)')
_BUILD_RE = re.compile(rb'Build:\s*([0-9]+(?:\.[0-9]+){0,3})')

# Installed dir names like "3ds Max 2019" / "3ds Max 2024".
_INSTALL_YEAR_RE = re.compile(r'3ds Max (\d{4})', re.IGNORECASE)

# The template scene.max files Autodesk ships with every version are
# byte-identical and carry the odd version 19.90 / Build 20.0.806.0. Real
# user files always have the version of the last saving application, so a
# template-like marker is treated as "unknown".
_TEMPLATE_LIKE = {19.9}


def _is_valid_exe(path):
    """True when the path is an existing, non-empty executable file."""
    try:
        return bool(path) and os.path.isfile(path) and os.path.getsize(path) > 0
    except OSError:
        return False


def _parse_float(raw):
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def version_to_year(version):
    """Year for a 3ds Max internal version number (N + 1998), or None."""
    v = _parse_float(version)
    if v is None:
        return None
    year = int(v) + 1998
    if 2000 <= year <= 2100:
        return year
    return None


def read_max_file_version(path):
    """Read the version markers from a .max file without launching 3ds Max.

    Args:
        path: absolute path to a .max file.

    Returns a dict:
        version     float ('3ds Max Version') or None
        saved_as    float ('Saved As Version') or None
        build       str   ('Build') or ''
        year        int   mapped from `version`, or None
        error       str   when the file is unreadable / not a .max file
    The dict is always returned; check `error` first.
    """
    result = {
        'version': None, 'saved_as': None, 'build': '',
        'year': None, 'error': '',
    }
    if not os.path.isfile(path):
        result['error'] = 'File not found'
        return result
    try:
        with open(path, 'rb') as f:
            data = f.read()
        version_m = _MAX_VERSION_RE.search(data)
        saved_m = _SAVED_AS_RE.search(data)
        build_m = _BUILD_RE.search(data)
    except (OSError, ValueError) as e:
        result['error'] = str(e)
        return result

    version = _parse_float(version_m.group(1)) if version_m else None
    saved_as = _parse_float(saved_m.group(1)) if saved_m else None
    build = build_m.group(1).decode('ascii', errors='replace') if build_m else ''

    # A template-like marker is not a real user-file version.
    version = None if version in _TEMPLATE_LIKE else version
    result['version'] = version
    result['saved_as'] = saved_as
    result['build'] = build
    result['year'] = version_to_year(version)
    return result


def detect_installed_max_versions():
    """Scan common install locations for every 3dsmaxbatch.exe.

    Returns a list of dicts (sorted by year, oldest first):
        {'path': <exe path>, 'year': <int>, 'version': <int>}
    Empty list when none found.
    """
    found = {}
    for pattern in _MAX_DIR_PATTERNS:
        try:
            matches = glob.glob(pattern)
        except Exception:
            continue
        for match in matches:
            m = _INSTALL_YEAR_RE.search(match)
            if not m:
                continue
            try:
                year = int(m.group(1))
            except ValueError:
                continue
            if not (2000 <= year <= 2100):
                continue
            if _is_valid_exe(match):
                found[match] = {
                    'path': match,
                    'year': year,
                    'version': year - 1998,
                }
    return sorted(found.values(), key=lambda d: d['year'])


def pick_3dsmax_for_file(installed, file_version):
    """Pick the closest installed version >= file_version.

    Args:
        installed: list from detect_installed_max_versions()
        file_version: internal version (float/int) read from the .max file

    Returns an entry dict, or None when every installed version is older
    than the file (i.e. the file cannot be opened on this computer).
    """
    target = version_to_year(file_version)
    if target is None:
        return None
    best = None
    for entry in installed:
        if entry['year'] >= target:
            if best is None or entry['year'] < best['year']:
                best = entry
    return best
