"""Lluvias y ríos: qué cantones conviene preparar (pedido de Andrés, para decidir dónde poner kits).

Una decisión por cantón, pintada en un mapa: rojo "actuar", amarillo "atención". Solo fuentes públicas del visor del
INAMHI (inamhi.geoglows.org) y mapas de la SNGR; no inventa nada y las reglas van escritas en la página:
- Lo que viene: alertas meteorológicas del INAMHI (incluida la de crecida), lluvia pronosticada del INAMHI (modelo WRF,
  ~48 h), riesgo de crecida repentina del FFGS (lluvia pronosticada mayor que la que aguanta la cuenca) y crecida de
  ríos GEOGLOWS en su escenario central comparado con 47 años de historia de cada tramo (no el ícono del visor, que
  muestra el peor de 51 escenarios).
- El terreno: humedad del suelo (FFGS) y lluvia ya caída por satélite (PERSIANN, 72 h).
- Dónde duele: susceptibilidad a inundación y a deslizamientos de la SNGR y cuánta gente vive en esas zonas (WorldPop);
  lo prepara una vez preparar_territorio.py.
Solo biblioteca estándar.
"""

import csv
import gzip
import io
import json
import math
import os
import re
import struct
import unicodedata
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

import emergencias

ECUADOR = timezone(timedelta(hours=-5))
SERVICIOS = "https://services.geoglows.org"
UA = {"User-Agent": "monitoreo-caro (tablero interno SNGR)"}
TESELAS = [(8, 15), (9, 15), (8, 16), (9, 16)]  # Ecuador entero en zoom 5
CAJA = (-81.5, -5.5, -75.0, 1.7)  # oeste, sur, este, norte (Ecuador continental)
GEOSERVER = SERVICIOS + "/geoserver"
NIVELES = {"R0": 0, "R2": 2, "R5": 5, "R10": 10, "R25": 25, "R50": 50, "R100": 100}
NIVELES_INAMHI = {"Bajo": 0, "Medio": 1, "Alto": 2, "Muy Alto": 3, "Crecida": 4}
NOMBRES_INAMHI = ["", "media", "alta", "muy alta", "de crecida"]
AQUI = os.path.dirname(os.path.abspath(__file__))

# Reglas del tablero (van explicadas en la página)
HORIZONTE = 7  # días del pronóstico de ríos que cuentan; más allá es menos confiable
LLUVIA_VIENE = 40  # mm pronosticados por el INAMHI en ~48 h, promedio del cantón
LLUVIA_CAIDA = 50  # mm caídos en 72 h (satélite), promedio del cantón
SUELO_SATURADO = 0.8  # humedad del suelo del FFGS (0 a 1)
RIO_AÑOS = 5  # el escenario central del río alcanza una crecida que en la historia se vio 1 vez cada 5 años o menos
RIO_MINIMO = 1.0  # m3/s: tramos casi secos en la historia no cuentan (el modelo marca "100 años" con cualquier gota)
RIO_CANDIDATOS = 200  # tramos que se revisan a fondo cada día (los de ícono más alto)
COBERTURA_ALERTA = 0.1  # parte del cantón que debe cubrir la alerta del INAMHI
SUSC_INUNDACION = 0.1  # parte del cantón con susceptibilidad ALTA a inundación
SUSC_DESLIZAMIENTO = 0.25  # parte del cantón en las dos clases más altas de deslizamiento


def pedir(url, timeout=90):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
        return r.read()


def normal(texto):
    """Mayúsculas sin tildes, para comparar nombres de cantones entre fuentes."""
    t = unicodedata.normalize("NFD", texto or "")
    return re.sub(r"\s+", " ", "".join(c for c in t if unicodedata.category(c) != "Mn")).upper().strip()


def bonito(nombre):
    """'DISTRITO METROPOLITANO DE QUITO' -> 'Distrito Metropolitano de Quito'."""
    chicas = {"DE", "DEL", "LA", "LAS", "LOS", "Y"}
    palabras = nombre.lower().split()
    return " ".join(p if (i and p.upper() in chicas) else p[:1].upper() + p[1:] for i, p in enumerate(palabras))


