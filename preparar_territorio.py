"""Prepara una sola vez lo que no cambia: cantones, susceptibilidad de la SNGR y población (para lluvias.py y el mapa).

Fuentes (todas públicas):
- Límites cantonales: geoBoundaries ECU ADM2 (INEC / OCHA, CC BY 3.0 IGO).
- Susceptibilidad a inundación (BAJA/MEDIA/ALTA) y a deslizamientos (clases 1-5): mapas de la SNGR que publica el
  visor del INAMHI (services.geoglows.org/geoserver, capas ecuador:flood y ecuador:landslides).
- Población: WorldPop 2020, 1 km, ajustada a la ONU (CC BY 4.0). Las localidades del censo (capa `locations`)
  solo se usan para saber la provincia y el nombre con tildes de cada cantón.
Escribe `public/territorio.json` (mapa y cifras fijas por cantón) y `territorio_rejilla.json` (qué cantón cae en cada
celda de 0,02°, para que lluvias.py sume la lluvia y las alertas por cantón). Uso: python3 preparar_territorio.py
"""

import json
import math
import os
import re
import struct
import urllib.request
from array import array
from collections import Counter, defaultdict

from lluvias import SERVICIOS, UA, bonito, normal, pedir, puntos_de_tesela

AQUI = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(AQUI, ".territorio")  # descargas grandes, fuera de git
OESTE, NORTE = -81.1, 1.5
ESTE, SUR = -75.1, -5.1
FINO = 0.005  # ~550 m: para susceptibilidad y localidades
GRUESO = 0.02  # ~2,2 km: lo que usa lluvias.py en cada corrida
POR = round(GRUESO / FINO)


def bajar(nombre, url, timeout=600):
    os.makedirs(CACHE, exist_ok=True)
    ruta = os.path.join(CACHE, nombre)
    if not os.path.exists(ruta):
        print(f"  bajando {nombre}…")
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r, open(ruta, "wb") as f:
            f.write(r.read())
    return ruta


class Lienzo:
    """Rejilla fina sobre Ecuador continental donde se pintan polígonos (relleno par-impar por filas)."""

    def __init__(self, paso, tipo="B"):
        self.paso = paso
        self.ancho = round((ESTE - OESTE) / paso)
        self.alto = round((NORTE - SUR) / paso)
        self.v = array(tipo, [0]) * (self.ancho * self.alto)

    def pintar(self, poligono, valor, solo_si_mayor=False):
        cortes = defaultdict(list)
        for anillo in poligono:
            for (x1, y1), (x2, y2) in zip(anillo, anillo[1:]):
                if y1 == y2:
                    continue
                fa = (NORTE - max(y1, y2)) / self.paso - 0.5
                fb = (NORTE - min(y1, y2)) / self.paso - 0.5
                for i in range(max(0, math.ceil(fa)), min(self.alto - 1, math.floor(fb)) + 1):
                    yc = NORTE - (i + 0.5) * self.paso
                    if min(y1, y2) <= yc < max(y1, y2):
                        cortes[i].append(x1 + (yc - y1) * (x2 - x1) / (y2 - y1))
        for i, xs in cortes.items():
            xs.sort()
            base = i * self.ancho
            for a, b in zip(xs[::2], xs[1::2]):
                ja = max(0, math.ceil((a - OESTE) / self.paso - 0.5))
                jb = min(self.ancho - 1, math.floor((b - OESTE) / self.paso - 0.5))
                for j in range(ja, jb + 1):
                    if not solo_si_mayor or self.v[base + j] < valor:
                        self.v[base + j] = valor

    def en(self, lon, lat):
        i, j = int((NORTE - lat) / self.paso), int((lon - OESTE) / self.paso)
        if 0 <= i < self.alto and 0 <= j < self.ancho:
            return self.v[i * self.ancho + j]
        return 0


def poligonos(geom):
    return geom["coordinates"] if geom["type"] == "MultiPolygon" else [geom["coordinates"]]


