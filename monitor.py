"""Monitoreo Caro: recoge lo que se dice de El Niño, la Secretaría de Gestión de Riesgos y Carolina Lozano.

Una corrida: recolectar (medios, YouTube, redes) -> guardar en D1 -> clasificar con Gemini -> resumen del día.
Solo biblioteca estándar (Python 3.9+). Claves por variables de entorno (o .env en la Mac).
"""

import email.utils
import hashlib
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

AQUI = os.path.dirname(os.path.abspath(__file__))
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"
ECUADOR = timezone(timedelta(hours=-5))


def cargar_env():
    ruta = os.path.join(AQUI, ".env")
    if os.path.exists(ruta):
        for linea in open(ruta, encoding="utf-8"):
            linea = linea.strip()
            if linea and not linea.startswith("#") and "=" in linea:
                k, v = linea.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


cargar_env()


def config(nombre, defecto=""):
    return os.environ.get(nombre, defecto).strip()


def ahora():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def huella(*partes):
    return hashlib.sha1("|".join(str(p) for p in partes).encode()).hexdigest()[:20]


def limpiar(texto, maximo=1500):
    texto = html.unescape(re.sub(r"<[^>]+>", " ", texto or ""))
    return re.sub(r"\s+", " ", texto).strip()[:maximo]


def pedir(url, data=None, headers=None, method=None, timeout=60):
    cabeceras = {"User-Agent": UA}
    cabeceras.update(headers or {})
    req = urllib.request.Request(url, data=data, headers=cabeceras, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def fecha_iso(texto):
    """RFC 822 (RSS), ISO 8601 o epoch -> ISO UTC. None si no se entiende."""
    if texto is None or texto == "":
        return None
    try:
        if isinstance(texto, (int, float)) or str(texto).isdigit():
            return datetime.fromtimestamp(int(texto), timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        texto = str(texto)
        if re.match(r"^\d{4}-\d{2}-\d{2}", texto):
            d = datetime.fromisoformat(texto.replace("Z", "+00:00")[:25])
            if d.tzinfo is None:
                d = d.replace(tzinfo=timezone.utc)
        elif re.match(r"^\d{8}T\d{6}Z$", texto):  # GDELT
            d = datetime.strptime(texto, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
        else:
            d = email.utils.parsedate_to_datetime(texto)
        return d.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        try:  # Twitter: "Wed Oct 07 22:10:00 +0000 2026"
            d = datetime.strptime(texto, "%a %b %d %H:%M:%S %z %Y")
            return d.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        except Exception:
            return None


# ---------------------------------------------------------------- qué buscamos

# Búsquedas en Google Noticias (Ecuador). La "consulta" se guarda para saber qué trajo cada pieza.
BUSQUEDAS_NOTICIAS = {
    "carolina": ['"Carolina Lozano"', 'carolozanohok'],
    "secretaria": [
        '"Secretaría de Gestión de Riesgos"',
        '"Secretaría Nacional de Gestión de Riesgos"',
        'SNGR Ecuador',
        '"Gestión de Riesgos" Ecuador',
    ],
    "nino": ['"Fenómeno de El Niño" Ecuador', '"El Niño" Ecuador lluvias', 'Ecuador inundaciones', 'Ecuador emergencia lluvias'],
}

# Para filtrar los RSS generales de los medios: la pieza entra solo si menciona algo de esto.
PALABRAS = re.compile(
    r"carolina lozano|lozano haro|carolozanohok|riesgos_ec|gesti[oó]n de riesgos|\bsngr\b|"
    r"fen[oó]meno (de )?el ni[nñ]o|\bel ni[nñ]o\b|inundaci|deslave|desliz|aluvi[oó]n|"
    r"desbord|damnificad|afectados por (las )?lluvias|estado de excepci[oó]n|"
    r"emergencia (por|ante) (las )?lluvias|coe nacional|alerta (roja|naranja|amarilla)",
    re.I,
)

FEEDS_MEDIOS = {
    "El Universo": "https://www.eluniverso.com/arc/outboundfeeds/rss/?outputType=xml",
    "El Comercio": "https://www.elcomercio.com/feed/",
    "El Diario": "https://www.eldiario.ec/feed/",
    "Metro Ecuador": "https://www.metroecuador.com.ec/arc/outboundfeeds/rss/?outputType=xml",
    "Radio Pichincha": "https://www.radiopichincha.com/feed/",
    "La República": "https://www.larepublica.ec/feed/",
}

# Búsquedas en YouTube (API oficial gratuita: cada búsqueda cuesta 100 de las 10.000 unidades diarias).
BUSQUEDAS_YOUTUBE = ['"Carolina Lozano" riesgos', '"Gestión de Riesgos" Ecuador', 'fenómeno de El Niño Ecuador']
COMENTARIOS_POR_VIDEO = 40
VIDEOS_CON_COMENTARIOS = 6

ESQUEMA_CLASIFICACION = {
    "type": "object",
    "properties": {
        "piezas": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "n": {"type": "integer"},
                    "relevante": {"type": "boolean"},
                    "sobre": {"type": "string", "enum": ["carolina", "secretaria", "nino"]},
                    "tono": {"type": "string", "enum": ["positivo", "neutro", "critico"]},
                    "tema": {"type": "string"},
                    "provincia": {"type": "string"},
                    "alerta": {"type": "boolean"},
                    "resumen": {"type": "string"},
                    "aspecto": {"type": "string"},
                    "idea": {"type": "string"},
                    "rumor": {"type": "string"},
                    "necesidad": {"type": "string"},
                    "actor": {"type": "string"},
                },
                "required": ["n", "relevante", "sobre", "tono", "tema", "provincia", "alerta", "resumen", "aspecto", "idea",
                             "rumor", "necesidad", "actor"],
            },
        }
    },
    "required": ["piezas"],
}

