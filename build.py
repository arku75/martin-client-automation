#!/usr/bin/env python3
"""
build.py — Empaqueta el programa en un solo archivo ejecutable.

Genera `client_content_publisher.pyz` con zipapp, de la propia biblioteca estandar.
Ese archivo funciona tal cual en Linux, macOS y Windows: lo unico que hace
falta en el ordenador de destino es Python 3.10 o superior.

    python3 build.py

No usa PyInstaller a proposito: PyInstaller produce un binario por sistema
operativo y hay que compilarlo en cada uno. Un .pyz es el mismo archivo para
todos y pesa unos 60 KB.
"""
from __future__ import annotations

import shutil
import sys
import zipapp
from pathlib import Path

HERE = Path(__file__).resolve().parent
BUILD = HERE / "build"
OUT = HERE / "dist" / "client_content_publisher.pyz"

# Lo que entra en el paquete. La interfaz y los idiomas viajan dentro del .pyz.
INCLUDE = ["core.py", "app.py", "ui.html", "app.js", "i18n.json"]

MAIN = '''# punto de entrada del paquete
import sys, os
from pathlib import Path
sys.path.insert(0, os.path.dirname(__file__))
import app
sys.exit(app.main())
'''

# ── Lanzadores: doble clic y listo, sin tocar la terminal ──

BAT = r'''@echo off
title Client Content Publisher
cd /d "%~dp0"

rem Busca Python. En Windows suele estar como "py"; si no, como "python".
where py >nul 2>&1 && (py -3 client_content_publisher.pyz & goto :eof)
where python >nul 2>&1 && (python client_content_publisher.pyz & goto :eof)

echo.
echo   Python is missing. It is the only thing this program needs.
echo.
echo   1. The download page will open.
echo   2. Download Python and run the installer.
echo   3. IMPORTANT: tick the box "Add python.exe to PATH".
echo   4. When it finishes, open this file again.
echo.
pause
start https://www.python.org/downloads/
'''

COMMAND = r'''#!/bin/bash
# Doble clic en macOS
cd "$(dirname "$0")"
if command -v python3 >/dev/null 2>&1; then
  python3 client_content_publisher.pyz
else
  echo
  echo "  Python is missing. It is the only thing this program needs."
  echo "  The download page will open: install Python and open this file again."
  echo
  read -n 1 -s -r -p "  Press any key..."
  open https://www.python.org/downloads/
fi
'''

DESKTOP = '''[Desktop Entry]
Type=Application
Name=Client Content Publisher
Comment=Prepare articles from a DOCX and photo; configure your own publishing API
Exec=sh -c 'cd "$(dirname "%k")" && python3 client_content_publisher.pyz'
Icon=text-editor
Terminal=false
Categories=Office;Publishing;
'''

SH = '''#!/bin/bash
# Doble clic en Linux (o: ./Abrir\\ Avanture\\ Publisher.sh)
cd "$(dirname "$0")"
python3 client_content_publisher.pyz || {
  echo "Python 3 is missing. Install it with:  sudo apt install python3"
  read -n 1 -s -r -p "Press any key..."
}
'''

READMETXT = """CLIENT CONTENT PUBLISHER — PUBLIC EDITION

Requires Python 3.10 or newer. Run the launcher for your operating system,
or run: python3 client_content_publisher.pyz

The application runs on your computer and opens a browser interface.
No client account, website endpoint or credential is included.
Import a DOCX and photo to preview and edit locally. Publishing requires
Settings > Site with your own compatible API and login. Image uploads are
disabled until you explicitly choose your own provider in Advanced mode.

English, Slovenian and Spanish are available in the language menu.
Draft is the default publishing status. Read MANUAL.md for setup, API
compatibility, optional network features and data storage.

Source: https://github.com/arku75/martin-client-automation
License: MIT (see LICENSE)
"""

LAUNCHERS = {
    "Open Client Content Publisher.bat": (BAT, 0o644),
    "Open Client Content Publisher.command": (COMMAND, 0o755),
    "Open Client Content Publisher.sh": (SH, 0o755),
    "Client Content Publisher.desktop": (DESKTOP, 0o755),
    "README.txt": (READMETXT, 0o644),
}


def build() -> int:
    if sys.version_info < (3, 10):
        print("Necesitas Python 3.10 o superior para construir el paquete.")
        return 1

    if BUILD.exists():
        shutil.rmtree(BUILD)
    BUILD.mkdir(parents=True)
    OUT.parent.mkdir(parents=True, exist_ok=True)

    for name in INCLUDE:
        src = HERE / name
        if not src.exists():
            print(f"Falta {name}")
            return 1
        shutil.copy2(src, BUILD / name)
    (BUILD / "__main__.py").write_text(MAIN, "utf-8")

    zipapp.create_archive(BUILD, OUT, interpreter="/usr/bin/env python3",
                          compressed=True)
    OUT.chmod(0o755)
    shutil.rmtree(BUILD)

    # Lanzadores para abrirlo con doble clic en cualquier sistema.
    for name, (content, mode) in LAUNCHERS.items():
        f = OUT.parent / name
        # Los .bat necesitan saltos de línea de Windows.
        nl = "\r\n" if name.endswith(".bat") else "\n"
        f.write_text(content, "utf-8", newline=nl)
        f.chmod(mode)

    # Zip con todo dentro, listo para enviar al cliente.
    zip_path = OUT.parent.parent / "ClientContentPublisher.zip"
    if zip_path.exists():
        zip_path.unlink()
    import zipfile as _zip
    with _zip.ZipFile(zip_path, "w", _zip.ZIP_DEFLATED) as z:
        # Package generated outputs only, never arbitrary files from dist/.
        for name in [OUT.name, *LAUNCHERS]:
            f = OUT.parent / name
            z.write(f, f"ClientContentPublisher/{f.name}")
        z.write(HERE / "README.md", "ClientContentPublisher/MANUAL.md")
        z.write(HERE / "LICENSE", "ClientContentPublisher/LICENSE")
        z.write(HERE / "README.es.md", "ClientContentPublisher/README.es.md")
        z.write(HERE / "CHANGELOG.md", "ClientContentPublisher/CHANGELOG.md")
        z.write(HERE / "docs/API.md", "ClientContentPublisher/docs/API.md")

    size = OUT.stat().st_size / 1024
    print(f"\n  Listo: {OUT}  ({size:.0f} KB)")
    print(f"  ZIP para enviar: {zip_path}  ({zip_path.stat().st_size // 1024} KB)")
    print(f"  Carpeta para entregar: {OUT.parent}\n")
    print("  Doble clic:      «Abrir Client Content Publisher» (.bat / .command / .sh)")
    print("  O por terminal:  python3 client_content_publisher.pyz\n")
    return 0


if __name__ == "__main__":
    sys.exit(build())
