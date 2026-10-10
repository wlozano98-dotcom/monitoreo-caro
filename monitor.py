"""Monitoreo Caro: recoge lo que se dice de El Niño, la Secretaría de Gestión de Riesgos y Carolina Lozano.

Una corrida: recolectar (medios, YouTube, redes) -> guardar en D1 -> clasificar con Gemini -> resumen del día.
Solo biblioteca estándar (Python 3.9+). Claves por variables de entorno (o .env en la Mac).
"""

import email.utils
import hashlib
import html
import json
import math
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
            texto = re.sub(r"(T\d{2}:\d{2}:\d{2})\.\d+", r"\1", texto)  # sin milisegundos (TikTok, Facebook)
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
                    "tono_actor": {"type": "string", "enum": ["positivo", "neutro", "critico"]},
                },
                "required": ["n", "relevante", "sobre", "tono", "tema", "provincia", "alerta", "resumen", "aspecto", "idea",
                             "rumor", "necesidad", "actor", "tono_actor"],
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
    "Secretaría de Gestión de Riesgos", "Carolina Lozano", "Gobierno central",
    "Municipio o Prefectura", "Fuerzas Armadas y Policía", "Bomberos y Cruz Roja", "Ninguno",
]

ACTORES_SNGR = ACTORES[:3]  # la Secretaría, Carolina y el Gobierno central

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
- actor: a quién se dirige la pieza o a quién le atribuye la respuesta (el mérito o la culpa), uno de
  {json.dumps(ACTORES, ensure_ascii=False)}. "Gobierno central" reúne a la Presidencia, los ministerios y demás entidades
  del Ejecutivo, salvo la Secretaría de Gestión de Riesgos y Carolina Lozano, que van aparte. Alcaldías, municipios,
  prefecturas, gobernaciones locales y sus cuentas (p. ej. @MunicipioQuito, @SeguridadeQuito, @PabelMunoz, alcaldes,
  prefectos) son "Municipio o Prefectura". Fíjate en a quién responde la pieza (si es respuesta, va el texto original).
  Que una cuenta etiquete a @Riesgos_Ec de pasada no basta: cuenta a quién se le reclama o reconoce de verdad.
- tono_actor: el juicio sobre ese actor: "positivo", "neutro" o "critico" ("neutro" si actor es "Ninguno").
- tono: el juicio SOLO hacia la Secretaría de Gestión de Riesgos y Carolina Lozano (o hacia el Gobierno central en la
  emergencia, porque la Secretaría es parte de él): "positivo" (reconoce, agradece, informa logros de la SNGR),
  "neutro" (informativo, o la pieza no las juzga) o "critico" (les reclama, acusa, se burla o denuncia).
  Una crítica a un alcalde, municipio, prefectura, bomberos u otro actor que no sea la SNGR, Carolina o el Gobierno
  central NO es crítica: tono "neutro" (el juicio va en tono_actor). Ej.: "el alcalde no limpió las alcantarillas" ->
  actor "Municipio o Prefectura", tono_actor "critico", tono "neutro".
- tema: uno de {json.dumps(TEMAS, ensure_ascii=False)}.
- provincia: la provincia de Ecuador principal mencionada, una de {json.dumps(PROVINCIAS, ensure_ascii=False)},
  o "" si no hay.
- alerta: true SOLO si es una crítica fuerte o acusación grave contra la Secretaría o Carolina (negligencia, corrupción,
  muertes atribuidas a la falta de respuesta, pedidos de renuncia) o una noticia de impacto nacional que exige una
  reacción de la Secretaría. Críticas a alcaldes, prefectos u otros actores NO son alerta.
  Insultos, groserías o ataques sin argumento ni hecho concreto NO son alerta (son tono crítico y nada más).
- resumen: una frase corta en español (máx. 20 palabras) de qué dice.
- aspecto: qué aspecto de la respuesta de la Secretaría / Carolina / Gobierno central evalúa o describe, uno de
  {json.dumps(ASPECTOS, ensure_ascii=False)}. "Ninguno" si solo informa del clima o de daños sin hablar de la respuesta,
  o si habla de la respuesta de municipios, prefecturas u otros actores locales.
  El tono de la pieza es el juicio sobre ese aspecto (positivo = va bien, critico = va mal).
- idea: la idea o percepción de fondo que transmite, como la repetiría la gente, en frase genérica y reutilizable
  (máx. 10 palabras, sin nombres de lugares ni cifras). Ej.: "La ayuda llega tarde", "La Secretaría está en el
  territorio", "No hubo alertas a tiempo", "Las autoridades se toman fotos y no ayudan", "Hay coordinación con los
  municipios", "El municipio no limpió las alcantarillas". También cuenta lo que se dice de alcaldes, prefectos u otros
  actores (nombra el tipo de actor en la idea). "" si la pieza es puramente informativa y no transmite ninguna idea sobre
  la respuesta.
