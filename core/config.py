import os
import json


# Plugin directory
PLUGIN_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_FILE = os.path.join(PLUGIN_DIR, "export_to_ue_config.json")


def load_config():
    """Load configuration from JSON file in plugin directory.
    
    Returns a dict with saved settings, or empty dict if file doesn't exist.
    """
    if not os.path.exists(CONFIG_FILE):
        return {}
    
    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            config = json.load(f)
        return config
    except (json.JSONDecodeError, IOError):
        return {}


def save_config(config_dict):
    """Save configuration to JSON file in plugin directory.
    
    Args:
        config_dict: dict containing settings to persist
    """
    try:
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
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