def utm17s(lon, lat):
    """WGS84 -> UTM zona 17 sur (EPSG:32717), fórmulas de Snyder. El mapa de deslizamientos viene en ese sistema."""
    a, f = 6378137.0, 1 / 298.257223563
    e2 = f * (2 - f)
    ep2 = e2 / (1 - e2)
    k0, lon0 = 0.9996, math.radians(-81)
    fi, la = math.radians(lat), math.radians(lon)
    n = a / math.sqrt(1 - e2 * math.sin(fi) ** 2)
    t, c = math.tan(fi) ** 2, ep2 * math.cos(fi) ** 2
    aa = math.cos(fi) * (la - lon0)
    m = a * ((1 - e2 / 4 - 3 * e2**2 / 64 - 5 * e2**3 / 256) * fi
             - (3 * e2 / 8 + 3 * e2**2 / 32 + 45 * e2**3 / 1024) * math.sin(2 * fi)
             + (15 * e2**2 / 256 + 45 * e2**3 / 1024) * math.sin(4 * fi)
             - (35 * e2**3 / 3072) * math.sin(6 * fi))
    x = k0 * n * (aa + (1 - t + c) * aa**3 / 6 + (5 - 18 * t + t * t + 72 * c - 58 * ep2) * aa**5 / 120) + 500000
    y = k0 * (m + n * math.tan(fi) * (aa**2 / 2 + (5 - t + 9 * c + 4 * c * c) * aa**4 / 24
                                       + (61 - 58 * t + t * t + 600 * c - 330 * ep2) * aa**6 / 720)) + 10000000
    return x, y


def simplificar(puntos, tol):
    """Douglas-Peucker, para que el mapa pese poco."""
    if len(puntos) < 4:
        return puntos
    pila, marcas = [(0, len(puntos) - 1)], {0, len(puntos) - 1}
    while pila:
        a, b = pila.pop()
        (x1, y1), (x2, y2) = puntos[a], puntos[b]
        dx, dy = x2 - x1, y2 - y1
        largo = math.hypot(dx, dy)
        peor, cual = 0, None
        for k in range(a + 1, b):
            # Anillo cerrado (primer punto = último): se mide la distancia al punto, no a una recta de largo cero
            d = (abs(dy * (puntos[k][0] - x1) - dx * (puntos[k][1] - y1)) / largo if largo
                 else math.hypot(puntos[k][0] - x1, puntos[k][1] - y1))
            if d > peor:
                peor, cual = d, k
        if cual is not None and peor > tol:
            marcas.add(cual)
            pila += [(a, cual), (cual, b)]
    return [puntos[k] for k in sorted(marcas)]


def camino_svg(geom):
    partes = []
    for poligono in poligonos(geom):
        for anillo in poligono:
            s = simplificar(anillo, 0.006)
            if len(s) < 4:
                continue
            pts = [f"{(x - OESTE) * 100:.1f} {(NORTE - y) * 100:.1f}" for x, y in s]
            partes.append("M" + "L".join(pts) + "Z")
    return "".join(partes)


# ---------------------------------------------------------------- población: WorldPop 2020 (1 km, ajustada a la ONU)
# Es la cuadrícula de población que usan OCHA y la ONU en emergencias: cuenta a toda la gente, ciudades incluidas.
# Viene en BigTIFF comprimido (LZW + predictor); se lee con lo de abajo y se guarda ya descomprimido.

def etiquetas(b):
    """Etiquetas de un TIFF o BigTIFF."""
    e = '<' if b[:2] == b'II' else '>'
    big = struct.unpack(e+'H', b[2:4])[0] == 43
    TAM = {1:1,2:1,3:2,4:4,5:8,6:1,7:1,8:2,9:4,10:8,11:4,12:8,16:8,17:8,18:8}
    FMT = {1:'B',2:'c',3:'H',4:'I',8:'h',9:'i',11:'f',12:'d',16:'Q',17:'q',18:'Q'}
    if big:
        off = struct.unpack(e+'Q', b[8:16])[0]; n = struct.unpack(e+'Q', b[off:off+8])[0]; p = off+8; ent = 20
    else:
        off = struct.unpack(e+'I', b[4:8])[0]; n = struct.unpack(e+'H', b[off:off+2])[0]; p = off+2; ent = 12
    t = {}
    for k in range(n):
        q = p + k*ent
        tag, typ = struct.unpack(e+'HH', b[q:q+4])
        cnt = struct.unpack(e+('Q' if big else 'I'), b[q+4:q+(12 if big else 8)])[0]
        vpos = q + (12 if big else 8); lim = 8 if big else 4
        sz = TAM.get(typ,1)*cnt
        if sz > lim: vpos = struct.unpack(e+('Q' if big else 'I'), b[vpos:vpos+lim])[0]
        raw = b[vpos:vpos+sz]
        t[tag] = raw.decode(errors='replace') if typ == 2 else list(struct.unpack(e+FMT.get(typ,'B')*cnt, raw))
    return e, t