# ---------------------------------------------------------------- teselas vectoriales (MVT), lector mínimo


def _varint(b, i):
    r = s = 0
    while True:
        c = b[i]
        i += 1
        r |= (c & 0x7F) << s
        s += 7
        if c < 0x80:
            return r, i


def _campos(b):
    i = 0
    while i < len(b):
        k, i = _varint(b, i)
        f, t = k >> 3, k & 7
        if t == 0:
            v, i = _varint(b, i)
        elif t == 2:
            n, i = _varint(b, i)
            v = b[i : i + n]
            i += n
        elif t == 1:
            v = b[i : i + 8]
            i += 8
        elif t == 5:
            v = b[i : i + 4]
            i += 4
        else:
            raise ValueError(f"tipo protobuf {t}")
        yield f, t, v


def _valor(b):
    for f, _, v in _campos(b):
        if f == 1:
            return v.decode()
        if f == 2:
            return struct.unpack("<f", v)[0]
        if f == 3:
            return struct.unpack("<d", v)[0]
        if f in (4, 5):
            return v
        if f == 6:
            return (v >> 1) ^ -(v & 1)
        if f == 7:
            return bool(v)


def puntos_de_tesela(datos, z, x, y):
    """Propiedades de cada punto de una tesela MVT, con su lon/lat."""
    if datos[:2] == b"\x1f\x8b":
        datos = gzip.decompress(datos)
    salida = []
    for f, _, capa in _campos(datos):
        if f != 3:
            continue
        claves, valores, objetos, ext = [], [], [], 4096
        for g, _, w in _campos(capa):
            if g == 3:
                claves.append(w.decode())
            elif g == 4:
                valores.append(_valor(w))
            elif g == 2:
                objetos.append(w)
            elif g == 5:
                ext = w
        for obj in objetos:
            etiquetas, geom = b"", []
            for g, _, w in _campos(obj):
                if g == 2:
                    etiquetas = w
                elif g == 4:
                    geom = w
            nums, i = [], 0
            while i < len(etiquetas):
                v, i = _varint(etiquetas, i)
                nums.append(v)
            props = {claves[nums[k]]: valores[nums[k + 1]] for k in range(0, len(nums), 2)}
            g3, i = [], 0
            while i < len(geom) and len(g3) < 3:
                v, i = _varint(geom, i)
                g3.append(v)
            if len(g3) == 3:
                px, py = (g3[1] >> 1) ^ -(g3[1] & 1), (g3[2] >> 1) ^ -(g3[2] & 1)
                n = 2**z
                props["lon"] = (x + px / ext) / n * 360 - 180
                props["lat"] = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * (y + py / ext) / n))))
            salida.append(props)
    return salida


def tramos_de_rio(fecha):
    """Puntos de río de GEOGLOWS con su pronóstico wd01..wd14 (wd01 = día de inicialización)."""
    puntos = []
    for x, y in TESELAS:
        url = f"{SERVICIOS}/martin/mvt_hydroviewer_warnings_points/5/{x}/{y}?datetime={fecha}"
        puntos += puntos_de_tesela(pedir(url), 5, x, y)
    return puntos


# ---------------------------------------------------------------- cuadrícula: lluvia satelital y zonas del INAMHI


class Rejilla:
    """La cuadrícula de 0,04° (unos 4 km) que usa la lluvia satelital; sirve también para pintar las zonas de alerta."""

    def __init__(self, x0, y0, dx, dy, filas):
        self.x0, self.y0, self.dx, self.dy, self.filas = x0, y0, dx, dy, filas

    def celda(self, lon, lat):
        i, j = int((lat - self.y0) / self.dy), int((lon - self.x0) / self.dx)
        if 0 <= i < len(self.filas) and 0 <= j < len(self.filas[0]):
            return i, j

    def valor(self, lon, lat):
        c = self.celda(lon, lat)
        if c:
            v = self.filas[c[0]][c[1]]
            return None if v is None or v < 0 else v

    def vacia(self):
        return Rejilla(self.x0, self.y0, self.dx, self.dy, [[0] * len(self.filas[0]) for _ in self.filas])


