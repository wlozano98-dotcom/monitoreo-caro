// Monitoreo Caro: API del tablero. Público, solo lectura. Lee D1 y guarda la respuesta 5 minutos en caché.

const CACHE_SEG = 300;
// Fecha de Ecuador (UTC-5) de una pieza: la de publicación o, si no hay, la de recogida.
const DIA = "date(datetime(COALESCE(fecha, recogido), '-5 hours'))";
const FUENTES = ["medios", "youtube", "x", "tiktok", "facebook"];
const SOBRE = ["carolina", "secretaria", "nino"];
const TONOS = ["positivo", "neutro", "critico"];
const ASPECTOS = ["Rapidez de la respuesta", "Llegada de la ayuda", "Presencia en territorio", "Coordinación entre instituciones", "Prevención y alertas", "Comunicación e información", "Liderazgo de Carolina Lozano"];
const ACTORES = ["Secretaría de Gestión de Riesgos", "Carolina Lozano", "Gobierno central", "Municipio o Prefectura", "Fuerzas Armadas y Policía", "Bomberos y Cruz Roja"];

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    if (url.pathname === "/api/corregir" && request.method === "POST") return corregir(env.DB, request);
    if (url.pathname === "/api/tablero" || url.pathname === "/api/piezas") {
      const cache = caches.default;
      // La versión publicada va en la clave: al desplegar no se sirven respuestas de la versión anterior.
      const clave = new Request(url.toString() + "&_v=" + (env.VERSION?.id || ""), { method: "GET" });
      let resp = await cache.match(clave);
      if (resp) return resp;
      try {
        const datos = await (url.pathname === "/api/piezas" ? piezasDe : tablero)(env.DB, url.searchParams);
        resp = new Response(JSON.stringify(datos), {
          headers: { "content-type": "application/json; charset=utf-8", "cache-control": `public, max-age=${CACHE_SEG}` },
        });
        ctx.waitUntil(cache.put(clave, resp.clone()));
        return resp;
      } catch (e) {
        return new Response(JSON.stringify({ error: String(e.message || e) }), {
          status: 500,
          headers: { "content-type": "application/json; charset=utf-8" },
        });
      }
    }
    return env.ASSETS.fetch(request);
  },
};

// Corrección hecha desde el tablero (abierta a cualquiera, decisión de Andrés): se aplica directo a la pieza, queda
// en `correcciones` (con un hash de la IP, para poder deshacer) y la IA ya no vuelve a clasificar esa pieza.
const CORREGIBLES = {
  tono: TONOS,
  tono_actor: TONOS,
  actor: [...ACTORES, "Ninguno"],
  aspecto: [...ASPECTOS, "Ninguno"],
  relevante: ["0", "1"],
};
async function corregir(db, request) {
  const json = (datos, status = 200) => new Response(JSON.stringify(datos), { status, headers: { "content-type": "application/json; charset=utf-8" } });
  let cuerpo;
  try {
    cuerpo = await request.json();
  } catch {
    return json({ error: "cuerpo inválido" }, 400);
  }
  const { id, cambios } = cuerpo || {};
  if (typeof id !== "string" || !/^[0-9a-f]{6,40}$/.test(id) || !cambios || typeof cambios !== "object") return json({ error: "datos inválidos" }, 400);
  const validos = Object.entries(cambios).filter(([c, v]) => CORREGIBLES[c]?.includes(String(v)));
  if (!validos.length) return json({ error: "nada que corregir" }, 400);
  const actual = await db.prepare("SELECT tono, tono_actor, actor, aspecto, relevante FROM piezas WHERE id = ?").bind(id).first();
  if (!actual) return json({ error: "no existe" }, 404);
  const ip = request.headers.get("cf-connecting-ip") || "";
  const huella = [...new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode("monitoreo-caro:" + ip)))]
    .slice(0, 6).map((b) => b.toString(16).padStart(2, "0")).join("");
  const ahora = new Date().toISOString().slice(0, 19) + "Z";
  const sentencias = [];
  for (const [campo, v] of validos) {
    const valor = campo === "relevante" ? Number(v) : v === "Ninguno" ? null : v;
    if (String(actual[campo] ?? "Ninguno") === String(valor ?? "Ninguno")) continue;
    sentencias.push(db.prepare("INSERT INTO correcciones (creado, pieza, campo, antes, despues, quien) VALUES (?, ?, ?, ?, ?, ?)").bind(ahora, id, campo, actual[campo] == null ? "Ninguno" : String(actual[campo]), valor == null ? "Ninguno" : String(valor), huella));
    sentencias.push(db.prepare(`UPDATE piezas SET ${campo} = ?, corregido = 1 WHERE id = ?`).bind(valor, id));
  }
  if (sentencias.length) await db.batch(sentencias);
  return json({ ok: true, cambios: sentencias.length / 2 });
}

// Para ordenar por alcance: vistas + interacciones. Los medios no traen vistas: cuentan como 1.000 (una nota de un
// medio llega a más gente que un tuit con pocas vistas, pero no a más que un video viral).
const ALCANCE = "CASE WHEN fuente = 'medios' THEN 1000 ELSE COALESCE(vistas, 0) + interacciones END";

