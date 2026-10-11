#!/usr/bin/env bash
# ==============================================================================
# InstaLinux - Скрипт удаления программы из системы
# ==============================================================================

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
NC='\033[0m'

echo -e "${RED}Удаление InstaLinux...${NC}"

rm -rf "$HOME/.local/share/instalinux/app"
rm -f "$HOME/.local/bin/instalinux"
rm -f "$HOME/.local/share/applications/instalinux.desktop"
rm -f "$HOME/.local/share/icons/hicolor/scalable/apps/instalinux.svg"

if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$HOME/.local/share/applications" 2>/dev/null || true
fi

echo -e "${GREEN}InstaLinux успешно удален.${NC}"
