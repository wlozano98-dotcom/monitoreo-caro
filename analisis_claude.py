"""Análisis de fondo hecho por Claude (rutina en la nube, 8:00, 12:00 y 20:00 de Ecuador).

El agente de la nube no tiene claves ni toca la base:
  1. `preparar` (en GitHub Actions, con claves): escribe analisis/contexto.md con las piezas de los últimos 3 días.
  2. El agente lee ese archivo, marco_legal.md y la ley, y escribe analisis/ultimo.json; `validar` lo revisa.
  3. `cargar` (en GitHub Actions, al cambiar analisis/ultimo.json): lo pasa a la base. Las cifras de cada narrativa
     y rumor se cuentan aquí con las piezas que el agente citó, igual que con Gemini.

Uso: python3 analisis_claude.py preparar | validar [archivo] | cargar [archivo]
"""

import json
import os
import sys
from datetime import datetime, timedelta, timezone

import monitor as m

CARPETA = os.path.join(m.AQUI, "analisis")
CONTEXTO = os.path.join(CARPETA, "contexto.md")
ULTIMO = os.path.join(CARPETA, "ultimo.json")
ID_CORTO = 10  # las piezas se citan por los primeros 10 caracteres de su id


def preparar():
    db = m.D1()
    ahora_utc = datetime.now(timezone.utc)
    iso = lambda d: d.strftime("%Y-%m-%dT%H:%M:%SZ")
    hace24, hace48, hace72 = (iso(ahora_utc - timedelta(hours=h)) for h in (24, 48, 72))
    cifras = db.q(
        "SELECT COALESCE(fecha, recogido) >= ? AS hoy, fuente, tono, COUNT(*) AS n FROM piezas "
        "WHERE relevante = 1 AND COALESCE(fecha, recogido) >= ? GROUP BY hoy, fuente, tono ORDER BY hoy DESC, fuente",
        [hace24, hace48],
    )
    piezas = db.q(
        "SELECT id, fuente, medio, autor, url, titulo, texto, resumen, tono, tema, provincia, aspecto, idea, rumor, "
        "necesidad, actor, alerta, interacciones, COALESCE(fecha, recogido) AS f FROM piezas "
        "WHERE relevante = 1 AND COALESCE(fecha, recogido) >= ? ORDER BY f DESC LIMIT 450",
        [hace72],
    )
    previa = db.q("SELECT datos FROM narrativas ORDER BY creado DESC LIMIT 1")
    vigentes = json.loads(previa[0]["datos"]).get("narrativas", []) if previa else []

    hora_ec = datetime.now(m.ECUADOR).strftime("%Y-%m-%d %H:%M")
    lineas = [
        f"# Contexto para el análisis de fondo ({hora_ec}, hora de Ecuador)",
        "",
        "Piezas ya clasificadas por Gemini (puede equivocarse: verifica con el texto). Cita las piezas por su [id].",
        "",
        "## Cifras: últimas 24 h frente a las 24 h anteriores",
        "",
    ]
    lineas += [f"- {'hoy' if c['hoy'] else 'ayer'} · {c['fuente']} · {c['tono']}: {c['n']}" for c in cifras] or ["- sin datos"]
    lineas += ["", "## Narrativas de la corrida anterior", ""]
    lineas += [
        f"- {n['titulo']} — {n['total']} piezas; {n['ultimas24']} en 24 h vs {n['previas24']} antes. {n['explicacion']}"
        for n in vigentes
    ] or ["- ninguna"]
    lineas += ["", f"## Piezas de los últimos 3 días ({len(piezas)}, de la más reciente a la más antigua)", ""]
    for p in piezas:
        quien = p["medio"] if p["fuente"] == "medios" else f"@{p['autor'] or ''} ({p['medio'] or ''})"
        marcas = [x for x in [
            p["tono"], p["tema"], p["provincia"], p["aspecto"] and f"aspecto: {p['aspecto']}",
            p["actor"] and f"atribuye a: {p['actor']}", p["necesidad"] and f"pide: {p['necesidad']}",
            p["interacciones"] and f"{p['interacciones']} interacciones", p["alerta"] and "ALERTA",
            p["rumor"] and f"RUMOR: {p['rumor']}",
        ] if x]
        lineas.append(f"[{p['id'][:ID_CORTO]}] {p['f'][:16].replace('T', ' ')} UTC · {p['fuente']} · {quien} · {' · '.join(marcas)}")
        for texto in (p["titulo"], p["resumen"], p["idea"] and f"idea: {p['idea']}", (p["texto"] or "")[:280]):
            if texto:
                lineas.append(f"    {texto}")
        lineas.append("")
    os.makedirs(CARPETA, exist_ok=True)
    with open(CONTEXTO, "w", encoding="utf-8") as f:
        f.write("\n".join(lineas))
    print(f"Contexto: {len(piezas)} piezas -> {os.path.relpath(CONTEXTO, m.AQUI)}")