def fechas_de(espacio, capa):
    """Fechas disponibles de una capa con tiempo en GeoServer (de su GetCapabilities WMS)."""
    xml = pedir(f"{GEOSERVER}/{espacio}/wms?service=WMS&version=1.1.1&request=GetCapabilities", timeout=120).decode()
    trozo = xml[xml.index(f"<Name>{capa}</Name>"):]
    return re.search(r'<Extent name="time"[^>]*>([^<]+)', trozo).group(1).strip().split(",")


def cuadricula(espacio, capa, fecha):
    """Una cuadrícula de GeoServer como números (WCS en texto plano), recortada a Ecuador continental."""
    o, s, e, n = CAJA
    texto = pedir(
        f"{GEOSERVER}/{espacio}/wcs?service=WCS&version=2.0.1&request=GetCoverage&coverageId={espacio}__{capa}"
        f"&format=text/plain&subset=Long({o},{e})&subset=Lat({s},{n})&subset=time(%22{fecha}%22)", timeout=180
    ).decode()
    par = lambda k: float(re.search(rf'{k}", ([-\d.E]+)', texto).group(1))
    filas = [[float(v) for v in linea.split()] for linea in texto.split("Band 0:")[1].strip().splitlines()]
    return Rejilla(par("elt_0_2"), par("elt_1_2"), par("elt_0_0"), par("elt_1_1"), filas)


def alertas_inamhi(ahora_utc):
    """Alertas meteorológicas del INAMHI vigentes ahora (o que empiezan en las próximas 24 h)."""
    lista = json.loads(pedir(f"{SERVICIOS}/api/hydroviewer/get-meteo-warnings").decode().replace("NaN", "null"))["result"]
    limite = ahora_utc + timedelta(hours=24)
    vigentes = []
    for a in lista:
        # Las horas del INAMHI son de Ecuador.
        ini = datetime.fromisoformat(a["start"]).replace(tzinfo=ECUADOR)
        fin = datetime.fromisoformat(a["end"]).replace(tzinfo=ECUADOR)
        if fin >= ahora_utc and ini <= limite and a["warning"] not in {v["no"] for v in vigentes}:
            vigentes.append({"no": a["warning"], "tipo": a["type"], "inicio": a["start"], "fin": a["end"]})
    return vigentes


def pintar_alerta(rejilla, geojson):
    """Marca en la rejilla el nivel más alto de la alerta que cubre el centro de cada celda (relleno par-impar)."""
    for f in geojson.get("features", []):
        nivel = NIVELES_INAMHI.get(f["properties"].get("level"), 0)
        if not nivel:
            continue
        geom = f["geometry"]
        poligonos = geom["coordinates"] if geom["type"] == "MultiPolygon" else [geom["coordinates"]]
        for poligono in poligonos:
            cortes = defaultdict(list)  # fila -> longitudes donde un borde cruza el centro de la fila
            for anillo in poligono:
                for (x1, y1), (x2, y2) in zip(anillo, anillo[1:]):
                    if y1 == y2:
                        continue
                    i_a = math.ceil((min(y1, y2) - rejilla.y0) / rejilla.dy - 0.5)
                    i_b = math.floor((max(y1, y2) - rejilla.y0) / rejilla.dy - 0.5)
                    for i in range(min(i_a, i_b), max(i_a, i_b) + 1):
                        yc = rejilla.y0 + (i + 0.5) * rejilla.dy
                        if min(y1, y2) <= yc < max(y1, y2):
                            cortes[i].append(x1 + (yc - y1) * (x2 - x1) / (y2 - y1))
            ancho = len(rejilla.filas[0])
            for i, xs in cortes.items():
                if not 0 <= i < len(rejilla.filas):
                    continue
                xs.sort()
                for a, b in zip(xs[::2], xs[1::2]):
                    j_a = max(0, math.ceil((a - rejilla.x0) / rejilla.dx - 0.5))
                    j_b = min(ancho - 1, math.floor((b - rejilla.x0) / rejilla.dx - 0.5))
                    for j in range(j_a, j_b + 1):
                        if rejilla.filas[i][j] < nivel:
                            rejilla.filas[i][j] = nivel




# ---------------------------------------------------------------- territorio (lo prepara preparar_territorio.py)