TEMAS = [
    "Lluvias e inundaciones",
    "Deslaves y vías",
    "Afectados y damnificados",
    "Ayuda humanitaria",
    "Respuesta del Gobierno",
    "Prevención y alertas",
    "Agricultura y producción",
    "Salud",
    "Educación",
    "Energía y servicios",
    "Política y críticas",
    "Otro",
]

# Aspectos de la respuesta que la gente evalúa (para el marcador "bien / mal").
ASPECTOS = [
    "Rapidez de la respuesta",
    "Llegada de la ayuda",
    "Presencia en territorio",
    "Coordinación entre instituciones",
    "Prevención y alertas",
    "Comunicación e información",
    "Liderazgo de Carolina Lozano",
    "Ninguno",
]

# Lo que la gente pide (demanda concreta).
NECESIDADES = [
    "Agua", "Alimentos", "Albergue", "Salud", "Maquinaria y limpieza", "Vías y puentes", "Evacuación y rescate",
    "Información y alertas", "Dinero y créditos", "Ninguna",
]

# A quién se le atribuye la respuesta (para bien o para mal).
ACTORES = [
    "Secretaría de Gestión de Riesgos", "Carolina Lozano", "Presidencia y Gobierno central", "Ministerios",
    "Municipio o Prefectura", "Fuerzas Armadas y Policía", "Bomberos y Cruz Roja", "Ninguno",
]

PROVINCIAS = [
    "Azuay", "Bolívar", "Cañar", "Carchi", "Chimborazo", "Cotopaxi", "El Oro", "Esmeraldas", "Galápagos",
    "Guayas", "Imbabura", "Loja", "Los Ríos", "Manabí", "Morona Santiago", "Napo", "Orellana", "Pastaza",
    "Pichincha", "Santa Elena", "Santo Domingo de los Tsáchilas", "Sucumbíos", "Tungurahua", "Zamora Chinchipe",
]

