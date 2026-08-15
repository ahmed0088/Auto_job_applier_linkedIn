'''
Author:     Sai Vignesh Golla
License:    MIT License
            https://opensource.org/license/mit
GitHub:     https://github.com/GodsScion/Auto_job_applier_linkedIn

Local "control panel" web app. It lets a non-technical person configure and run
the tool from a browser instead of editing Python files and using a terminal.

IMPORTANT - how configuration works:
  * This app reads/writes ONLY `user_config.json` at the project root.
  * It NEVER edits the config/*.py files.
  * The config/*.py modules load user_config.json over their built-in defaults
    (see config/_overrides.py), so saving here changes the tool's behaviour
    while leaving the classic "edit the .py files" workflow intact. With no
    user_config.json present the tool behaves exactly as it always has.

SECURITY: this app handles LinkedIn credentials, so it binds to 127.0.0.1 only
(never 0.0.0.0) and runs with debug OFF. Do not change these.
'''

from flask import Flask, request, jsonify, render_template, send_file
from flask_cors import CORS
from werkzeug.utils import secure_filename
import csv
from datetime import datetime
import os
import io
import re
import sys
import json
import copy
import shutil
import signal
import zipfile
import tempfile
import subprocess
import threading
import importlib

import config_schema
from config import _overrides

app = Flask(__name__)
CORS(app)

# Project root is the folder this file lives in.
ROOT = os.path.dirname(os.path.abspath(__file__))
USER_CONFIG_PATH = _overrides.USER_CONFIG_PATH
LOG_PATH = os.path.join(ROOT, ".bot_run.log")
PID_PATH = os.path.join(ROOT, ".bot_run.pid")

PATH = 'all excels/'

RESUME_UPLOAD_DIR = os.path.join(ROOT, "all resumes", "default")
ALLOWED_RESUME_EXTENSIONS = {".pdf", ".doc", ".docx"}


# ===========================================================================
# Profiles - run this tool for more than one LinkedIn account from one
# installation. "default" is always your existing setup, unchanged; any other
# profile gets its own settings, resume, application history, and browser
# session (see config/_overrides.py and modules/helpers.py).
# ===========================================================================
ACTIVE_PROFILE_PATH = os.path.join(ROOT, ".active_profile")
_PROFILE_NAME_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_-]{0,39}$')


def _profile_exists(name: str) -> bool:
    return name == "default" or os.path.isdir(_overrides.profile_dir(name))


def list_profiles() -> list:
    names = ["default"]
    if os.path.isdir(_overrides.PROFILES_DIR):
        for entry in sorted(os.listdir(_overrides.PROFILES_DIR)):
            if entry != "default" and os.path.isdir(os.path.join(_overrides.PROFILES_DIR, entry)):
                names.append(entry)
    return names


def get_active_profile() -> str:
    try:
        with open(ACTIVE_PROFILE_PATH, "r", encoding="utf-8") as f:
            name = f.read().strip()
    except OSError:
        return "default"
    return name if name and _profile_exists(name) else "default"


def _resume_dir_for(name: str) -> str:
    if name == "default":
        return RESUME_UPLOAD_DIR
    return os.path.join(_overrides.profile_dir(name), "resume")


def _history_dir_for(name: str) -> str:
    if name == "default":
        return os.path.join(ROOT, "all excels")
    return _overrides.profile_dir(name)


def _chrome_profile_dir_for(name: str) -> str:
    '''
    Mirrors modules/helpers.py's get_default_temp_profile() so profile deletion
    can also clean up that profile's isolated Chrome browser session. Keep the
    two in sync if that logic ever changes.
    '''
    suffix = "" if name == "default" else f"-{name}"
    home = os.path.expanduser("~")
    if sys.platform.startswith("win"):
        return f"C:\\temp\\auto-job-apply-profile{suffix}"
    elif sys.platform.startswith("linux"):
        return os.path.join(home, f".auto-job-apply-profile{suffix}")
    return os.path.join(home, "Library", "Application Support", "Google", "Chrome", f"auto-job-apply-profile{suffix}")


