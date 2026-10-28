#!/bin/bash
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