INSTRUCCIONES = f"""Eres analista de monitoreo de medios y redes sociales en Ecuador. El cliente es la Secretaría Nacional de
Gestión de Riesgos (SNGR) de Ecuador y su titular, la secretaria Carolina Lozano (Carolina Alejandra Lozano Haro), durante
el fenómeno de El Niño 2026 (lluvias, inundaciones, deslaves, emergencias).

Para cada pieza numerada (noticia, publicación o comentario) devuelve:
- relevante: true si trata de El Niño / lluvias / emergencias / gestión de riesgos EN ECUADOR, o de la Secretaría o de
  Carolina Lozano. false si es de otro país, otro tema, otra persona con el mismo nombre, spam o publicidad.
- sobre: "carolina" si menciona o se dirige a Carolina Lozano; si no, "secretaria" si menciona a la Secretaría / SNGR /
  Riesgos Ecuador; si no, "nino".
- tono hacia la Secretaría y Carolina (si no las menciona, hacia la respuesta del Estado ante la emergencia):
  "positivo" (reconoce, agradece, informa logros), "neutro" (informativo) o "critico" (reclama, acusa, se burla, denuncia).
- tema: uno de {json.dumps(TEMAS, ensure_ascii=False)}.
- provincia: la provincia de Ecuador principal mencionada, una de {json.dumps(PROVINCIAS, ensure_ascii=False)},
  o "" si no hay.
- alerta: true SOLO si es una crítica fuerte o acusación grave contra la Secretaría o Carolina (negligencia, corrupción,
  muertes atribuidas a la falta de respuesta, pedidos de renuncia) o una noticia de impacto nacional que exige reacción.
- resumen: una frase corta en español (máx. 20 palabras) de qué dice.
- aspecto: qué aspecto de la respuesta del Estado / la Secretaría evalúa o describe, uno de
  {json.dumps(ASPECTOS, ensure_ascii=False)}. "Ninguno" si solo informa del clima o de daños sin hablar de la respuesta.
  El tono de la pieza es el juicio sobre ese aspecto (positivo = va bien, critico = va mal).
- idea: la idea o percepción de fondo que transmite, como la repetiría la gente, en frase genérica y reutilizable
  (máx. 10 palabras, sin nombres de lugares ni cifras). Ej.: "La ayuda llega tarde", "La Secretaría está en el
  territorio", "No hubo alertas a tiempo", "Las autoridades se toman fotos y no ayudan", "Hay coordinación con los
  municipios". "" si la pieza es puramente informativa y no transmite ninguna idea sobre la respuesta.
- rumor: si la pieza difunde o menciona un rumor, cadena, alerta falsa o dato sin confirmar sobre la emergencia (p. ej.
  "viene un tsunami", "cortarán el agua a todo Guayaquil", "están cobrando por los kits"), descríbelo en máx. 12 palabras
  como afirmación genérica; si no, "". No marques como rumor las críticas u opiniones, solo afirmaciones de hecho dudosas.
- necesidad: lo que la gente pide o le falta, uno de {json.dumps(NECESIDADES, ensure_ascii=False)}.
- actor: a quién se le atribuye la respuesta (el mérito o la culpa), uno de {json.dumps(ACTORES, ensure_ascii=False)}.
Responde solo con el JSON pedido, una entrada por cada número recibido."""


# ---------------------------------------------------------------- D1


class D1:
    def __init__(self):
        self.cuenta = config("CLOUDFLARE_ACCOUNT_ID")
        self.base = config("D1_ID", "ced01674-3a31-4bcf-97e0-81538cc399b7")
        self.token = config("CLOUDFLARE_TOKEN")
        self.consultas = 0

    def _post(self, cuerpo):
        url = f"https://api.cloudflare.com/client/v4/accounts/{self.cuenta}/d1/database/{self.base}/query"
        for intento in range(3):
            try:
                r = json.loads(
                    pedir(
                        url,
                        data=json.dumps(cuerpo).encode(),
                        headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"},
                        method="POST",
                    )
                )
                self.consultas += 1
                return r["result"]
            except urllib.error.HTTPError as e:
                detalle = e.read().decode(errors="replace")[:300]
                if e.code >= 500 and intento < 2:
                    time.sleep(3)
                    continue
                raise RuntimeError(f"D1 HTTP {e.code}: {detalle}")

    def q(self, sql, params=None):
        return self._post({"sql": sql, "params": params or []})[0].get("results", [])

    def lote(self, sentencias):
        """Varias sentencias [(sql, params)] en una sola llamada (transacción)."""
        for i in range(0, len(sentencias), 50):
            self._post({"batch": [{"sql": s, "params": p} for s, p in sentencias[i : i + 50]]})


COLUMNAS = ["id", "fuente", "medio", "url", "titulo", "texto", "autor", "fecha", "recogido", "interacciones", "padre", "consulta"]


def guardar(db, piezas):
    """Inserta piezas nuevas; si ya existían, solo actualiza las interacciones. Devuelve cuántas eran nuevas."""
    if not piezas:
        return 0
    vistas, unicas = set(), []
    for p in piezas:
        if p["id"] not in vistas:
            vistas.add(p["id"])
            unicas.append(p)
    ids = [p["id"] for p in unicas]
    existentes = set()
    for i in range(0, len(ids), 90):
        trozo = ids[i : i + 90]
        filas = db.q(f"SELECT id FROM piezas WHERE id IN ({','.join('?' * len(trozo))})", trozo)
        existentes.update(f["id"] for f in filas)
    sentencias = []
    por_sentencia = 90 // len(COLUMNAS)
    for i in range(0, len(unicas), por_sentencia):
        trozo = unicas[i : i + por_sentencia]
        marcas = ",".join("(" + ",".join("?" * len(COLUMNAS)) + ")" for _ in trozo)
        params = []
        for p in trozo:
            params += [p.get(c) if p.get(c) is not None else (0 if c == "interacciones" else None) for c in COLUMNAS]
        sentencias.append(
            (
                f"INSERT INTO piezas ({','.join(COLUMNAS)}) VALUES {marcas} "
                "ON CONFLICT(id) DO UPDATE SET interacciones = MAX(piezas.interacciones, excluded.interacciones)",
                params,
            )
        )
    db.lote(sentencias)
    return len([i for i in ids if i not in existentes])