// Las piezas detrás de un aspecto o un actor ("Ver noticias"), con su tono. Solo valores conocidos.
async function piezasDe(db, p) {
  const campo = p.get("tipo") === "actor" ? "actor" : "aspecto";
  const valor = p.get("valor");
  if (!(campo === "actor" ? ACTORES : ASPECTOS).includes(valor)) return { piezas: [] };
  const tono = campo === "actor" ? "COALESCE(tono_actor, tono)" : "tono";
  const cond = ["relevante = 1", `${campo} = ?`];
  const params = [valor];
  if (FUENTES.includes(p.get("fuente"))) cond.push("fuente = ?"), params.push(p.get("fuente"));
  if (SOBRE.includes(p.get("sobre"))) cond.push("sobre = ?"), params.push(p.get("sobre"));
  if (TONOS.includes(p.get("tono"))) cond.push(`${tono} = ?`), params.push(p.get("tono"));
  const r = await db
    .prepare(
      `SELECT id, fuente, medio, autor, url, titulo, resumen, tono AS tono_sngr, ${tono} AS tono, tono_actor, actor, aspecto, COALESCE(fecha, recogido) AS fecha, interacciones, vistas
       FROM piezas WHERE ${cond.join(" AND ")} ORDER BY ${ALCANCE} DESC, COALESCE(fecha, recogido) DESC LIMIT 30`,
    )
    .bind(...params)
    .all();
  return { piezas: r.results };
}

