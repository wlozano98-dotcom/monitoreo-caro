"""Dónde YA hay emergencia (pedido de Andrés), para marcarlo en el mapa de lluvias. Dos fuentes:

- SitRep de la SNGR (gestionderiesgos.gob.ec, informes de situación en PDF): ríos desbordados, ríos con tendencia a
  subir, declaratorias de emergencia cantonales, COE cantonales en alerta roja y albergues abiertos. Es lo oficial.
- Copernicus (Servicio de Monitoreo Global de Inundaciones, vía el WMS público de GloFAS): agua detectada por radar
  Sentinel-1, que ve a través de las nubes. Pasa por cada zona cada pocos días; no ve bien bajo el bosque ni dentro de
  las ciudades, y en zonas arroceras puede contar campos inundados. Se cuenta en km² por cantón.
"""

import json
import math
import re
import time
import unicodedata
import urllib.error
import urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

from lectores import png, texto_pdf

UA = {"User-Agent": "Mozilla/5.0 (monitoreo-caro, tablero interno SNGR)"}
PAGINA_SITREP = "https://www.gestionderiesgos.gob.ec/sitrep-eventos-de-lluvias-por-alerta-roja/"
GLOFAS = "https://ows.globalfloods.eu/glofas-ows/ows.py"
COLOR_AGUA = (232, 76, 120)  # así pinta Copernicus la inundación observada
CAJA = (-81.1, -5.1, -75.1, 1.5)  # Ecuador continental
CUADRO = 0.75  # grados por cuadro pedido (más grande y el servicio dibuja contornos en vez del agua)
DIAS_SATELITE = 7
AGUA_MINIMA = 1.0  # km²: menos que eso en un cantón no se marca (manchas sueltas)


def pedir(url, timeout=120, intentos=3):
    for k in range(intentos):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
                return r.read()
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as e:
            if k == intentos - 1 or (isinstance(e, urllib.error.HTTPError) and e.code < 500):
                raise
            time.sleep(4 * (k + 1))


def clave(texto):
    """Mayúsculas, sin tildes ni espacios: el texto de los PDF viene con espacios partidos ("S imón Bolívar")."""
    t = unicodedata.normalize("NFD", texto or "")
    return "".join(c for c in t if unicodedata.category(c) != "Mn" and not c.isspace()).upper()


# ---------------------------------------------------------------- SitRep


SECCIONES = [  # (lo que abre la sección, marca); None la cierra
    ("CUERPOSHIDRICOSDESBORDADOS", "desbordado"),
    ("CONTENDENCIAAUMENTARDENIVEL", "subiendo"),
    ("EVENTOSADVERSOSYAFECTACIONES", None),
    ("LOJAMIENTOSTEMPORALES", "albergue"),
    ("DECLARATORIASEMITIDASYCOE", "coe"),
    ("DECLARATORIASDEEMERGENCIAPROVINCIAL", None),
    ("DECLARATORIASDEEMERGENCIACANTONAL", "emergencia"),
    ("DECRETO", None),
    ("COMITESDEOPERACIONESDEEMERGENCIAS", None),
]


def ultimo_sitrep():
    """Número, fecha y enlace del último SitRep nacional de lluvias (los provinciales no traen el rango de fechas)."""
    html = pedir(PAGINA_SITREP).decode("utf-8", "replace")
    mejor = None
    for m in re.finditer(r'href="([^"]*SitRep-No-(\d+)-Lluvias-\d{8}-al-(\d{8})-(\d{2})h(\d{2})[^"]*\.pdf)"', html, re.I):
        url, num, dia, h, mi = m.groups()
        if not mejor or int(num) > mejor["numero"]:
            mejor = {"numero": int(num), "url": url, "fecha": f"{dia[4:]}-{dia[2:4]}-{dia[:2]}T{h}:{mi}"}
    return mejor


def marcas_sitrep(lineas, cantones):
    """Por cantón, qué dice el SitRep. `cantones` = {id: (provincia, cantón)} con los nombres del mapa."""
    nombres = sorted(((clave(p), clave(c), i) for i, (p, c) in cantones.items()), key=lambda t: -len(t[1]))
    marcas, modo = defaultdict(list), None
    for linea in lineas:
        k = clave(linea)
        for abre, nuevo in SECCIONES:
            if abre in k:
                modo = nuevo
        if not modo or k.startswith("FUENTE"):
            if k.startswith("FUENTE"):
                modo = None
            continue
        if modo == "coe" and not (k.startswith("CANTONAL") and "ROJA" in k):
            continue
        fecha = re.search(r"(\d{1,2})\s*/\s*(\d{1,2})\s*/\s*(\d{4})", linea)
        if not fecha:  # las filas de las tablas siempre traen fecha; así se descarta la prosa ("alojamiento" ≠ Loja)
            continue
        hallados = []
        for prov, cant, i in nombres:
            if prov in k and cant in k.replace(prov, "", 1) and not any(cant in otro for otro in hallados):
                hallados.append(cant)
                dato = {"tipo": modo, "fecha": f"{fecha.group(3)}-{int(fecha.group(2)):02d}-{int(fecha.group(1)):02d}"}
                if dato not in marcas[i]:
                    marcas[i].append(dato)
    return marcas