- rumor: si la pieza difunde o menciona un rumor, cadena, alerta falsa o dato sin confirmar sobre la emergencia (p. ej.
  "viene un tsunami", "cortarán el agua a todo Guayaquil", "están cobrando por los kits"), descríbelo en máx. 12 palabras
  como afirmación genérica; si no, "". No marques como rumor las críticas u opiniones, solo afirmaciones de hecho dudosas.
- necesidad: lo que la gente pide o le falta, uno de {json.dumps(NECESIDADES, ensure_ascii=False)}.
No inventes: si la pieza no dice algo (provincia, actor, necesidad), deja el campo vacío o en "Ninguno".
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


COLUMNAS = ["id", "fuente", "medio", "url", "titulo", "texto", "autor", "fecha", "recogido", "interacciones", "padre", "consulta", "vistas", "seguidores", "peso"]


ALCANCE_MEDIO = 1000  # una nota de medio cuenta como 1.000 vistas (los medios no publican sus vistas)


def peso(p):
    """Peso por alcance, escala comprimida: 10 vistas = 1, 100 = 2, 1.000 = 3 (una nota de medio), 100.000 = 5.
    Así un viral pesa más que un tuit chico, pero no aplasta todo el día."""
    alcance = ALCANCE_MEDIO if p.get("fuente") == "medios" else (p.get("vistas") or 0) + (p.get("interacciones") or 0)
    return round(max(1.0, math.log10(max(alcance, 1))), 2)


def guardar(db, piezas):
    """Inserta piezas nuevas; si ya existían, solo actualiza las interacciones. Devuelve cuántas eran nuevas."""
    if not piezas:
        return 0
    for p in piezas:
        p["peso"] = peso(p)
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
                "ON CONFLICT(id) DO UPDATE SET interacciones = MAX(piezas.interacciones, excluded.interacciones), "
                "vistas = MAX(COALESCE(piezas.vistas, 0), COALESCE(excluded.vistas, 0)), "
                "seguidores = COALESCE(excluded.seguidores, piezas.seguidores), "
                "peso = MAX(COALESCE(piezas.peso, 1), excluded.peso)",
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


# ---------------------------------------------------------------- agenda nacional (todos los titulares)

# Medios del país que ya monitoreamos. Google Noticias da hasta 100 titulares por medio y búsqueda; como la corrida
# es cada 2 horas y los titulares se guardan sin repetir, en el día se juntan más que eso.
AGENDA_MEDIOS = {
    "eluniverso.com": "El Universo", "expreso.ec": "Expreso", "eldiario.ec": "El Diario", "elcomercio.com": "El Comercio",
    "ecuavisa.com": "Ecuavisa", "radiopichincha.com": "Radio Pichincha", "primicias.ec": "Primicias",
    "teleamazonas.com": "Teleamazonas", "vistazo.com": "Vistazo", "fmmundo.com": "FM Mundo",
    "metroecuador.com.ec": "Metro Ecuador", "lahora.com.ec": "La Hora", "extra.ec": "Extra",
    "eltelegrafo.com.ec": "El Telégrafo", "elmercurio.com.ec": "El Mercurio", "larepublica.ec": "La República",
    "tctelevision.com": "TC Televisión", "planv.com.ec": "Plan V",
}


