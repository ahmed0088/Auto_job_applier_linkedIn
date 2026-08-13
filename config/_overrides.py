'''
Author:     Sai Vignesh Golla
License:    MIT License
            https://opensource.org/license/mit
GitHub:     https://github.com/GodsScion/Auto_job_applier_linkedIn

Loads user settings saved by the local control panel (see app.py) from
`user_config.json` at the project root, and applies them over the Python
defaults defined in the config/*.py files.

If `user_config.json` does not exist, everything here is a no-op and the tool
behaves exactly as it always has: configuration comes entirely from the
config/*.py defaults. This keeps the classic "edit the .py files" workflow
fully working for existing users.

------------------------------------------------------------------------------
Profiles (multiple accounts, one installation)

The control panel can manage more than one named profile (e.g. to run this
tool for a friend's LinkedIn account too) without duplicating the project.
Which profile is active is controlled by the AUTO_APPLIER_PROFILE environment
variable, which app.py sets before launching runAiBot.py as a subprocess.

- The "default" profile (or no env var set at all) behaves EXACTLY as before:
  `user_config.json` at the project root, application history in
  `all excels/`, logs in `logs/`. Nothing changes for existing users.
- Any other profile name gets its own `profiles/<name>/` folder, with its own
  user_config.json, application history CSVs, and logs - fully isolated from
  the default profile and every other profile. This is applied automatically
  here so individual profile JSON files never need to know their own paths.
------------------------------------------------------------------------------
'''

import os
import json

# This file lives in <project_root>/config/, so the project root is one level up.
_CONFIG_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT_DIR = os.path.dirname(_CONFIG_DIR)
PROFILES_DIR = os.path.join(_ROOT_DIR, "profiles")
DEFAULT_PROFILE = "default"

# Kept for backwards compatibility - this is still exactly what the "default"
# profile uses.
USER_CONFIG_PATH = os.path.join(_ROOT_DIR, "user_config.json")


def active_profile_name() -> str:
    '''Returns the active profile name from AUTO_APPLIER_PROFILE, or "default".'''
    name = (os.environ.get("AUTO_APPLIER_PROFILE") or "").strip()
    return name or DEFAULT_PROFILE


def profile_dir(name: str) -> str:
    '''Returns the storage folder for a (non-default) profile.'''
    return os.path.join(PROFILES_DIR, name)


def user_config_path_for(name: str) -> str:
    '''Returns the user_config.json path for the given profile name.'''
    if name == DEFAULT_PROFILE:
        return USER_CONFIG_PATH
    return os.path.join(profile_dir(name), "user_config.json")


def load_user_config(profile: str = None) -> dict:
    '''
    Returns the full override dictionary for `profile`'s user_config.json (or
    the AUTO_APPLIER_PROFILE-active profile if `profile` isn't given), or an
    empty dict if it's missing, unreadable, or not valid JSON. Never raises.

    `profile` exists for callers like app.py that track the active profile
    themselves (a file, since the control panel's own process never has
    AUTO_APPLIER_PROFILE set - only the bot subprocess it launches does).
    '''
    name = profile if profile is not None else active_profile_name()
    path = user_config_path_for(name)
    try:
        with open(path, "r", encoding="utf-8") as file:
            data = json.load(file)
            return data if isinstance(data, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError, OSError, ValueError):
        return {}


def apply(module_name: str, module_globals: dict) -> None:
    '''
    Overrides a config module's existing globals with values from the matching
    section of the active profile's user_config.json.

    - `module_name` is the module's `__name__` (e.g. "config.settings"); the last
      dotted part is the section name looked up in the JSON ("settings").
    - Only keys that ALREADY exist as globals in the module are applied, so the
      JSON can never introduce new names into the config namespace.
    '''
    section_name = module_name.split(".")[-1]
    section = load_user_config().get(section_name, {})
    if isinstance(section, dict):
        for key, value in section.items():
            if key in module_globals:
                module_globals[key] = value

    # For any profile other than "default", keep this profile's application
    # history and logs fully separate from every other profile, without every
    # profile's own JSON needing to know its own storage paths.
    profile = active_profile_name()
    if profile != DEFAULT_PROFILE and section_name == "settings":
        pdir = profile_dir(profile)
        os.makedirs(os.path.join(pdir, "logs", "screenshots"), exist_ok=True)
        if "file_name" in module_globals:
            module_globals["file_name"] = os.path.join(pdir, "all_applied_applications_history.csv")
        if "failed_file_name" in module_globals:
            module_globals["failed_file_name"] = os.path.join(pdir, "all_failed_applications_history.csv")
        if "logs_folder_path" in module_globals:
            module_globals["logs_folder_path"] = os.path.join(pdir, "logs") + os.sep
