"""Redes sociales vía Apify: X, TikTok y Facebook.

Apify regala 5 USD de crédito al mes. Presupuesto aproximado por día (precios del plan gratis, oct-2026):
  X        3 veces/día × 70 tweets   × 0,25 USD/1000  ≈ 0,05
  TikTok   1 vez/día: 30 videos × 0,30/1000 + 30 comentarios × 1,25/1000 ≈ 0,05
  Facebook 1 vez/día: 3 posts × 5/1000 + 10 comentarios × 2,5/1000 + arranques ≈ 0,045
  Total ≈ 0,145 USD/día ≈ 4,4 USD/mes. Si el uso del mes llega a TOPE_MES_USD, no se pide nada más.
"""

import json
import os
import urllib.parse
from datetime import datetime, timedelta, timezone

import monitor as m

TOPE_MES_USD = 4.5

CADA_HORAS = {"x": 8, "tiktok": 24, "facebook": 24}

ACTOR_X = "kaitoeasyapi~twitter-x-data-tweet-scraper-pay-per-result-cheapest"
ACTOR_TIKTOK = "apidojo~tiktok-scraper"
ACTOR_TIKTOK_COMENTARIOS = "clockworks~tiktok-comments-scraper"
ACTOR_FB_POSTS = "apify~facebook-posts-scraper"
ACTOR_FB_COMENTARIOS = "apify~facebook-comments-scraper"

# X: menciones y respuestas a sus cuentas, y conversación sobre El Niño en Ecuador.
BUSQUEDAS_X = [
    '(@carolozanohok OR to:carolozanohok OR "Carolina Lozano") -from:carolozanohok',
    '(@Riesgos_Ec OR to:Riesgos_Ec OR "Gestión de Riesgos" OR "Secretaría de Riesgos") -from:Riesgos_Ec',
    '("fenómeno de El Niño" OR "fenómeno del Niño") Ecuador',
]
TWEETS_POR_CORRIDA = 70

PERFILES_TIKTOK = ["carolinalozanohok", "riesgos_ec"]
BUSQUEDAS_TIKTOK = ["fenómeno del niño ecuador", "gestión de riesgos ecuador"]
VIDEOS_TIKTOK = 30
COMENTARIOS_TIKTOK = 30
VIDEOS_CON_COMENTARIOS = 3

PAGINAS_FACEBOOK = ["https://www.facebook.com/carolinalozanohok"]
POSTS_FACEBOOK = 3
COMENTARIOS_FACEBOOK = 10


# ---------------------------------------------------------------- Apify


def apify(actor, entrada, tope_usd, timeout=280):
    """Corre un actor y devuelve sus resultados. `tope_usd` es el máximo que Apify puede cobrar por esta corrida."""
    params = urllib.parse.urlencode({"timeout": timeout, "maxTotalChargeUsd": tope_usd})
    url = f"https://api.apify.com/v2/acts/{actor}/run-sync-get-dataset-items?{params}"
    datos = m.pedir(
        url,
        data=json.dumps(entrada).encode(),
        headers={"Authorization": f"Bearer {m.config('APIFY_TOKEN')}", "Content-Type": "application/json"},
        method="POST",
        timeout=timeout + 30,
    )
    items = json.loads(datos or b"[]")
    return [i for i in items if isinstance(i, dict) and not i.get("noResults") and not i.get("error")]


def gasto_del_mes():
    r = json.loads(m.pedir("https://api.apify.com/v2/users/me/limits", headers={"Authorization": f"Bearer {m.config('APIFY_TOKEN')}"}))
    return float(r["data"]["current"].get("monthlyUsageUsd", 0))


def toca(db, red):
    """True si ya pasaron CADA_HORAS desde la última vez (con 20 min de margen por el horario de GitHub)."""
    filas = db.q("SELECT cuando FROM ultimas WHERE red = ?", [red])
    if not filas:
        return True
    ultima = datetime.fromisoformat(filas[0]["cuando"].replace("Z", "+00:00"))
    return datetime.now(timezone.utc) - ultima >= timedelta(hours=CADA_HORAS[red], minutes=-20)


def marcar(db, red):
    db.q(
        "INSERT INTO ultimas (red, cuando) VALUES (?, ?) ON CONFLICT(red) DO UPDATE SET cuando = excluded.cuando",
        [red, m.ahora()],
    )