def recoger_titulares():
    """Todos los titulares de las últimas 24 h de los medios del país (Google Noticias por sitio + RSS propios)."""
    crudos = []
    for dominio, medio in AGENDA_MEDIOS.items():
        q = urllib.parse.quote(f"site:{dominio} when:1d")
        try:
            items = leer_rss(pedir(f"https://news.google.com/rss/search?q={q}&hl=es-419&gl=EC&ceid=EC:es-419"))
        except Exception as e:
            print(f"  Titulares {medio}: {e}")
            continue
        for it in items:
            titulo = re.sub(r"\s+-\s+[^-]{2,40}$", "", it["titulo"])  # Google le pega " - Medio" al final
            crudos.append((medio, titulo, it["url"], it["fecha"]))
        time.sleep(1)
    for medio, url in FEEDS_MEDIOS.items():
        try:
            for it in leer_rss(pedir(url, timeout=30)):
                crudos.append((medio, it["titulo"], it["url"], it["fecha"]))
        except Exception as e:
            print(f"  Titulares RSS {medio}: {e}")
    desde = (datetime.now(timezone.utc) - timedelta(hours=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
    salida, vistos = [], set()
    for medio, titulo, url, fecha in crudos:
        # Fuera: sin fecha, viejos y "titulares" que son secciones ("EN VIVO", "Economía").
        if not fecha or fecha < desde or len(titulo.split()) < 5:
            continue
        clave = huella("titular", re.sub(r"\W+", " ", titulo.lower()).strip())  # mismo titular por RSS y Google
        if clave in vistos:
            continue
        vistos.add(clave)
        dia = (datetime.fromisoformat(fecha[:19]) - timedelta(hours=5)).strftime("%Y-%m-%d")
        salida.append([clave, medio, titulo, url, fecha, dia, ahora()])
    return salida


def guardar_titulares(db, titulares):
    sentencias = []
    for i in range(0, len(titulares), 12):
        trozo = titulares[i : i + 12]
        marcas = ",".join("(?,?,?,?,?,?,?)" for _ in trozo)
        sentencias.append(
            (f"INSERT OR IGNORE INTO titulares (id, medio, titulo, url, fecha, dia, recogido) VALUES {marcas}",
             [v for t in trozo for v in t])
        )
    db.lote(sentencias)
    print(f"  Titulares: {len(titulares)} (últimas 30 h, sin repetir)")
    return len(titulares)


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
            "interacciones": likes + comentarios, "consulta": consulta, "vistas": vistas,
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

# Clasificar cada pieza: el modelo rápido. Pensar (resumen, acciones, narrativas, rumores): el mejor gratuito, pensando a
# fondo. Gemini Pro no tiene capa gratis (probado 2026-10-07: cuota 0).
# Clasificar: Flash pensando poco (Flash-Lite confundía a quién se dirige la crítica); Lite queda de reserva.
MODELOS_GEMINI = ["gemini-3.6-flash", "gemini-flash-latest", "gemini-flash-lite-latest"]
MODELOS_PENSAR = ["gemini-3.6-flash", "gemini-3.8-flash", "gemini-flash-latest", "gemini-flash-lite-latest"]


class CuotaAgotada(Exception):
    pass


def gemini(cuerpo, pensar=False):
    """Llama a Gemini probando modelos en orden. pensar=True: el modelo más listo, con razonamiento largo.
    Sin pensar (clasificar), los Gemini 3 razonan poco: basta para distinguir a quién va la crítica."""
    clave = config("GEMINI_KEY")
    if not clave:
        raise CuotaAgotada("falta GEMINI_KEY")
    errores = []
    for modelo in MODELOS_PENSAR if pensar else MODELOS_GEMINI:
        envio = cuerpo
        if modelo.startswith("gemini-3"):
            envio = json.loads(json.dumps(cuerpo))
            envio["generationConfig"]["thinkingConfig"] = {"thinkingLevel": "high" if pensar else "low"}
        for intento in range(3):
            try:
                r = json.loads(
                    pedir(
                        f"https://generativelanguage.googleapis.com/v1beta/models/{modelo}:generateContent",
                        data=json.dumps(envio).encode(),
                        headers={"Content-Type": "application/json", "x-goog-api-key": clave},
                        method="POST",
                        timeout=240 if pensar else 180,
                    )
                )
                if pensar:
                    print(f"  (pensó con {modelo})")
                return json.loads(r["candidates"][0]["content"]["parts"][-1]["text"])
            except urllib.error.HTTPError as e:
                detalle = e.read().decode(errors="replace")
                errores.append(f"{modelo}: HTTP {e.code} {detalle[:150]}")
                print(f"  {errores[-1]}")
                if e.code == 429 and "PerDay" in detalle:
                    break  # cuota diaria de este modelo: probar el otro
                # Al pensar hay modelos de reemplazo: un solo reintento corto antes de pasar al siguiente.
                if e.code in (429, 500, 503) and intento < (1 if pensar else 2):
                    time.sleep(15 if pensar else 20 * (intento + 1))
                    continue
                break
            except (TimeoutError, OSError) as e:  # se colgó (socket.timeout, URLError): siguiente modelo
                errores.append(f"{modelo}: sin respuesta ({e})")
                print(f"  {errores[-1]}")
                break
            except (KeyError, ValueError, IndexError) as e:
                errores.append(f"{modelo}: respuesta inválida ({e})")
                break
    raise CuotaAgotada(" | ".join(errores[-2:]))


ALCANCE_MIN_ALERTA = 20  # en redes, una alerta necesita al menos estas interacciones (un trol sin eco no es crisis)


def con_alcance(p):
    return p["fuente"] == "medios" or (p.get("interacciones") or 0) >= ALCANCE_MIN_ALERTA


def tuit_original(tid, cache={}):
    """Texto del tuit al que responde una pieza de X (vía pública de inserción de tuits, gratis). "" si no se puede."""
    if not tid or not str(tid).isdigit():
        return ""
    if tid not in cache:
        try:
            t = json.loads(pedir(f"https://cdn.syndication.twimg.com/tweet-result?id={tid}&token=a", timeout=15))
            cache[tid] = f"@{t.get('user', {}).get('screen_name', '')}: {limpiar(t.get('text'), 400)}"
        except Exception:
            cache[tid] = ""
    return cache[tid]


def ejemplos_corregidos(db, maximo=25):
    """Las últimas correcciones del equipo, como ejemplos para que Gemini no repita el error."""
    filas = db.q(
        "SELECT p.fuente, p.titulo, p.texto, c.campo, c.antes, c.despues FROM correcciones c JOIN piezas p ON p.id = c.pieza "
        "ORDER BY c.creado DESC LIMIT ?",
        [maximo],
    )
    if not filas:
        return ""
    lineas = [
        f"- {f['fuente']}: \"{limpiar(f['titulo'] or f['texto'], 220)}\" -> {f['campo']} correcto: {f['despues']} (no {f['antes']})"
        for f in filas
    ]
    return "\n\nCorrecciones hechas por el equipo de la Secretaría (aprende el criterio, no las copies a ciegas):\n" + "\n".join(lineas)


def clasificar(db, maximo):
    """Clasifica hasta `maximo` piezas pendientes, de a 25 por llamada a Gemini."""
    pendientes = db.q(
        "SELECT id, fuente, medio, titulo, texto, autor, interacciones, padre FROM piezas WHERE clasificado = 0 AND corregido IS NULL ORDER BY recogido DESC LIMIT ?",
        [maximo],
    )
    hechas = 0
    ejemplos = ejemplos_corregidos(db) if pendientes else ""
    for i in range(0, len(pendientes), 25):
        trozo = pendientes[i : i + 25]
        lineas = []
        for n, p in enumerate(trozo):
            tipo = "Noticia" if p["fuente"] == "medios" else f"{p['fuente']}"
            original = tuit_original(p["padre"]) if p["fuente"] == "x" else ""
            if original:
                original = f"(Responde a {original})\n"
            elif p["padre"] and p["fuente"] != "medios":
                original = "(Es un comentario o respuesta)\n"
            lineas.append(
                f"[{n}] {tipo} | {p['medio'] or ''} | {p['autor'] or ''}\n{original}{p['titulo'] or ''}\n{(p['texto'] or '')[:700]}"
            )
        cuerpo = {
            "systemInstruction": {"parts": [{"text": INSTRUCCIONES + ejemplos}]},
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
                    "alerta = ?, resumen = ?, aspecto = ?, idea = ?, rumor = ?, necesidad = ?, actor = ?, tono_actor = ? WHERE id = ?",
                    [
                        1 if x["relevante"] else 0,
                        x["sobre"],
                        x["tono"],
                        x["tema"] if x["tema"] in TEMAS else "Otro",
                        x["provincia"] if x["provincia"] in PROVINCIAS else "",
                        1 if x["alerta"] and con_alcance(p) else 0,
                        limpiar(x["resumen"], 300),
                        x.get("aspecto") if x.get("aspecto") in ASPECTOS[:-1] else None,
                        limpiar(x.get("idea"), 120) or None,
                        limpiar(x.get("rumor"), 160) or None,
                        x.get("necesidad") if x.get("necesidad") in NECESIDADES[:-1] else None,
                        x.get("actor") if x.get("actor") in ACTORES[:-1] else None,
                        x.get("tono_actor") if x.get("actor") in ACTORES[:-1] and x.get("tono_actor") in ("positivo", "neutro", "critico") else None,
                        p["id"],
                    ],
                )
            )
        db.lote(sentencias)
        hechas += len(sentencias)
    print(f"  Clasificadas: {hechas} de {len(pendientes)} pendientes")
    return hechas


# Resumen propio de la Ley Orgánica para la Gestión Integral del Riesgo de Desastres (no el texto de LEXIS).
MARCO_LEGAL = open(os.path.join(AQUI, "marco_legal.md"), encoding="utf-8").read()
# Texto literal de los artículos que importan para recomendar (respuesta, competencias, COE, comunicación, alertas,
# declaratorias, registro de afectados, transparencia e infracciones). La ley completa (54 páginas) hacía que los
# modelos gratuitos no alcanzaran a responder; con estos artículos el pedido pesa una décima parte.
ARTICULOS_CLAVE = [13, 14, 19, 21, 23, 28, 29, 35, 41, 61, 62, 63, 64, 65, 66, 67, 68, 71, 72, 73, 76, 78, 80]


def articulos_de_la_ley(numeros):
    texto = open(os.path.join(AQUI, "ley", "ley_gestion_integral_riesgo_desastres.md"), encoding="utf-8").read()
    texto = texto[: texto.index("DISPOSICIONES GENERALES", texto.index("Art. 82"))]  # solo el cuerpo de la ley
    texto = re.sub(r"\n[^\n]*Página \d+ de \d+[^\n]*", "", texto)  # pies de página
    texto = re.sub(r"[ \t]+", " ", texto)
    partes = re.split(r"(?=\bArt\. ?\d+\.\s?-)", texto)
    elegidos = []
    for p in partes:
        m = re.match(r"Art\. ?(\d+)\.", p)
        if m and int(m.group(1)) in numeros:
            fin = re.search(r"\n\s*(CAPÍTULO|Sección|DISPOSICIONES)", p)
            elegidos.append(re.sub(r"\s*\n\s*", " ", p[: fin.start()] if fin else p).strip())
    return "\n\n".join(elegidos)


LEY_ARTICULOS = articulos_de_la_ley(ARTICULOS_CLAVE)

INSTRUCCIONES_RESUMEN = """Eres el asesor estratégico de comunicación de la secretaria Carolina Lozano, titular de la
Secretaría Nacional de Gestión de Riesgos (SNGR) de Ecuador, durante El Niño 2026. Ella tiene 2 minutos para leerte.

Recibes: (1) cifras de las últimas 24 horas frente a las 24 anteriores, (2) las narrativas vigentes y (3) las piezas
de las últimas 24 horas (medio o cuenta, tono, tema, provincia, interacciones, resumen y texto).

Piensa primero: qué cambió frente a ayer, qué crece, quién lo empuja, qué riesgo reputacional u operativo hay para la
Secretaría y para ella, qué oportunidad hay, y qué haría un buen equipo de crisis hoy.

Luego escribe:
- vinetas: 4 frases cortas. Primero lo más importante para decidir, no lo más obvio. Cada una con un dato concreto
  sacado de las piezas (cifra, medio, provincia, cuenta). Distingue lo que dicen los medios de lo que dice la gente en
  redes. Si algo crece o cae frente a ayer, dilo. Nada de bulla: un comentario o respuesta suelta de una cuenta
  pequeña (pocas vistas) no merece viñeta; solo lo que tiene alcance o se repite en muchas piezas. Lo que se reclama a
  alcaldes o prefectos solo entra si afecta a la Secretaría.
- acciones: exactamente 3 decisiones para HOY, de comunicación o de gestión, ordenadas por urgencia. Cada una debe ser
  específica (qué, quién, dónde, por qué canal) y responder a algo concreto de las piezas; nada genérico como "desplegar
  ayuda" o "coordinar con los COE" sin decir qué cambia. "porque": la evidencia (cifras, medios, provincias).
  "base_legal": el o los artículos de la ley que dan a la Secretaría la competencia para hacerlo (p. ej. "Art. 61 y 72").
  Cada acción debe estar dentro de las competencias de la Secretaría según el MARCO LEGAL de abajo: si algo le toca a un
  GAD, al COE o a la Presidencia, la acción es coordinar, pedir, apoyar de forma subsidiaria o emitir lineamientos, no
  ejecutarlo ella. Nunca propongas algo que cruce los límites de la sección 4 del marco legal.
CERO INFORMACIÓN FALSA: solo afirma lo que está en las piezas recibidas. No completes cifras, nombres, fechas ni lugares
que no estén escritos ahí; si dos piezas dan cifras distintas, di que difieren. Si no hay datos sobre algo, dilo ("no
hay datos de…"). Un vacío honesto vale más que una frase convincente. Si la información es poca, dilo y propone qué
vigilar.
Sé breve: cada viñeta en máximo 18 palabras; cada acción en máximo 12 palabras; cada "porque" en máximo 20 palabras.

""" + MARCO_LEGAL + "\n\nTEXTO LITERAL DE LOS ARTÍCULOS CLAVE (para verificar competencias y citar):\n" + LEY_ARTICULOS


def resumen_del_dia(db, vigentes=None):
    hoy = datetime.now(ECUADOR).strftime("%Y-%m-%d")
    ahora_utc = datetime.now(timezone.utc)
    hace24 = (ahora_utc - timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%SZ")
    hace48 = (ahora_utc - timedelta(hours=48)).strftime("%Y-%m-%dT%H:%M:%SZ")
    filas = db.q(
        "SELECT fuente, medio, autor, sobre, tono, tema, provincia, alerta, resumen, texto, titulo, interacciones, rumor, "
        "necesidad, actor, aspecto, vistas FROM piezas WHERE relevante = 1 AND COALESCE(fecha, recogido) >= ? "
        "ORDER BY alerta DESC, interacciones DESC LIMIT 200",
        [hace24],
    )
    if not filas:
        return
    cifras = db.q(
        "SELECT COALESCE(fecha, recogido) >= ? AS hoy, fuente, tono, COUNT(*) AS n FROM piezas "
        "WHERE relevante = 1 AND COALESCE(fecha, recogido) >= ? GROUP BY hoy, fuente, tono",
        [hace24, hace48],
    )
    texto = "CIFRAS (hoy = últimas 24 h; ayer = 24 h anteriores):\n" + "\n".join(
        f"- {'hoy' if c['hoy'] else 'ayer'} | {c['fuente']} | {c['tono']} | {c['n']}" for c in cifras
    )
    if vigentes:
        texto += "\n\nNARRATIVAS VIGENTES (3 días):\n" + "\n".join(
            f"- {n['titulo']} ({n['total']} menciones; {n['ultimas24']} hoy vs {n['previas24']} ayer)" for n in vigentes
        )
    texto += "\n\nPIEZAS DE HOY:\n" + "\n".join(
        f"- {f['fuente']} | {f['autor'] or f['medio'] or ''} | sobre {f['sobre']} | {f['tono']} | {f['tema']} | "
        f"{f['provincia'] or '-'} | {f['interacciones'] or 0} interacciones | {f['vistas'] or 0} vistas"
        f"{' | ALERTA' if f['alerta'] else ''}{' | pide ' + f['necesidad'] if f['necesidad'] else ''}"
        f"{' | dirigido a ' + f['actor'] if f['actor'] else ''}{' | RUMOR: ' + f['rumor'] if f['rumor'] else ''}"
        f"\n  {f['titulo'] or ''} {f['resumen'] or ''} {(f['texto'] or '')[:300]}"
        for f in filas
    )
    cuerpo = {
        "systemInstruction": {"parts": [{"text": INSTRUCCIONES_RESUMEN}]},
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
                            "properties": {
                                "accion": {"type": "string"},
                                "porque": {"type": "string"},
                                "base_legal": {"type": "string"},
                            },
                            "required": ["accion", "porque", "base_legal"],
                        },
                    },
                },
                "required": ["vinetas", "acciones"],
            },
            "temperature": 0.4,
        },
    }
    try:
        r = gemini(cuerpo, pensar=True)
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
    "sueltos. Busca el marco de fondo (qué cree la gente sobre la respuesta, a quién culpa o reconoce, qué teme), no el "
    "hecho noticioso. Para cada una: titulo (la idea como la diría la gente, máx. 8 palabras), explicacion (1 o 2 frases: "
    "quién la empuja, medios o redes, y qué riesgo u oportunidad es para la Secretaría y para Carolina) y n (los números de "
    "TODAS las ideas que pertenecen a esa narrativa). Cada número va en una sola narrativa como máximo; deja fuera las "
    "ideas sueltas que no se repiten. Si una narrativa de la corrida anterior sigue viva, conserva su título para poder "
    "seguir su evolución. No inventes nada."
)
INSTRUCCIONES_RUMORES = (
    "Eres verificador de datos en Ecuador durante la emergencia por El Niño 2026. Recibes rumores numerados que circulan en "
    "medios y redes. Agrupa los que dicen lo mismo (hasta 8 grupos; un rumor que aparece una sola vez también puede ser un "
    "grupo si es grave). Para cada grupo: titulo (el rumor como afirmación, máx. 12 palabras), explicacion (1 frase: por "
    "qué conviene aclararlo y qué debería confirmar o desmentir la Secretaría) y n (los números que pertenecen al grupo). "
    "Descarta lo que NO es rumor: alertas, pronósticos o cifras oficiales (Inamhi, SNGR, COE), opiniones y críticas. Un "
    "rumor es una afirmación de hecho sin fuente o falsa que puede causar pánico, desconfianza o mala conducta. Si nada "
    "califica, devuelve grupos vacío. No inventes nada que no esté en los rumores. En la explicación, la respuesta "
    "sugerida es siempre información oficial clara (arts. 61 y 72); nunca sancionar a ciudadanos por opinar o criticar."
)


