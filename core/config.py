import os
import json
import shutil

# Plugin directory (parent of core/)
PLUGIN_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Legacy config location: plugin install dir. Overwritten when the extension
# is updated, so we migrated to the user config dir instead.
_LEGACY_CONFIG_FILE = os.path.join(PLUGIN_DIR, "export_to_ue_config.json")


def get_config_path():
    """Return the config file path in the user config directory.

    Uses bpy.utils.user_resource('CONFIG') so settings survive extension
    updates (the plugin dir gets replaced on update).
    """
    try:
        import bpy
        config_dir = bpy.utils.user_resource('CONFIG')
    except Exception:
        config_dir = os.path.join(os.path.expanduser("~"), "AppData", "Roaming", "Blender Foundation", "Blender")
    return os.path.join(config_dir, "export_to_ue_config.json")


def load_config():
    """Load configuration from JSON file.

    Reads from the user config dir. On first run, migrates the legacy config
    (previously stored in the plugin install dir) so no settings are lost.

    Returns a dict with saved settings, or empty dict if file doesn't exist.
    """
    config_path = get_config_path()
    if not os.path.exists(config_path):
        # First run with the new location: migrate legacy config if present.
        if os.path.exists(_LEGACY_CONFIG_FILE):
            try:
                with open(_LEGACY_CONFIG_FILE, 'r', encoding='utf-8') as f:
                    legacy = json.load(f)
                if isinstance(legacy, dict):
                    save_config(legacy)
                    print(f"Export to UE: migrated config from {_LEGACY_CONFIG_FILE}")
                    return legacy
            except (json.JSONDecodeError, IOError) as e:
                print(f"Export to UE: could not migrate legacy config: {e}")
        return {}

    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
        return config if isinstance(config, dict) else {}
    except (json.JSONDecodeError, IOError):
        return {}


def save_config(config_dict):
    """Save configuration to JSON file in the user config dir.

    Args:
        config_dict: dict containing settings to persist
    """
    config_path = get_config_path()
    try:
        os.makedirs(os.path.dirname(config_path), exist_ok=True)
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(config_dict, f, indent=2, ensure_ascii=False)
    except IOError as e:
        print(f"Export to UE: Failed to save config: {e}")


def get_saved_export_path():
    """Get the saved export path from config file.

    Returns empty string if no valid path is saved.
    """
    config = load_config()
    path = config.get("export_path", "")
    # Only return non-empty paths
    return path if path else ""


def save_export_path(path):
    """Save the export path to config file.

    Args:
        path: str - the export directory path to save
    """
    config = load_config()
    config["export_path"] = path
    save_config(config)


# ============================================================
# Save to .MAX settings
# ============================================================

def get_saved_max_exe_path():
    """Get the saved 3dsmaxbatch.exe path from config file.

    Returns empty string if no valid path is saved.
    """
    config = load_config()
    max_cfg = config.get('max_settings', {})
    return max_cfg.get('max_exe_path') or config.get('max_exe_path', '')


def save_max_exe_path(path):
    """Save the 3dsmaxbatch.exe path to config file.

    Args:
        path: str - the 3dsmaxbatch.exe path to save
    """
    config = load_config()
    if 'max_settings' not in config:
        config['max_settings'] = {}
    config['max_settings']['max_exe_path'] = path
    save_config(config)


# NOTE (0.2.0): the .max save path and custom file name are no longer stored
# in the plugin config. They live in the .blend file (Scene properties) so
# each blend keeps its own values and new scenes start with empty fields.
