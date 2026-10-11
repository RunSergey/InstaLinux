import sys
import os
import shutil
import subprocess
import tarfile
import urllib.parse
from pathlib import Path
from typing import Dict, Any, Optional, List

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, GLib, Gio, Gdk

from .models import (
    CATEGORIES,
    get_installed_apps,
    scan_all_system_applications,
    USER_OPT_DIR,
    USER_BIN_DIR,
)
from .inspector import PackageInspector
from .installer import InstallerEngine

class InstaLinuxWindow(Adw.ApplicationWindow):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.set_title("InstaLinux - Установщик программ")
        self.set_default_size(840, 660)
        self.set_icon_name("instalinux")

        # State
        self.current_pkg_info: Optional[Dict[str, Any]] = None
        self.chosen_icon_path: Optional[str] = None
        self.installer = InstallerEngine(status_callback=self.on_log_message)
        self.all_system_apps: List[Dict[str, Any]] = []

        self._build_ui()
        self._setup_window_drag_and_drop()
        self._load_installed_apps()
        self._load_system_apps()

    def _build_ui(self):
        # Main layout container
        self.main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.set_content(self.main_box)

        # Header Bar
        header = Adw.HeaderBar()
        self.main_box.append(header)

        # Main View Switcher in Header (Установка | Установленные | Все приложения)
        self.view_stack = Adw.ViewStack()
        self.view_stack.set_vexpand(True)
        self.view_stack.set_hexpand(True)

        view_switcher_title = Adw.ViewSwitcherTitle()
        view_switcher_title.set_stack(self.view_stack)
        header.set_title_widget(view_switcher_title)

        # Page 1: Install page
        self.install_page_box = self._create_install_page()
        page1 = self.view_stack.add_titled(self.install_page_box, "install", "Установка")
        page1.set_icon_name("list-add-symbolic")

        # Page 2: InstaLinux Installed Manager
        self.installed_page_box = self._create_installed_page()
        self.page2 = self.view_stack.add_titled(self.installed_page_box, "installed", "Мои установки")
        self.page2.set_icon_name("application-x-executable-symbolic")

        # Page 3: All Computer Apps & Duplicate Cleaner
        self.all_apps_page_box = self._create_all_apps_page()
        self.page3 = self.view_stack.add_titled(self.all_apps_page_box, "all_apps", "Все программы ПК")
        self.page3.set_icon_name("software-properties-symbolic")

        # Toast overlay for notifications
        self.toast_overlay = Adw.ToastOverlay()
        self.toast_overlay.set_vexpand(True)
        self.toast_overlay.set_hexpand(True)
        self.toast_overlay.set_child(self.view_stack)
        self.main_box.append(self.toast_overlay)

    def _setup_window_drag_and_drop(self):
        """Setup robust drag and drop target covering the whole window."""
        drop_target = Gtk.DropTarget.new(Gio.File.__gtype__, Gdk.DragAction.COPY | Gdk.DragAction.MOVE)
        drop_target.set_gtypes([Gio.File.__gtype__, Gdk.FileList.__gtype__, str])
        drop_target.connect("drop", self.on_file_dropped)
        self.add_controller(drop_target)

    def show_toast(self, text: str):
        toast = Adw.Toast.new(text)
        toast.set_timeout(3)
        self.toast_overlay.add_toast(toast)

    # ==========================
    # PAGE 1: INSTALLER
    # ==========================
    def _create_install_page(self) -> Gtk.Widget:
        self.install_stack = Gtk.Stack()
        self.install_stack.set_vexpand(True)
        self.install_stack.set_hexpand(True)
        self.install_stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)

        drop_view = self._create_drop_zone_view()
        self.install_stack.add_named(drop_view, "drop_zone")

        config_view = self._create_config_view()
        self.install_stack.add_named(config_view, "configure")

        return self.install_stack

    def _create_drop_zone_view(self) -> Gtk.Widget:
        status_page = Adw.StatusPage()
        status_page.set_vexpand(True)
        status_page.set_hexpand(True)
        status_page.set_icon_name("package-x-generic-symbolic")
        status_page.set_title("Перетащите файл для установки")
        status_page.set_description(
            "Программы устанавливаются по стандарту Linux (~/.local/opt или /opt) и не зависят от InstaLinux.\n"
            "Автоматически создаётся ярлык, настраиваются права и ссылки для запуска из терминала.\n\n"
            "Поддерживаемые форматы:\n"
            "📦 Пакеты Debian / Ubuntu (.deb)\n"
            "🚀 Портативные приложения (.AppImage)\n"
            "🗜️ Архивы (.tar.gz, .zip, .tar.xz, .tar.bz2)\n"
            "⚙️ Исполняемые файлы и скрипты (.sh, .run, .bin)"
        )

        content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        content_box.set_halign(Gtk.Align.CENTER)
        content_box.set_margin_top(12)

        pick_btn = Gtk.Button(label="Выбрать файл...")
        pick_btn.add_css_class("suggested-action")
        pick_btn.add_css_class("pill")
        pick_btn.set_size_request(200, 48)
        pick_btn.connect("clicked", self.on_choose_file_clicked)
        content_box.append(pick_btn)

        hint_lbl = Gtk.Label(label="или просто перетащите файл из папки Загрузки в это окно")
        hint_lbl.add_css_class("dim-label")
        content_box.append(hint_lbl)

        status_page.set_child(content_box)
        return status_page

    def _create_config_view(self) -> Gtk.Widget:
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_vexpand(True)
        scrolled.set_hexpand(True)

        clamp = Adw.Clamp()
        clamp.set_maximum_size(680)
        clamp.set_margin_top(20)
        clamp.set_margin_bottom(30)
        clamp.set_margin_start(20)
        clamp.set_margin_end(20)

        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)

        # Top Bar: Back button and File Name
        top_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        back_btn = Gtk.Button.new_from_icon_name("go-previous-symbolic")
        back_btn.set_tooltip_text("Назад к выбору файла")
        back_btn.connect("clicked", lambda b: self.install_stack.set_visible_child_name("drop_zone"))
        top_bar.append(back_btn)

        file_title_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self.file_label = Gtk.Label(label="", xalign=0)
        self.file_label.add_css_class("heading")
        self.file_path_label = Gtk.Label(label="", xalign=0)
        self.file_path_label.add_css_class("caption")
        self.file_path_label.add_css_class("dim-label")
        file_title_box.append(self.file_label)
        file_title_box.append(self.file_path_label)

        top_bar.append(file_title_box)
        main_box.append(top_bar)

        # Preferences Group 1: General Info
        pref_group = Adw.PreferencesGroup()
        pref_group.set_title("Параметры приложения")
        pref_group.set_description("Настройте отображение программы в системе и меню")

        self.name_entry_row = Adw.EntryRow()
        self.name_entry_row.set_title("Название приложения")
        pref_group.add(self.name_entry_row)

        self.icon_action_row = Adw.ActionRow()
        self.icon_action_row.set_title("Иконка приложения")
        self.icon_action_row.set_subtitle("Автоматически извлечённая или выбранная вами")

        self.icon_preview = Gtk.Image.new_from_icon_name("application-x-executable")
        self.icon_preview.set_pixel_size(40)
        self.icon_action_row.add_prefix(self.icon_preview)

        icon_btn = Gtk.Button(label="Выбрать иконку...")
        icon_btn.set_valign(Gtk.Align.CENTER)
        icon_btn.connect("clicked", self.on_choose_icon_clicked)
        self.icon_action_row.add_suffix(icon_btn)
        pref_group.add(self.icon_action_row)

        self.category_row = Adw.ComboRow()
        self.category_row.set_title("Категория в меню")
        cat_model = Gtk.StringList()
        for cat_id, cat_title in CATEGORIES:
            cat_model.append(cat_title)
        self.category_row.set_model(cat_model)
        pref_group.add(self.category_row)

        main_box.append(pref_group)

        # Preferences Group 2: Scope & Execution
        pref_group2 = Adw.PreferencesGroup()
        pref_group2.set_title("Стандартное размещение Linux")

        self.scope_row = Adw.ComboRow()
        self.scope_row.set_title("Куда установить")
        scope_model = Gtk.StringList()
        scope_model.append("Для пользователя (~/.local/opt, без root-пароля)")
        scope_model.append("Для всей системы (/opt, требует права sudo/root)")
        self.scope_row.set_model(scope_model)
        pref_group2.add(self.scope_row)

        self.binary_row = Adw.ComboRow()
        self.binary_row.set_title("Главный исполняемый файл")
        self.binary_model = Gtk.StringList()
        self.binary_row.set_model(self.binary_model)
        self.binary_row.set_visible(False)
        pref_group2.add(self.binary_row)

        self.terminal_switch = Adw.SwitchRow()
        self.terminal_switch.set_title("Запускать в окне терминала")
        self.terminal_switch.set_subtitle("Включите для консольных утилит и командных скриптов")
        pref_group2.add(self.terminal_switch)

        main_box.append(pref_group2)

        # Status & Progress Area
        self.progress_bar = Gtk.ProgressBar()
        self.progress_bar.set_visible(False)
        main_box.append(self.progress_bar)

        self.status_label = Gtk.Label(label="", xalign=0)
        self.status_label.add_css_class("dim-label")
        main_box.append(self.status_label)

        # Install Action Button
        self.install_btn = Gtk.Button(label="Установить приложение")
        self.install_btn.add_css_class("suggested-action")
        self.install_btn.add_css_class("pill")
        self.install_btn.set_size_request(220, 48)
        self.install_btn.set_halign(Gtk.Align.CENTER)
        self.install_btn.connect("clicked", self.on_start_install_clicked)
        main_box.append(self.install_btn)

        clamp.set_child(main_box)
        scrolled.set_child(clamp)
        return scrolled

    # ==========================
    # PAGE 2: INSTALLED VIA INSTALINUX
    # ==========================
    def _create_installed_page(self) -> Gtk.Widget:
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_vexpand(True)
        scrolled.set_hexpand(True)

        clamp = Adw.Clamp()
        clamp.set_maximum_size(720)
        clamp.set_margin_top(20)
        clamp.set_margin_bottom(20)
        clamp.set_margin_start(20)
        clamp.set_margin_end(20)

        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)

        title_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        lbl = Gtk.Label(label="Установленные через InstaLinux")
        lbl.add_css_class("title-2")
        title_box.append(lbl)

        refresh_btn = Gtk.Button.new_from_icon_name("view-refresh-symbolic")
        refresh_btn.set_tooltip_text("Обновить список")
        refresh_btn.set_halign(Gtk.Align.END)
        refresh_btn.set_hexpand(True)
        refresh_btn.connect("clicked", lambda b: self._load_installed_apps())
        title_box.append(refresh_btn)
        main_box.append(title_box)

        self.installed_container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        main_box.append(self.installed_container)

        self.empty_label = Gtk.Label(label="Вы пока не установили ни одной программы через InstaLinux.\nПерейдите на вкладку «Установка», чтобы добавить первое приложение.")
        self.empty_label.set_justify(Gtk.Justification.CENTER)
        self.empty_label.add_css_class("dim-label")
        self.empty_label.set_margin_top(40)
        main_box.append(self.empty_label)

        clamp.set_child(main_box)
        scrolled.set_child(clamp)
        return scrolled

    def _load_installed_apps(self):
        while child := self.installed_container.get_first_child():
            self.installed_container.remove(child)

        apps = get_installed_apps()
        self.empty_label.set_visible(len(apps) == 0)

        if not apps:
            return

        group = Adw.PreferencesGroup()
        self.installed_container.append(group)

        for app in apps:
            row = Adw.ActionRow()
            app_name = app.get("name", "Программа")
            app_type = app.get("type", "").upper()
            date = app.get("install_date", "")
            scope_dir = app.get("install_dir", "")
            row.set_title(app_name)
            row.set_subtitle(f"Тип: {app_type} • Путь: {scope_dir} • Дата: {date}")

            icon_path = app.get("icon_path")
            if icon_path and Path(icon_path).exists():
                icon = Gtk.Image.new_from_file(icon_path)
            else:
                icon = Gtk.Image.new_from_icon_name("application-x-executable")
            icon.set_pixel_size(36)
            row.add_prefix(icon)

            btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            btn_box.set_valign(Gtk.Align.CENTER)

            install_dir = app.get("install_dir")
            if install_dir and Path(install_dir).exists():
                open_btn = Gtk.Button.new_from_icon_name("folder-open-symbolic")
                open_btn.set_tooltip_text("Открыть папку программы")
                open_btn.connect("clicked", lambda b, p=install_dir: subprocess.run(["xdg-open", p], check=False))
                btn_box.append(open_btn)

            del_btn = Gtk.Button.new_from_icon_name("user-trash-symbolic")
            del_btn.add_css_class("destructive-action")
            del_btn.set_tooltip_text("Удалить приложение")
            del_btn.connect("clicked", lambda b, a=app: self.on_uninstall_clicked(a))
            btn_box.append(del_btn)

            row.add_suffix(btn_box)
            group.add(row)

    # ==========================
    # PAGE 3: ALL COMPUTER APPLICATIONS & DUPLICATES CLEANER
    # ==========================
    def _create_all_apps_page(self) -> Gtk.Widget:
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_vexpand(True)
        scrolled.set_hexpand(True)

        clamp = Adw.Clamp()
        clamp.set_maximum_size(750)
        clamp.set_margin_top(20)
        clamp.set_margin_bottom(20)
        clamp.set_margin_start(20)
        clamp.set_margin_end(20)

        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)

        # Header with Search & Filter
        title_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        lbl = Gtk.Label(label="Все программы на компьютере")
        lbl.add_css_class("title-2")
        title_box.append(lbl)

        refresh_btn = Gtk.Button.new_from_icon_name("view-refresh-symbolic")
        refresh_btn.set_tooltip_text("Пересканировать программы")
        refresh_btn.set_halign(Gtk.Align.END)
        refresh_btn.set_hexpand(True)
        refresh_btn.connect("clicked", lambda b: self._load_system_apps())
        title_box.append(refresh_btn)
        main_box.append(title_box)

        # Search Bar and Duplicates Filter Checkbox
        filter_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
        self.search_entry = Gtk.SearchEntry()
        self.search_entry.set_hexpand(True)
        self.search_entry.set_placeholder_text("Поиск по названию или типу (APT, Snap, Flatpak)...")
        self.search_entry.connect("search-changed", lambda e: self._filter_system_apps())
        filter_box.append(self.search_entry)

        self.dup_only_check = Gtk.CheckButton(label="Только дубликаты")
        self.dup_only_check.connect("toggled", lambda b: self._filter_system_apps())
        filter_box.append(self.dup_only_check)

        main_box.append(filter_box)

        # Applications List Group Container
        self.system_apps_container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        main_box.append(self.system_apps_container)

        self.empty_search_label = Gtk.Label(label="Программы не найдены")
        self.empty_search_label.add_css_class("dim-label")
        self.empty_search_label.set_margin_top(30)
        self.empty_search_label.set_visible(False)
        main_box.append(self.empty_search_label)

        clamp.set_child(main_box)
        scrolled.set_child(clamp)
        return scrolled

    def _load_system_apps(self):
        """Scans the system in background thread and populates UI."""
        import threading
        def worker():
            apps = scan_all_system_applications()
            GLib.idle_add(self._on_system_apps_scanned, apps)

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()

    def _on_system_apps_scanned(self, apps: List[Dict[str, Any]]):
        self.all_system_apps = apps
        self._filter_system_apps()

    def _filter_system_apps(self):
        """Filters applications by search text and duplicate toggle."""
        while child := self.system_apps_container.get_first_child():
            self.system_apps_container.remove(child)

        query = self.search_entry.get_text().strip().lower()
        only_duplicates = self.dup_only_check.get_active()

        filtered = []
        for app in self.all_system_apps:
            if only_duplicates and not app.get("is_duplicate"):
                continue
            if query:
                match_name = query in app["name"].lower()
                match_type = query in app.get("pkg_type", "").lower()
                match_cmd = query in app.get("exec", "").lower()
                if not (match_name or match_type or match_cmd):
                    continue
            filtered.append(app)

        self.empty_search_label.set_visible(len(filtered) == 0)

        if not filtered:
            return

        group = Adw.PreferencesGroup()
        self.system_apps_container.append(group)

        for app in filtered:
            row = Adw.ActionRow()
            app_name = app.get("name", "Программа")
            pkg_type = app.get("pkg_type", "Система")
            is_dup = app.get("is_duplicate", False)

            if is_dup:
                row.set_title(f"⚠️ {app_name}")
            else:
                row.set_title(app_name)

            path_str = app.get("path", "")
            row.set_subtitle(f"Формат: {pkg_type} • Ярлык: {path_str}")

            # Icon
            icon_name = app.get("icon", "")
            if icon_name and Path(icon_name).exists():
                icon = Gtk.Image.new_from_file(icon_name)
            elif icon_name:
                icon = Gtk.Image.new_from_icon_name(icon_name)
            else:
                icon = Gtk.Image.new_from_icon_name("application-x-executable")
            icon.set_pixel_size(36)
            row.add_prefix(icon)

            # Actions buttons
            btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            btn_box.set_valign(Gtk.Align.CENTER)

            # Delete / Uninstall Button
            del_btn = Gtk.Button.new_from_icon_name("user-trash-symbolic")
            del_btn.add_css_class("destructive-action")
            del_btn.set_tooltip_text(f"Удалить ({pkg_type})")
            del_btn.connect("clicked", lambda b, a=app: self.on_system_app_uninstall_clicked(a))
            btn_box.append(del_btn)

            row.add_suffix(btn_box)
            group.add(row)

    # ==========================
    # EVENT HANDLERS & FILE SELECTION
    # ==========================
    def on_choose_file_clicked(self, button):
        """Open native file chooser dialog."""
        dialog = Gtk.FileChooserNative(
            title="Выберите файл программы или архива",
            transient_for=self,
            action=Gtk.FileChooserAction.OPEN
        )

        filter_all = Gtk.FileFilter()
        filter_all.set_name("Все поддерживаемые форматы (.deb, .AppImage, архивы, .sh)")
        filter_all.add_pattern("*.deb")
        filter_all.add_pattern("*.AppImage")
        filter_all.add_pattern("*.appimage")
        filter_all.add_pattern("*.tar.gz")
        filter_all.add_pattern("*.tgz")
        filter_all.add_pattern("*.tar.xz")
        filter_all.add_pattern("*.tar.bz2")
        filter_all.add_pattern("*.zip")
        filter_all.add_pattern("*.sh")
        filter_all.add_pattern("*.run")
        filter_all.add_pattern("*.bin")
        dialog.add_filter(filter_all)

        filter_any = Gtk.FileFilter()
        filter_any.set_name("Все файлы (*)")
        filter_any.add_pattern("*")
        dialog.add_filter(filter_any)

        downloads = Path.home() / "Downloads"
        if downloads.exists():
            dialog.set_current_folder(Gio.File.new_for_path(str(downloads)))

        def on_response(dlg, response):
            if response == Gtk.ResponseType.ACCEPT:
                gfile = dlg.get_file()
                if gfile and gfile.get_path():
                    self.process_selected_file(Path(gfile.get_path()))

        dialog.connect("response", on_response)
        dialog.show()

    def on_file_dropped(self, drop_target, value, x, y):
        """Handle Drag & Drop event with support for Gio.File, Gdk.FileList, and URI strings."""
        paths: List[Path] = []

        if hasattr(value, "get_path") and value.get_path():
            paths.append(Path(value.get_path()))
        elif hasattr(value, "get_files"):
            for f in value.get_files():
                if f.get_path():
                    paths.append(Path(f.get_path()))
        elif isinstance(value, str):
            for line in value.splitlines():
                line = line.strip()
                if line.startswith("file://"):
                    p = urllib.parse.unquote(urllib.parse.urlparse(line).path)
                    paths.append(Path(p))
                elif line.startswith("/"):
                    paths.append(Path(line))

        valid_paths = [p for p in paths if p.exists()]
        if valid_paths:
            self.process_selected_file(valid_paths[0])
            return True

        return False

    def process_selected_file(self, file_path: Path):
        """Inspect the chosen package/archive and show configuration UI."""
        self.current_pkg_info = PackageInspector.inspect(file_path)
        info = self.current_pkg_info

        self.file_label.set_text(file_path.name)
        self.file_path_label.set_text(str(file_path))
        self.name_entry_row.set_text(info.get("suggested_name", file_path.stem))

        if info.get("detected_type") == "deb":
            self.scope_row.set_selected(1) # System
            self.scope_row.set_sensitive(False)
        else:
            self.scope_row.set_selected(0) # User
            self.scope_row.set_sensitive(True)

        lower_name = file_path.name.lower()
        if any(w in lower_name for w in ["krita", "gimp", "inkscape", "blender", "draw", "photo"]):
            self.category_row.set_selected(3) # Graphics
        elif any(w in lower_name for w in ["code", "ide", "git", "pycharm", "sublime", "dev"]):
            self.category_row.set_selected(1) # Development
        elif any(w in lower_name for w in ["music", "audio", "video", "player", "vlc", "obs"]):
            self.category_row.set_selected(4) # AudioVideo
        elif any(w in lower_name for w in ["browser", "chrome", "firefox", "telegram", "discord"]):
            self.category_row.set_selected(5) # Network
        else:
            self.category_row.set_selected(0) # Utility

        self.chosen_icon_path = info.get("suggested_icon")
        self._update_icon_preview(self.chosen_icon_path)

        execs = info.get("executables", [])
        if execs and info.get("detected_type") == "archive":
            self.binary_model.splice(0, self.binary_model.get_n_items(), execs)
            self.binary_row.set_visible(True)
            self.binary_row.set_selected(0)
        else:
            self.binary_row.set_visible(False)

        self.status_label.set_text("")
        self.progress_bar.set_visible(False)
        self.install_btn.set_sensitive(True)
        self.install_stack.set_visible_child_name("configure")

    def _update_icon_preview(self, path: Optional[str]):
        if path and Path(path).exists():
            self.icon_preview.set_from_file(path)
        else:
            self.icon_preview.set_from_icon_name("application-x-executable")

    def on_choose_icon_clicked(self, button):
        """Open native dialog to pick icon file."""
        dialog = Gtk.FileChooserNative(
            title="Выберите иконку (PNG или SVG)",
            transient_for=self,
            action=Gtk.FileChooserAction.OPEN
        )
        filter_img = Gtk.FileFilter()
        filter_img.set_name("Изображения (*.png, *.svg)")
        filter_img.add_pattern("*.png")
        filter_img.add_pattern("*.svg")
        dialog.add_filter(filter_img)

        def on_response(dlg, response):
            if response == Gtk.ResponseType.ACCEPT:
                gfile = dlg.get_file()
                if gfile and gfile.get_path():
                    self.chosen_icon_path = gfile.get_path()
                    self._update_icon_preview(self.chosen_icon_path)

        dialog.connect("response", on_response)
        dialog.show()

    def on_log_message(self, message: str):
        GLib.idle_add(self._update_log_ui, message)

    def _update_log_ui(self, message: str):
        self.status_label.set_text(message)

    def on_start_install_clicked(self, button):
        if not self.current_pkg_info:
            return

        app_name = self.name_entry_row.get_text().strip()
        if not app_name:
            self.show_toast("Введите название приложения!")
            return

        cat_idx = self.category_row.get_selected()
        category_id = CATEGORIES[cat_idx][0] if cat_idx < len(CATEGORIES) else "Utility"
        scope = "system" if self.scope_row.get_selected() == 1 else "user"
        terminal = self.terminal_switch.get_active()

        chosen_binary = None
        if self.binary_row.get_visible() and self.binary_model.get_n_items() > 0:
            bin_idx = self.binary_row.get_selected()
            chosen_binary = self.binary_model.get_string(bin_idx)

        self.install_btn.set_sensitive(False)
        self.progress_bar.set_visible(True)
        self.progress_bar.pulse()

        import threading
        thread = threading.Thread(
            target=self._run_install_worker,
            args=(
                Path(self.current_pkg_info["source_path"]),
                app_name,
                self.current_pkg_info["detected_type"],
                self.chosen_icon_path,
                chosen_binary,
                scope,
                category_id,
                terminal
            ),
            daemon=True
        )
        thread.start()

    def _run_install_worker(self, src, name, ptype, icon, binary, scope, cat, term):
        try:
            res = self.installer.install(
                source_path=src,
                app_name=name,
                detected_type=ptype,
                icon_path=icon,
                chosen_binary=binary,
                install_scope=scope,
                category=cat,
                terminal=term
            )
            GLib.idle_add(self._on_install_success, name)
        except Exception as e:
            GLib.idle_add(self._on_install_error, str(e))

    def _on_install_success(self, app_name: str):
        self.progress_bar.set_visible(False)
        self.install_btn.set_sensitive(True)
        self.show_toast(f"'{app_name}' успешно установлено!")
        self._load_installed_apps()
        self._load_system_apps()
        self.view_stack.set_visible_child_name("installed")
        self.install_stack.set_visible_child_name("drop_zone")

    def _on_install_error(self, err_msg: str):
        self.progress_bar.set_visible(False)
        self.install_btn.set_sensitive(True)
        self.status_label.set_text(f"Ошибка: {err_msg}")
        self.show_toast(f"Ошибка: {err_msg}")

    def on_uninstall_clicked(self, app_data: Dict[str, Any]):
        app_name = app_data.get("name", "приложение")
        dialog = Adw.MessageDialog(
            transient_for=self,
            heading=f"Удалить {app_name}?",
            body="Файлы программы и ярлык будут полностью удалены."
        )
        dialog.add_response("cancel", "Отмена")
        dialog.add_response("delete", "Удалить")
        dialog.set_response_appearance("delete", Adw.ResponseAppearance.DESTRUCTIVE)

        def on_response(dlg, response):
            if response == "delete":
                ok, msg = InstallerEngine.uninstall(app_data)
                self.show_toast(msg)
                self._load_installed_apps()
                self._load_system_apps()

        dialog.connect("response", on_response)
        dialog.present()

    def on_system_app_uninstall_clicked(self, app_item: Dict[str, Any]):
        app_name = app_item.get("name", "приложение")
        pkg_type = app_item.get("pkg_type", "программу")
        path_str = app_item.get("path", "")

        dialog = Adw.MessageDialog(
            transient_for=self,
            heading=f"Удалить {app_name}?",
            body=f"Тип программы: {pkg_type}\nРасположение: {path_str}\n\nБудет выполнено удаление пакета/ярлыка."
        )
        dialog.add_response("cancel", "Отмена")
        dialog.add_response("delete", "Удалить")
        dialog.set_response_appearance("delete", Adw.ResponseAppearance.DESTRUCTIVE)

        def on_response(dlg, response):
            if response == "delete":
                ok, msg = InstallerEngine.uninstall_system_app(app_item)
                self.show_toast(msg)
                self._load_system_apps()

        dialog.connect("response", on_response)
        dialog.present()


class InstaLinuxApp(Adw.Application):
    def __init__(self):
        super().__init__(
            application_id="io.github.instalinux.InstaLinux",
            flags=Gio.ApplicationFlags.FLAGS_NONE
        )

    def do_activate(self):
        win = self.props.active_window
        if not win:
            win = InstaLinuxWindow(application=self)
        win.present()

def main():
    app = InstaLinuxApp()
    return app.run(sys.argv)