def armar_grupo(titulo, explicacion, miembros):
    """Cifras de una narrativa o rumor a partir de sus piezas (se cuentan aquí, no las inventa el modelo)."""
    ahora_utc = datetime.now(timezone.utc)
    hace24 = (ahora_utc - timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%SZ")
    hace48 = (ahora_utc - timedelta(hours=48)).strftime("%Y-%m-%dT%H:%M:%SZ")
    tonos = {"positivo": 0, "neutro": 0, "critico": 0}
    fuentes = {}
    actores = {}
    for f in miembros:
        # Si la pieza habla de un alcalde, prefecto u otro actor, su tono es el juicio sobre ese actor.
        local = f.get("actor") and f["actor"] not in ACTORES_SNGR and f.get("tono_actor")
        tono = f["tono_actor"] if local else f["tono"]
        tonos[tono] = tonos.get(tono, 0) + 1
        if f.get("actor"):
            actores[f["actor"]] = actores.get(f["actor"], 0) + 1
        fuentes[f["fuente"]] = fuentes.get(f["fuente"], 0) + 1
    ejemplos = sorted(miembros, key=lambda f: (-(f["interacciones"] or 0), f["f"]))[:3]
    por_dia = {}  # piezas por día de Ecuador, para la curva de cada narrativa
    for f in miembros:
        dia = (datetime.fromisoformat(f["f"][:19]) - timedelta(hours=5)).strftime("%Y-%m-%d")
        por_dia[dia] = por_dia.get(dia, 0) + 1
    return {
        "titulo": limpiar(titulo, 120),
        "explicacion": limpiar(explicacion, 400),
        "total": len(miembros),
        "ultimas24": sum(1 for f in miembros if f["f"] >= hace24),
        "previas24": sum(1 for f in miembros if hace48 <= f["f"] < hace24),
        "tonos": tonos,
        "fuentes": fuentes,
        "interacciones": sum(f["interacciones"] or 0 for f in miembros),
        "porDia": por_dia,
        "actores": actores,
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


def agrupar(filas, campo, instrucciones, minimo, anteriores=None):
    """Gemini agrupa los textos de `campo`; las cifras (total, hoy vs ayer, tono, fuentes) se cuentan aquí."""
    lineas = "\n".join(
        f"[{n}] ({f['tono']}, {f['fuente']}, {f['autor'] or f['medio'] or ''}) {f[campo]} — {(f['resumen'] or '')[:160]}"
        for n, f in enumerate(filas)
    )
    if anteriores:
        lineas = "TÍTULOS DE LA CORRIDA ANTERIOR: " + " | ".join(anteriores) + "\n\n" + lineas
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
    r = gemini(cuerpo, pensar=True)
    salida, usados = [], set()
    for g in r.get("grupos", []):
        miembros = []
        for n in g.get("n", []):
            if isinstance(n, int) and 0 <= n < len(filas) and n not in usados:
                usados.add(n)
                miembros.append(filas[n])
        if len(miembros) >= minimo:
            salida.append(armar_grupo(g["titulo"], g["explicacion"], miembros))
    salida.sort(key=lambda x: (-x["ultimas24"], -x["total"]))
    return salida


def narrativas(db):
    """Narrativas y rumores de los últimos 3 días (se guardan juntos; el tablero muestra la última agrupación)."""
    ahora_utc = datetime.now(timezone.utc)
    desde = (ahora_utc - timedelta(days=3)).strftime("%Y-%m-%dT%H:%M:%SZ")
    columnas = ("id, fuente, medio, autor, url, titulo, texto, resumen, tono, idea, rumor, interacciones, actor, tono_actor, "
                "COALESCE(fecha, recogido) AS f")
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
    previa = db.q("SELECT datos FROM narrativas ORDER BY creado DESC LIMIT 1")
    anteriores = [n["titulo"] for n in json.loads(previa[0]["datos"]).get("narrativas", [])] if previa else []
    try:
        if len(ideas) >= 5:
            datos["narrativas"] = agrupar(ideas, "idea", INSTRUCCIONES_NARRATIVAS, 2, anteriores)
        if rumores:
            datos["rumores"] = agrupar(rumores, "rumor", INSTRUCCIONES_RUMORES, 1)
    except CuotaAgotada as e:
        print(f"  Narrativas no se pudieron: {e}")
        return
    db.q("INSERT INTO narrativas (creado, datos) VALUES (?, ?)", [ahora(), json.dumps(datos, ensure_ascii=False)])
    db.q("DELETE FROM narrativas WHERE creado < ?", [(ahora_utc - timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%SZ")])
    print(f"  Narrativas: {len(datos['narrativas'])} · rumores: {len(datos['rumores'])}")
    return datos["narrativas"]


INSTRUCCIONES_AGENDA = """Eres analista de medios en Ecuador. Recibes los titulares numerados que publicaron los medios
del país en las últimas 24 horas.
1. Define en "temas" los 8 a 14 TEMAS de la agenda nacional que más se repiten. Un tema es un asunto de actualidad, ni
   demasiado amplio ("Noticias") ni un hecho suelto: p. ej. "Terremoto en Panamá y alerta de tsunami", "Selección de
   Ecuador y Fecha FIFA", "Inseguridad y crimen", "Apagones y crisis eléctrica", "Feriado del 9 de octubre". Nombre
   corto (máx. 6 palabras), en español, sin cifras. Si te paso los temas de la corrida anterior, reutiliza esos
   nombres cuando sea el mismo asunto.
2. El tema 0 es SIEMPRE "El Niño y lluvias": El Niño, lluvias, tormentas, alertas meteorológicas, inundaciones,
   deslaves, oleaje, damnificados, emergencias por lluvias y su prevención EN ECUADOR (también la Secretaría de Gestión
   de Riesgos cuando habla de eso, y la política que gira en torno a El Niño, como mover las elecciones por El Niño).
   Lluvias o desastres de otros países no van aquí.
3. En "asignacion" pon TODOS los titulares, cada uno con el número de su tema (t). Usa t = -1 solo si de verdad no
   encaja en ningún tema."""


def agenda(db):
    """Ranking de temas de la agenda nacional (24 h) y dónde queda El Niño. Gemini solo agrupa; aquí se cuenta."""
    ahora_utc = datetime.now(timezone.utc)
    desde = (ahora_utc - timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%SZ")
    filas = db.q("SELECT id, medio, titulo, url FROM titulares WHERE fecha >= ? ORDER BY fecha DESC LIMIT 1500", [desde])
    if len(filas) < 30:
        print(f"  Agenda: muy pocos titulares ({len(filas)})")
        return
    previa = db.q("SELECT datos FROM agenda ORDER BY creado DESC LIMIT 1")
    anteriores = [t["tema"] for t in json.loads(previa[0]["datos"])["temas"]] if previa else []
    texto = "\n".join(f"[{n}] {f['titulo']}" for n, f in enumerate(filas))
    if anteriores:
        texto = "TEMAS DE LA CORRIDA ANTERIOR: " + " | ".join(anteriores) + "\n\n" + texto
    cuerpo = {
        "systemInstruction": {"parts": [{"text": INSTRUCCIONES_AGENDA}]},
        "contents": [{"role": "user", "parts": [{"text": texto}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseSchema": {
                "type": "object",
                "properties": {
                    "temas": {"type": "array", "items": {"type": "string"}},
                    "asignacion": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {"n": {"type": "integer"}, "t": {"type": "integer"}},
                            "required": ["n", "t"],
                        },
                    },
                },
                "required": ["temas", "asignacion"],
            },
            "temperature": 0.2,
        },
    }
    try:
        r = gemini(cuerpo)
    except CuotaAgotada as e:
        print(f"  Agenda no se pudo: {e}")
        return
    nombres = [limpiar(t, 60) for t in r.get("temas", [])] or ["El Niño y lluvias"]
    temas = [{"tema": nombre, "nino": i == 0, "miembros": []} for i, nombre in enumerate(nombres)]
    usados = set()
    for a in r.get("asignacion", []):
        n, t = a.get("n"), a.get("t")
        if isinstance(n, int) and 0 <= n < len(filas) and n not in usados and isinstance(t, int) and 0 <= t < len(temas):
            usados.add(n)
            temas[t]["miembros"].append(filas[n])
    print(f"  Agenda: {len(usados)} de {len(filas)} titulares con tema")
    temas = [t for t in temas if t["miembros"] or t["nino"]]
    temas.sort(key=lambda t: -len(t["miembros"]))
    sentencias = [("UPDATE titulares SET tema = NULL, nino = 0 WHERE fecha >= ?", [desde])]
    for t in temas:
        ids = [f["id"] for f in t["miembros"]]
        for i in range(0, len(ids), 90):
            trozo = ids[i : i + 90]
            sentencias.append(
                (f"UPDATE titulares SET tema = ?, nino = ? WHERE id IN ({','.join('?' * len(trozo))})",
                 [t["tema"], 1 if t["nino"] else 0] + trozo)
            )
    db.lote(sentencias)
    datos = {
        "total": len(filas),
        "medios": len({f["medio"] for f in filas}),
        "temas": [
            {
                "tema": t["tema"],
                "nino": t["nino"],
                "n": len(t["miembros"]),
                "medios": len({f["medio"] for f in t["miembros"]}),
                "ejemplos": [{"titulo": f["titulo"], "medio": f["medio"], "url": f["url"]} for f in t["miembros"][:3]],
            }
            for t in temas
        ],
    }
    db.q("INSERT INTO agenda (creado, datos) VALUES (?, ?)", [ahora(), json.dumps(datos, ensure_ascii=False)])
    db.q("DELETE FROM agenda WHERE creado < ?", [(ahora_utc - timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%SZ")])
    nino = next((t for t in datos["temas"] if t["nino"]), None)
    puesto = datos["temas"].index(nino) + 1 if nino and nino["n"] else None
    print(f"  Agenda: {len(filas)} titulares, {len(temas)} temas; El Niño puesto {puesto} con {nino['n'] if nino else 0}")
    return datos


def analisis_de_claude_reciente(db, horas=9):
    """True si el último análisis de fondo lo hizo Claude (rutina de 8, 12 y 20 h) hace menos de `horas`."""
    filas = db.q("SELECT texto, creado FROM resumenes ORDER BY creado DESC LIMIT 1")
    if not filas or json.loads(filas[0]["texto"]).get("autor") != "Claude":
        return False
    creado = datetime.fromisoformat(filas[0]["creado"].replace("Z", "+00:00"))
    return datetime.now(timezone.utc) - creado < timedelta(hours=horas)


# ---------------------------------------------------------------- corrida


def main():
    args = set(sys.argv[1:])
    inicio = ahora()
    db = D1()
    detalle = {}
    if "--solo-agenda" in args:  # para probar: solo titulares y ranking, sin tocar piezas ni corridas
        guardar_titulares(db, recoger_titulares())
        agenda(db)
        return

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

    print("Titulares de la agenda nacional…")
    try:
        detalle["titulares"] = guardar_titulares(db, recoger_titulares())
    except Exception as e:
        print(f"  ERROR titulares: {e}")
        detalle["titulares"] = f"error: {str(e)[:150]}"

    if "--sin-gemini" not in args:
        # La agenda cada 4 horas basta para ver la evolución y cuida la cuota de Gemini.
        ultima = db.q("SELECT MAX(creado) AS c FROM agenda")[0]["c"]
        if not ultima or ultima < (datetime.now(timezone.utc) - timedelta(hours=3, minutes=50)).strftime("%Y-%m-%dT%H:%M:%SZ"):
            print("Agenda nacional…")
            agenda(db)
        print("Gemini…")
        detalle["clasificadas"] = clasificar(db, int(config("MAX_CLASIFICAR", "400")))
        if analisis_de_claude_reciente(db):
            print("  Análisis de fondo: lo hizo Claude hace menos de 9 h, Gemini no lo repite")
        else:
            # Primero las narrativas: el resumen las usa para decidir qué importa.
            vigentes = narrativas(db)
            resumen_del_dia(db, vigentes)

    detalle["consultas_d1"] = db.consultas
    db.q("INSERT INTO corridas (inicio, fin, detalle) VALUES (?, ?, ?)", [inicio, ahora(), json.dumps(detalle, ensure_ascii=False)])
    print("Listo:", json.dumps(detalle, ensure_ascii=False))


if __name__ == "__main__":
    main()
