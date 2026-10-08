// Monitoreo Caro: API del tablero. Público, solo lectura. Lee D1 y guarda la respuesta 5 minutos en caché.

const CACHE_SEG = 300;
// Fecha de Ecuador (UTC-5) de una pieza: la de publicación o, si no hay, la de recogida.
const DIA = "date(datetime(COALESCE(fecha, recogido), '-5 hours'))";
const FUENTES = ["medios", "youtube", "x", "tiktok", "facebook"];
const SOBRE = ["carolina", "secretaria", "nino"];
const TONOS = ["positivo", "neutro", "critico"];

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    if (url.pathname === "/api/tablero") {
      const cache = caches.default;
      const clave = new Request(url.toString(), { method: "GET" });
      let resp = await cache.match(clave);
      if (resp) return resp;
      try {
        const datos = await tablero(env.DB, url.searchParams);
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

async function tablero(db, p) {
  const dias = Math.min(Math.max(parseInt(p.get("dias") || "7", 10) || 7, 1), 60);
  const hoyEc = new Date(Date.now() - 5 * 3600e3).toISOString().slice(0, 10);
  const desde = new Date(Date.parse(hoyEc) - (dias - 1) * 86400e3).toISOString().slice(0, 10);

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

  const [porDia, temas, provincias, alertas, piezas, redes, totales, resumen, corrida, pendientes, aspectos, narrativas, actores, necesidades, voces] = await db.batch([
    q(`SELECT ${DIA} AS dia, fuente, tono, COUNT(*) AS n FROM piezas ${W} GROUP BY dia, fuente, tono ORDER BY dia`),
    q(`SELECT tema, tono, COUNT(*) AS n FROM piezas ${W} GROUP BY tema, tono`),
    q(`SELECT provincia, COUNT(*) AS n, SUM(tono = 'critico') AS criticas FROM piezas ${W} AND provincia != '' GROUP BY provincia ORDER BY n DESC LIMIT 12`),
    q(`SELECT fuente, medio, autor, url, titulo, resumen, sobre, tono, tema, provincia, fecha, interacciones FROM piezas ${W} AND alerta = 1 ORDER BY COALESCE(fecha, recogido) DESC LIMIT 15`),
    q(`SELECT fuente, medio, autor, url, titulo, resumen, sobre, tono, tema, provincia, fecha, interacciones FROM piezas ${W} AND fuente = 'medios' ORDER BY COALESCE(fecha, recogido) DESC LIMIT 80`),
    q(`SELECT fuente, medio, autor, url, titulo, texto, resumen, sobre, tono, tema, fecha, interacciones FROM piezas ${W} AND fuente != 'medios' ORDER BY interacciones DESC LIMIT 25`),
    // hoyEc lo arma el servidor (AAAA-MM-DD), por eso va en el texto: así no se corre el orden de los parámetros.
    q(`SELECT ${DIA} = '${hoyEc}' AS es_hoy, sobre, tono, alerta, COUNT(*) AS n FROM piezas ${W} AND ${DIA} >= date('${hoyEc}', '-1 day') GROUP BY es_hoy, sobre, tono, alerta`),
    db.prepare("SELECT fecha, texto, creado FROM resumenes ORDER BY fecha DESC LIMIT 1"),
    db.prepare("SELECT inicio, fin, detalle FROM corridas ORDER BY inicio DESC LIMIT 1"),
    db.prepare("SELECT COUNT(*) AS n FROM piezas WHERE clasificado = 0"),
    q(`SELECT aspecto, tono, COUNT(*) AS n FROM piezas ${W} AND aspecto IS NOT NULL GROUP BY aspecto, tono`),
    db.prepare("SELECT creado, datos FROM narrativas ORDER BY creado DESC LIMIT 1"),
    q(`SELECT actor, tono, COUNT(*) AS n FROM piezas ${W} AND actor IS NOT NULL GROUP BY actor, tono`),
    q(`SELECT necesidad, provincia, COUNT(*) AS n FROM piezas ${W} AND necesidad IS NOT NULL GROUP BY necesidad, provincia`),
    // Quién mueve la conversación: medios por cantidad; cuentas de redes por interacciones (sin comentarios sueltos).
    q(`SELECT fuente, COALESCE(NULLIF(autor, ''), medio) AS quien, MAX(medio) AS nombre, COUNT(*) AS n, SUM(interacciones) AS inter,
         SUM(tono = 'critico') AS criticas, SUM(tono = 'positivo') AS positivas
       FROM piezas ${W} AND padre IS NULL GROUP BY fuente, quien
       ORDER BY CASE WHEN fuente = 'medios' THEN n * 1000 ELSE inter END DESC LIMIT 40`),
  ]);

  const r = resumen.results[0];
  const c = corrida.results[0];
  return {
    hoy: hoyEc,
    desde,
    dias,
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
  };
}
