#!/usr/bin/env bash
set -euo pipefail
G="\033[0;32m"; R="\033[0;31m"; N="\033[0m"
ok() { echo -e "  ${G}+${N} $1"; }
fail() { echo -e "  ${R}x${N} $1"; }
echo ""; echo "Manim Video Skill — Setup Check"; echo ""
errors=0
if command -v python3 &>/dev/null; then ok "Python $(python3 --version 2>&1 | awk '{print $2}')"; else fail "Python 3 not found"; errors=$((errors+1)); fi
if python3 -c "import manim" 2>/dev/null; then ok "Manim $(manim --version 2>&1 | head -1)"; else fail "Manim not installed: pip install manim"; errors=$((errors+1)); fi
if command -v pdflatex &>/dev/null; then ok "LaTeX (pdflatex)"; else fail "LaTeX not found (macOS: brew install --cask mactex-no-gui)"; errors=$((errors+1)); fi
if command -v ffmpeg &>/dev/null; then ok "ffmpeg"; else fail "ffmpeg not found"; errors=$((errors+1)); fi
echo ""
[ $errors -eq 0 ] && echo -e "${G}All prerequisites satisfied.${N}" || echo -e "${R}$errors prerequisite(s) missing.${N}"
echo ""