def territorio():
    """Celdas de 0,02° con su cantón, la rejilla para ubicar puntos y las cifras fijas de cada cantón."""
    r = json.load(open(os.path.join(AQUI, "territorio_rejilla.json")))
    ids = []
    for k in range(0, len(r["tramos"]), 2):
        ids += [r["tramos"][k]] * r["tramos"][k + 1]
    rejilla = Rejilla(r["oeste"], r["norte"], r["paso"], -r["paso"],
                      [ids[i * r["ancho"]:(i + 1) * r["ancho"]] for i in range(r["alto"])])
    celdas = [(r["oeste"] + (j + 0.5) * r["paso"], r["norte"] - (i + 0.5) * r["paso"], c)
              for i, fila in enumerate(rejilla.filas) for j, c in enumerate(fila) if c]
    fijo = {c["id"]: c for c in json.load(open(os.path.join(AQUI, "public", "territorio.json")))["cantones"]}
    return celdas, rejilla, fijo


def promedio_por_canton(celdas, fuente):
    suma, n = Counter(), Counter()
    for lon, lat, c in celdas:
        v = fuente.valor(lon, lat)
        if v is not None:
            suma[c] += v
            n[c] += 1
    return {c: suma[c] / n[c] for c in n}


# ---------------------------------------------------------------- fuentes


def lluvia_que_viene(ahora_utc, celdas):
    """Lluvia pronosticada por el INAMHI (WRF, acumulados diarios) para los días que aún no terminan: ~48 h."""
    ahora_iso = ahora_utc.strftime("%Y-%m-%dT%H:%M:%S")
    futuras = [f for f in fechas_de("wrf", "wrf_precipitation_daily") if f[:19] > ahora_iso]
    if not futuras:
        raise RuntimeError("el WRF no tiene días por delante")
    total = Counter()
    for f in futuras:
        for c, v in promedio_por_canton(celdas, cuadricula("wrf", "wrf_precipitation_daily", f)).items():
            total[c] += v
    return total, futuras[-1]


def lluvia_caida(celdas):
    fecha = max(fechas_de("satellite_based_precipitation", "persiann_pdir_72h"))
    return promedio_por_canton(celdas, cuadricula("satellite_based_precipitation", "persiann_pdir_72h", fecha)), fecha


def ffgs(ahora_utc, rejilla):
    """Cuencas del FFGS (corridas cada 6 h): humedad del suelo y si la lluvia pronosticada supera la que aguanta."""
    hoy = ahora_utc.date()
    for fecha in (hoy, hoy - timedelta(days=1)):
        for hora in ("19", "13", "07", "01"):
            dt = f"{fecha} {hora}:00:00"
            cuencas = {}
            for x, y in TESELAS:
                url = f"{SERVICIOS}/martin/mvt_ffgs/5/{x}/{y}?datetime={urllib.parse.quote(dt)}"
                for p in puntos_de_tesela(pedir(url), 5, x, y):
                    cuencas[p["basin"]] = p
            if cuencas:
                por = defaultdict(lambda: {"cuencas": 0, "riesgo": 0, "suelo": []})
                for p in cuencas.values():
                    c = rejilla.valor(p["lon"], p["lat"])
                    ffg, fmap, asm = (float(p.get(k) or -999) for k in ("ffg", "fmap", "asm"))
                    if not c or ffg <= 0:
                        continue
                    por[c]["cuencas"] += 1
                    por[c]["riesgo"] += fmap >= ffg
                    if 0 <= asm <= 1:
                        por[c]["suelo"].append(asm)
                return por, dt
    raise RuntimeError("el FFGS no tiene corridas de hoy ni de ayer")


def maximos_anuales(cid):
    texto = pedir(f"{SERVICIOS}/api/hydroviewer/get-historical-csv?comid={cid}", timeout=180).decode()
    anual = defaultdict(float)
    for x in csv.DictReader(io.StringIO(texto)):
        if x["value"]:
            anual[x["datetime"][:4]] = max(anual[x["datetime"][:4]], float(x["value"]))
    return sorted(anual.values())


