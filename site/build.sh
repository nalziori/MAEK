#!/bin/sh
# Assemble the static Pages site into _site/ (used by CI and for local preview).
set -eu
cd "$(dirname "$0")/.."
untracked=$(git ls-files --others site/ | grep -vE "node_modules|/\.shots/|peek[0-9]*\.mjs" || true)
if [ -n "$untracked" ]; then echo "ERROR: site files not in git (Pages would 404):"; echo "$untracked"; exit 1; fi
rm -rf _site
mkdir -p _site/assets/fonts
cp -R site/. _site/
rm -f _site/build.sh _site/verify-site.mjs _site/package.json _site/package-lock.json
rm -rf _site/node_modules _site/.shots _site/.gitignore _site/peek.mjs
cp dashboard/assets/fonts/PretendardVariable.woff2 dashboard/assets/fonts/OFL.txt _site/assets/fonts/
cp docs/MAEK_demo.mp4 _site/assets/demo.mp4
touch _site/.nojekyll
echo "site built: $(du -sh _site | cut -f1)"
