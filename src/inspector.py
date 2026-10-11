import os
import shutil
import subprocess
import tarfile
import zipfile
import re
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

class PackageInspector:
    """Detects format, extracts metadata, icon, and candidates for executables."""

    @staticmethod
    def inspect(file_path: Path) -> Dict[str, Any]:
        path = Path(file_path).resolve()
        name = path.name
        stem = path.stem
        lower_name = name.lower()

        info: Dict[str, Any] = {
            "source_path": str(path),
            "file_name": name,
            "detected_type": "unknown",
            "suggested_name": PackageInspector._clean_app_name(stem),
            "suggested_icon": None,
            "executables": [],
            "description": "",
            "version": "",
            "requires_root": False,
        }

        if lower_name.endswith(".deb"):
            info["detected_type"] = "deb"
            info["requires_root"] = True
            deb_info = PackageInspector._inspect_deb(path)
            info.update(deb_info)
        elif lower_name.endswith(".appimage"):
            info["detected_type"] = "appimage"
            info["executables"] = [str(path)]
            appimage_info = PackageInspector._inspect_appimage(path)
            info.update(appimage_info)
        elif lower_name.endswith((".tar.gz", ".tgz", ".tar.xz", ".tar.bz2", ".zip", ".tar")):
            info["detected_type"] = "archive"
            arch_info = PackageInspector._inspect_archive(path)
            info.update(arch_info)
        elif lower_name.endswith((".sh", ".run", ".bin")):
            info["detected_type"] = "script"
            info["executables"] = [str(path)]
        else:
            # Check if it's an executable binary
            if os.access(path, os.X_OK) and not path.is_dir():
                info["detected_type"] = "binary"
                info["executables"] = [str(path)]

        return info

    @staticmethod
    def _clean_app_name(stem: str) -> str:
        # Strip common archive/packaging extensions from stem
        stem = re.sub(r'(\.tar|\.x86_64|\.amd64|\.linux|\.AppImage)$', '', stem, flags=re.IGNORECASE)
        # Remove version numbers like -1.2.3 or _1.2.3 or -v2.0
        cleaned = re.sub(r'[-_]v?(\d+\.)+.*$', '', stem)
        # Convert dashes/underscores to spaces and capitalize
        parts = re.split(r'[-_]', cleaned)
        title = " ".join(p.capitalize() for p in parts if p)
        return title or stem

    @staticmethod
    def _inspect_deb(path: Path) -> Dict[str, Any]:
        info: Dict[str, Any] = {}
        try:
            # dpkg-deb -I output contains Package, Version, Description, etc.
            res = subprocess.run(
                ["dpkg-deb", "-I", str(path)],
                capture_output=True,
                text=True,
                check=False
            )
            out = res.stdout
            pkg_m = re.search(r"^\s*Package:\s*(.+)$", out, re.M)
            ver_m = re.search(r"^\s*Version:\s*(.+)$", out, re.M)
            desc_m = re.search(r"^\s*Description:\s*(.+)$", out, re.M)
            if pkg_m:
                pkg_name = pkg_m.group(1).strip()
                info["suggested_name"] = pkg_name.capitalize()
            if ver_m:
                info["version"] = ver_m.group(1).strip()
            if desc_m:
                info["description"] = desc_m.group(1).strip()
        except Exception:
            pass
        return info

    @staticmethod
    def _inspect_appimage(path: Path) -> Dict[str, Any]:
        info: Dict[str, Any] = {}
        # Try to extract icon or desktop file using --appimage-extract
        # But doing extraction could be slow on big AppImages, so we do a quick check
        # We can extract just the icon or .desktop if possible
        temp_dir = Path(f"/tmp/instalinux_preview_{os.getpid()}")
        try:
            # Check if AppImage has execution rights
            if not os.access(path, os.X_OK):
                os.chmod(path, os.stat(path).st_mode | 0o111)

            # Try to extract desktop & icons only
            # Many AppImages support --appimage-extract "*.desktop" or ".DirIcon"
            res = subprocess.run(
                [str(path), "--appimage-extract", ".DirIcon"],
                cwd=temp_dir.parent,
                capture_output=True,
                timeout=5
            )
            extracted_dir = temp_dir.parent / "squashfs-root"
            if extracted_dir.exists():
                icon = extracted_dir / ".DirIcon"
                if icon.exists():
                    cache_icon = Path.home() / ".cache" / "instalinux" / f"{path.stem}.png"
                    cache_icon.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(icon, cache_icon)
                    info["suggested_icon"] = str(cache_icon)
                shutil.rmtree(extracted_dir, ignore_errors=True)
        except Exception:
            pass
        return info

    @staticmethod
    def _inspect_archive(path: Path) -> Dict[str, Any]:
        info: Dict[str, Any] = {"executables": []}
        candidates = []
        icons = []

        try:
            if tarfile.is_tarfile(path):
                with tarfile.open(path, 'r:*') as tar:
                    for m in tar.getmembers():
                        p = Path(m.name)
                        # Check extensions
                        if p.suffix.lower() in [".png", ".svg", ".ico"]:
                            icons.append(m.name)
                        # Check executable bit or common binary names
                        if m.isfile() and (m.mode & 0o111 or p.suffix in ["", ".sh", ".bin"]):
                            candidates.append(m.name)
            elif zipfile.is_zipfile(path):
                with zipfile.ZipFile(path, 'r') as z:
                    for name in z.namelist():
                        p = Path(name)
                        if p.suffix.lower() in [".png", ".svg", ".ico"]:
                            icons.append(name)
                        if p.suffix in ["", ".sh", ".bin"] and not name.endswith("/"):
                            candidates.append(name)
        except Exception:
            pass

        # Sort candidates to put main entrypoints at top
        main_name = path.stem.split('.')[0].lower()
        prioritized = []
        others = []
        for c in candidates:
            c_name = Path(c).name.lower()
            if c_name in [main_name, f"{main_name}.sh", "start.sh", "run.sh", "launch"]:
                prioritized.append(c)
            elif not any(ignored in c for ignored in ["lib/", "share/", ".so", "uninstall", "test"]):
                others.append(c)

        info["executables"] = prioritized + others
        if icons:
            # Return relative path of first suitable icon
            info["archive_icon_entry"] = icons[0]

        return info