def primero(d, *claves, defecto=None):
    """El primer valor no vacío entre varias claves posibles (los actores cambian nombres de campos). Acepta 'a.b'."""
    for c in claves:
        v = d
        for parte in c.split("."):
            v = v.get(parte) if isinstance(v, dict) else None
        if v not in (None, "", [], {}):
            return v
    return defecto


def entero(v):
    try:
        return int(v or 0)
    except (TypeError, ValueError):
        return 0


# ---------------------------------------------------------------- X


def recoger_x(db):
    if not toca(db, "x"):
        print("  X: todavía no toca")
        return []
    desde = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
    items = apify(
        ACTOR_X,
        {
            "searchTerms": [f"{b} since:{desde}" for b in BUSQUEDAS_X],
            "maxItems": TWEETS_POR_CORRIDA,
            "queryType": "Latest",
            "lang": "es",
        },
        tope_usd=0.03,
    )
    piezas = []
    for t in items:
        tid = str(primero(t, "id", "id_str", "tweetId", defecto=""))
        texto = primero(t, "text", "full_text", "fullText", defecto="")
        if not tid or not texto:
            continue
        usuario = primero(t, "author.userName", "author.screen_name", "user.screen_name", "author.username", defecto="")
        url = primero(t, "url", "twitterUrl", defecto=f"https://x.com/{usuario or 'i'}/status/{tid}")
        piezas.append(
            {
                "id": m.huella("x", tid),
                "fuente": "x",
                "medio": primero(t, "author.name", "user.name", defecto=usuario),
                "url": url,
                "titulo": "",
                "texto": m.limpiar(texto),
                "autor": usuario,
                "fecha": m.fecha_iso(primero(t, "createdAt", "created_at")),
                "recogido": m.ahora(),
                "interacciones": sum(
                    entero(primero(t, c)) for c in ("likeCount", "retweetCount", "replyCount", "quoteCount", "favorite_count", "retweet_count")
                ),
                "padre": primero(t, "inReplyToId", "in_reply_to_status_id_str"),
                "consulta": "x",
            }
        )
    marcar(db, "x")
    print(f"  X: {len(piezas)} tweets")
    return piezas


# ---------------------------------------------------------------- TikTok


