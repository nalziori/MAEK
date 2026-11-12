#!/bin/sh
# Build MAEK_offline.zip: the static site + official embeddable Python + START.bat. No install, no internet.
#   sh offline/make_bundle.sh [output dir]
set -eu
cd "$(dirname "$0")/.."
PY_VER=3.12.10
PY_ZIP=python-$PY_VER-embed-amd64.zip
OUT=${1:-dist}
sh site/build.sh
rm -rf "$OUT/MAEK_offline" && mkdir -p "$OUT/MAEK_offline/python" "$OUT/cache"
[ -f "$OUT/cache/$PY_ZIP" ] || curl -fsSL "https://www.python.org/ftp/python/$PY_VER/$PY_ZIP" -o "$OUT/cache/$PY_ZIP"
sha256sum "$OUT/cache/$PY_ZIP"
unzip -q "$OUT/cache/$PY_ZIP" -d "$OUT/MAEK_offline/python"
cp -R _site "$OUT/MAEK_offline/site"
cp offline/serve.py offline/START.bat "$OUT/MAEK_offline/"
printf '\357\273\277' > "$OUT/MAEK_offline/README.txt" && cat offline/README.txt >> "$OUT/MAEK_offline/README.txt"
(cd "$OUT" && rm -f MAEK_offline.zip && powershell -NoProfile -Command "Compress-Archive -Path MAEK_offline -DestinationPath MAEK_offline.zip")
ls -la "$OUT/MAEK_offline.zip"; sha256sum "$OUT/MAEK_offline.zip"
