import json
import os
import shutil
import subprocess
import tarfile
import zipfile
import re
import configparser
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

# Standard FreeDesktop / Linux Paths
# Apps installed per-user go to ~/.local/opt or ~/.local/share/applications
USER_OPT_DIR = Path.home() / ".local" / "opt"
USER_BIN_DIR = Path.home() / ".local" / "bin"
USER_DESKTOP_DIR = Path.home() / ".local" / "share" / "applications"
USER_ICONS_DIR = Path.home() / ".local" / "share" / "icons" / "hicolor" / "scalable" / "apps"

# System Paths
SYSTEM_OPT_DIR = Path("/opt")
SYSTEM_BIN_DIR = Path("/usr/local/bin")
SYSTEM_DESKTOP_DIR = Path("/usr/share/applications")

# Registry of installations made by InstaLinux
DATABASE_FILE = Path.home() / ".local" / "share" / "instalinux" / "installed_apps.json"

CATEGORIES = [
    ("Utility", "Утилиты / Инструменты"),
    ("Development", "Разработка"),
    ("Office", "Офис"),
    ("Graphics", "Графика / Дизайн"),
    ("AudioVideo", "Аудио и Видео"),
    ("Network", "Интернет / Сеть"),
    ("Game", "Игры"),
    ("System", "Система"),
]

def ensure_dirs():
    """Ensure all required user directories exist according to Linux standards."""
    USER_OPT_DIR.mkdir(parents=True, exist_ok=True)
    USER_BIN_DIR.mkdir(parents=True, exist_ok=True)
    USER_DESKTOP_DIR.mkdir(parents=True, exist_ok=True)
    USER_ICONS_DIR.mkdir(parents=True, exist_ok=True)
    DATABASE_FILE.parent.mkdir(parents=True, exist_ok=True)

def sanitize_id(name: str) -> str:
    """Generate a clean identifier for app id / desktop filename."""
    s = re.sub(r'[^a-zA-Z0-9_\-]', '-', name.lower().strip())
    s = re.sub(r'-+', '-', s)
    return s.strip('-') or "app"

