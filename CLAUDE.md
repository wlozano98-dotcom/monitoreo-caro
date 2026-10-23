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
- Agenda nacional (pedido de Andrés): cada corrida guarda TODOS los titulares de 24 h de los medios del país
  (`AGENDA_MEDIOS`, Google Noticias `site:` + RSS propios) en `titulares`; cada 4 h `agenda()` le pide a Gemini los
  temas y asigna cada titular (tema 0 = "El Niño y lluvias"); los conteos y el puesto se cuentan en Python.
  Va dentro del panel del nivel. Sin Google Trends (decisión de Andrés). Historial desde el 9 oct 2026. `--solo-agenda` para probar.
  Puente (19 oct): los titulares que la agenda pone en El Niño y que las búsquedas no trajeron entran como piezas
  (`consulta = 'agenda'`, solo 30 h). `guardar` no repite una nota de medio con el mismo título.
- Búsquedas por los EFECTOS (lluvia, inundación, deslave, damnificados…), no por la etiqueta "El Niño": la etiqueta
  perdía ~40 % (p. ej. la suspensión de clases). Así en Google Noticias, YouTube, X, TikTok y el filtro de RSS
  (`PALABRAS`). Gemini descarta lo irrelevante. Andrés descartó las búsquedas que "se ajustan solas" (llegan tarde, derivan).
- `vigilante.py` (pedido de Andrés): cada corrida revisa errores de fuentes, Google Noticias en 0, titulares, cobertura
  (búsquedas vs agenda, mínimo 50 %), redes, Gemini, análisis de Claude, SitRep. monitor.yml además avisa si el
  contexto para Claude tiene más de 7 h (la hora de la corrida se toma al empezar: `HORA_INICIO`). Si hay algo, deja `avisos.txt` y el
  último paso de monitor.yml pone la corrida en rojo -> GitHub manda correo (problema nuevo, o uno viejo 1 vez al día).
  Solo en GitHub (`GITHUB_ACTIONS`). Aviso por correo, sin nada visual en el tablero (decisión de Andrés).
- `lluvias.py` + `public/lluvias.html` (pedido de Andrés: dónde preposicionar kits; SIN medios ni redes): mapa por
  cantón en rojo "actuar" / amarillo "atención" + lista. Fuentes del visor del INAMHI (services.geoglows.org, públicas):
  alertas meteorológicas (nivel "Crecida" incluido), lluvia pronosticada WRF (~48 h), FFGS (crecida repentina = lluvia
  pronosticada >= la que aguanta la cuenca; humedad del suelo), lluvia satelital PERSIANN 72 h y ríos GEOGLOWS.
  Rojo = viene algo fuerte (INAMHI muy alta/crecida, crecida repentina o río) Y terreno mojado. La susceptibilidad SNGR
  NO decide el color: solo el tipo de kit y la población expuesta.
  OJO ríos: el ícono del visor (R2..R100) es el PEOR de 51 escenarios; ya engañó una vez (Azuay "100 años"). Se usa el
  escenario central (flow_avg) contra los máximos anuales 1980-hoy de cada tramo (tabla `rios_maximos`); tramos casi
  secos se descartan (Guayaquil marcaba R100 con caudal 0). Tabla `lluvias`, `/api/lluvias`, `--solo-lluvias`.
- `emergencias.py` (pedido de Andrés: dónde YA hay emergencia; no cambia el color, se marca aparte en el mapa):
  último SitRep nacional de la SNGR (PDF de gestionderiesgos.gob.ec/sitrep-eventos-de-lluvias-por-alerta-roja/, se lee
  con `lectores.py`, solo cuando sale uno nuevo; tabla `sitrep`) -> por cantón: desbordado, subiendo, emergencia, coe,
  albergue (solo filas con fecha). Y agua observada por Copernicus GFM (WMS público de GloFAS, EPSG:3857, cuadros de
  0,75°: más grande y dibuja contornos; color exacto 232,76,120; tabla `agua_satelite` por día). "Emergencia oficial" =
  todo menos "subiendo". Ojo arrozales del Guayas: el radar puede contarlos como agua.
  SitRep provinciales (misma página, nombres de archivo distintos por provincia): `sitreps_provinciales` lee cada PDF
  una vez (tabla `sitrep_prov`), reconoce la provincia y la fecha de publicación, y saca por cantón impactadas,
  afectadas, damnificadas y "personas beneficiadas" (= atendidas; SNGR y otras instituciones, puede repetirse gente).
  `tablas_de_personas` lee el ENCABEZADO para el orden de columnas (cada provincia lo arma distinto; raíces "AFECTAD").
  El mapa tiene vista Cantones / Provincias (provincias pintadas por personas impactadas del SitRep nacional).
  Andrés rechazó el termómetro de % de población: no volver a ponerlo.