def escenario_central(cid, inicio, fechas):
    """Mayor caudal diario del escenario central (promedio de los 51) en las fechas dadas, y su día."""
    texto = pedir(f"{SERVICIOS}/api/hydroviewer/get-forecast-csv?comid={cid}&date={inicio}", timeout=180).decode()
    dia = defaultdict(list)
    for x in csv.DictReader(io.StringIO(texto)):
        if x["flow_avg"] and x["datetime"][:10] in fechas:
            dia[x["datetime"][:10]].append(float(x["flow_avg"]))
    medias = {d: sum(v) / len(v) for d, v in dia.items()}
    return max(((q, d) for d, q in medias.items()), default=(0, None))


def rios(db, puntos, inicio, fechas, rejilla):
    """Crecidas de río en su escenario central, comparadas con la historia simulada de cada tramo (1980-hoy).
    Solo se revisan a fondo los tramos donde el visor muestra ícono de 5 años o más (su peor escenario)."""
    from concurrent.futures import ThreadPoolExecutor

    claves = [f"wd{d:02d}" for d in range(1, 15)]
    dias_idx = [(datetime.fromisoformat(f).date() - inicio).days for f in fechas]
    vistos, candidatos = set(), []
    for p in sorted(puntos, key=lambda p: -max(NIVELES.get(p.get(claves[k]), 0) for k in dias_idx)):
        if p["comid"] in vistos or max(NIVELES.get(p.get(claves[k]), 0) for k in dias_idx) < 5:
            continue
        vistos.add(p["comid"])
        candidatos.append(p)
    candidatos = candidatos[:RIO_CANDIDATOS]
    ids = [p["comid"] for p in candidatos]
    guardados = {}
    for i in range(0, len(ids), 90):
        trozo = ids[i:i + 90]
        for f in db.q(f"SELECT comid, maximos FROM rios_maximos WHERE comid IN ({','.join('?' * len(trozo))})", trozo):
            guardados[f["comid"]] = json.loads(f["maximos"])
    faltan = [c for c in ids if c not in guardados]
    with ThreadPoolExecutor(8) as ex:
        for c, m in zip(faltan, ex.map(maximos_anuales, faltan)):
            guardados[c] = m
        centrales = dict(zip(ids, ex.map(lambda c: escenario_central(c, inicio.isoformat(), set(fechas)), ids)))
    if faltan:
        db.lote([("INSERT OR REPLACE INTO rios_maximos (comid, maximos) VALUES (?, ?)", [c, json.dumps(guardados[c])])
                 for c in faltan])
    por = defaultdict(list)
    descartados = 0
    for p in candidatos:
        anos, (q, dia) = guardados[p["comid"]], centrales[p["comid"]]
        if not anos or anos[len(anos) // 2] < RIO_MINIMO:
            descartados += 1
            continue
        veces = sum(a >= q for a in anos)  # años de la historia con una crecida igual o mayor
        periodo = (len(anos) + 1) / veces if veces else len(anos) + 1
        c = rejilla.valor(p["lon"], p["lat"])
        if c and periodo >= RIO_AÑOS:
            por[c].append({"periodo": round(periodo), "dia": dia, "nunca": not veces})
    print(f"  Ríos: {len(candidatos)} tramos revisados, {descartados} descartados por casi secos, "
          f"{sum(len(v) for v in por.values())} con crecida en el escenario central")
    return por


# ---------------------------------------------------------------- decisión por cantón


def calcular(db, ahora_utc=None):
    ahora_utc = ahora_utc or datetime.now(timezone.utc)
    hoy = ahora_utc.astimezone(ECUADOR).date()
    celdas, rejilla, fijo = territorio()
    fuentes, errores = {}, {}

    def intentar(nombre, funcion, *args):
        try:
            return funcion(*args)
        except Exception as e:
            print(f"  ERROR {nombre}: {e}")
            errores[nombre] = str(e)[:200]

    # Alertas del INAMHI pintadas en la rejilla de cantones
    vigentes = intentar("inamhi", alertas_inamhi, ahora_utc) or []
    zonas = Rejilla(rejilla.x0, rejilla.y0, rejilla.dx, rejilla.dy, [[0] * len(rejilla.filas[0]) for _ in rejilla.filas])
    for a in vigentes:
        geo = intentar("inamhi", lambda n: json.loads(pedir(f"{SERVICIOS}/api/met-data-explorer/get-meteo-warnings?no={n}", timeout=180)), a["no"])
        if geo:
            pintar_alerta(zonas, geo)
    cobertura = defaultdict(Counter)
    celdas_por = Counter()
    for lon, lat, c in celdas:
        celdas_por[c] += 1
        nivel = zonas.valor(lon, lat) or 0
        for n in range(1, nivel + 1):
            cobertura[c][n] += 1
    nivel_inamhi = {c: max((n for n in range(1, 5) if cobertura[c][n] >= COBERTURA_ALERTA * celdas_por[c]), default=0)
                    for c in celdas_por}

    viene = intentar("wrf", lluvia_que_viene, ahora_utc, celdas)
    wrf, fuentes["wrf"] = viene if viene else ({}, None)
    caida = intentar("persiann", lluvia_caida, celdas)
    mm72, fuentes["persiann"] = caida if caida else ({}, None)
    flash = intentar("ffgs", ffgs, ahora_utc, rejilla)
    cuencas, fuentes["ffgs"] = flash if flash else ({}, None)

    # Ríos: el pronóstico GEOGLOWS sale una vez al día; si ya se revisó, se reutiliza
    inicio, puntos = None, []
    for atras in (0, 1, 2):
        fecha = (hoy - timedelta(days=atras)).isoformat()
        puntos = intentar("rios", tramos_de_rio, fecha) or []
        if any(p.get("wd01") for p in puntos):
            inicio = datetime.fromisoformat(fecha).date()
            break
    crecidas = {}
    if inicio:
        fechas = [(hoy + timedelta(days=d)).isoformat() for d in range(HORIZONTE)]
        previa = db.q("SELECT datos FROM lluvias ORDER BY creado DESC LIMIT 1")
        previa = json.loads(previa[0]["datos"]) if previa else {}
        if previa.get("fuentes", {}).get("rios") == inicio.isoformat() and "crecidas" in previa:
            crecidas = {int(k): v for k, v in previa["crecidas"].items()}
        else:
            crecidas = intentar("rios", rios, db, puntos, inicio, fechas, rejilla) or {}
        fuentes["rios"] = inicio.isoformat()

    # Dónde ya hay emergencia: SitRep de la SNGR y agua vista por satélite (no cambian el color: se marcan aparte)
    reporte = intentar("sitrep", emergencias.sitrep, db, {i: (c["provincia"], c["canton"]) for i, c in fijo.items()}) or {}
    satelite = intentar("satelite", emergencias.agua_satelite, db, rejilla) or {}
    ya = {}
    for k, marcas in (reporte.get("marcas") or {}).items():
        resumen = {}
        for m in marcas:  # por tipo, la fecha más reciente y cuántas veces aparece
            r = resumen.setdefault(m["tipo"], {"tipo": m["tipo"], "fecha": m["fecha"], "veces": 0})
            r["veces"] += 1
            r["fecha"] = max(r["fecha"] or "", m["fecha"] or "") or None
        ya[int(k)] = {"sitrep": list(resumen.values())}
    for k, v in (satelite.get("cantones") or {}).items():
        ya.setdefault(int(k), {})["agua"] = v

    filas = []
    for c, info in fijo.items():
        suelo = cuencas.get(c, {}).get("suelo") or []
        suelo = sum(suelo) / len(suelo) if suelo else None
        riesgo = cuencas.get(c, {}).get("riesgo", 0)
        rio = sorted(crecidas.get(c, []), key=lambda r: (-r["periodo"], r["dia"] or ""))
        # Lo que viene. "Fuerte": alerta INAMHI muy alta o de crecida, crecida repentina o río. La alerta alta y la
        # lluvia pronosticada dicen casi lo mismo (va a llover) y solas cubren media sierra: no bastan para el rojo.
        llega = []
        if nivel_inamhi.get(c, 0) >= 2:
            llega.append("inamhi")
        if wrf.get(c, 0) >= LLUVIA_VIENE:
            llega.append("lluvia")
        if riesgo:
            llega.append("repentina")
        if rio:
            llega.append("rio")
        fuerte = nivel_inamhi.get(c, 0) >= 3 or bool(riesgo) or bool(rio)
        terreno = []
        if suelo is not None and suelo >= SUELO_SATURADO:
            terreno.append("suelo")
        if mm72.get(c, 0) >= LLUVIA_CAIDA:
            terreno.append("caida")
        inund = info["inund_alta"] >= SUSC_INUNDACION
        desl = info["desl_alta"] >= SUSC_DESLIZAMIENTO
        # Rojo: viene algo fuerte y el terreno ya está mojado. La susceptibilidad no decide el color (las crecidas
        # repentinas pasan también fuera de las llanuras inundables): dice qué kit llevar y cuánta gente vive ahí.
        if fuerte and terreno:
            color = "rojo"
        elif (llega and terreno) or (fuerte and (inund or desl)):
            color = "amarillo"
        else:
            continue
        filas.append({
            "id": c, "canton": info["canton"], "provincia": info["provincia"], "color": color,
            "llega": llega, "terreno": terreno, "inund": inund, "desl": desl,
            "inamhi": NOMBRES_INAMHI[nivel_inamhi.get(c, 0)],
            "wrf": round(wrf[c]) if c in wrf else None,
            "mm72": round(mm72[c]) if c in mm72 else None,
            "suelo": round(suelo * 100) if suelo is not None else None,
            "repentina": riesgo, "cuencas": cuencas.get(c, {}).get("cuencas", 0),
            "rio": {"tramos": len(rio), "periodo": rio[0]["periodo"], "dia": rio[0]["dia"], "nunca": rio[0]["nunca"]} if rio else None,
            "pob": info["pob"], "pob_inund": info["pob_inund"], "pob_desl": info["pob_desl"],
            "inund_alta": info["inund_alta"], "desl_alta": info["desl_alta"],
            "ya": ya.get(c),
        })
    # Orden (decisión de Andrés): primero la gente en zona de inundación, que es lo más grave; luego deslizamientos.
    filas.sort(key=lambda f: (f["color"] != "rojo", -f["pob_inund"], -f["pob_desl"]))
    color = {f["id"]: f["color"] for f in filas}
    graves = {"desbordado": 0, "emergencia": 1, "albergue": 2, "coe": 3, "subiendo": 4}
    lista_ya = []
    for c, v in ya.items():
        info = fijo[c]
        primero = min((graves[m["tipo"]] for m in v.get("sitrep", [])), default=9)
        lista_ya.append({"id": c, "canton": info["canton"], "provincia": info["provincia"], "color": color.get(c),
                         "pob": info["pob"], "pob_inund": info["pob_inund"], "pob_desl": info["pob_desl"], **v,
                         "_orden": (primero, -(v.get("agua") or {}).get("km2", 0), -info["pob_inund"])})
    lista_ya.sort(key=lambda f: f.pop("_orden"))
    return {
        "creado": ahora_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "sitrep": {k: reporte.get(k) for k in ("numero", "fecha", "url", "cifras")} if reporte else None,
        "satelite": {"pasadas": satelite.get("pasadas", [])} if satelite else None,
        "ya": lista_ya,
        "inamhi": vigentes,
        "fuentes": fuentes,
        "errores": errores,
        "crecidas": {str(k): v for k, v in crecidas.items()},
        "cantones": filas,
    }


def lluvias(db):
    """Calcula y guarda una foto en `lluvias`. Se llama en cada corrida del monitor."""
    datos = calcular(db)
    db.q("INSERT OR REPLACE INTO lluvias (creado, datos) VALUES (?, ?)", [datos["creado"], json.dumps(datos, ensure_ascii=False)])
    db.q("DELETE FROM lluvias WHERE creado < ?",
         [(datetime.now(timezone.utc) - timedelta(days=60)).strftime("%Y-%m-%dT%H:%M:%SZ")])
    n = Counter(f["color"] for f in datos["cantones"])
    print(f"  Lluvias: rojo {n['rojo']}, amarillo {n['amarillo']}, alertas INAMHI {[a['no'] for a in datos['inamhi']]}, "
          f"errores {list(datos['errores'])}")
    return datos