def get_installed_apps() -> List[Dict[str, Any]]:
    """Load list of applications installed through InstaLinux."""
    ensure_dirs()
    if not DATABASE_FILE.exists():
        return []
    try:
        with open(DATABASE_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return data.get("apps", [])
    except Exception:
        return []

def save_installed_app(app_data: Dict[str, Any]):
    """Save an application entry to database."""
    ensure_dirs()
    apps = get_installed_apps()
    apps = [a for a in apps if a.get("id") != app_data.get("id")]
    apps.append(app_data)
    with open(DATABASE_FILE, 'w', encoding='utf-8') as f:
        json.dump({"apps": apps}, f, indent=2, ensure_ascii=False)

def remove_installed_app(app_id: str) -> bool:
    """Remove application entry from database."""
    ensure_dirs()
    apps = get_installed_apps()
    new_apps = [a for a in apps if a.get("id") != app_id]
    with open(DATABASE_FILE, 'w', encoding='utf-8') as f:
        json.dump({"apps": new_apps}, f, indent=2, ensure_ascii=False)
    return len(new_apps) < len(apps)

def create_desktop_shortcut(
    name: str,
    exec_path: str,
    icon_path: Optional[str] = None,
    comment: str = "",
    categories: str = "Utility;",
    terminal: bool = False,
    is_system: bool = False,
    app_id: Optional[str] = None
) -> Path:
    """Generate standard FreeDesktop .desktop shortcut."""
    if not app_id:
        app_id = sanitize_id(name)

    target_dir = SYSTEM_DESKTOP_DIR if is_system else USER_DESKTOP_DIR
    desktop_file = target_dir / f"{app_id}.desktop"

    content = [
        "[Desktop Entry]",
        "Version=1.0",
        "Type=Application",
        f"Name={name}",
        f"Comment={comment or name}",
        f"Exec={exec_path} %U",
        f"Terminal={'true' if terminal else 'false'}",
        f"Categories={categories}",
    ]

    if icon_path:
        content.append(f"Icon={icon_path}")

    if is_system:
        temp_desktop = Path(f"/tmp/{app_id}.desktop")
        with open(temp_desktop, 'w', encoding='utf-8') as f:
            f.write("\n".join(content) + "\n")
        subprocess.run(["pkexec", "cp", str(temp_desktop), str(desktop_file)], check=True)
        subprocess.run(["pkexec", "chmod", "644", str(desktop_file)], check=True)
        temp_desktop.unlink(missing_ok=True)
        subprocess.run(["pkexec", "update-desktop-database", str(SYSTEM_DESKTOP_DIR)], check=False, stderr=subprocess.DEVNULL)
    else:
        ensure_dirs()
        with open(desktop_file, 'w', encoding='utf-8') as f:
            f.write("\n".join(content) + "\n")
        os.chmod(desktop_file, 0o755)
        subprocess.run(["update-desktop-database", str(USER_DESKTOP_DIR)], check=False, stderr=subprocess.DEVNULL)

    return desktop_file


def scan_all_system_applications() -> List[Dict[str, Any]]:
    """
    Scans the entire operating system for installed GUI applications,
    detects their packaging source (APT/DEB, Snap, Flatpak, User) and flags duplicate titles.
    """
    desktop_dirs = [
        (Path.home() / ".local" / "share" / "applications", "user"),
        (Path("/var/lib/snapd/desktop/applications"), "snap"),
        (Path("/var/lib/flatpak/exports/share/applications"), "flatpak"),
        (Path.home() / ".local" / "share" / "flatpak" / "exports" / "share" / "applications", "flatpak"),
        (Path("/usr/share/applications"), "system"),
    ]

    seen_names: Dict[str, List[Dict[str, Any]]] = {}
    apps: List[Dict[str, Any]] = []

    for dir_path, dir_type in desktop_dirs:
        if not dir_path.exists():
            continue

        for desktop_file in sorted(dir_path.glob("*.desktop")):
            config = configparser.RawConfigParser(strict=False)
            try:
                config.read(desktop_file, encoding="utf-8")
                if not config.has_section("Desktop Entry"):
                    continue
                sec = config["Desktop Entry"]
                if sec.get("NoDisplay", "false").lower() == "true":
                    continue
                if sec.get("Type", "Application") != "Application":
                    continue

                app_name = sec.get("Name", desktop_file.stem)
                icon = sec.get("Icon", "application-x-executable")
                exec_cmd = sec.get("Exec", "")
                comment = sec.get("Comment", "")

                # Detect packaging source
                snap_name = sec.get("X-SnapInstanceName")
                if dir_type == "snap" or snap_name or "/snap/" in exec_cmd:
                    pkg_type = "Snap"
                    target_pkg = snap_name or desktop_file.stem.split("_")[0]
                elif dir_type == "flatpak" or "flatpak run" in exec_cmd:
                    pkg_type = "Flatpak"
                    target_pkg = desktop_file.stem
                elif dir_type == "user":
                    pkg_type = "Пользовательское"
                    target_pkg = str(desktop_file)
                else:
                    pkg_type = "DEB / APT"
                    target_pkg = None

                item = {
                    "id": desktop_file.stem,
                    "name": app_name,
                    "comment": comment,
                    "icon": icon,
                    "exec": exec_cmd,
                    "path": str(desktop_file),
                    "pkg_type": pkg_type,
                    "target_pkg": target_pkg,
                    "is_duplicate": False,
                }

                # Track duplicates
                norm_key = re.sub(r'\s+', ' ', app_name.strip().lower())
                if norm_key not in seen_names:
                    seen_names[norm_key] = []
                seen_names[norm_key].append(item)

                apps.append(item)
            except Exception:
                continue

    # Mark duplicates
    for norm_key, items in seen_names.items():
        if len(items) > 1:
            for item in items:
                item["is_duplicate"] = True

    # Sort: duplicates first, then alphabetically
    apps.sort(key=lambda x: (not x.get("is_duplicate", False), x["name"].lower()))
    return apps
