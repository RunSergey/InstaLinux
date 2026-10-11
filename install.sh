#!/usr/bin/env bash
# ==============================================================================
# InstaLinux - Скрипт автоматической установки
# Поддерживает Debian, Ubuntu, Linux Mint и производные дистрибутивы
# ==============================================================================

set -e

# Цвета для красивого вывода
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${BLUE}==============================================${NC}"
echo -e "${BLUE}        Установка InstaLinux в систему        ${NC}"
echo -e "${BLUE}==============================================${NC}"

# Проверка зависимостей системы
echo -e "${YELLOW}--> Проверка системных зависимостей...${NC}"
MISSING_PKGS=""

for pkg in python3 python3-gi gir1.2-gtk-4.0 gir1.2-adw-1 tar unzip; do
    if ! dpkg -s "$pkg" >/dev/null 2>&1; then
        MISSING_PKGS="$MISSING_PKGS $pkg"
    fi
done

if [ -n "$MISSING_PKGS" ]; then
    echo -e "${YELLOW}--> Обнаружены недостающие пакеты:${MISSING_PKGS}${NC}"
    echo -e "${YELLOW}--> Устанавливаем через apt (потребуется sudo)...${NC}"
    sudo apt update
    sudo apt install -y $MISSING_PKGS
else
    echo -e "${GREEN}Все необходимые системные библиотеки уже установлены!${NC}"
fi

# Пути установки
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_DIR="$HOME/.local/share/instalinux/app"
BIN_DIR="$HOME/.local/bin"
DESKTOP_DIR="$HOME/.local/share/applications"
ICONS_DIR="$HOME/.local/share/icons/hicolor"

echo -e "${YELLOW}--> Создание директорий...${NC}"
mkdir -p "$INSTALL_DIR"
mkdir -p "$BIN_DIR"
mkdir -p "$DESKTOP_DIR"
mkdir -p "$ICONS_DIR/scalable/apps"

echo -e "${YELLOW}--> Копирование файлов InstaLinux...${NC}"
rm -rf "$INSTALL_DIR"/*
cp -r "$SCRIPT_DIR/src" "$INSTALL_DIR/"
cp "$SCRIPT_DIR/main.py" "$INSTALL_DIR/"

# Иконки (SVG + PNG всех размеров для дока GNOME и трея)
echo -e "${YELLOW}--> Установка иконок приложения...${NC}"
if [ -f "$SCRIPT_DIR/assets/instalinux.svg" ]; then
    cp "$SCRIPT_DIR/assets/instalinux.svg" "$ICONS_DIR/scalable/apps/instalinux.svg"
    cp "$SCRIPT_DIR/assets/instalinux.svg" "$ICONS_DIR/scalable/apps/io.github.instalinux.InstaLinux.svg"
fi

for size in 16 24 32 48 64 128 256; do
    if [ -f "$SCRIPT_DIR/assets/instalinux_${size}.png" ]; then
        mkdir -p "$ICONS_DIR/${size}x${size}/apps"
        cp "$SCRIPT_DIR/assets/instalinux_${size}.png" "$ICONS_DIR/${size}x${size}/apps/instalinux.png"
        cp "$SCRIPT_DIR/assets/instalinux_${size}.png" "$ICONS_DIR/${size}x${size}/apps/io.github.instalinux.InstaLinux.png"
    fi
done

# Исполняемый скрипт в ~/.local/bin/instalinux
cat << 'EOF' > "$BIN_DIR/instalinux"
#!/usr/bin/env bash
python3 "$HOME/.local/share/instalinux/app/main.py" "$@"
EOF

chmod +x "$BIN_DIR/instalinux"

# Ярлык в меню приложений
cat << EOF > "$DESKTOP_DIR/io.github.instalinux.InstaLinux.desktop"
[Desktop Entry]
Version=1.0
Type=Application
Name=InstaLinux
Comment=Универсальный установщик программ (.deb, .AppImage, архивы, .sh)
Exec=$BIN_DIR/instalinux %U
Icon=instalinux
Terminal=false
Categories=System;Utility;PackageManager;
StartupWMClass=io.github.instalinux.InstaLinux
Keywords=installer;deb;appimage;package;tar;zip;установщик;
StartupNotify=true
EOF

chmod +x "$DESKTOP_DIR/io.github.instalinux.InstaLinux.desktop"
cp "$DESKTOP_DIR/io.github.instalinux.InstaLinux.desktop" "$DESKTOP_DIR/instalinux.desktop"

# Обновляем базу данных меню и кэш иконок
if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$DESKTOP_DIR" 2>/dev/null || true
fi
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
    gtk-update-icon-cache -f -t "$ICONS_DIR" 2>/dev/null || true
fi

echo -e "${GREEN}==============================================${NC}"
echo -e "${GREEN}      InstaLinux успешно установлен!        ${NC}"
echo -e "${GREEN}==============================================${NC}"
echo -e "Теперь вы можете:"
echo -e "1. Найти ${BLUE}InstaLinux${NC} в главном меню приложений вашей системы."
echo -e "2. Или запустить его из любого терминала командой: ${YELLOW}instalinux${NC}"
echo ""
