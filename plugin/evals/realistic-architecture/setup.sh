here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cp -r "$here/../_fixtures/densepack-scripts/." .
if [ -d "$here/resources" ]; then cp -r "$here/resources/." .; fi
mkdir -p ../fonts && mv _fonts/* ../fonts/ && rmdir _fonts
