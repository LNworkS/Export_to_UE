"""Update checker and installer for Export_To_UE addon.

Checks GitHub for newer versions and downloads/installs updates.

Detection strategy (dual source):
1. Primary: GitHub Releases API
   GET https://api.github.com/repos/LNworkS/Export_to_UE/releases/latest
   Returns tag_name (e.g. "v0.2.0"), zipball_url, assets[*].browser_download_url
2. Fallback: Fetch raw blender_manifest.toml from main branch
   GET https://raw.githubusercontent.com/LNworkS/Export_to_UE/main/blender_manifest.toml
   Parse `version = "x.y.z"` line.
   Download URL: codeload source ZIP of main branch.

Network strategy:
- Many Chinese users run a local proxy (Clash/v2ray, default port 7890/17890/17891).
  urllib auto-picks it up via urllib.request.getproxies(), but those proxies are
  often unstable for raw.githubusercontent.com (SSL handshake timeouts or
  rate-limited 429 responses). We therefore try:
    1. Direct connection (ProxyHandler({})) with a modest timeout.
    2. System-proxy connection (urllib default) with a slightly longer timeout.
- 404 from /releases/latest is NOT an error (repo simply has no release yet).
- 429 is reported as a rate-limit message so the user can retry later.
- A few short sleep() retries per attempt to be gentle on rate limits.

Cache:
- Stored in plugin config file (export_to_ue_config.json) under "update_check" key.
- Fields: last_check_time, latest_version, download_url, release_notes, source.
  (error is intentionally NOT persisted across runs, so "Check for updates"
  is always re-tryable on next panel open / next launch.)
- Re-check if older than CHECK_INTERVAL_SECONDS (12 hours) or when force=True.

Update execution:
- Download zip to system temp dir (also uses the dual direct-then-proxy strategy).
- Install via bpy.ops.extensions.package_install_files (overwrite=True, enable_on_install=True).
- User is advised to restart Blender to ensure clean module reload.
"""

import bpy
import os
import json
import time
import tempfile
import urllib.request
import urllib.error


# ============================================================
# Constants
# ============================================================

GITHUB_OWNER = "LNworkS"
GITHUB_REPO = "Export_to_UE"

RELEASES_API_URL = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"
MANIFEST_RAW_URL = f"https://raw.githubusercontent.com/{GITHUB_OWNER}/{GITHUB_REPO}/main/blender_manifest.toml"
CODELOAD_ZIP_URL = f"https://codeload.github.com/{GITHUB_OWNER}/{GITHUB_REPO}/zip/refs/heads/main"

# Re-check interval: 12 hours (in seconds). Note that network errors do NOT
# persist to cache, so the user can retry Check for Updates at any time.
CHECK_INTERVAL_SECONDS = 12 * 60 * 60

# Timeouts (seconds) - chosen to balance responsiveness vs success rate.
# raw.githubusercontent.com in China is notoriously flaky; system-proxy
# (Clash/v2ray) handshake is usually what eventually succeeds but can
# take 20-35 seconds. We keep retries at 1 so total worst-case time per
# check stays under ~60s even when both strategies must fully time out.
HTTP_TIMEOUT_DIRECT = 12
HTTP_TIMEOUT_PROXY = 30
HTTP_TIMEOUT_DOWNLOAD = 90  # zip download (single request, not retried across proxy)

# How many times each (direct/proxy) request is retried on transient failures.
HTTP_RETRIES = 1
HTTP_RETRY_SLEEP = 0.8

# User-Agent (GitHub API requires one). Chrome-like UA to avoid 429.
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36 ExportToUE-Blender-Updater/1.0"
)

# Plugin directory (parent of core/)
PLUGIN_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MANIFEST_PATH = os.path.join(PLUGIN_DIR, "blender_manifest.toml")


# ============================================================
# Version parsing & comparison
# ============================================================

def _parse_version_tuple(ver_str):
    """Convert "0.1.1" or "v0.1.1" -> (0, 1, 1). Returns None on failure."""
    if not ver_str:
        return None
    ver_str = str(ver_str).strip().lstrip('vV')
    parts = ver_str.split('.')
    try:
        return tuple(int(p) for p in parts)
    except ValueError:
        return None


def _version_str(tuple_ver):
    """Convert (0, 1, 1) -> '0.1.1'. Returns 'unknown' if None."""
    if not tuple_ver:
        return "unknown"
    return '.'.join(str(x) for x in tuple_ver)