# ===========================================================================
# Default config values (the pristine config/*.py defaults, ignoring any
# user_config.json). Captured once at startup so /api/config can always show
# "default overlaid with the user's current saved values".
# ===========================================================================
def _load_defaults() -> dict:
    '''
    Import each config module with overrides temporarily disabled, so we read
    the untouched Python defaults regardless of whether user_config.json exists
    right now. Returns {config_module: {key: default_value}}.
    '''
    original_loader = _overrides.load_user_config
    _overrides.load_user_config = lambda: {}
    try:
        import config.secrets as _secrets
        import config.personals as _personals
        import config.questions as _questions
        import config.search as _search
        import config.settings as _settings
        modules = {
            "secrets": _secrets,
            "personals": _personals,
            "questions": _questions,
            "search": _search,
            "settings": _settings,
        }
        # Reload in case they were already imported (with real overrides) earlier.
        for module in modules.values():
            importlib.reload(module)
        defaults = {}
        for field in config_schema.iter_fields():
            module_name = field["config_module"]
            key = field["key"]
            module = modules.get(module_name)
            defaults.setdefault(module_name, {})[key] = getattr(module, key, None)
        return defaults
    finally:
        _overrides.load_user_config = original_loader


DEFAULTS = _load_defaults()


# ===========================================================================
# Config API helpers
# ===========================================================================
def _effective_config() -> dict:
    '''
    Return {config_module: {key: value}} of the pristine defaults overlaid with
    the CURRENT contents of user_config.json (re-read from disk on every call).
    Only keys defined in config_schema are included.
    '''
    effective = copy.deepcopy(DEFAULTS)
    user = _overrides.load_user_config(get_active_profile())
    for field in config_schema.iter_fields():
        module_name = field["config_module"]
        key = field["key"]
        section = user.get(module_name)
        if isinstance(section, dict) and key in section:
            effective[module_name][key] = section[key]
    return effective


def _coerce(field_type: str, value):
    '''
    Coerce an incoming JSON value into the type declared for the field in the
    schema. Raises ValueError on invalid numbers so the caller can reject them.
    '''
    if field_type in ("text", "password", "textarea", "select"):
        return "" if value is None else str(value)

    if field_type == "number":
        if isinstance(value, bool):
            raise ValueError("expected a number, got a boolean")
        if isinstance(value, (int, float)):
            number = value
        else:
            text = str(value).strip()
            if text == "":
                raise ValueError("expected a number, got an empty value")
            number = float(text)
        # Keep whole numbers as ints (the config defaults are ints).
        if isinstance(number, float) and number.is_integer():
            return int(number)
        return number

    if field_type == "bool":
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in ("true", "1", "yes", "on")

    if field_type == "list":
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip() != ""]
        text = str(value).strip()
        if text == "":
            return []
        return [item.strip() for item in text.split(",") if item.strip() != ""]

    # Unknown type: pass through untouched.
    return value


def _validate_field(field: dict, value) -> None:
    '''
    Extra semantic validation on top of _coerce()'s type conversion - raises
    ValueError (message goes straight into the API error response) if `value`
    doesn't satisfy the field's rules. Never called for values _coerce()
    already rejected.

    - "select" fields must be one of `field["options"]`, always (this is the
      one rule that isn't opt-in via `validate` - a select field is only ever
      as good as its options list, so there's no reason not to enforce it).
    - "number" fields respect an optional {"min": ..., "max": ...} in
      `field["validate"]`.
    - "text"/"textarea" fields respect an optional {"pattern": <regex>,
      "message": <shown on failure>} - only checked when non-empty, so the
      field can still be left blank to skip whatever question it answers.
    '''
    ftype = field["type"]
    spec = field.get("validate") or {}

    if ftype == "select" and "options" in field and value not in field["options"]:
        raise ValueError(f"must be one of: {', '.join(repr(o) for o in field['options'])}")

    if ftype == "number":
        if "min" in spec and value < spec["min"]:
            raise ValueError(f"must be at least {spec['min']}")
        if "max" in spec and value > spec["max"]:
            raise ValueError(f"must be at most {spec['max']}")

    if ftype in ("text", "textarea") and value and "pattern" in spec:
        if not re.fullmatch(spec["pattern"], value):
            raise ValueError(spec.get("message") or "is not in the expected format")


# ===========================================================================
# Bot subprocess management (run / stop / status / logs)
# ===========================================================================
_bot_proc = None
_bot_lock = threading.Lock()


def _bot_command():
    '''The command used to launch the bot. Isolated so tests can monkeypatch it.'''
    return [sys.executable, os.path.join(ROOT, "runAiBot.py")]