def cifras_sitrep(lineas):
    """Los totales de "Puntos importantes" y de afectaciones. Los números vienen partidos ("3 7 4", "22. 374")."""
    t = re.sub(r"(?<=\d)[ .]+(?=\d)", "", " ".join(lineas))
    t = re.sub(r"\s+", " ", t)
    patrones = {
        "eventos": r"registrado (\d+) eventos",
        "provincias": r"(\d+) provincias, \d+ cantones",
        "cantones": r"\d+ provincias, (\d+) cantones",
        "impactadas": r"impactaron a (\d+) ?personas",
        "afectadas": r"Personas afectadas: ?(\d+)",
        "damnificadas": r"Personas damnificadas: ?(\d+)",
        "fallecidas": r"Personas fallecidas: ?(\d+)",
        "viviendas_afectadas": r"Viviendas afectadas: ?(\d+)",
        "viviendas_destruidas": r"Viviendas destruidas: ?(\d+)",
        "bienes": r"total de (\d+) bienes",
    }
    salida = {}
    for k, p in patrones.items():
        m = re.search(p, t, re.I)
        if m:
            salida[k] = int(m.group(1))
    return salida


def sitrep(db, cantones):
    """Marcas del último SitRep; se lee el PDF solo cuando sale uno nuevo."""
    ultimo = ultimo_sitrep()
    if not ultimo:
        raise RuntimeError("no se encontró el SitRep nacional en la página de la SNGR")
    guardado = db.q("SELECT datos FROM sitrep WHERE numero = ?", [ultimo["numero"]])
    datos = json.loads(guardado[0]["datos"]) if guardado else {}
    if "cifras" not in datos:
        lineas = texto_pdf(pedir(ultimo["url"], timeout=180))
        datos = dict(ultimo, marcas={str(k): v for k, v in marcas_sitrep(lineas, cantones).items()},
                     cifras=cifras_sitrep(lineas))
        db.q("INSERT OR REPLACE INTO sitrep (numero, datos) VALUES (?, ?)", [ultimo["numero"], json.dumps(datos, ensure_ascii=False)])
    print(f"  SitRep n.º {datos['numero']}: {len(datos['marcas'])} cantones con marcas")
    return datos


# ---------------------------------------------------------------- Copernicus: agua vista por satélite


def a_mercator(lon, lat):
    return lon * 20037508.34 / 180, math.log(math.tan((90 + lat) * math.pi / 360)) * 6378137


def de_mercator(x, y):
    return x * 180 / 20037508.34, math.degrees(2 * math.atan(math.exp(y / 6378137)) - math.pi / 2)


def imagen(capa, fecha, o, s, e, n, ancho, alto):
    x1, y1 = a_mercator(o, s)
    x2, y2 = a_mercator(e, n)
    url = (f"{GLOFAS}?service=WMS&version=1.3.0&request=GetMap&layers={capa}&styles=&crs=EPSG:3857"
           f"&bbox={x1},{y1},{x2},{y2}&width={ancho}&height={alto}&format=image/png&transparent=true&time={fecha}T00:00:00Z")
    datos = pedir(url)
    return png(datos) if len(datos) > 300 else None  # ~140 bytes = imagen vacía


def cuadros():
    o, s, e, n = CAJA
    salida, lat = [], s
    while lat < n:
        lon = o
        while lon < e:
            salida.append((lon, lat, min(lon + CUADRO, e), min(lat + CUADRO, n)))
            lon += CUADRO
        lat += CUADRO
    return salida