def lzw(datos):
    """Descompresión LZW de TIFF (códigos de 9 a 12 bits, MSB primero, cambio anticipado)."""
    tabla = [bytes([i]) for i in range(256)] + [b'', b'']
    salida, bits, nbits, ancho, previo = bytearray(), 0, 0, 9, None
    for byte in datos:
        bits = (bits << 8) | byte; nbits += 8
        while nbits >= ancho:
            nbits -= ancho; codigo = (bits >> nbits) & ((1 << ancho) - 1)
            if codigo == 256:
                tabla = tabla[:258]; ancho, previo = 9, None; continue
            if codigo == 257:
                return bytes(salida)
            if previo is None:
                entrada = tabla[codigo]
            elif codigo < len(tabla):
                entrada = tabla[codigo]; tabla.append(previo + entrada[:1])
            else:
                entrada = previo + previo[:1]; tabla.append(entrada)
            salida += entrada; previo = entrada
            if len(tabla) + 1 >= (1 << ancho) and ancho < 12:
                ancho += 1
    return bytes(salida)

def raster_tiff(ruta):
    from array import array
    b = open(ruta, 'rb').read(); e, t = etiquetas(b)
    ancho, alto = t[256][0], t[257][0]
    filas_tira = t.get(278, [alto])[0]
    v = array('I')
    for off, n in zip(t[273], t[279]):
        crudo = lzw(b[off:off+n]) if t[259][0] == 5 else b[off:off+n]
        a = array('I'); a.frombytes(crudo[:len(crudo)//4*4])
        if e == '>': a.byteswap()
        if t.get(317, [1])[0] == 2:  # predictor horizontal: sumar a lo largo de cada fila (en enteros de 32 bits)
            from itertools import accumulate
            for i in range(0, len(a), ancho):
                a[i:i+ancho] = array('I', (x & 0xFFFFFFFF for x in accumulate(a[i:i+ancho])))
        v += a
    f = array('f'); f.frombytes(v.tobytes())
    sx, sy = t[33550][0], t[33550][1]; x0, y0 = t[33922][3], t[33922][4]
    return {'x0': x0, 'y0': y0, 'dx': sx, 'dy': sy, 'ancho': ancho, 'alto': alto, 'v': f[:ancho*alto], 'nulo': float(t.get(42113, '-1e30').strip().strip(chr(0)))}


def worldpop():
    bin_ = os.path.join(CACHE, "worldpop.f32")
    meta = os.path.join(CACHE, "worldpop.json")
    if not os.path.exists(bin_):
        tif = bajar("worldpop.tif", "https://data.worldpop.org/GIS/Population/Global_2000_2020_1km_UNadj/2020/ECU/"
                    "ecu_ppp_2020_1km_Aggregated_UNadj.tif")
        print("  descomprimiendo WorldPop (unos 3 minutos, solo la primera vez)…")
        r = raster_tiff(tif)
        open(bin_, "wb").write(r.pop("v").tobytes())
        json.dump(r, open(meta, "w"))
    r = json.load(open(meta))
    r["v"] = array("f")
    r["v"].frombytes(open(bin_, "rb").read())
    return r


def main():
    # 1. Cantones
    meta = json.loads(pedir("https://www.geoboundaries.org/api/current/gbOpen/ECU/ADM2/"))
    limites = json.load(open(bajar("adm2.geojson", meta["simplifiedGeometryGeoJSON"])))
    cantones = [f for f in limites["features"] if any(OESTE < x < ESTE for p in poligonos(f["geometry"]) for x, _ in p[0][:50])]
    print(f"{len(cantones)} cantones continentales (de {len(limites['features'])})")
    fino = Lienzo(FINO, "H")
    for n, f in enumerate(cantones, start=1):
        for pol in poligonos(f["geometry"]):
            fino.pintar(pol, n)

    # 2. Localidades con población (las teselas se solapan en los bordes: sin repetidos)
    vistos, localidades = set(), []
    # Zoom 8 (precisión ~40 m): en zoom 5 cada punto se corre hasta 300 m, y las franjas inundables son angostas.
    for x in range(70, 75):
        for y in range(126, 132):
            for p in puntos_de_tesela(pedir(f"{SERVICIOS}/martin/locations/8/{x}/{y}", timeout=180), 8, x, y):
                clave = (p.get("localidad"), p.get("parroquia"), round(p["lon"], 3), round(p["lat"], 3))
                if clave not in vistos and p.get("total"):
                    vistos.add(clave)
                    localidades.append(p)
    print(f"{len(localidades)} localidades, {sum(p['total'] for p in localidades):,} personas")

    # Provincia y nombre con tildes: lo que más dicen las localidades que caen en el cantón
    provincias, nombres = defaultdict(Counter), defaultdict(Counter)
    for p in localidades:
        n = fino.en(p["lon"], p["lat"])
        if n:
            provincias[n][p.get("provincia")] += 1
            nombres[n][p.get("canton")] += 1

    # 3. Susceptibilidad a inundación (vector con etiquetas) pintada en la rejilla fina
    print("Susceptibilidad a inundación…")
    inund = Lienzo(FINO)
    capa = json.load(open(bajar("inundacion.geojson", f"{SERVICIOS}/geoserver/ecuador/wfs?service=WFS&version=2.0.0"
                                "&request=GetFeature&typeNames=ecuador:flood&outputFormat=application/json")))
    clases = {"BAJA": 1, "MEDIA": 2, "ALTA": 3}
    for f in sorted(capa["features"], key=lambda f: clases.get(f["properties"]["sui"], 0)):
        for pol in poligonos(f["geometry"]):
            inund.pintar(pol, clases.get(f["properties"]["sui"], 0), solo_si_mayor=True)

    # 4. Susceptibilidad a deslizamientos (cuadrícula en UTM 17S, clases 1-5; se toma ~1 km)
    print("Susceptibilidad a deslizamientos…")
    texto = open(bajar("deslizamientos.txt", f"{SERVICIOS}/geoserver/ecuador/wcs?service=WCS&version=2.0.1"
                       "&request=GetCoverage&coverageId=ecuador__landslides&format=text/plain"
                       "&scalesize=http://www.opengis.net/def/axis/OGC/1/i(650),http://www.opengis.net/def/axis/OGC/1/j(720)")).read()
    par = lambda k: float(re.search(rf'{k}", ([-\d.E]+)', texto).group(1))
    dx0, dy0, ddx, ddy = par("elt_0_2"), par("elt_1_2"), par("elt_0_0"), par("elt_1_1")
    filas = [[int(float(v)) for v in l.split()] for l in texto.split("Band 0:")[1].strip().splitlines()]

    def desliz(lon, lat):
        x, y = utm17s(lon, lat)
        i, j = int((y - dy0) / ddy), int((x - dx0) / ddx)
        return filas[i][j] if 0 <= i < len(filas) and 0 <= j < len(filas[0]) else 0

    # 5. Cifras fijas por cantón (celdas finas: área; localidades: personas)
    celdas, inund_alta, inund_media, desl_alta = Counter(), Counter(), Counter(), Counter()
    grueso = array("H", [0]) * ((fino.ancho // POR) * (fino.alto // POR))
    votos = defaultdict(Counter)
    for i in range(fino.alto):
        lat = NORTE - (i + 0.5) * FINO
        for j in range(fino.ancho):
            n = fino.v[i * fino.ancho + j]
            if not n:
                continue
            celdas[n] += 1
            c = inund.v[i * fino.ancho + j]
            inund_alta[n] += c == 3
            inund_media[n] += c == 2
            if i % 2 == 0 and j % 2 == 0:  # deslizamientos cada ~1 km basta (es la resolución del mapa)
                desl_alta[n] += 4 * (desliz(OESTE + (j + 0.5) * FINO, lat) >= 4)
            votos[(i // POR) * (fino.ancho // POR) + j // POR][n] += 1
    for k, c in votos.items():
        grueso[k] = c.most_common(1)[0][0]

    # Cada celda de 1 km de WorldPop se reparte en 4 puntos (un cuarto de la gente cada uno) para cruzarla con las
    # zonas de susceptibilidad, que son más finas.
    print("Población (WorldPop)…")
    wp = worldpop()
    pob, pob_inund, pob_desl = Counter(), Counter(), Counter()
    for i in range(wp["alto"]):
        for j in range(wp["ancho"]):
            v = wp["v"][i * wp["ancho"] + j]
            if not v > 0:
                continue
            for di, dj in ((0.25, 0.25), (0.25, 0.75), (0.75, 0.25), (0.75, 0.75)):
                lon, lat = wp["x0"] + (j + dj) * wp["dx"], wp["y0"] - (i + di) * wp["dy"]
                n = fino.en(lon, lat)
                if not n:
                    continue
                pob[n] += v / 4
                if inund.en(lon, lat) == 3:
                    pob_inund[n] += v / 4
                if desliz(lon, lat) >= 4:
                    pob_desl[n] += v / 4
    print(f"  {sum(pob.values()):,.0f} personas en cantones continentales")

    salida = []
    for n, f in enumerate(cantones, start=1):
        geo = f["properties"]["shapeName"]
        nombre = nombres[n].most_common(1)[0][0] if nombres[n] else geo
        if normal(nombre) != normal(geo):
            nombre = geo  # si las localidades dicen otra cosa, manda el límite oficial
        total = celdas[n] or 1
        salida.append({
            "id": n,
            "canton": bonito(nombre),
            "provincia": bonito(provincias[n].most_common(1)[0][0]) if provincias[n] else "",
            "d": camino_svg(f["geometry"]),
            "inund_alta": round(inund_alta[n] / total, 3),
            "inund_media": round(inund_media[n] / total, 3),
            "desl_alta": round(min(desl_alta[n], total) / total, 3),
            "pob": round(pob[n]),
            "pob_inund": round(pob_inund[n]),
            "pob_desl": round(pob_desl[n]),
        })
    json.dump({"vista": [0, 0, round((ESTE - OESTE) * 100), round((NORTE - SUR) * 100)], "cantones": salida},
              open(os.path.join(AQUI, "public", "territorio.json"), "w"), ensure_ascii=False, separators=(",", ":"))
    # Rejilla gruesa por filas, comprimida por tramos [valor, repeticiones]
    tramos, previo, cuenta = [], None, 0
    for v in grueso:
        if v == previo:
            cuenta += 1
        else:
            if previo is not None:
                tramos += [previo, cuenta]
            previo, cuenta = v, 1
    tramos += [previo, cuenta]
    json.dump({"oeste": OESTE, "norte": NORTE, "paso": GRUESO, "ancho": fino.ancho // POR, "alto": fino.alto // POR,
               "tramos": tramos}, open(os.path.join(AQUI, "territorio_rejilla.json"), "w"), separators=(",", ":"))
    sin_prov = [c["canton"] for c in salida if not c["provincia"]]
    print(f"Listo: {len(salida)} cantones; sin provincia: {sin_prov}")
    for c in sorted(salida, key=lambda c: -c["pob_inund"])[:8]:
        print(f"  {c['canton']} ({c['provincia']}): inundación alta {c['inund_alta']:.0%}, desliz. alta {c['desl_alta']:.0%}, "
              f"personas {c['pob']:,} (en inundación alta {c['pob_inund']:,}, en deslizamiento alto {c['pob_desl']:,})")


if __name__ == "__main__":
    main()
