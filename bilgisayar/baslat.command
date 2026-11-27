#!/bin/bash
# Vadeli Sinyal Tarayıcı — macOS/Linux tek tıkla başlatıcı (Finder'da çift tıklayın).
cd "$(dirname "$0")" || exit 1
PY=""
for aday in python3.13 python3.12 python3.11 python3 python3.10; do
  if command -v "$aday" >/dev/null 2>&1 && "$aday" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
    PY="$aday"; break
  fi
done
if [ -z "$PY" ]; then
  echo "Python 3.11 veya üstü bulunamadı. https://www.python.org/downloads/ adresinden kurun."
  open "https://www.python.org/downloads/" 2>/dev/null
  read -r -p "Kapatmak için Enter'a basın..." _
  exit 1
fi
exec "$PY" baslat.py "$@"
