import unittest
import tempfile
import os
import shutil
import tarfile
import zipfile
from pathlib import Path

from src.models import (
    sanitize_id,
    create_desktop_shortcut,
    save_installed_app,
    get_installed_apps,
    remove_installed_app
)
from src.inspector import PackageInspector
from src.installer import InstallerEngine

class TestInstaLinuxCore(unittest.TestCase):

    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp(prefix="instalinux_test_"))

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_sanitize_id(self):
        self.assertEqual(sanitize_id("My Cool App 1.0!"), "my-cool-app-1-0")
        self.assertEqual(sanitize_id("Visual Studio Code"), "visual-studio-code")
        self.assertEqual(sanitize_id("   "), "app")

    def test_inspector_archive(self):
        # Create a sample tar.gz with an executable script and an icon
        archive_path = self.test_dir / "sample-app-1.0.tar.gz"
        sub_dir = self.test_dir / "sample-app"
        sub_dir.mkdir()
        
        main_sh = sub_dir / "sample-app.sh"
        with open(main_sh, "w") as f:
            f.write("#!/bin/bash\necho 'hello'")
        os.chmod(main_sh, 0o755)

        icon_file = sub_dir / "icon.png"
        icon_file.write_text("fake image data")

        with tarfile.open(archive_path, "w:gz") as tar:
            tar.add(main_sh, arcname="sample-app/sample-app.sh")
            tar.add(icon_file, arcname="sample-app/icon.png")

        info = PackageInspector.inspect(archive_path)
        self.assertEqual(info["detected_type"], "archive")
        self.assertEqual(info["suggested_name"], "Sample App")
        self.assertTrue(any("sample-app.sh" in x for x in info["executables"]))

    def test_install_and_uninstall_archive(self):
        # Create a test tar.gz
        archive_path = self.test_dir / "mytool.tar.gz"
        tool_src = self.test_dir / "mytool"
        tool_src.mkdir()
        bin_file = tool_src / "mytool"
        bin_file.write_text("#!/bin/sh\necho OK")
        bin_file.chmod(0o755)

        with tarfile.open(archive_path, "w:gz") as tar:
            tar.add(bin_file, arcname="mytool/mytool")

        engine = InstallerEngine()
        result = engine.install(
            source_path=archive_path,
            app_name="My Test Tool",
            detected_type="archive",
            chosen_binary="mytool/mytool",
            install_scope="user",
            category="Utility",
            terminal=False
        )

        self.assertEqual(result["name"], "My Test Tool")
        install_dir = Path(result["install_dir"])
        self.assertTrue(install_dir.exists())
        self.assertTrue(Path(result["desktop_file"]).exists())

        # Check DB
        apps = get_installed_apps()
        self.assertTrue(any(a["id"] == result["id"] for a in apps))

        # Test uninstall
        success, msg = InstallerEngine.uninstall(result)
        self.assertTrue(success)
        self.assertFalse(install_dir.exists())
        self.assertFalse(Path(result["desktop_file"]).exists())

if __name__ == "__main__":
    unittest.main()