def _is_running() -> bool:
    '''True if the tracked bot subprocess exists and has not exited.'''
    global _bot_proc
    if _bot_proc is None:
        return False
    if _bot_proc.poll() is None:
        return True
    # Process has exited; clean up tracking + PID file.
    _bot_proc = None
    _remove_pid_file()
    return False


def _remove_pid_file():
    try:
        os.remove(PID_PATH)
    except OSError:
        pass


def _terminate(proc) -> None:
    '''Terminate the subprocess and, where feasible, its child processes.'''
    if proc is None or proc.poll() is not None:
        return
    try:
        if os.name == "nt":
            # Kill the whole process tree on Windows.
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        else:
            # We launched with start_new_session=True, so the child is its own
            # process-group leader; signal the whole group.
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            except (ProcessLookupError, PermissionError):
                proc.terminate()
    except Exception:
        try:
            proc.terminate()
        except Exception:
            pass
    # Give it a moment, then force-kill if still alive.
    try:
        proc.wait(timeout=5)
    except Exception:
        try:
            if os.name != "nt":
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            else:
                proc.kill()
        except Exception:
            pass


@app.route('/')
def home():
    """Serve the control panel single-page app."""
    return render_template('control_panel.html')


@app.route('/history')
def history():
    """Serve the applied-jobs history page."""
    return render_template('index.html')


# The applied-jobs history CSV the bot writes, and how its columns map to the JSON
# keys the history page consumes.
_HISTORY_CSV = 'all_applied_applications_history.csv'
_HISTORY_FIELDS = {
    'Job ID': 'Job_ID',
    'Title': 'Title',
    'Company': 'Company',
    'HR Name': 'HR_Name',
    'HR Link': 'HR_Link',
    'Job Link': 'Job_Link',
    'External Job link': 'External_Job_link',
    'Date Applied': 'Date_Applied',
}


@app.route('/applied-jobs', methods=['GET'])
def get_applied_jobs():
    """Return the applied-jobs history as JSON for the history page."""
    csv_path = os.path.join(_history_dir_for(get_active_profile()), _HISTORY_CSV)
    if not os.path.exists(csv_path):
        return jsonify({"error": "No applications history found yet."}), 404
    try:
        jobs = []
        with open(csv_path, 'r', encoding='utf-8') as f:
            for row in csv.DictReader(f):
                jobs.append({key: row.get(col, '') for col, key in _HISTORY_FIELDS.items()})
        return jsonify(jobs)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/applied-jobs/<job_id>', methods=['PUT'])