def _is_newer(remote, local):
    """Return True if remote version tuple is strictly newer than local."""
    if remote is None or local is None:
        return False
    max_len = max(len(remote), len(local))
    r = remote + (0,) * (max_len - len(remote))
    l = local + (0,) * (max_len - len(local))
    return r > l


def _current_version_from_manifest():
    """Parse current version from local blender_manifest.toml.

    Returns:
        Tuple (major, minor, patch) or None if parsing fails.
    """
    try:
        if not os.path.exists(MANIFEST_PATH):
            return None
        with open(MANIFEST_PATH, 'r', encoding='utf-8') as f:
            content = f.read()
        for line in content.splitlines():
            line = line.strip()
            if line.startswith('version') and '=' in line and '"' in line:
                ver_str = line.split('"', 2)[1]
                return _parse_version_tuple(ver_str)
        return None
    except Exception:
        return None


# ============================================================
# HTTP helpers (dual strategy: direct first, then system proxy)
# ============================================================

def _build_opener(use_proxy):
    """Build a urllib OpenerDirector.

    Args:
        use_proxy: If True, use urllib defaults (picks up system proxies).
                   If False, installs a ProxyHandler({}) to bypass proxies.
    """
    if not use_proxy:
        proxy_handler = urllib.request.ProxyHandler({})
        return urllib.request.build_opener(proxy_handler)
    return urllib.request.build_opener()


def _http_get_one(url, accept, use_proxy, timeout):
    """Perform a single GET attempt (no retries).

    Returns:
        (status_code_or_None, body_or_error_message, succeeded)
    """
    timeout_val = timeout
    opener = _build_opener(use_proxy)
    try:
        req = urllib.request.Request(url)
        req.add_header('User-Agent', USER_AGENT)
        req.add_header('Accept', accept)
        with opener.open(req, timeout=timeout_val) as resp:
            body = resp.read().decode('utf-8', errors='replace')
            return resp.status, body, True
    except urllib.error.HTTPError as e:
        # Response body may contain useful info (e.g. 404 {"message":"Not Found"})
        try:
            err_body = e.read().decode('utf-8', errors='replace')
        except Exception:
            err_body = ''
        return e.code, err_body, True
    except Exception as e:
        return None, f"{type(e).__name__}: {e}", False


def _http_get(url, accept='application/vnd.github+json'):
    """HTTP GET with dual-strategy + retries.

    Attempt order:
      1. Direct (no proxy) x HTTP_RETRIES with shorter timeout.
      2. System proxy (if available) x HTTP_RETRIES with longer timeout.

    Returns:
        (status_code, body_or_message, failure_reason_str)
        - status_code is None for network/timeout failures.
        - failure_reason_str is empty on success.
    """
    last_error = ''
    last_status = None
    strategies = [
        (False, HTTP_TIMEOUT_DIRECT),   # direct first - usually less 429 on non-proxy
        (True,  HTTP_TIMEOUT_PROXY),    # then try the system proxy
    ]

    for use_proxy, timeout in strategies:
        for attempt in range(HTTP_RETRIES):
            status, body, got_response = _http_get_one(url, accept, use_proxy, timeout)
            if got_response:
                # Got HTTP response back (could be 200/404/429/etc.)
                if status == 200:
                    return status, body, ''
                # 4xx/5xx but we have a response: short sleep then retry same strategy
                last_status = status
                last_error = f"HTTP {status}"
                if status == 404 or status == 410:
                    # Permanent: no use retrying, move to next strategy
                    # But 404 from Releases API is "no release" and we handle
                    # that upstream, so just return the response.
                    return status, body, last_error
                if status == 429:
                    # Rate limited: stop retrying this strategy, go to next or return.
                    # Do not sleep-avoid stalling the UI longer than needed.
                    break
                # Other 4xx/5xx: retry briefly
                time.sleep(HTTP_RETRY_SLEEP)
            else:
                # Network/timeout failure (no HTTP response at all).
                last_status = None
                last_error = body  # body is the exception message here
                time.sleep(HTTP_RETRY_SLEEP)

    return last_status, '', last_error