- `preparar_territorio.py` (se corre a mano, una vez): cantones (geoBoundaries/INEC), susceptibilidad SNGR a inundación
  (vector BAJA/MEDIA/ALTA) y deslizamientos (clases 1-5, UTM 17S) y población WorldPop 2020 1 km (BigTIFF LZW, lector
  propio; 3 min la primera vez). Las localidades del censo solo dan provincia y tildes. Escribe `public/territorio.json`
  (mapa) y `territorio_rejilla.json`. Descargas grandes en `.territorio/`. Andrés: no hay "kits por tipo", no decirlo.
- `migrations/`: esquema de D1 (tabla `piezas`, `resumenes`, `corridas`).

## Comandos

```
export PATH="$PWD/../Proyecto Moni/bin/node/bin:$PATH"; set -a; source .env; set +a
python3 monitor.py                                   # una corrida desde la Mac
./desplegar.sh                                       # publicar el tablero (pone versión a CSS y JS)
```

Análisis de fondo con Claude: rutina en la nube trig_019vffsRRdTVhhguuf5yzBBi (Opus 5.5), 6, 12, 18 y 22 h de Ecuador
(cron `20 3,11,17,23 * * *` UTC; 20 min de margen porque GitHub arranca tarde las corridas). Lee `analisis/contexto.md` (lo deja monitor.yml en la corrida previa), escribe
`analisis/ultimo.json` siguiendo `analisis/INSTRUCCIONES.md`; `analisis.yml` lo valida y lo carga (`analisis_claude.py`).
Regla de Andrés: CERO información falsa. Cada viñeta y acción cita ids de piezas; `validar` rechaza ids inexistentes.
Si hay análisis de Claude de menos de 9 h, Gemini no hace el análisis de fondo (solo clasifica).

Reglas del tablero (decisiones de Andrés):
- Todo el tablero va pesado por alcance (`peso` = log10 de vistas + interacciones, mínimo 1; nota de medio = 1.000 → 3).
  Sin selector piezas/alcance ni barra de filtros (fuente/sobre/tono; el API aún los acepta por URL). Las cifras de los gráficos son "pts"; las ventanitas dan pts y número de piezas.
- Sin botones de días: todo es acumulado desde el primer día con >= 10 piezas (6 oct). No recuperar historial.
- Termómetro = % del alcance de las últimas 24 h que critica a la SNGR o a Carolina (sin sumar alertas).
- `tono` = solo hacia la SNGR/Carolina (y Gobierno central en la emergencia); lo de alcaldes/GAD va en `actor` +
  `tono_actor`. Alertas: sin actores locales. Narrativas: SÍ incluyen lo que se dice de los GAD ("Apunta a").
- Aspectos y actores: total + ola día a día + "Ver noticias" (`/api/piezas`, ordenado por alcance, sin ocultar bulla).
- Corregir: cualquiera, directo (`/api/corregir`, historial en `correcciones`); la IA ya no reclasifica esa pieza y
  Gemini recibe las últimas 25 como ejemplos. Hitos: los propone la rutina de Claude (`hitos` en ultimo.json).
- Alertas: en redes solo con >= 20 interacciones (`ALCANCE_MIN_ALERTA`); insultos sin argumento no son alerta.
- Actores: "Gobierno central" reúne Presidencia y ministerios (todo menos SNGR y Carolina). Carolina siempre visible.
- La caché del API va ligada a la versión publicada (`version_metadata`).
- Mostrar a Andrés los cambios visuales antes de desplegar.
- Fechas: `fecha_iso` quita milisegundos (TikTok/Facebook); una pieza sin fecha usaría `recogido` y parecería de hoy.

URL: https://monitoreo-caro.wlozano98.workers.dev
