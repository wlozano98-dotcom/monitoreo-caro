"""Vigilante: revisa en cada corrida que nada se esté rompiendo en silencio (pedido de Andrés, 19 oct 2026).

Pasó: todas las corridas en verde mientras se perdía ~40 % de las notas de El Niño. Si algo falla, el último paso de
monitor.yml marca la corrida en rojo y GitHub manda un correo. Para no llenar el correo cada 2 horas: avisa cuando
aparece un problema nuevo, y si sigue, una vez al día.
"""

import json
from datetime import datetime, timedelta, timezone

COBERTURA_MIN = 0.5  # parte de los titulares de El Niño (agenda) que las búsquedas ya habían encontrado
RECORDAR_HORAS = 24


def hace(horas):
    return (datetime.now(timezone.utc) - timedelta(hours=horas)).strftime("%Y-%m-%dT%H:%M:%SZ")


def revisar(db, detalle):
    """Devuelve {clave: explicación} de lo que anda mal. La clave es fija para comparar entre corridas."""
    avisos = {}

    for fuente, valor in detalle.items():
        if isinstance(valor, str) and valor.startswith("error"):
            avisos[f"error {fuente}"] = f"{fuente} falló: {valor}"
    for nombre in detalle.get("lluvias_errores", []):
        avisos[f"lluvias {nombre}"] = f"Lluvias: no se pudo leer {nombre}"

    previas = [json.loads(c["detalle"]) for c in db.q("SELECT detalle FROM corridas ORDER BY inicio DESC LIMIT 2")]
    ultimas = [detalle] + previas
    if len(ultimas) == 3 and all(not isinstance(c.get("Google Noticias"), int) or c["Google Noticias"] == 0 for c in ultimas):
        avisos["google noticias"] = "Google Noticias no trajo nada en 3 corridas seguidas (¿bloqueo?)"
    if len(ultimas) >= 2 and all(not isinstance(c.get("titulares"), int) or c["titulares"] < 200 for c in ultimas[:2]):
        avisos["titulares"] = "La agenda nacional trae muy pocos titulares (menos de 200) en 2 corridas seguidas"

    # Cobertura: de lo que la agenda marcó como El Niño en 24 h, cuánto ya habían traído las búsquedas.
    c = db.q(
        "SELECT COUNT(*) AS total, SUM(EXISTS (SELECT 1 FROM piezas p WHERE (p.titulo = t.titulo OR p.url = t.url) "
        "AND COALESCE(p.consulta, '') <> 'agenda')) AS halladas FROM titulares t WHERE t.nino = 1 AND t.fecha >= ?",
        [hace(24)],
    )[0]
    if (c["total"] or 0) >= 15 and (c["halladas"] or 0) / c["total"] < COBERTURA_MIN:
        avisos["cobertura"] = (
            f"Las búsquedas solo encontraron {c['halladas']} de {c['total']} titulares de El Niño de 24 h "
            f"({100 * c['halladas'] // c['total']} %). El resto entró por la agenda, pero conviene revisar las búsquedas."
        )

    redes = db.q("SELECT detalle FROM corridas WHERE inicio >= ? AND detalle LIKE '%\"X\"%' LIMIT 1", [hace(30)])
    if not redes and "X" not in detalle:
        avisos["redes"] = "Las redes (X, TikTok, Facebook) no corrieron en las últimas 30 h"
    elif "X" in detalle and detalle["X"] == 0:
        avisos["x"] = "X no trajo ningún tuit en la corrida de la noche"

    sin = db.q("SELECT COUNT(*) AS n FROM piezas WHERE clasificado = 0 AND corregido IS NULL AND recogido < ?", [hace(6)])[0]["n"]
    if sin > 30:
        avisos["gemini"] = f"Gemini no clasifica: {sin} piezas llevan más de 6 h sin clasificar"

    r = db.q("SELECT texto, creado FROM resumenes ORDER BY creado DESC LIMIT 1")
    claude = db.q("SELECT creado FROM resumenes WHERE texto LIKE '%\"autor\": \"Claude\"%' OR texto LIKE '%\"autor\":\"Claude\"%' "
                  "ORDER BY creado DESC LIMIT 1")
    if not claude or claude[0]["creado"] < hace(12):
        avisos["claude"] = "El análisis de Claude no se actualiza hace más de 12 h (revisar la rutina en la nube)"
    elif not r or r[0]["creado"] < hace(12):
        avisos["resumen"] = "El resumen del día no se actualiza hace más de 12 h"

    s = db.q("SELECT numero, datos FROM sitrep ORDER BY numero DESC LIMIT 1")
    if s:
        fecha = json.loads(s[0]["datos"]).get("fecha") or ""
        if fecha and fecha < (datetime.now(timezone.utc) - timedelta(days=4)).strftime("%Y-%m-%dT%H:%M"):
            avisos["sitrep"] = f"El último SitRep leído (n.º {s[0]['numero']}, {fecha}) tiene más de 4 días: ¿cambió la página?"

    return avisos


def decidir(db, avisos):
    """True si hay que mandar correo: un problema nuevo respecto de la corrida anterior, o uno viejo sin aviso en 24 h."""
    if not avisos:
        return False
    previa = db.q("SELECT detalle FROM corridas ORDER BY inicio DESC LIMIT 1")
    antes = set(json.loads(previa[0]["detalle"]).get("avisos", {})) if previa else set()
    if set(avisos) - antes:
        return True
    enviado = db.q("SELECT 1 FROM corridas WHERE inicio >= ? AND detalle LIKE '%\"aviso_enviado\": true%' LIMIT 1",
                   [hace(RECORDAR_HORAS)])
    return not enviado