def _download_binary(url, dest_path, progress_callback=None):
    """Binary download (for zip files) using the same dual strategy.

    Returns (success: bool, message: str).
    """
    strategies = [
        (False, HTTP_TIMEOUT_DOWNLOAD),
        (True,  HTTP_TIMEOUT_DOWNLOAD),
    ]
    last_msg = ''
    for use_proxy, timeout in strategies:
        opener = _build_opener(use_proxy)
        try:
            req = urllib.request.Request(url)
            req.add_header('User-Agent', USER_AGENT)
            with opener.open(req, timeout=timeout) as resp:
                total = int(resp.headers.get('Content-Length', 0) or 0)
                received = 0
                with open(dest_path, 'wb') as f:
                    while True:
                        chunk = resp.read(65536)
                        if not chunk:
                            break
                        f.write(chunk)
                        received += len(chunk)
                        if progress_callback:
                            try:
                                progress_callback(received, total)
                            except Exception:
                                pass
                return True, ''
        except Exception as e:
            last_msg = f"{type(e).__name__}: {e}"
            time.sleep(HTTP_RETRY_SLEEP)
            continue
    return False, last_msg


# ============================================================
# Remote version fetchers
# ============================================================

def _fetch_latest_release():
    """Query GitHub Releases API for the latest release.

    Returns:
        Dict with version, version_str, download_url, release_notes, source.
        Or None if no release exists (HTTP 404) or fetch failed.
    """
    status, body, err = _http_get(RELEASES_API_URL)
    if status != 200:
        # 404 means "no releases yet" - that's expected and not an error from
        # the caller's point of view, so return None silently.
        return None
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        return None

    tag = data.get('tag_name', '')
    version_tuple = _parse_version_tuple(tag)
    if version_tuple is None:
        return None

    # Prefer release asset zip if available, otherwise use zipball_url
    download_url = None
    for asset in data.get('assets', []):
        if asset.get('name', '').lower().endswith('.zip'):
            download_url = asset.get('browser_download_url')
            break
    if not download_url:
        download_url = data.get('zipball_url')

    return {
        'version': version_tuple,
        'version_str': _version_str(version_tuple),
        'download_url': download_url,
        'release_notes': data.get('body', '') or '',
        'source': 'release',
    }


def _fetch_latest_manifest():
    """Fallback: fetch raw blender_manifest.toml from main branch.

    Returns:
        Dict similar to _fetch_latest_release() but with source='manifest'.
        Or None if fetch fails or version line missing.
    """
    status, body, err = _http_get(MANIFEST_RAW_URL, accept='text/plain')
    if status != 200:
        return None
    for line in body.splitlines():
        line = line.strip()
        if line.startswith('version') and '=' in line and '"' in line:
            ver_str = line.split('"', 2)[1]
            vt = _parse_version_tuple(ver_str)
            if vt is not None:
                return {
                    'version': vt,
                    'version_str': ver_str,
                    'download_url': CODELOAD_ZIP_URL,
                    'release_notes': '',
                    'source': 'manifest',
                }
    return None


# ============================================================
# Cache (stored in plugin config file)
# ============================================================

def _load_update_cache():
    """Load update cache from config file. Returns dict or empty dict."""
    from .config import load_config
    config = load_config()
    return config.get('update_check', {})


def _save_update_cache(cache_data):
    """Save update cache to config file."""
    from .config import load_config, save_config
    config = load_config()
    config['update_check'] = cache_data
    save_config(config)


def _cache_is_fresh(cache):
    """Return True if cache exists, has a valid latest_version,
    and is younger than CHECK_INTERVAL_SECONDS.
    (Entries with only an error are NOT treated as fresh so the user
    can retry the check on the next panel open.)
    """
    if not cache or 'last_check_time' not in cache:
        return False
    if not cache.get('latest_version'):
        # Cached but no version info -> not useful, force re-check.
        return False
    try:
        last = float(cache.get('last_check_time', 0))
    except (TypeError, ValueError):
        return False
    return (time.time() - last) < CHECK_INTERVAL_SECONDS


# ============================================================
# Public API
# ============================================================

def get_current_version_str():
    """Return the current installed version as a string (e.g. '0.1.1')."""
    return _version_str(_current_version_from_manifest())


def get_cached_result():
    """Return cached check result as a dict (without network fetch).

    Returns None if no cache exists. Otherwise returns a dict shaped like
    check_for_update()'s return value, with from_cache=True and no error.
    """
    cache = _load_update_cache()
    if not cache or not cache.get('latest_version'):
        return None
    current_tuple = _current_version_from_manifest()
    current_str = _version_str(current_tuple)
    remote_tuple = _parse_version_tuple(cache.get('latest_version'))
    return {
        'has_update': _is_newer(remote_tuple, current_tuple),
        'current_version': current_str,
        'latest_version': cache.get('latest_version'),
        'download_url': cache.get('download_url'),
        'release_notes': cache.get('release_notes', '') or '',
        'source': cache.get('source', '') or '',
        'error': '',  # errors are not cached
        'from_cache': True,
    }