def cuadros_con_pasada(fecha):
    """Qué cuadros cubrió el satélite ese día (de la huella de Sentinel-1); vacío si no pasó por Ecuador."""
    o, s, e, n = CAJA
    ancho, alto = 600, 660
    img = imagen("gfm_sentinel_1_footprint", fecha, o, s, e, n, ancho, alto)
    if not img:
        return []
    _, _, paleta, filas, canales = img
    y_n, y_s = a_mercator(0, n)[1], a_mercator(0, s)[1]
    cubiertos = []
    for c in cuadros():
        j1, j2 = int((c[0] - o) / (e - o) * ancho), int((c[2] - o) / (e - o) * ancho)
        i1 = int((y_n - a_mercator(0, c[3])[1]) / (y_n - y_s) * alto)
        i2 = int((y_n - a_mercator(0, c[1])[1]) / (y_n - y_s) * alto)
        visto = False
        for i in range(max(0, i1), min(alto, i2), 3):
            fila = filas[i]
            for j in range(max(0, j1), min(ancho, j2), 3):
                alfa = paleta[fila[j]][3] if paleta else fila[j * canales + canales - 1]
                if alfa:
                    visto = True
                    break
            if visto:
                break
        if visto:
            cubiertos.append(c)
    return cubiertos


def agua_en_cuadro(fecha, c, rejilla):
    """km² de agua detectada por cantón dentro de un cuadro."""
    lado = 512
    img = imagen("gfm_observed_flood_extent_group_layer", fecha, *c, lado, lado)
    km2 = defaultdict(float)
    if not img:
        return km2
    _, _, paleta, filas, _ = img
    if not paleta:
        return km2
    indices = {k for k, p in enumerate(paleta) if p[:3] == COLOR_AGUA and p[3]}
    if not indices:
        return km2
    x1, y1 = a_mercator(c[0], c[1])
    x2, y2 = a_mercator(c[2], c[3])
    px, py = (x2 - x1) / lado, (y2 - y1) / lado
    for i, fila in enumerate(filas):
        if not any(v in indices for v in set(fila)):
            continue
        lat = de_mercator(0, y2 - (i + 0.5) * py)[1]
        area = px * py * math.cos(math.radians(lat)) ** 2 / 1e6
        for j, v in enumerate(fila):
            if v in indices:
                canton = rejilla.valor(c[0] + (j + 0.5) * (c[2] - c[0]) / lado, lat)
                if canton:
                    km2[canton] += area
    return km2


def agua_del_dia(fecha, rejilla):
    cubiertos = cuadros_con_pasada(fecha)
    total, fallidos = defaultdict(float), 0

    def uno(c):
        try:
            return agua_en_cuadro(fecha, c, rejilla)
        except Exception as e:
            print(f"    cuadro {c} del {fecha}: {e}")
            return None

    with ThreadPoolExecutor(3) as ex:  # el servidor de Copernicus responde 502 si se le pide mucho a la vez
        for parcial in ex.map(uno, cubiertos):
            if parcial is None:
                fallidos += 1
                continue
            for k, v in parcial.items():
                total[k] += v
    return {"paso": bool(cubiertos), "incompleto": bool(fallidos),
            "km2": {str(k): round(v, 2) for k, v in total.items() if v >= AGUA_MINIMA}}


def agua_satelite(db, rejilla, hoy=None):
    """Agua detectada en los últimos días, por cantón: la pasada más reciente con agua (km² y fecha).
    Los días ya cerrados se guardan; hoy y ayer se vuelven a revisar porque Copernicus procesa con horas de retraso."""
    hoy = hoy or datetime.now(timezone.utc).date()
    fechas = [(hoy - timedelta(days=d)).isoformat() for d in range(DIAS_SATELITE)]
    guardados = {f["fecha"]: json.loads(f["datos"]) for f in
                 db.q(f"SELECT fecha, datos FROM agua_satelite WHERE fecha IN ({','.join('?' * len(fechas))})", fechas)}
    por_dia = {}
    for f in fechas:
        if f in guardados and f < (hoy - timedelta(days=1)).isoformat() and not guardados[f].get("incompleto"):
            por_dia[f] = guardados[f]
            continue
        por_dia[f] = agua_del_dia(f, rejilla)
        db.q("INSERT OR REPLACE INTO agua_satelite (fecha, datos) VALUES (?, ?)", [f, json.dumps(por_dia[f])])
    db.q("DELETE FROM agua_satelite WHERE fecha < ?", [(hoy - timedelta(days=60)).isoformat()])
    por_canton = {}
    for f in sorted(por_dia):  # de la más vieja a la más nueva: queda la última pasada con agua
        for k, v in por_dia[f]["km2"].items():
            if v >= AGUA_MINIMA:
                por_canton[k] = {"km2": v, "fecha": f}
    pasadas = sorted(f for f, d in por_dia.items() if d["paso"])
    print(f"  Satélite: pasadas {pasadas}, {len(por_canton)} cantones con agua detectada")
    return {"pasadas": pasadas, "cantones": por_canton}
