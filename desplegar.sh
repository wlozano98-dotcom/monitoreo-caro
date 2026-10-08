#!/bin/sh
# Publica el tablero. Pone la huella de estilos.css y app.js en sus enlaces para que Safari no muestre versiones viejas.
set -e
cd "$(dirname "$0")"
export PATH="$PWD/../Proyecto Moni/bin/node/bin:$PATH"
set -a; . ./.env; set +a
css=$(shasum public/estilos.css | cut -c1-8)
js=$(shasum public/app.js | cut -c1-8)
sed -i '' -E "s#estilos\.css(\?v=[0-9a-f]+)?\"#estilos.css?v=$css\"#; s#app\.js(\?v=[0-9a-f]+)?\"#app.js?v=$js\"#" public/index.html
CLOUDFLARE_API_TOKEN=$CLOUDFLARE_TOKEN npx wrangler deploy
