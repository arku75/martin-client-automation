#!/bin/bash
# Doble clic en Linux (o: ./Abrir\ Avanture\ Publisher.sh)
cd "$(dirname "$0")"
python3 client_content_publisher.pyz || {
  echo "Python 3 is missing. Install it with:  sudo apt install python3"
  read -n 1 -s -r -p "Press any key..."
}
