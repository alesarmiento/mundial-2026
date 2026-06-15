#!/usr/bin/env bash
# Regenera el panel y lo publica en GitHub Pages (alesarmiento/mundial-2026).
# El repo es autocontenido: motor + datos + index.html. Sirve para correr local o en la nube.
# Uso: ./deploy.sh   |   ./deploy.sh --sims 20000
set -e
cd "$(dirname "$0")"

python3 engine.py "$@"

FECHA=$(python3 -c "import json;print(json.load(open('data/results.json'))['_meta']['ultima_fecha_cargada'])" 2>/dev/null || echo "")
git add -A
if git commit -m "auto: actualizar Mundial 2026 (fecha ${FECHA})" >/dev/null 2>&1; then
  git push origin main
  echo "Publicado. URL: https://alesarmiento.github.io/mundial-2026/"
else
  echo "Sin cambios que publicar."
fi