# ---------------------------------------------------------------- medios


def leer_rss(xml_bytes):
    """Devuelve [{titulo, url, fecha, texto, medio}] de un RSS o Atom."""
    raiz = ET.fromstring(xml_bytes)
    salida = []
    for item in raiz.iter("item"):
        fuente = item.find("source")
        salida.append(
            {
                "titulo": limpiar(item.findtext("title"), 400),
                "url": (item.findtext("link") or "").strip(),
                "fecha": fecha_iso(item.findtext("pubDate")),
                "texto": limpiar(item.findtext("description")),
                "medio": fuente.text.strip() if fuente is not None and fuente.text else None,
            }
        )
    return salida


def recoger_google_noticias():
    piezas = []
    for sobre, consultas in BUSQUEDAS_NOTICIAS.items():
        for consulta in consultas:
            q = urllib.parse.quote(f"{consulta} when:2d")
            url = f"https://news.google.com/rss/search?q={q}&hl=es-419&gl=EC&ceid=EC:es-419"
            try:
                items = leer_rss(pedir(url))
            except Exception as e:
                print(f"  Google Noticias '{consulta}': {e}")
                continue
            for it in items:
                titulo = it["titulo"]
                medio = it["medio"]
                if medio and titulo.endswith(" - " + medio):
                    titulo = titulo[: -len(medio) - 3]
                texto = it["texto"]
                if texto.startswith(titulo):  # Google repite el título en la descripción
                    texto = ""
                piezas.append(
                    {
                        # misma noticia por varias búsquedas: la huella es medio + título
                        "id": huella("noticia", (medio or "").lower(), titulo.lower()),
                        "fuente": "medios",
                        "medio": medio or "Google Noticias",
                        "url": it["url"],
                        "titulo": titulo,
                        "texto": texto,
                        "fecha": it["fecha"],
                        "recogido": ahora(),
                        "consulta": consulta,
                    }
                )
            time.sleep(1)
    print(f"  Google Noticias: {len(piezas)}")
    return piezas


def recoger_feeds_medios():
    piezas = []
    for medio, url in FEEDS_MEDIOS.items():
        try:
            items = leer_rss(pedir(url, timeout=30))
        except Exception as e:
            print(f"  RSS {medio}: {e}")
            continue
        for it in items:
            if not PALABRAS.search(it["titulo"] + " " + it["texto"]):
                continue
            piezas.append(
                {
                    "id": huella("noticia", medio.lower(), it["titulo"].lower()),
                    "fuente": "medios",
                    "medio": medio,
                    "url": it["url"],
                    "titulo": it["titulo"],
                    "texto": it["texto"],
                    "fecha": it["fecha"],
                    "recogido": ahora(),
                    "consulta": "rss",
                }
            )
    print(f"  RSS de medios: {len(piezas)}")
    return piezas


def recoger_gdelt():
    """GDELT (medios del mundo): solo lo publicado en Ecuador. Se satura seguido; si falla, no pasa nada."""
    consulta = '("Gestión de Riesgos" OR "Carolina Lozano" OR "El Niño") sourcecountry:EC'
    url = (
        "https://api.gdeltproject.org/api/v2/doc/doc?mode=artlist&format=json&maxrecords=75&timespan=1d&query="
        + urllib.parse.quote(consulta)
    )
    try:
        datos = json.loads(pedir(url, timeout=40) or b"{}")
    except Exception as e:
        print(f"  GDELT: {e}")
        return []
    piezas = []
    for a in datos.get("articles", []):
        titulo = limpiar(a.get("title"), 400)
        medio = a.get("domain") or "GDELT"
        piezas.append(
            {
                "id": huella("noticia", medio.lower(), titulo.lower()),
                "fuente": "medios",
                "medio": medio,
                "url": a.get("url"),
                "titulo": titulo,
                "texto": "",
                "fecha": fecha_iso(a.get("seendate")),
                "recogido": ahora(),
                "consulta": "gdelt",
            }
        )
    print(f"  GDELT: {len(piezas)}")
    return piezas


# ---------------------------------------------------------------- YouTube (API oficial, clave gratuita)