async function tablero(db, p) {
  const hoyEc = new Date(Date.now() - 5 * 3600e3).toISOString().slice(0, 10);
  const iso = (ms) => new Date(ms).toISOString().slice(0, 19) + "Z";
  const hace24 = iso(Date.now() - 24 * 3600e3);
  const hace48 = iso(Date.now() - 48 * 3600e3);
  // Todo el período: desde el primer día con al menos 10 piezas (antes solo hay notas sueltas).
  const inicio = await db
    .prepare(`SELECT MIN(dia) AS d FROM (SELECT ${DIA} AS dia FROM piezas WHERE relevante = 1 GROUP BY dia HAVING COUNT(*) >= 10)`)
    .first();
  const desde = inicio?.d || hoyEc;

  // Filtros: solo valores conocidos (nunca texto del navegador directo al SQL).
  const cond = ["relevante = 1", `${DIA} >= ?`];
  const params = [desde];
  const fuente = p.get("fuente");
  if (FUENTES.includes(fuente)) {
    cond.push("fuente = ?");
    params.push(fuente);
  }
  const sobre = p.get("sobre");
  if (SOBRE.includes(sobre)) {
    cond.push("sobre = ?");
    params.push(sobre);
  }
  const tono = p.get("tono");
  if (TONOS.includes(tono)) {
    cond.push("tono = ?");
    params.push(tono);
  }
  const W = "WHERE " + cond.join(" AND ");
  const q = (sql, extra = []) => db.prepare(sql).bind(...params, ...extra);

  const [porDia, temas, provincias, alertas, piezas, redes, totales, resumen, corrida, pendientes, aspectos, narrativas, actores, necesidades, voces, hitos, agenda, agendaDias] = await db.batch([
    q(`SELECT ${DIA} AS dia, fuente, tono, COUNT(*) AS n, ROUND(SUM(COALESCE(peso, 1)), 2) AS p FROM piezas ${W} GROUP BY dia, fuente, tono ORDER BY dia`),
    q(`SELECT tema, tono, COUNT(*) AS n, ROUND(SUM(COALESCE(peso, 1)), 2) AS p FROM piezas ${W} GROUP BY tema, tono`),
    q(`SELECT provincia, COUNT(*) AS n, SUM(tono = 'critico') AS criticas, ROUND(SUM(COALESCE(peso, 1)), 2) AS p, ROUND(SUM(CASE WHEN tono = 'critico' THEN COALESCE(peso, 1) ELSE 0 END), 2) AS pc FROM piezas ${W} AND provincia != '' GROUP BY provincia ORDER BY p DESC LIMIT 12`),
    q(`SELECT id, fuente, medio, autor, url, titulo, resumen, sobre, tono, tema, provincia, fecha, interacciones, actor, aspecto, tono_actor FROM piezas ${W} AND alerta = 1 ORDER BY COALESCE(fecha, recogido) DESC LIMIT 15`),
    q(`SELECT id, fuente, medio, autor, url, titulo, resumen, sobre, tono, tema, provincia, fecha, interacciones, actor, aspecto, tono_actor FROM piezas ${W} AND fuente = 'medios' ORDER BY COALESCE(fecha, recogido) DESC LIMIT 80`),
    q(`SELECT id, fuente, medio, autor, url, titulo, texto, resumen, sobre, tono, tema, fecha, interacciones, vistas, actor, aspecto, tono_actor FROM piezas ${W} AND fuente != 'medios' ORDER BY COALESCE(vistas, 0) + interacciones DESC LIMIT 25`),
    // "Hoy" = últimas 24 horas; "ayer" = las 24 anteriores (así no se vacía a medianoche). Las fechas las arma el servidor.
    // El termómetro no depende de los filtros: siempre todas las fuentes, últimas 24 h frente a las 24 anteriores.
    db.prepare(`SELECT COALESCE(fecha, recogido) >= '${hace24}' AS es_hoy, sobre, tono, alerta, COUNT(*) AS n, ROUND(SUM(COALESCE(peso, 1)), 2) AS p FROM piezas WHERE relevante = 1 AND COALESCE(fecha, recogido) >= '${hace48}' GROUP BY es_hoy, sobre, tono, alerta`),
    db.prepare("SELECT fecha, texto, creado FROM resumenes ORDER BY fecha DESC LIMIT 1"),
    db.prepare("SELECT inicio, fin, detalle FROM corridas ORDER BY inicio DESC LIMIT 1"),
    db.prepare("SELECT COUNT(*) AS n FROM piezas WHERE clasificado = 0"),
    q(`SELECT ${DIA} AS dia, aspecto, tono, COUNT(*) AS n, ROUND(SUM(COALESCE(peso, 1)), 2) AS p FROM piezas ${W} AND aspecto IS NOT NULL GROUP BY dia, aspecto, tono`),
    db.prepare("SELECT creado, datos FROM narrativas ORDER BY creado DESC LIMIT 1"),
    // El juicio sobre cada actor (tono_actor); las piezas viejas, sin él, usan el tono general.
    q(`SELECT ${DIA} AS dia, actor, COALESCE(tono_actor, tono) AS tono, COUNT(*) AS n, ROUND(SUM(COALESCE(peso, 1)), 2) AS p FROM piezas ${W} AND actor IS NOT NULL GROUP BY dia, actor, tono`),
    q(`SELECT necesidad, provincia, COUNT(*) AS n, ROUND(SUM(COALESCE(peso, 1)), 2) AS p FROM piezas ${W} AND necesidad IS NOT NULL GROUP BY necesidad, provincia`),
    // Quién mueve la conversación: medios por cantidad; cuentas de redes por alcance (vistas; si no hay, interacciones).
    // Sin comentarios sueltos.
    q(`SELECT fuente, COALESCE(NULLIF(autor, ''), medio) AS quien, MAX(medio) AS nombre, COUNT(*) AS n, SUM(interacciones) AS inter,
         SUM(vistas) AS vistas, MAX(seguidores) AS seguidores, SUM(tono = 'critico') AS criticas, SUM(tono = 'positivo') AS positivas
       FROM piezas ${W} AND padre IS NULL GROUP BY fuente, quien
       ORDER BY CASE WHEN fuente = 'medios' THEN n * 1000 ELSE COALESCE(SUM(vistas), 0) + inter END DESC LIMIT 40`),
    // Hitos que marcó Claude, con el enlace de la primera pieza que los cuenta.
    db.prepare("SELECT h.dia, h.titulo, (SELECT url FROM piezas WHERE id = json_extract(h.ids, '$[0]')) AS url FROM hitos h WHERE h.dia >= ? ORDER BY h.dia").bind(desde),
    // Agenda nacional (no depende de los filtros): la última foto y, por día, cuántos titulares tuvo cada tema.
    db.prepare("SELECT creado, datos FROM agenda ORDER BY creado DESC LIMIT 1"),
    db.prepare("SELECT dia, tema, MAX(nino) AS nino, COUNT(*) AS n FROM titulares WHERE nino IS NOT NULL GROUP BY dia, tema ORDER BY dia"),
  ]);

  const r = resumen.results[0];
  const c = corrida.results[0];
  return {
    hoy: hoyEc,
    desde,
    filtros: { fuente: FUENTES.includes(fuente) ? fuente : "", sobre: SOBRE.includes(sobre) ? sobre : "", tono: TONOS.includes(tono) ? tono : "" },
    porDia: porDia.results,
    temas: temas.results,
    provincias: provincias.results,
    alertas: alertas.results,
    piezas: piezas.results,
    redes: redes.results.map((x) => ({ ...x, texto: (x.texto || "").slice(0, 400) })),
    totales: totales.results,
    resumen: r ? { fecha: r.fecha, creado: r.creado, ...JSON.parse(r.texto) } : null,
    corrida: c ? { inicio: c.inicio, fin: c.fin, detalle: JSON.parse(c.detalle || "{}") } : null,
    pendientes: pendientes.results[0].n,
    aspectos: aspectos.results,
    narrativas: narrativas.results[0] ? { creado: narrativas.results[0].creado, ...JSON.parse(narrativas.results[0].datos) } : null,
    actores: actores.results,
    necesidades: necesidades.results,
    voces: voces.results,
    hitos: hitos.results,
    agenda: agenda.results[0] ? { creado: agenda.results[0].creado, ...JSON.parse(agenda.results[0].datos) } : null,
    agendaDias: agendaDias.results,
  };
}