def mark_job_applied(job_id):
    """Stamp one job's 'Date Applied' (matched by Job ID) with the current time."""
    csv_path = os.path.join(_history_dir_for(get_active_profile()), _HISTORY_CSV)
    if not os.path.exists(csv_path):
        return jsonify({"error": f"History file not found at {csv_path}"}), 404
    try:
        with open(csv_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            columns = reader.fieldnames
            rows = list(reader)
        matched = False
        for row in rows:
            if row.get('Job ID') == job_id:
                row['Date Applied'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                matched = True
        if not matched:
            return jsonify({"error": f"Job ID {job_id} not found"}), 404
        with open(csv_path, 'w', encoding='utf-8', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=columns)
            writer.writeheader()
            writer.writerows(rows)
        return jsonify({"message": "Date Applied updated."}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ===========================================================================
# Control-panel API
# ===========================================================================
@app.route('/api/schema', methods=['GET'])
def api_schema():
    '''Returns the field schema the UI renders its forms from.'''
    return jsonify(config_schema.SCHEMA)


@app.route('/api/upload-resume', methods=['POST'])
def api_upload_resume():
    '''
    Accepts a resume file (multipart form field "resume"), saves it under the
    ACTIVE profile's resume folder, and returns the project-relative path to
    use as `default_resume_path`. Does not touch user_config.json itself - the
    UI saves the returned path through the normal /api/config flow.
    '''
    file = request.files.get('resume')
    if not file or not file.filename:
        return jsonify({"error": "No file was provided"}), 400

    filename = secure_filename(file.filename)
    ext = os.path.splitext(filename)[1].lower()
    if ext not in ALLOWED_RESUME_EXTENSIONS:
        return jsonify({"error": "Please upload a PDF or Word document (.pdf, .doc, .docx)"}), 400

    profile = get_active_profile()
    upload_dir = _resume_dir_for(profile)
    try:
        os.makedirs(upload_dir, exist_ok=True)
        file.save(os.path.join(upload_dir, filename))
    except OSError as err:
        return jsonify({"error": f"Could not save the file: {err}"}), 500

    rel_path = f"all resumes/default/{filename}" if profile == "default" else f"profiles/{profile}/resume/{filename}"
    return jsonify({"path": rel_path})


def _create_ai_client_for_active_profile():
    '''
    Builds an AI client from the ACTIVE PROFILE's effective secrets (from
    user_config.json), not whatever config.secrets held when this process (the
    control panel, not the bot subprocess) first imported it. Mirrors the same
    "temporarily override module attributes, then restore" pattern
    _load_defaults() already uses for reading pristine defaults.
    '''
    import config.secrets as _secrets_module
    from modules.ai.connections import create_ai_client
    secrets = _effective_config().get("secrets", {})
    patched_keys = ("use_AI", "ai_provider", "llm_model", "llm_api_key", "llm_api_url")
    original = {key: getattr(_secrets_module, key, None) for key in patched_keys}
    try:
        for key in patched_keys:
            if key in secrets:
                setattr(_secrets_module, key, secrets[key])
        return create_ai_client()
    finally:
        for key, value in original.items():
            setattr(_secrets_module, key, value)


@app.route('/api/fill-from-resume', methods=['POST'])
def api_fill_from_resume():
    '''
    Reads the active profile's resume file and asks the AI to extract profile
    fields from it (name, contact info, experience, ...). Returns them for the
    frontend to pre-fill the form with - nothing is saved automatically, you
    still review and click Save yourself. Deliberately never asks the AI to
    guess demographic/EEO fields (gender, ethnicity, disability, veteran
    status, date of birth) from a resume - see profile_extraction_prompt.
    '''
    effective = _effective_config()
    if not effective.get("secrets", {}).get("use_AI"):
        return jsonify({"error": 'Turn on "Use AI" and set an API key in the Account tab first.'}), 400

    resume_path = str(effective.get("questions", {}).get("default_resume_path", "") or "").strip()
    if not resume_path:
        return jsonify({"error": "No resume path is set. Upload a resume first."}), 400
    if not os.path.isabs(resume_path):
        resume_path = os.path.join(ROOT, resume_path)
    if not os.path.isfile(resume_path):
        return jsonify({"error": f'Resume file not found at "{resume_path}". Upload a resume first.'}), 400

    from modules.resumes.extractor import extract_resume_text
    resume_text = extract_resume_text(resume_path)
    if not resume_text:
        return jsonify({"error": "Couldn't read any text from that resume file (unsupported format, or a scanned/image-only PDF)."}), 400

    client = _create_ai_client_for_active_profile()
    if not client:
        return jsonify({"error": "Could not start the AI client - check your provider/model/API key in the Account tab."}), 400

    from modules.ai.connections import extract_profile_info
    result = extract_profile_info(client, resume_text)
    if "error" in result:
        return jsonify({"error": result["error"]}), 400

    return jsonify({"fields": result})


@app.route('/api/profiles', methods=['GET'])
def api_list_profiles():
    '''Lists every profile, which one is currently active, and whether there's any saved data yet.'''
    return jsonify({"profiles": list_profiles(), "active": get_active_profile(), "has_data": _has_any_saved_data()})


@app.route('/api/profiles', methods=['POST'])
def api_create_profile():
    '''Creates a new, empty profile (its own settings/resume/history/browser session).'''
    payload = request.get_json(silent=True) or {}
    name = str(payload.get("name", "")).strip()
    if not _PROFILE_NAME_RE.match(name):
        return jsonify({"error": "Profile name must be 1-40 characters: letters, numbers, - or _ only, starting with a letter or number."}), 400
    if name.lower() == "default":
        return jsonify({"error": '"default" is reserved for your existing profile.'}), 400
    if _profile_exists(name):
        return jsonify({"error": f'A profile named "{name}" already exists.'}), 400
    try:
        pdir = _overrides.profile_dir(name)
        os.makedirs(pdir, exist_ok=True)
        os.makedirs(os.path.join(pdir, "resume"), exist_ok=True)
        os.makedirs(os.path.join(pdir, "logs", "screenshots"), exist_ok=True)
        config_path = _overrides.user_config_path_for(name)
        if not os.path.exists(config_path):
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump({}, f)
    except OSError as err:
        return jsonify({"error": f"Could not create profile: {err}"}), 500
    return jsonify({"profiles": list_profiles(), "active": get_active_profile()})


@app.route('/api/profiles/active', methods=['POST'])
def api_set_active_profile():
    '''Switches which profile the control panel (and the next run) uses.'''
    with _bot_lock:
        if _is_running():
            return jsonify({"error": "Stop the current run before switching profiles."}), 409
    payload = request.get_json(silent=True) or {}
    name = str(payload.get("name", "")).strip()
    if not _profile_exists(name):
        return jsonify({"error": f'Profile "{name}" does not exist.'}), 404
    try:
        with open(ACTIVE_PROFILE_PATH, "w", encoding="utf-8") as f:
            f.write(name)
    except OSError as err:
        return jsonify({"error": f"Could not switch profile: {err}"}), 500
    return jsonify({"profiles": list_profiles(), "active": get_active_profile()})


@app.route('/api/profiles/<name>', methods=['DELETE'])
def api_delete_profile(name):
    '''Deletes a profile's settings/resume/history, and its isolated Chrome session.'''
    if name == "default":
        return jsonify({"error": "The default profile can't be deleted."}), 400
    if not _profile_exists(name):
        return jsonify({"error": f'Profile "{name}" does not exist.'}), 404
    if get_active_profile() == name:
        return jsonify({"error": "Switch to a different profile before deleting this one."}), 400
    with _bot_lock:
        if _is_running():
            return jsonify({"error": "Stop the current run before deleting a profile."}), 409
    try:
        shutil.rmtree(_overrides.profile_dir(name))
    except OSError as err:
        return jsonify({"error": f"Could not delete profile folder: {err}"}), 500
    try:
        chrome_dir = _chrome_profile_dir_for(name)
        if chrome_dir and os.path.isdir(chrome_dir):
            shutil.rmtree(chrome_dir)
    except OSError:
        pass
    return jsonify({"profiles": list_profiles(), "active": get_active_profile()})


# Data considered "yours" - never part of the git-tracked project itself (see
# .gitignore) - that import/export moves between installs. Relative paths;
# nothing here needs to exist for any given user, existence is checked at
# copy/zip time.
PORTABLE_DATA_PATHS = [
    os.path.join("config", "secrets.py"),
    os.path.join("config", "personals.py"),
    "user_config.json",
    "profiles",
    "all resumes",
    "all excels",
]


def _copy_portable_data(source_dir: str, dest_dir: str) -> tuple:
    '''
    Copies every path in PORTABLE_DATA_PATHS that exists under `source_dir`
    into the matching path under `dest_dir`. Returns (imported, errors), both
    lists of relative-path strings (errors formatted as "path: reason").
    '''
    imported, errors = [], []
    for rel_path in PORTABLE_DATA_PATHS:
        src = os.path.join(source_dir, rel_path)
        dst = os.path.join(dest_dir, rel_path)
        try:
            if os.path.isfile(src):
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.copy2(src, dst)
                imported.append(rel_path)
            elif os.path.isdir(src):
                shutil.copytree(src, dst, dirs_exist_ok=True)
                imported.append(rel_path)
        except OSError as err:
            errors.append(f"{rel_path}: {err}")
    return imported, errors


def _has_any_saved_data() -> bool:
    '''Whether this install already has real user data, vs. being a fresh download.'''
    if os.path.isfile(os.path.join(ROOT, "config", "secrets.py")):
        return True
    if os.path.isfile(USER_CONFIG_PATH) and os.path.getsize(USER_CONFIG_PATH) > 2:  # more than just "{}"
        return True
    if list_profiles():
        return True
    return False


def _safe_extract_zip(zf: zipfile.ZipFile, dest_dir: str) -> None:
    '''Extracts `zf` into `dest_dir`, refusing any entry that would land outside it
    (a maliciously-crafted zip using ../ or an absolute path - "zip slip").'''
    dest_abs = os.path.abspath(dest_dir)
    for member in zf.namelist():
        member_abs = os.path.abspath(os.path.join(dest_dir, member))
        if member_abs != dest_abs and not member_abs.startswith(dest_abs + os.sep):
            raise ValueError(f"Unsafe path in backup file: {member}")
    zf.extractall(dest_dir)


def _portable_category(rel_path: str) -> str | None:
    '''Which PORTABLE_DATA_PATHS entry `rel_path` (forward-slash-separated) falls
    under, or None if it isn't one of ours. Used to sanity-check every file in a
    browser-uploaded folder server-side, rather than trusting the client-side filter.'''
    for candidate in PORTABLE_DATA_PATHS:
        candidate_norm = candidate.replace(os.sep, "/")
        if rel_path == candidate_norm or rel_path.startswith(candidate_norm + "/"):
            return candidate
    return None


@app.route('/api/import-data', methods=['POST'])
def api_import_data():
    '''
    Copies saved data (secrets, personal info, and every profile - settings,
    resume, application history) from another local copy of this project (e.g.
    an older download) into this one. Lets someone moving to an updated
    download skip re-entering everything by hand.

    Only ever reads from the given `source_dir` and writes to this project's
    own well-known paths (config/secrets.py, config/personals.py,
    user_config.json, profiles/<name>/) - the source path never controls where
    anything gets written, so there's no path-traversal write risk. This is a
    local-only app (binds to 127.0.0.1), so accepting an arbitrary local
    filesystem path to read from is the same trust model as resume upload.
    '''
    with _bot_lock:
        if _is_running():
            return jsonify({"error": "Stop the current run before importing data."}), 409
    payload = request.get_json(silent=True) or {}
    source_dir = str(payload.get("source_dir", "")).strip()
    if not source_dir:
        return jsonify({"error": "Please provide the path to your other project folder."}), 400
    source_dir = os.path.expanduser(source_dir)
    if not os.path.isdir(source_dir):
        return jsonify({"error": f'"{source_dir}" is not a folder that exists on this computer.'}), 400
    if os.path.abspath(source_dir) == os.path.abspath(ROOT):
        return jsonify({"error": "That's this project's own folder - pick your OTHER copy instead."}), 400

    imported, errors = _copy_portable_data(source_dir, ROOT)
    if not imported and not errors:
        return jsonify({"error": "Didn't find anything to import in that folder - is it the right project folder?"}), 400

    return jsonify({
        "imported": imported,
        "errors": errors,
        "profiles": list_profiles(),
        "active": get_active_profile(),
    })


@app.route('/api/import-data-file', methods=['POST'])
def api_import_data_file():
    '''
    Same as /api/import-data, but the source is an uploaded .zip (from
    /api/export-data) instead of a local folder path - for moving data from a
    different computer, where there's no shared filesystem path to point at.
    '''
    with _bot_lock:
        if _is_running():
            return jsonify({"error": "Stop the current run before importing data."}), 409
    file = request.files.get('backup')
    if not file or not file.filename:
        return jsonify({"error": "Please choose a backup .zip file."}), 400
    if not file.filename.lower().endswith('.zip'):
        return jsonify({"error": "That doesn't look like a .zip file exported from this tool."}), 400

    with tempfile.TemporaryDirectory() as tmp_dir:
        try:
            with zipfile.ZipFile(file.stream) as zf:
                _safe_extract_zip(zf, tmp_dir)
        except (zipfile.BadZipFile, ValueError) as err:
            return jsonify({"error": f"That file isn't a valid backup: {err}"}), 400
        imported, errors = _copy_portable_data(tmp_dir, ROOT)

    if not imported and not errors:
        return jsonify({"error": "That backup file didn't contain anything recognizable to import."}), 400

    return jsonify({
        "imported": imported,
        "errors": errors,
        "profiles": list_profiles(),
        "active": get_active_profile(),
    })


@app.route('/api/import-data-folder', methods=['POST'])
def api_import_data_folder():
    '''
    Same as /api/import-data, but the source is a folder picked through the
    browser's own native folder-browse dialog (an <input type="file"
    webkitdirectory> - no typed/pasted path needed) instead of a path string.
    Browsers don't expose that folder's real filesystem path to a webpage, so
    the frontend uploads the individual files instead, each carrying its path
    relative to the selected folder as its multipart filename - already
    filtered client-side to just the portable-data files, but re-checked here
    against PORTABLE_DATA_PATHS server-side too, since client-side filtering
    is only a courtesy, never a security boundary.
    '''
    with _bot_lock:
        if _is_running():
            return jsonify({"error": "Stop the current run before importing data."}), 409
    files = request.files.getlist('files')
    if not files:
        return jsonify({"error": "Didn't find anything recognizable to import in that folder."}), 400

    imported = set()
    errors = []
    root_abs = os.path.abspath(ROOT)
    for file in files:
        rel_path = (file.filename or "").replace("\\", "/").lstrip("/")
        category = _portable_category(rel_path)
        if not category:
            continue  # Not one of ours (e.g. .git, logs, screenshots) - silently skip
        dst_abs = os.path.abspath(os.path.join(ROOT, rel_path))
        if dst_abs != root_abs and not dst_abs.startswith(root_abs + os.sep):
            errors.append(f"{rel_path}: unsafe path, skipped")
            continue
        try:
            dst_dir = os.path.dirname(dst_abs)
            if dst_dir:
                os.makedirs(dst_dir, exist_ok=True)
            file.save(dst_abs)
            imported.add(category)
        except OSError as err:
            errors.append(f"{rel_path}: {err}")

    if not imported and not errors:
        return jsonify({"error": "Didn't find anything recognizable to import in that folder - is it the right project folder?"}), 400

    return jsonify({
        "imported": sorted(imported),
        "errors": errors,
        "profiles": list_profiles(),
        "active": get_active_profile(),
    })


@app.route('/api/export-data', methods=['GET'])
def api_export_data():
    '''
    Downloads a single .zip with everything /api/import-data(-file) can
    restore: secrets, personal info, user_config.json, and every profile
    (settings, resume, application history). For moving data to a different
    computer, or just as a manual backup - folder-to-folder import already
    covers moving between two folders on the same machine.
    '''
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        wrote_anything = False
        for rel_path in PORTABLE_DATA_PATHS:
            abs_path = os.path.join(ROOT, rel_path)
            if os.path.isfile(abs_path):
                zf.write(abs_path, rel_path)
                wrote_anything = True
            elif os.path.isdir(abs_path):
                for dirpath, _dirnames, filenames in os.walk(abs_path):
                    for filename in filenames:
                        file_abs = os.path.join(dirpath, filename)
                        zf.write(file_abs, os.path.relpath(file_abs, ROOT))
                        wrote_anything = True
        if not wrote_anything:
            zf.writestr("README.txt", "No saved data found in this install yet - nothing to back up.")
    buffer.seek(0)
    filename = f"auto_job_applier_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
    return send_file(buffer, mimetype="application/zip", as_attachment=True, download_name=filename)


@app.route('/api/config', methods=['GET'])
def api_get_config():
    '''
    Returns the effective config: pristine defaults overlaid with the current
    user_config.json, grouped by config module (secrets, personals, questions,
    search, settings).
    '''
    return jsonify(_effective_config())


@app.route('/api/config', methods=['POST'])
def api_save_config():
    '''
    Accepts {config_module: {key: value}}, validates against the schema, coerces
    each value to its declared type, rejects unknown modules/keys, merges into
    user_config.json (read-modify-write) and returns the full saved config.
    '''
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"error": "Expected a JSON object of {section: {key: value}}"}), 400

    valid = config_schema.valid_keys()
    unknown = []
    coerced = {}

    for section, values in payload.items():
        if not isinstance(values, dict):
            return jsonify({"error": f"Section '{section}' must be an object"}), 400
        if section not in valid:
            unknown.append(section)
            continue
        for key, value in values.items():
            field = valid[section].get(key)
            if field is None:
                unknown.append(f"{section}.{key}")
                continue
            try:
                coerced_value = _coerce(field["type"], value)
                _validate_field(field, coerced_value)
                coerced.setdefault(section, {})[key] = coerced_value
            except ValueError as err:
                return jsonify({"error": f"Invalid value for '{section}.{key}': {err}"}), 400

    if unknown:
        return jsonify({"error": "Unknown settings rejected", "unknown": unknown}), 400

    # Read-modify-write the active profile's user_config.json.
    current = _overrides.load_user_config(get_active_profile())
    for section, values in coerced.items():
        target = current.get(section)
        if not isinstance(target, dict):
            target = {}
        target.update(values)
        current[section] = target

    config_path = _overrides.user_config_path_for(get_active_profile())
    try:
        os.makedirs(os.path.dirname(config_path), exist_ok=True)
        with open(config_path, "w", encoding="utf-8") as file:
            json.dump(current, file, indent=2, ensure_ascii=False)
    except OSError as err:
        return jsonify({"error": f"Could not save settings: {err}"}), 500

    return jsonify(current)


@app.route('/api/run', methods=['POST'])
def api_run():
    '''Starts the bot as a subprocess if it isn't already running.'''
    global _bot_proc
    with _bot_lock:
        if _is_running():
            return jsonify({"running": True, "pid": _bot_proc.pid,
                            "message": "The tool is already running."})
        try:
            # Truncate the log at the start of each run.
            log_file = open(LOG_PATH, "w", encoding="utf-8")
            popen_kwargs = {
                "cwd": ROOT,
                "stdout": log_file,
                "stderr": subprocess.STDOUT,
                # Tells config/_overrides.py and modules/helpers.py which profile's
                # settings, resume, history, and browser session to use.
                "env": {**os.environ, "AUTO_APPLIER_PROFILE": get_active_profile()},
            }
            if os.name == "nt":
                popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
            else:
                popen_kwargs["start_new_session"] = True
            _bot_proc = subprocess.Popen(_bot_command(), **popen_kwargs)
        except Exception as err:
            return jsonify({"running": False, "error": str(err)}), 500
        try:
            with open(PID_PATH, "w", encoding="utf-8") as pid_file:
                pid_file.write(str(_bot_proc.pid))
        except OSError:
            pass
        return jsonify({"running": True, "pid": _bot_proc.pid})


@app.route('/api/stop', methods=['POST'])
def api_stop():
    '''Stops the running bot subprocess (and its children where possible).'''
    global _bot_proc
    with _bot_lock:
        if _bot_proc is not None:
            _terminate(_bot_proc)
            _bot_proc = None
        _remove_pid_file()
        return jsonify({"running": False})


@app.route('/api/status', methods=['GET'])
def api_status():
    '''Reports whether the bot subprocess is currently running.'''
    with _bot_lock:
        running = _is_running()
        pid = _bot_proc.pid if (running and _bot_proc is not None) else None
        return jsonify({"running": running, "pid": pid})


@app.route('/api/logs', methods=['GET'])
def api_logs():
    '''
    Returns the run log starting from byte offset ?offset=N, plus the byte
    offset to read from next time. The UI polls this while the bot runs.
    '''
    try:
        offset = int(request.args.get("offset", 0))
    except (TypeError, ValueError):
        offset = 0
    if offset < 0:
        offset = 0
    if not os.path.exists(LOG_PATH):
        return jsonify({"content": "", "next_offset": 0})
    try:
        with open(LOG_PATH, "rb") as log_file:
            log_file.seek(0, os.SEEK_END)
            size = log_file.tell()
            if offset > size:
                # Log was truncated (a new run started); start over.
                offset = 0
            log_file.seek(offset)
            data = log_file.read()
        content = data.decode("utf-8", errors="replace")
        return jsonify({"content": content, "next_offset": offset + len(data)})
    except OSError as err:
        return jsonify({"content": "", "next_offset": offset, "error": str(err)})


def _resolve_port(preferred: int = 5000) -> int:
    '''
    Pick a port to serve on. Honors the PORT environment variable (the launcher
    scripts set it). Otherwise tries `preferred`, and if that's taken - e.g. port
    5000 is used by AirPlay Receiver on macOS - asks the OS for any free port so
    the panel always starts instead of crashing with "address already in use".
    '''
    import socket
    requested = os.environ.get("PORT", "").strip()
    if requested.isdigit():
        return int(requested)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        try:
            probe.bind(("127.0.0.1", preferred))
            return preferred
        except OSError:
            pass
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


if __name__ == '__main__':
    # SECURITY: localhost only, debug OFF. This app handles credentials.
    port = _resolve_port(5000)
    url = "http://127.0.0.1:%d" % port
    print(
        "\n  Control panel ready at:  %s\n"
        "  Keep this window open while you use the tool; close it to stop.\n" % url,
        flush=True,
    )
    # The launcher scripts set PANEL_OPEN_BROWSER=1 so the browser opens itself,
    # to the right port, cross-platform. Running `python app.py` by hand won't.
    if os.environ.get("PANEL_OPEN_BROWSER", "").strip() not in ("", "0", "false", "False"):
        import threading
        import webbrowser
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    app.run(host="127.0.0.1", port=port, debug=False)
