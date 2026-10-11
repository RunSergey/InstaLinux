import os
import shutil
import subprocess
import tarfile
import zipfile
import time
from pathlib import Path
from typing import Dict, Any, Optional, Tuple, Callable

from .models import (
    USER_OPT_DIR,
    USER_BIN_DIR,
    USER_ICONS_DIR,
    USER_DESKTOP_DIR,
    SYSTEM_OPT_DIR,
    SYSTEM_BIN_DIR,
    SYSTEM_DESKTOP_DIR,
    ensure_dirs,
    sanitize_id,
    save_installed_app,
    remove_installed_app,
    create_desktop_shortcut
)

class InstallerEngine:
    """Handles installation and removal for .deb, .AppImage, archives, and scripts."""

    def __init__(self, status_callback: Optional[Callable[[str], None]] = None):
        self.status_cb = status_callback or (lambda msg: None)

    def log(self, message: str):
        self.status_cb(message)

    def install(
        self,
        source_path: Path,
        app_name: str,
        detected_type: str,
        icon_path: Optional[str] = None,
        chosen_binary: Optional[str] = None,
        install_scope: str = "user", # "user" or "system"
        category: str = "Utility",
        terminal: bool = False
    ) -> Dict[str, Any]:
        """Performs the full installation workflow."""
        ensure_dirs()
        app_id = sanitize_id(app_name)
        source_path = Path(source_path).resolve()

        self.log(f"Начало установки: {app_name} ({detected_type})...")

        if detected_type == "deb":
            return self._install_deb(source_path, app_name, app_id, icon_path, category)
        elif detected_type == "appimage":
            return self._install_appimage(source_path, app_name, app_id, icon_path, install_scope, category, terminal)
        elif detected_type == "archive":
            return self._install_archive(source_path, app_name, app_id, icon_path, chosen_binary, install_scope, category, terminal)
        elif detected_type in ["script", "binary"]:
            return self._install_single_executable(source_path, app_name, app_id, icon_path, install_scope, category, terminal)
        else:
            raise ValueError(f"Неизвестный тип пакета: {detected_type}")

    def _copy_icon(self, icon_path: Optional[str], app_id: str) -> Optional[str]:
        if not icon_path or not Path(icon_path).exists():
            return None
        icon_file = Path(icon_path)
        ext = icon_file.suffix or ".png"
        dest_icon = USER_ICONS_DIR / f"{app_id}{ext}"
        try:
            shutil.copy2(icon_file, dest_icon)
            return str(dest_icon)
        except Exception:
            return str(icon_file)

    def _install_deb(
        self,
        deb_path: Path,
        app_name: str,
        app_id: str,
        icon_path: Optional[str],
        category: str
    ) -> Dict[str, Any]:
        self.log("Установка системного пакета .deb через apt / dpkg...")
        cmd = ["pkexec", "apt-get", "install", "-y", str(deb_path)]
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0:
            self.log("Попытка установки через dpkg...")
            res_dpkg = subprocess.run(["pkexec", "dpkg", "-i", str(deb_path)], capture_output=True, text=True)
            if res_dpkg.returncode != 0:
                subprocess.run(["pkexec", "apt-get", "install", "-f", "-y"], capture_output=True, text=True)

        pkg_name = app_id
        try:
            out = subprocess.run(["dpkg-deb", "-f", str(deb_path), "Package"], capture_output=True, text=True).stdout.strip()
            if out:
                pkg_name = out
        except Exception:
            pass

        saved_data = {
            "id": app_id,
            "name": app_name,
            "type": "deb",
            "package_name": pkg_name,
            "install_date": time.strftime("%Y-%m-%d %H:%M"),
            "scope": "system",
            "source_file": str(deb_path),
            "category": category,
        }
        save_installed_app(saved_data)
        self.log("Установка .deb успешно завершена!")
        return saved_data

    def _install_appimage(
        self,
        appimage_path: Path,
        app_name: str,
        app_id: str,
        icon_path: Optional[str],
        install_scope: str,
        category: str,
        terminal: bool
    ) -> Dict[str, Any]:
        self.log("Копирование AppImage и настройка прав доступа...")

        if install_scope == "system":
            target_dir = SYSTEM_OPT_DIR / app_id
            subprocess.run(["pkexec", "mkdir", "-p", str(target_dir)], check=True)
            target_file = target_dir / f"{app_id}.AppImage"
            subprocess.run(["pkexec", "cp", str(appimage_path), str(target_file)], check=True)
            subprocess.run(["pkexec", "chmod", "755", str(target_file)], check=True)
            # Create symlink in /usr/local/bin
            subprocess.run(["pkexec", "ln", "-sf", str(target_file), f"/usr/local/bin/{app_id}"], check=False)
        else:
            # Standard user directory: ~/.local/opt/<app_id>
            target_dir = USER_OPT_DIR / app_id
            target_dir.mkdir(parents=True, exist_ok=True)
            target_file = target_dir / f"{app_id}.AppImage"
            shutil.copy2(appimage_path, target_file)
            target_file.chmod(target_file.stat().st_mode | 0o755)
            # User symlink in ~/.local/bin
            user_bin = USER_BIN_DIR / app_id
            try:
                user_bin.unlink(missing_ok=True)
                user_bin.symlink_to(target_file)
            except Exception:
                pass

        final_icon = self._copy_icon(icon_path, app_id)

        self.log("Создание ярлыка в меню приложений...")
        desktop_file = create_desktop_shortcut(
            name=app_name,
            exec_path=str(target_file),
            icon_path=final_icon,
            categories=f"{category};",
            terminal=terminal,
            is_system=(install_scope == "system"),
            app_id=app_id
        )

        saved_data = {
            "id": app_id,
            "name": app_name,
            "type": "appimage",
            "install_date": time.strftime("%Y-%m-%d %H:%M"),
            "scope": install_scope,
            "install_dir": str(target_dir),
            "exec_path": str(target_file),
            "desktop_file": str(desktop_file),
            "icon_path": final_icon,
            "category": category,
        }
        save_installed_app(saved_data)
        self.log("AppImage успешно установлен и добавлен в меню!")
        return saved_data

    def _install_archive(
        self,
        archive_path: Path,
        app_name: str,
        app_id: str,
        icon_path: Optional[str],
        chosen_binary: Optional[str],
        install_scope: str,
        category: str,
        terminal: bool
    ) -> Dict[str, Any]:
        self.log("Распаковка архива...")

        temp_extract = Path(f"/tmp/instalinux_{app_id}_{int(time.time())}")
        temp_extract.mkdir(parents=True, exist_ok=True)

        if tarfile.is_tarfile(archive_path):
            with tarfile.open(archive_path, 'r:*') as tar:
                tar.extractall(path=temp_extract)
        elif zipfile.is_zipfile(archive_path):
            with zipfile.ZipFile(archive_path, 'r') as z:
                z.extractall(path=temp_extract)
        else:
            raise ValueError(f"Не удалось распаковать архив {archive_path.name}")

        contents = list(temp_extract.iterdir())
        extracted_root = temp_extract
        if len(contents) == 1 and contents[0].is_dir():
            extracted_root = contents[0]

        if install_scope == "system":
            target_dir = SYSTEM_OPT_DIR / app_id
            self.log(f"Перемещение в системную директорию {target_dir}...")
            subprocess.run(["pkexec", "rm", "-rf", str(target_dir)], check=False)
            subprocess.run(["pkexec", "mv", str(extracted_root), str(target_dir)], check=True)
            shutil.rmtree(temp_extract, ignore_errors=True)
        else:
            # Standard user directory: ~/.local/opt/<app_id>
            target_dir = USER_OPT_DIR / app_id
            self.log(f"Перемещение в директорию {target_dir}...")
            if target_dir.exists():
                shutil.rmtree(target_dir)
            shutil.move(str(extracted_root), str(target_dir))
            shutil.rmtree(temp_extract, ignore_errors=True)

        # Determine binary
        if chosen_binary:
            binary_name = Path(chosen_binary).name
            potential = target_dir / chosen_binary
            if not potential.exists():
                matches = list(target_dir.rglob(binary_name))
                target_exec = matches[0] if matches else (target_dir / binary_name)
            else:
                target_exec = potential
        else:
            execs = [f for f in target_dir.rglob("*") if f.is_file() and os.access(f, os.X_OK)]
            target_exec = execs[0] if execs else (target_dir / app_id)

        if install_scope == "system":
            subprocess.run(["pkexec", "chmod", "+x", str(target_exec)], check=False)
            subprocess.run(["pkexec", "ln", "-sf", str(target_exec), f"/usr/local/bin/{app_id}"], check=False)
        else:
            try:
                target_exec.chmod(target_exec.stat().st_mode | 0o755)
            except Exception:
                pass
            user_bin = USER_BIN_DIR / app_id
            try:
                user_bin.unlink(missing_ok=True)
                user_bin.symlink_to(target_exec)
            except Exception:
                pass

        if not icon_path:
            for icon_candidate in target_dir.rglob("*.png"):
                icon_path = str(icon_candidate)
                break
            if not icon_path:
                for icon_candidate in target_dir.rglob("*.svg"):
                    icon_path = str(icon_candidate)
                    break

        final_icon = self._copy_icon(icon_path, app_id)

        self.log("Создание ярлыка в меню приложений...")
        desktop_file = create_desktop_shortcut(
            name=app_name,
            exec_path=str(target_exec),
            icon_path=final_icon,
            categories=f"{category};",
            terminal=terminal,
            is_system=(install_scope == "system"),
            app_id=app_id
        )

        saved_data = {
            "id": app_id,
            "name": app_name,
            "type": "archive",
            "install_date": time.strftime("%Y-%m-%d %H:%M"),
            "scope": install_scope,
            "install_dir": str(target_dir),
            "exec_path": str(target_exec),
            "desktop_file": str(desktop_file),
            "icon_path": final_icon,
            "category": category,
        }
        save_installed_app(saved_data)
        self.log("Программа из архива успешно установлена!")
        return saved_data

    def _install_single_executable(
        self,
        src_file: Path,
        app_name: str,
        app_id: str,
        icon_path: Optional[str],
        install_scope: str,
        category: str,
        terminal: bool
    ) -> Dict[str, Any]:
        self.log(f"Установка исполняемого файла / скрипта {src_file.name}...")

        if install_scope == "system":
            target_dir = SYSTEM_OPT_DIR / app_id
            subprocess.run(["pkexec", "mkdir", "-p", str(target_dir)], check=True)
            target_file = target_dir / src_file.name
            subprocess.run(["pkexec", "cp", str(src_file), str(target_file)], check=True)
            subprocess.run(["pkexec", "chmod", "755", str(target_file)], check=True)
            subprocess.run(["pkexec", "ln", "-sf", str(target_file), f"/usr/local/bin/{app_id}"], check=False)
        else:
            target_dir = USER_OPT_DIR / app_id
            target_dir.mkdir(parents=True, exist_ok=True)
            target_file = target_dir / src_file.name
            shutil.copy2(src_file, target_file)
            target_file.chmod(target_file.stat().st_mode | 0o755)
            user_bin = USER_BIN_DIR / app_id
            try:
                user_bin.unlink(missing_ok=True)
                user_bin.symlink_to(target_file)
            except Exception:
                pass

        final_icon = self._copy_icon(icon_path, app_id)

        self.log("Создание ярлыка...")
        desktop_file = create_desktop_shortcut(
            name=app_name,
            exec_path=str(target_file),
            icon_path=final_icon,
            categories=f"{category};",
            terminal=terminal,
            is_system=(install_scope == "system"),
            app_id=app_id
        )

        saved_data = {
            "id": app_id,
            "name": app_name,
            "type": "executable",
            "install_date": time.strftime("%Y-%m-%d %H:%M"),
            "scope": install_scope,
            "install_dir": str(target_dir),
            "exec_path": str(target_file),
            "desktop_file": str(desktop_file),
            "icon_path": final_icon,
            "category": category,
        }
        save_installed_app(saved_data)
        self.log("Файл успешно установлен и готов к запуску!")
        return saved_data

    @staticmethod
    def uninstall(app_data: Dict[str, Any]) -> Tuple[bool, str]:
        """Completely removes an application installed via InstaLinux."""
        app_id = app_data.get("id")
        app_type = app_data.get("type")
        scope = app_data.get("scope", "user")

        try:
            if app_type == "deb":
                pkg_name = app_data.get("package_name") or app_id
                res = subprocess.run(
                    ["pkexec", "apt-get", "remove", "-y", pkg_name],
                    capture_output=True,
                    text=True
                )
                if res.returncode != 0:
                    return False, f"Ошибка при удалении пакета {pkg_name}: {res.stderr}"

            else:
                # Remove desktop shortcut
                desktop_file = app_data.get("desktop_file")
                if desktop_file and Path(desktop_file).exists():
                    if scope == "system":
                        subprocess.run(["pkexec", "rm", "-f", desktop_file], check=False)
                    else:
                        Path(desktop_file).unlink(missing_ok=True)

                # Remove symlink
                if scope == "system":
                    subprocess.run(["pkexec", "rm", "-f", f"/usr/local/bin/{app_id}"], check=False)
                else:
                    (USER_BIN_DIR / app_id).unlink(missing_ok=True)

                # Remove installed files directory
                install_dir = app_data.get("install_dir")
                if install_dir and Path(install_dir).exists():
                    if scope == "system":
                        subprocess.run(["pkexec", "rm", "-rf", install_dir], check=False)
                    else:
                        shutil.rmtree(install_dir, ignore_errors=True)

                # Remove cached icon if any
                icon_path = app_data.get("icon_path")
                if icon_path and Path(icon_path).exists():
                    try:
                        Path(icon_path).unlink(missing_ok=True)
                    except Exception:
                        pass

            # Remove from DB
            remove_installed_app(app_id)

            # Update desktop db
            try:
                subprocess.run(["update-desktop-database", str(USER_DESKTOP_DIR)], check=False, stderr=subprocess.DEVNULL)
            except Exception:
                pass

            return True, f"Приложение '{app_data.get('name')}' успешно удалено!"
        except Exception as e:
            return False, f"Ошибка удаления: {str(e)}"

    @staticmethod
    def uninstall_system_app(app_item: Dict[str, Any]) -> Tuple[bool, str]:
        """
        Removes any detected application on the computer (User desktop file, Snap, Flatpak, or APT).
        Helps cleanup unwanted software and duplicates.
        """
        pkg_type = app_item.get("pkg_type")
        path_str = app_item.get("path")
        app_name = app_item.get("name")

        try:
            if pkg_type == "Пользовательское":
                # Remove user desktop file
                if path_str and Path(path_str).exists():
                    Path(path_str).unlink(missing_ok=True)
                subprocess.run(["update-desktop-database", str(USER_DESKTOP_DIR)], check=False, stderr=subprocess.DEVNULL)
                return True, f"Пользовательский ярлык '{app_name}' удалён."

            elif pkg_type == "Snap":
                snap_pkg = app_item.get("target_pkg")
                if not snap_pkg:
                    return False, "Не удалось определить имя Snap-пакета"
                res = subprocess.run(["pkexec", "snap", "remove", snap_pkg], capture_output=True, text=True)
                if res.returncode == 0:
                    return True, f"Snap-пакет '{snap_pkg}' успешно удалён."
                return False, f"Ошибка Snap: {res.stderr}"

            elif pkg_type == "Flatpak":
                flatpak_pkg = app_item.get("target_pkg")
                if not flatpak_pkg:
                    return False, "Не удалось определить ID Flatpak"
                res = subprocess.run(["flatpak", "uninstall", "-y", flatpak_pkg], capture_output=True, text=True)
                if res.returncode == 0:
                    return True, f"Flatpak '{flatpak_pkg}' успешно удалён."
                return False, f"Ошибка Flatpak: {res.stderr}"

            elif pkg_type == "DEB / APT":
                # Detect package using dpkg -S
                pkg_name = None
                if path_str:
                    res = subprocess.run(["dpkg", "-S", path_str], capture_output=True, text=True, check=False)
                    if res.returncode == 0:
                        pkg_name = res.stdout.split(":")[0].strip()

                if not pkg_name:
                    return False, f"Не удалось автоматически найти системный пакет для {path_str}."

                res_apt = subprocess.run(["pkexec", "apt-get", "remove", "-y", pkg_name], capture_output=True, text=True)
                if res_apt.returncode == 0:
                    return True, f"Системный пакет '{pkg_name}' успешно удалён через APT."
                return False, f"Ошибка удаления: {res_apt.stderr}"

            else:
                return False, "Неизвестный тип пакета"
        except Exception as e:
            return False, f"Ошибка при удалении: {str(e)}"