def youtube(recurso, **params):
    params["key"] = config("YOUTUBE_KEY")
    return json.loads(pedir(f"https://www.googleapis.com/youtube/v3/{recurso}?" + urllib.parse.urlencode(params), timeout=30))


def recoger_youtube():
    if not config("YOUTUBE_KEY"):
        print("  YouTube: falta YOUTUBE_KEY, se salta")
        return []
    desde = (datetime.now(timezone.utc) - timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
    videos = {}
    for consulta in BUSQUEDAS_YOUTUBE:
        try:
            r = youtube("search", part="snippet", q=consulta, type="video", regionCode="EC", relevanceLanguage="es",
                        publishedAfter=desde, maxResults=25, order="date")
        except Exception as e:
            print(f"  YouTube '{consulta}': {e}")
            continue
        for v in r.get("items", []):
            videos.setdefault(v["id"]["videoId"], (v["snippet"], consulta))
    if not videos:
        return []
    estadisticas = {}
    ids = list(videos)
    for i in range(0, len(ids), 50):
        r = youtube("videos", part="statistics", id=",".join(ids[i : i + 50]))
        for v in r.get("items", []):
            st = v.get("statistics", {})
            estadisticas[v["id"]] = (int(st.get("viewCount", 0)), int(st.get("likeCount", 0)), int(st.get("commentCount", 0)))
    piezas = []
    for vid, (sn, consulta) in videos.items():
        vistas, likes, comentarios = estadisticas.get(vid, (0, 0, 0))
        piezas.append({
            "id": huella("youtube", vid), "fuente": "youtube", "medio": sn.get("channelTitle"),
            "url": f"https://www.youtube.com/watch?v={vid}", "titulo": limpiar(sn.get("title"), 400),
            "texto": limpiar(sn.get("description")), "fecha": fecha_iso(sn.get("publishedAt")), "recogido": ahora(),
            "interacciones": likes + comentarios, "consulta": consulta,
        })
    # Comentarios de los videos con más conversación (cuestan 1 unidad cada pedido).
    con_mas = sorted((v for v in videos if estadisticas.get(v, (0, 0, 0))[2] > 0), key=lambda v: -estadisticas[v][2])
    for vid in con_mas[:VIDEOS_CON_COMENTARIOS]:
        try:
            r = youtube("commentThreads", part="snippet", videoId=vid, maxResults=COMENTARIOS_POR_VIDEO, order="relevance",
                        textFormat="plainText")
        except Exception as e:
            print(f"  YouTube comentarios {vid}: {e}")
            continue
        for c in r.get("items", []):
            cs = c["snippet"]["topLevelComment"]["snippet"]
            piezas.append({
                "id": huella("youtube-c", c["id"]), "fuente": "youtube", "medio": videos[vid][0].get("channelTitle"),
                "url": f"https://www.youtube.com/watch?v={vid}&lc={c['id']}", "titulo": "",
                "texto": limpiar(cs.get("textDisplay")), "autor": cs.get("authorDisplayName"),
                "fecha": fecha_iso(cs.get("publishedAt")), "recogido": ahora(),
                "interacciones": int(cs.get("likeCount", 0)) + int(c["snippet"].get("totalReplyCount", 0)),
                "padre": f"https://www.youtube.com/watch?v={vid}", "consulta": "comentarios",
            })
    print(f"  YouTube: {len(videos)} videos, {len(piezas) - len(videos)} comentarios")
    return piezas


# ---------------------------------------------------------------- redes (Apify)

import redes  # noqa: E402  (va aparte porque depende de los actores de Apify)


# ---------------------------------------------------------------- Gemini

MODELOS_GEMINI = ["gemini-flash-lite-latest", "gemini-flash-latest"]


class CuotaAgotada(Exception):
    pass


def gemini(cuerpo):
    clave = config("GEMINI_KEY")
    if not clave:
        raise CuotaAgotada("falta GEMINI_KEY")
    errores = []
    for modelo in MODELOS_GEMINI:
        for intento in range(3):
            try:
                r = json.loads(
                    pedir(
                        f"https://generativelanguage.googleapis.com/v1beta/models/{modelo}:generateContent",
                        data=json.dumps(cuerpo).encode(),
                        headers={"Content-Type": "application/json", "x-goog-api-key": clave},
                        method="POST",
                        timeout=180,
                    )
                )
                return json.loads(r["candidates"][0]["content"]["parts"][-1]["text"])
            except urllib.error.HTTPError as e:
                detalle = e.read().decode(errors="replace")
                errores.append(f"{modelo}: HTTP {e.code} {detalle[:150]}")
                print(f"  {errores[-1]}")
                if e.code == 429 and "PerDay" in detalle:
                    break  # cuota diaria de este modelo: probar el otro
                if e.code in (429, 500, 503) and intento < 2:
                    time.sleep(20 * (intento + 1))
                    continue
                break
            except (KeyError, ValueError, IndexError) as e:
                errores.append(f"{modelo}: respuesta inválida ({e})")
                break
    raise CuotaAgotada(" | ".join(errores[-2:]))


def clasificar(db, maximo):
    """Clasifica hasta `maximo` piezas pendientes, de a 25 por llamada a Gemini."""
    pendientes = db.q(
        "SELECT id, fuente, medio, titulo, texto, autor FROM piezas WHERE clasificado = 0 ORDER BY recogido DESC LIMIT ?",
        [maximo],
    )
    hechas = 0
    for i in range(0, len(pendientes), 25):
        trozo = pendientes[i : i + 25]
        lineas = []
        for n, p in enumerate(trozo):
            tipo = "Noticia" if p["fuente"] == "medios" else f"{p['fuente']}"
            lineas.append(
                f"[{n}] {tipo} | {p['medio'] or ''} | {p['autor'] or ''}\n{p['titulo'] or ''}\n{(p['texto'] or '')[:700]}"
            )
        cuerpo = {
            "systemInstruction": {"parts": [{"text": INSTRUCCIONES}]},
            "contents": [{"role": "user", "parts": [{"text": "\n\n".join(lineas)}]}],
            "generationConfig": {
                "responseMimeType": "application/json",
                "responseSchema": ESQUEMA_CLASIFICACION,
                "temperature": 0.1,
            },
        }
        try:
            r = gemini(cuerpo)
        except CuotaAgotada as e:
            print(f"  Gemini no disponible, se sigue en la próxima corrida: {e}")
            break
        por_n = {x["n"]: x for x in r.get("piezas", []) if isinstance(x.get("n"), int)}
        sentencias = []
        for n, p in enumerate(trozo):
            x = por_n.get(n)
            if not x:
                continue
            sentencias.append(
                (
                    "UPDATE piezas SET clasificado = 1, relevante = ?, sobre = ?, tono = ?, tema = ?, provincia = ?, "
                    "alerta = ?, resumen = ?, aspecto = ?, idea = ?, rumor = ?, necesidad = ?, actor = ? WHERE id = ?",
                    [
                        1 if x["relevante"] else 0,
                        x["sobre"],
                        x["tono"],
                        x["tema"] if x["tema"] in TEMAS else "Otro",
                        x["provincia"] if x["provincia"] in PROVINCIAS else "",
                        1 if x["alerta"] else 0,
                        limpiar(x["resumen"], 300),
                        x.get("aspecto") if x.get("aspecto") in ASPECTOS[:-1] else None,
                        limpiar(x.get("idea"), 120) or None,
                        limpiar(x.get("rumor"), 160) or None,
                        x.get("necesidad") if x.get("necesidad") in NECESIDADES[:-1] else None,
                        x.get("actor") if x.get("actor") in ACTORES[:-1] else None,
                        p["id"],
                    ],
                )
            )
        db.lote(sentencias)
        hechas += len(sentencias)
    print(f"  Clasificadas: {hechas} de {len(pendientes)} pendientes")
    return hechas


def resumen_del_dia(db):
    hoy = datetime.now(ECUADOR).strftime("%Y-%m-%d")
    desde = (datetime.now(timezone.utc) - timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%SZ")
    filas = db.q(
        "SELECT fuente, medio, sobre, tono, tema, provincia, alerta, resumen, interacciones, rumor, necesidad FROM piezas "
        "WHERE relevante = 1 AND COALESCE(fecha, recogido) >= ? ORDER BY alerta DESC, interacciones DESC LIMIT 150",
        [desde],
    )
    if not filas:
        return
    texto = "\n".join(
        f"- {f['fuente']} | {f['medio'] or ''} | sobre {f['sobre']} | {f['tono']} | {f['tema']} | {f['provincia'] or '-'}"
        f"{' | ALERTA' if f['alerta'] else ''}{' | pide ' + f['necesidad'] if f['necesidad'] else ''}"
        f"{' | RUMOR: ' + f['rumor'] if f['rumor'] else ''} | {f['resumen']}"
        for f in filas
    )
    cuerpo = {
        "systemInstruction": {
            "parts": [
                {
                    "text": "Eres el analista de comunicación de la secretaria Carolina Lozano (Secretaría Nacional de Gestión "
                    "de Riesgos de Ecuador). Con las piezas de las últimas 24 horas escribe un resumen ejecutivo en español "
                    "para ella: 4 a 6 viñetas cortas (qué se dice, cuál es el tono hacia la Secretaría y hacia ella, qué "
                    "temas y provincias dominan, qué críticas hay que atender). Directo, sin adornos, sin inventar datos. "
                    "Además, 3 acciones de comunicación o de gestión que convendría tomar hoy según lo que se dice (qué "
                    "hacer, dónde y por qué), concretas y sustentadas en las piezas. "
                    'Devuelve JSON {"vinetas": ["...", ...], "acciones": [{"accion": "...", "porque": "..."}]}.'
                }
            ]
        },
        "contents": [{"role": "user", "parts": [{"text": texto}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseSchema": {
                "type": "object",
                "properties": {
                    "vinetas": {"type": "array", "items": {"type": "string"}},
                    "acciones": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {"accion": {"type": "string"}, "porque": {"type": "string"}},
                            "required": ["accion", "porque"],
                        },
                    },
                },
                "required": ["vinetas", "acciones"],
            },
            "temperature": 0.3,
        },
    }
    try:
        r = gemini(cuerpo)
    except CuotaAgotada as e:
        print(f"  Resumen del día no se pudo: {e}")
        return
    db.q(
        "INSERT INTO resumenes (fecha, texto, creado) VALUES (?, ?, ?) "
        "ON CONFLICT(fecha) DO UPDATE SET texto = excluded.texto, creado = excluded.creado",
        [hoy, json.dumps({"vinetas": r.get("vinetas", []), "acciones": r.get("acciones", [])[:3]}, ensure_ascii=False), ahora()],
    )
    print("  Resumen del día: listo")


INSTRUCCIONES_NARRATIVAS = (
    "Eres analista de opinión pública en Ecuador. Recibes ideas numeradas que circulan en medios y redes sobre la "
    "respuesta del Estado y de la Secretaría Nacional de Gestión de Riesgos (titular: Carolina Lozano) ante El Niño 2026. "
    "Agrúpalas en las narrativas de fondo que están calando en la población (entre 3 y 8): ideas que se repiten, no temas "
    "sueltos. Para cada una: titulo (la idea como la diría la gente, máx. 8 palabras), explicacion (1 o 2 frases: qué se "
    "dice y por qué importa para la Secretaría) y n (los números de TODAS las ideas que pertenecen a esa narrativa). Cada "
    "número va en una sola narrativa como máximo; deja fuera las ideas sueltas que no se repiten. No inventes nada."
)
INSTRUCCIONES_RUMORES = (
    "Eres verificador de datos en Ecuador durante la emergencia por El Niño 2026. Recibes rumores numerados que circulan en "
    "medios y redes. Agrupa los que dicen lo mismo (hasta 8 grupos; un rumor que aparece una sola vez también puede ser un "
    "grupo si es grave). Para cada grupo: titulo (el rumor como afirmación, máx. 12 palabras), explicacion (1 frase: por "
    "qué conviene aclararlo y qué debería confirmar o desmentir la Secretaría) y n (los números que pertenecen al grupo). "
    "No inventes nada que no esté en los rumores."
)


def agrupar(filas, campo, instrucciones, minimo):
    """Gemini agrupa los textos de `campo`; las cifras (total, hoy vs ayer, tono, fuentes) se cuentan aquí."""
    lineas = "\n".join(f"[{n}] ({f['tono']}, {f['fuente']}) {f[campo]}" for n, f in enumerate(filas))
    cuerpo = {
        "systemInstruction": {"parts": [{"text": instrucciones}]},
        "contents": [{"role": "user", "parts": [{"text": lineas}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseSchema": {
                "type": "object",
                "properties": {
                    "grupos": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "titulo": {"type": "string"},
                                "explicacion": {"type": "string"},
                                "n": {"type": "array", "items": {"type": "integer"}},
                            },
                            "required": ["titulo", "explicacion", "n"],
                        },
                    }
                },
                "required": ["grupos"],
            },
            "temperature": 0.2,
        },
    }
    r = gemini(cuerpo)
    ahora_utc = datetime.now(timezone.utc)
    hace24 = (ahora_utc - timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%SZ")
    hace48 = (ahora_utc - timedelta(hours=48)).strftime("%Y-%m-%dT%H:%M:%SZ")
    salida, usados = [], set()
    for g in r.get("grupos", []):
        miembros = []
        for n in g.get("n", []):
            if isinstance(n, int) and 0 <= n < len(filas) and n not in usados:
                usados.add(n)
                miembros.append(filas[n])
        if len(miembros) < minimo:
            continue
        tonos = {"positivo": 0, "neutro": 0, "critico": 0}
        fuentes = {}
        for f in miembros:
            tonos[f["tono"]] = tonos.get(f["tono"], 0) + 1
            fuentes[f["fuente"]] = fuentes.get(f["fuente"], 0) + 1
        ejemplos = sorted(miembros, key=lambda f: (-(f["interacciones"] or 0), f["f"]))[:3]
        salida.append(
            {
                "titulo": limpiar(g["titulo"], 120),
                "explicacion": limpiar(g["explicacion"], 400),
                "total": len(miembros),
                "ultimas24": sum(1 for f in miembros if f["f"] >= hace24),
                "previas24": sum(1 for f in miembros if hace48 <= f["f"] < hace24),
                "tonos": tonos,
                "fuentes": fuentes,
                "interacciones": sum(f["interacciones"] or 0 for f in miembros),
                "ejemplos": [
                    {
                        "fuente": f["fuente"],
                        "quien": f["autor"] or f["medio"],
                        "url": f["url"],
                        "texto": limpiar(f["titulo"] or f["texto"] or f["resumen"], 220),
                        "tono": f["tono"],
                    }
                    for f in ejemplos
                ],
            }
        )
    salida.sort(key=lambda x: (-x["ultimas24"], -x["total"]))
    return salida


def narrativas(db):
    """Narrativas y rumores de los últimos 3 días (se guardan juntos; el tablero muestra la última agrupación)."""
    ahora_utc = datetime.now(timezone.utc)
    desde = (ahora_utc - timedelta(days=3)).strftime("%Y-%m-%dT%H:%M:%SZ")
    columnas = "id, fuente, medio, autor, url, titulo, texto, resumen, tono, idea, rumor, interacciones, COALESCE(fecha, recogido) AS f"
    ideas = db.q(
        f"SELECT {columnas} FROM piezas WHERE relevante = 1 AND idea IS NOT NULL AND COALESCE(fecha, recogido) >= ? "
        "ORDER BY interacciones DESC LIMIT 600",
        [desde],
    )
    rumores = db.q(
        f"SELECT {columnas} FROM piezas WHERE relevante = 1 AND rumor IS NOT NULL AND COALESCE(fecha, recogido) >= ? "
        "ORDER BY interacciones DESC LIMIT 200",
        [desde],
    )
    datos = {"narrativas": [], "rumores": []}
    try:
        if len(ideas) >= 5:
            datos["narrativas"] = agrupar(ideas, "idea", INSTRUCCIONES_NARRATIVAS, 2)
        if rumores:
            datos["rumores"] = agrupar(rumores, "rumor", INSTRUCCIONES_RUMORES, 1)
    except CuotaAgotada as e:
        print(f"  Narrativas no se pudieron: {e}")
        return
    db.q("INSERT INTO narrativas (creado, datos) VALUES (?, ?)", [ahora(), json.dumps(datos, ensure_ascii=False)])
    db.q("DELETE FROM narrativas WHERE creado < ?", [(ahora_utc - timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%SZ")])
    print(f"  Narrativas: {len(datos['narrativas'])} · rumores: {len(datos['rumores'])}")


# ---------------------------------------------------------------- corrida


def main():
    args = set(sys.argv[1:])
    inicio = ahora()
    db = D1()
    detalle = {}

    recolectores = [
        ("Google Noticias", recoger_google_noticias),
        ("RSS medios", recoger_feeds_medios),
        ("GDELT", recoger_gdelt),
        ("YouTube", recoger_youtube),
    ]
    if "--sin-redes" not in args:
        recolectores += redes.recolectores()
    for nombre, funcion in recolectores:
        print(f"{nombre}…")
        try:
            detalle[nombre] = guardar(db, funcion())
        except Exception as e:
            print(f"  ERROR {nombre}: {e}")
            detalle[nombre] = f"error: {str(e)[:150]}"

    if "--sin-gemini" not in args:
        print("Gemini…")
        detalle["clasificadas"] = clasificar(db, int(config("MAX_CLASIFICAR", "400")))
        resumen_del_dia(db)
        narrativas(db)

    detalle["consultas_d1"] = db.consultas
    db.q("INSERT INTO corridas (inicio, fin, detalle) VALUES (?, ?, ?)", [inicio, ahora(), json.dumps(detalle, ensure_ascii=False)])
    print("Listo:", json.dumps(detalle, ensure_ascii=False))


if __name__ == "__main__":
    main()