def recoger_tiktok(db):
    if not toca(db, "tiktok"):
        print("  TikTok: todavía no toca")
        return []
    entrada = {
        "startUrls": [f"https://www.tiktok.com/@{p}" for p in PERFILES_TIKTOK],
        "keywords": BUSQUEDAS_TIKTOK,
        "maxItems": VIDEOS_TIKTOK,
        "dateRange": "THIS_WEEK",
        "location": "EC",
        "sortType": "DATE_POSTED",
    }
    videos = apify(ACTOR_TIKTOK, entrada, tope_usd=0.02)
    piezas = []
    for v in videos:
        vid = str(primero(v, "id", "aweme_id", defecto=""))
        url = primero(v, "postPage", "webVideoUrl", "url", defecto="")
        if not vid or not url:
            continue
        usuario = primero(v, "channel.username", "authorMeta.name", "author.uniqueId", defecto="")
        piezas.append(
            {
                "id": m.huella("tiktok", vid),
                "fuente": "tiktok",
                "medio": primero(v, "channel.name", "authorMeta.nickName", defecto=usuario),
                "url": url,
                "titulo": "",
                "texto": m.limpiar(primero(v, "title", "text", "desc", defecto="")),
                "autor": usuario,
                "fecha": m.fecha_iso(primero(v, "uploadedAtFormatted", "createTimeISO", "uploadedAt", "createTime")),
                "recogido": m.ahora(),
                "interacciones": sum(entero(primero(v, c)) for c in ("likes", "comments", "shares", "diggCount", "commentCount", "shareCount")),
                "consulta": "tiktok",
            }
        )
    # Comentarios: los videos de sus cuentas con más comentarios (ahí está la conversación sobre ellas).
    propios = [p for p in piezas if (p["autor"] or "").lower() in PERFILES_TIKTOK] or piezas
    propios.sort(key=lambda p: -p["interacciones"])
    urls = [p["url"] for p in propios[:VIDEOS_CON_COMENTARIOS]]
    if urls:
        comentarios = apify(
            ACTOR_TIKTOK_COMENTARIOS,
            {"postURLs": urls, "commentsPerPost": COMENTARIOS_TIKTOK // len(urls), "maxRepliesPerComment": 0},
            tope_usd=0.05,
        )
        for c in comentarios:
            cid = str(primero(c, "cid", "id", defecto=""))
            texto = primero(c, "text", defecto="")
            if not cid or not texto:
                continue
            padre = primero(c, "videoWebUrl", "postUrl", defecto="")
            piezas.append(
                {
                    "id": m.huella("tiktok-c", cid),
                    "fuente": "tiktok",
                    "medio": "Comentario en TikTok",
                    "url": padre,
                    "titulo": "",
                    "texto": m.limpiar(texto),
                    "autor": primero(c, "uniqueId", "user.uniqueId", defecto=""),
                    "fecha": m.fecha_iso(primero(c, "createTimeISO", "createTime")),
                    "recogido": m.ahora(),
                    "interacciones": entero(primero(c, "diggCount", "likes")) + entero(primero(c, "replyCommentTotal")),
                    "padre": padre,
                    "consulta": "comentarios",
                }
            )
    marcar(db, "tiktok")
    print(f"  TikTok: {len(piezas)} (videos y comentarios)")
    return piezas


# ---------------------------------------------------------------- Facebook


def recoger_facebook(db):
    if not toca(db, "facebook"):
        print("  Facebook: todavía no toca")
        return []
    desde = (datetime.now(timezone.utc) - timedelta(days=3)).strftime("%Y-%m-%d")
    posts = apify(
        ACTOR_FB_POSTS,
        {"startUrls": [{"url": u} for u in PAGINAS_FACEBOOK], "resultsLimit": POSTS_FACEBOOK, "onlyPostsNewerThan": desde},
        tope_usd=0.03,
    )
    piezas = []
    for p in posts:
        url = primero(p, "url", "topLevelUrl", "facebookUrl", defecto="")
        if not url:
            continue
        piezas.append(
            {
                "id": m.huella("facebook", primero(p, "postId", "id", defecto=url)),
                "fuente": "facebook",
                "medio": primero(p, "pageName", "user.name", defecto="Facebook"),
                "url": url,
                "titulo": "",
                "texto": m.limpiar(primero(p, "text", "message", defecto="")),
                "autor": primero(p, "pageName", "user.name", defecto=""),
                "fecha": m.fecha_iso(primero(p, "time", "timestamp")),
                "recogido": m.ahora(),
                "interacciones": entero(primero(p, "likes")) + entero(primero(p, "comments")) + entero(primero(p, "shares")),
                "consulta": "facebook",
            }
        )
    if piezas:
        comentarios = apify(
            ACTOR_FB_COMENTARIOS,
            {"startUrls": [{"url": p["url"]} for p in piezas], "resultsLimit": COMENTARIOS_FACEBOOK, "viewOption": "RANKED_UNFILTERED"},
            tope_usd=0.04,
        )
        for c in comentarios:
            texto = primero(c, "text", defecto="")
            if not texto:
                continue
            padre = primero(c, "facebookUrl", "postUrl", "inputUrl", defecto="")
            piezas.append(
                {
                    "id": m.huella("facebook-c", primero(c, "id", "commentUrl", defecto=texto)),
                    "fuente": "facebook",
                    "medio": "Comentario en Facebook",
                    "url": primero(c, "commentUrl", defecto=padre),
                    "titulo": "",
                    "texto": m.limpiar(texto),
                    "autor": primero(c, "profileName", defecto=""),
                    "fecha": m.fecha_iso(primero(c, "date", "time")),
                    "recogido": m.ahora(),
                    "interacciones": entero(primero(c, "likesCount", "likes")),
                    "padre": padre,
                    "consulta": "comentarios",
                }
            )
    marcar(db, "facebook")
    print(f"  Facebook: {len(piezas)} (posts y comentarios)")
    return piezas


# ---------------------------------------------------------------- para monitor.py


def recolectores():
    if not m.config("APIFY_TOKEN"):
        print("Redes: falta APIFY_TOKEN, se saltan")
        return []
    try:
        gasto = gasto_del_mes()
    except Exception as e:
        print(f"Redes: no se pudo ver el gasto de Apify ({e}), se saltan por precaución")
        return []
    print(f"Redes: Apify lleva {gasto:.2f} USD este mes (tope {TOPE_MES_USD})")
    if gasto >= TOPE_MES_USD:
        print("Redes: tope del mes alcanzado, se saltan hasta el próximo mes")
        return []
    db = m.D1()
    return [
        ("X", lambda: recoger_x(db)),
        ("TikTok", lambda: recoger_tiktok(db)),
        ("Facebook", lambda: recoger_facebook(db)),
    ]