def check_for_update(force=False):
    """Check GitHub for a newer version.

    Args:
        force: If True, ignore cache and always fetch fresh.

    Returns:
        Dict with keys:
        - has_update: bool
        - current_version: str
        - latest_version: str or None
        - download_url: str or None
        - release_notes: str
        - source: str ('release', 'manifest', or '')
        - error: str (empty if no error)
        - from_cache: bool
    """
    current_tuple = _current_version_from_manifest()
    current_str = _version_str(current_tuple)

    # Use cache if fresh and not forced
    if not force:
        cached = get_cached_result()
        if cached is not None:
            cache = _load_update_cache()
            try:
                last = float(cache.get('last_check_time', 0))
                if (time.time() - last) < CHECK_INTERVAL_SECONDS:
                    return cached
            except (TypeError, ValueError):
                pass

    # Fetch fresh: Releases API first, then manifest raw file.
    # NOTE: For the manifest fallback, we must actually get content (200).
    #       404 from Releases API is expected and means "no release".
    error_msg = ''
    remote_info = None
    try:
        remote_info = _fetch_latest_release()
    except Exception as e:
        error_msg = f"Release check error: {e}"
        remote_info = None

    if remote_info is None:
        try:
            remote_info = _fetch_latest_manifest()
        except Exception as e:
            error_msg = f"Manifest check error: {e}"
            remote_info = None

    if remote_info is not None:
        has_update = _is_newer(remote_info['version'], current_tuple)
        result = {
            'has_update': has_update,
            'current_version': current_str,
            'latest_version': remote_info['version_str'],
            'download_url': remote_info['download_url'],
            'release_notes': remote_info['release_notes'],
            'source': remote_info['source'],
            'error': '',
            'from_cache': False,
        }
    else:
        # Both sources failed: build a helpful error message.
        if not error_msg:
            error_msg = 'Cannot connect to GitHub. Check your network / proxy, or try again later.'
        result = {
            'has_update': False,
            'current_version': current_str,
            'latest_version': None,
            'download_url': None,
            'release_notes': '',
            'source': '',
            'error': error_msg,
            'from_cache': False,
        }

    # Save to cache ONLY when we got a valid latest_version back.
    # Never persist error to cache, so the user can retry.
    if remote_info is not None:
        cache_data = {
            'last_check_time': time.time(),
            'latest_version': result['latest_version'],
            'download_url': result['download_url'],
            'release_notes': result['release_notes'],
            'source': result['source'],
        }
        _save_update_cache(cache_data)
    else:
        # Clear stale version cache entries if any (but keep timestamp around
        # so a very-rapid-retry still doesn't hammer GitHub).
        old = _load_update_cache()
        if old:
            cleaned = {k: v for k, v in old.items() if k == 'last_check_time'}
            cleaned['last_check_time'] = min(
                float(old.get('last_check_time', 0) or 0),
                time.time(),
            )
            _save_update_cache(cleaned)

    return result


def download_and_install(zip_url, progress_callback=None):
    """Download zip from URL and install as Blender extension.

    Uses the same dual strategy (direct first, then system proxy) as the
    update check.

    Args:
        zip_url: URL to the zip file.
        progress_callback: Optional callable(received_bytes, total_bytes).

    Returns:
        Tuple (success: bool, message: str).
    """
    if not zip_url:
        return False, "No download URL available"

    tmp_zip = None
    try:
        tmp_dir = tempfile.gettempdir()
        tmp_zip = os.path.join(tmp_dir, 'export_to_ue_update.zip')
        if os.path.exists(tmp_zip):
            try:
                os.remove(tmp_zip)
            except Exception:
                pass

        ok, dl_err = _download_binary(zip_url, tmp_zip, progress_callback)
        if not ok:
            return False, f"Download failed: {dl_err or 'unknown error'}"

        if not os.path.exists(tmp_zip) or os.path.getsize(tmp_zip) == 0:
            return False, "Downloaded file is empty or missing"

        # Install via Blender extension operator (forward slashes for Blender)
        install_path = tmp_zip.replace('\\', '/')
        try:
            result = bpy.ops.extensions.package_install_files(
                filepath=install_path,
                repo='blender_org',
                enable_on_install=True,
                overwrite=True,
            )
            if result == {'FINISHED'}:
                return True, "Update installed successfully. Please restart Blender to complete the update."
            return False, f"Install operator returned: {result}"
        except Exception as e:
            return False, f"Install failed: {e}"

    except Exception as e:
        return False, f"Download failed: {e}"