def validar(ruta=ULTIMO):
    """Revisa la forma del análisis. Devuelve el dict o termina con error explicando qué falta."""
    try:
        a = json.load(open(ruta, encoding="utf-8"))
    except Exception as e:
        sys.exit(f"No se pudo leer {ruta}: {e}")
    errores = []
    if not (isinstance(a.get("vinetas"), list) and 3 <= len(a["vinetas"]) <= 5 and all(isinstance(v, str) and v for v in a["vinetas"])):
        errores.append("vinetas: lista de 3 a 5 frases")
    acc = a.get("acciones")
    if not (isinstance(acc, list) and len(acc) == 3 and all(isinstance(x, dict) and x.get("accion") and x.get("porque") and x.get("base_legal") for x in acc)):
        errores.append("acciones: exactamente 3, cada una con accion, porque y base_legal")
    for campo in ("narrativas", "rumores"):
        grupos = a.get(campo)
        if not isinstance(grupos, list) or not all(isinstance(g, dict) and g.get("titulo") and g.get("explicacion") and isinstance(g.get("ids"), list) and g["ids"] for g in grupos):
            errores.append(f"{campo}: lista (puede ser vacía) de {{titulo, explicacion, ids: [ids de piezas]}}")
    if not a.get("narrativas"):
        errores.append("narrativas: al menos una")
    if errores:
        sys.exit("Análisis inválido:\n- " + "\n- ".join(errores))
    print("Análisis válido.")
    return a


def cargar(ruta=ULTIMO):
    a = validar(ruta)
    db = m.D1()
    # Si ya se cargó este mismo análisis, no repetir.
    huella = m.huella(json.dumps(a, sort_keys=True, ensure_ascii=False))
    ultimo = db.q("SELECT texto FROM resumenes ORDER BY creado DESC LIMIT 1")
    if ultimo and json.loads(ultimo[0]["texto"]).get("huella") == huella:
        print("Este análisis ya estaba cargado.")
        return
    columnas = "id, fuente, medio, autor, url, titulo, texto, resumen, tono, interacciones, COALESCE(fecha, recogido) AS f"

    def piezas_de(ids):
        cortos = sorted({str(i).strip("[] ")[:ID_CORTO] for i in ids if str(i).strip()})
        if not cortos:
            return []
        filtro = " OR ".join("id LIKE ?" for _ in cortos)
        return db.q(f"SELECT {columnas} FROM piezas WHERE {filtro}", [c + "%" for c in cortos])

    datos = {"narrativas": [], "rumores": [], "autor": "Claude"}
    for campo, minimo in (("narrativas", 2), ("rumores", 1)):
        for g in a[campo]:
            miembros = piezas_de(g["ids"])
            if len(miembros) >= minimo:
                datos[campo].append(m.armar_grupo(g["titulo"], g["explicacion"], miembros))
            else:
                print(f"  Se omite '{g['titulo']}' ({campo}): solo {len(miembros)} piezas encontradas")
        datos[campo].sort(key=lambda x: (-x["ultimas24"], -x["total"]))
    db.q("INSERT INTO narrativas (creado, datos) VALUES (?, ?)", [m.ahora(), json.dumps(datos, ensure_ascii=False)])

    hoy = datetime.now(m.ECUADOR).strftime("%Y-%m-%d")
    resumen = {
        "vinetas": [m.limpiar(v, 300) for v in a["vinetas"]],
        "acciones": [
            {"accion": m.limpiar(x["accion"], 200), "porque": m.limpiar(x["porque"], 300), "base_legal": m.limpiar(x["base_legal"], 80)}
            for x in a["acciones"]
        ],
        "autor": "Claude",
        "huella": huella,
    }
    db.q(
        "INSERT INTO resumenes (fecha, texto, creado) VALUES (?, ?, ?) "
        "ON CONFLICT(fecha) DO UPDATE SET texto = excluded.texto, creado = excluded.creado",
        [hoy, json.dumps(resumen, ensure_ascii=False), m.ahora()],
    )
    print(f"Cargado: {len(datos['narrativas'])} narrativas, {len(datos['rumores'])} rumores, resumen y 3 acciones.")


if __name__ == "__main__":
    orden = sys.argv[1] if len(sys.argv) > 1 else ""
    ruta = sys.argv[2] if len(sys.argv) > 2 else ULTIMO
    if orden == "preparar":
        preparar()
    elif orden == "validar":
        validar(ruta)
    elif orden == "cargar":
        cargar(ruta)
    else:
        sys.exit(__doc__)
