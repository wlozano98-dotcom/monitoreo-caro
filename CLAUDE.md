# Monitoreo Caro — escucha de medios y redes (El Niño 2026)

Tablero público para Carolina Lozano (Secretaria Nacional de Gestión de Riesgos de Ecuador) y su equipo: qué dicen
medios y redes sobre El Niño, la Secretaría y ella. Presupuesto cero: solo capas gratuitas. Todo en español.

**No tocar ni mezclar con `../Proyecto Moni` ni `../Agente Zimbra AN`.** Misma cuenta de Cloudflare, pero Worker
(`monitoreo-caro`) y base D1 (`monitoreo-caro`) propios. Node se toma prestado de `../Proyecto Moni/bin/node` (solo lectura).

## Piezas

- `monitor.py`: una corrida = recolectar → guardar en D1 (API REST) → clasificar con Gemini (25 piezas por llamada) →
  resumen del día → narrativas. Solo biblioteca estándar.
  Narrativas (pedido de Andrés): cada pieza lleva `aspecto` (rapidez, llegada de la ayuda…) e `idea` (frase genérica);
  `narrativas()` le pide a Gemini que agrupe las ideas de 3 días y las cifras (total, hoy vs ayer, tono, fuentes) se
  cuentan en Python, no las inventa Gemini. El tablero muestra la última agrupación y el marcador bien/mal por aspecto. `--sin-redes`, `--sin-gemini` para probar.
- `redes.py`: X, TikTok y Facebook vía Apify (crédito gratis 5 USD/mes, tope propio 4,5). Solo en la corrida de la noche
  (20-22 h de Ecuador; `REDES_AHORA=1` para forzar). Actores: X kaitoeasyapi (ignora maxItems, para por el tope de
  0,02 USD; `apify()` lee los datos aunque la corrida quede ABORTED), TikTok clockworks~free-tiktok-scraper (apidojo
  limita corridas al mes en cuenta gratis) + clockworks comentarios, Facebook apify posts/comentarios (comentarios solo
  si el post tiene). YouTube va en `monitor.py` con la API oficial (YOUTUBE_KEY, proyecto Google "Monitoreo Caro").
- `.github/workflows/monitor.yml`: cada 2 horas. Repo PÚBLICO a propósito: los minutos de Actions de repos privados
  se comparten con el Agente Asamblea (privado, ~2.000 min/mes) y lo dejaríamos sin minutos. Las claves van en Secrets.
- `src/index.js` + `public/`: Worker que sirve el tablero (sin login, decisión de Andrés) y `/api/tablero` (caché 5 min).
- `migrations/`: esquema de D1 (tabla `piezas`, `resumenes`, `corridas`).

## Comandos

```
export PATH="$PWD/../Proyecto Moni/bin/node/bin:$PATH"; set -a; source .env; set +a
python3 monitor.py                                   # una corrida desde la Mac
./desplegar.sh                                       # publicar el tablero (pone versión a CSS y JS)
```

Análisis de fondo con Claude: rutina en la nube trig_019vffsRRdTVhhguuf5yzBBi (Opus 5.5), 6, 12, 18 y 22 h de Ecuador
(cron `0 3,11,17,23 * * *` UTC). Lee `analisis/contexto.md` (lo deja monitor.yml en la corrida previa), escribe
`analisis/ultimo.json` siguiendo `analisis/INSTRUCCIONES.md`; `analisis.yml` lo valida y lo carga (`analisis_claude.py`).
Regla de Andrés: CERO información falsa. Cada viñeta y acción cita ids de piezas; `validar` rechaza ids inexistentes.
Si hay análisis de Claude de menos de 9 h, Gemini no hace el análisis de fondo (solo clasifica).

Reglas del tablero (decisiones de Andrés):
- Termómetro = un solo indicador: % crítico de las últimas 24 h + 10 puntos por alerta (no depende de los filtros).
- Alertas: en redes solo con >= 20 interacciones (`ALCANCE_MIN_ALERTA`); insultos sin argumento no son alerta.
- Actores: "Gobierno central" reúne Presidencia y ministerios (todo menos SNGR y Carolina). Carolina siempre visible.
- Filtro "Hoy" = últimas 24 h. La caché del API va ligada a la versión publicada (`version_metadata`).
- Mostrar a Andrés los cambios visuales antes de desplegar.
- Fechas: `fecha_iso` quita milisegundos (TikTok/Facebook); una pieza sin fecha usaría `recogido` y parecería de hoy.

URL: https://monitoreo-caro.wlozano98.workers.dev
