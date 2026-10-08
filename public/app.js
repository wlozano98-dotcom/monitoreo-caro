// Monitoreo El Niño: tablero. Sin frameworks. Pide /api/tablero y dibuja todo en SVG/HTML.

const FUENTES = { medios: "Medios", youtube: "YouTube", x: "X", tiktok: "TikTok", facebook: "Facebook" };
const TONOS = { positivo: "Positivo", neutro: "Neutro", critico: "Crítico" };
const SOBRE = { carolina: "Carolina", secretaria: "Secretaría", nino: "El Niño" };
const color = (tipo, clave) => `var(--${tipo}-${clave})`;

const estado = { dias: 7, fuente: "", sobre: "", tono: "" };
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const num = (n) => Number(n || 0).toLocaleString("es-EC");

// --------------------------------------------------------------- filtros (se recuerdan en la URL)

function leerURL() {
  const p = new URLSearchParams(location.search);
  const d = parseInt(p.get("dias"), 10);
  if ([1, 7, 14, 30].includes(d)) estado.dias = d;
  for (const k of ["fuente", "sobre", "tono"]) estado[k] = p.get(k) || "";
}
function escribirURL() {
  const p = new URLSearchParams();
  if (estado.dias !== 7) p.set("dias", estado.dias);
  for (const k of ["fuente", "sobre", "tono"]) if (estado[k]) p.set(k, estado[k]);
  history.replaceState(null, "", p.toString() ? "?" + p : location.pathname);
}
function pintarFiltros() {
  document.querySelectorAll("[data-dias]").forEach((b) => b.setAttribute("aria-pressed", String(+b.dataset.dias === estado.dias)));
  $("f-fuente").value = estado.fuente;
  $("f-sobre").value = estado.sobre;
  $("f-tono").value = estado.tono;
}
document.querySelectorAll("[data-dias]").forEach((b) =>
  b.addEventListener("click", () => {
    estado.dias = +b.dataset.dias;
    cambiar();
  }),
);
for (const k of ["fuente", "sobre", "tono"]) $("f-" + k).addEventListener("change", (e) => {
  estado[k] = e.target.value;
  cambiar();
});
function cambiar() {
  pintarFiltros();
  escribirURL();
  cargar();
}

// --------------------------------------------------------------- carga

async function cargar() {
  const p = new URLSearchParams({ dias: estado.dias });
  for (const k of ["fuente", "sobre", "tono"]) if (estado[k]) p.set(k, estado[k]);
  document.body.style.cursor = "progress";
  try {
    const r = await fetch("/api/tablero?" + p);
    const d = await r.json();
    if (d.error) throw new Error(d.error);
    pintar(d);
  } catch (e) {
    $("estado").textContent = "No se pudo cargar: " + e.message;
  } finally {
    document.body.style.cursor = "";
  }
}

function hace(iso) {
  if (!iso) return "";
  const min = Math.round((Date.now() - Date.parse(iso)) / 60000);
  if (min < 1) return "recién";
  if (min < 60) return `hace ${min} min`;
  const h = Math.round(min / 60);
  if (h < 24) return `hace ${h} h`;
  return `hace ${Math.round(h / 24)} d`;
}
function fechaCorta(iso) {
  if (!iso) return "";
  return new Date(iso).toLocaleString("es-EC", { timeZone: "America/Guayaquil", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
}

function pintar(d) {
  $("estado").innerHTML = d.corrida
    ? `Actualizado <b>${esc(hace(d.corrida.fin))}</b>${d.pendientes ? ` · ${num(d.pendientes)} por clasificar` : ""}`
    : "Sin corridas todavía";
  pintarResumen(d);
  pintarKpis(d);
  pintarNarrativas(d.narrativas);
  pintarAspectos(d.aspectos);
  pintarAlertas(d.alertas);
  const dias = listaDias(d.desde, d.hoy);
  barrasPorDia($("g-volumen"), dias, d.porDia, "fuente", FUENTES, "s");
  barrasPorDia($("g-tono"), dias, d.porDia, "tono", TONOS, "t");
  leyenda($("ley-fuentes"), FUENTES, "s");
  leyenda($("ley-tonos"), TONOS, "t");
  pintarTemas(d.temas);
  pintarProvincias(d.provincias);
  pintarLista($("redes"), d.redes, true);
  pintarLista($("noticias"), d.piezas, false);
}

function pintarResumen(d) {
  const r = d.resumen;
  $("resumen").innerHTML = r && r.vinetas.length ? r.vinetas.map((v) => `<li>${esc(v)}</li>`).join("") : `<li class="vacio">Todavía no hay resumen.</li>`;
  $("resumen-pie").textContent = r ? `Últimas 24 horas · escrito por IA ${hace(r.creado)} · no depende de los filtros` : "";
}

function pintarKpis(d) {
  const hoy = { total: 0, critico: 0, carolina: 0, carolinaCritico: 0 };
  const ayer = { total: 0, critico: 0 };
  for (const f of d.totales) {
    const b = f.es_hoy ? hoy : ayer;
    b.total += f.n;
    if (f.tono === "critico") b.critico += f.n;
    if (f.es_hoy && f.sobre === "carolina") {
      hoy.carolina += f.n;
      if (f.tono === "critico") hoy.carolinaCritico += f.n;
    }
  }
  const pct = (a, b) => (b ? Math.round((100 * a) / b) : 0);
  const delta = hoy.total - ayer.total;
  const pctHoy = pct(hoy.critico, hoy.total);
  const pctAyer = pct(ayer.critico, ayer.total);
  const flecha = (n, sufijo = "") =>
    n === 0 ? "igual que ayer" : `<span class="${n > 0 ? "sube" : "baja"}">${n > 0 ? "▲" : "▼"} ${Math.abs(n)}${sufijo}</span> frente a ayer`;
  const tarjetas = [
    { etiqueta: "Menciones hoy", valor: num(hoy.total), extra: `${flecha(delta)} (${num(ayer.total)})` },
    { etiqueta: "Críticas hoy", valor: pctHoy + "%", extra: `${num(hoy.critico)} piezas · ${flecha(pctHoy - pctAyer, " pts")}`, malo: pctHoy >= 40 },
    { etiqueta: "Sobre Carolina hoy", valor: num(hoy.carolina), extra: `${num(hoy.carolinaCritico)} críticas` },
    { etiqueta: `Alertas (${d.dias === 1 ? "hoy" : d.dias + " días"})`, valor: num(d.alertas.length), extra: d.alertas.length ? "ver abajo" : "ninguna", malo: d.alertas.length > 0 },
  ];
  $("kpis").innerHTML = tarjetas
    .map((t) => `<div class="kpi${t.malo ? " malo" : ""}"><p class="etiqueta">${t.etiqueta}</p><p class="valor">${t.valor}</p><p class="extra">${t.extra}</p></div>`)
    .join("");
}

function pintarAlertas(alertas) {
  $("panel-alertas").hidden = !alertas.length;
  pintarLista($("alertas"), alertas, true);
}

// --------------------------------------------------------------- narrativas y percepción

function pintarNarrativas(nar) {
  const el = $("narrativas");
  if (!nar || !nar.lista.length) {
    el.innerHTML = `<p class="vacio">Todavía no hay suficientes ideas para agrupar.</p>`;
    return;
  }
  $("narrativas-pie").textContent = `Las ideas que más se repiten en medios y redes en los últimos 3 días · agrupadas por IA ${hace(nar.creado)} · no dependen de los filtros.`;
  el.innerHTML = nar.lista
    .map((n) => {
      const t = n.tonos;
      const total = t.positivo + t.neutro + t.critico || 1;
      const clase = t.critico / total >= 0.5 ? " critica" : t.positivo / total >= 0.5 ? " positiva" : "";
      const dif = n.ultimas24 - n.previas24;
      const tendencia =
        n.ultimas24 === 0 && n.previas24 === 0
          ? "sin novedad en 48 h"
          : dif > 0
            ? `<span class="sube">▲ creciendo</span> (${num(n.ultimas24)} hoy, ${num(n.previas24)} ayer)`
            : dif < 0
              ? `<span class="baja">▼ bajando</span> (${num(n.ultimas24)} hoy, ${num(n.previas24)} ayer)`
              : `estable (${num(n.ultimas24)} en 24 h)`;
      const segs = Object.keys(TONOS).filter((k) => t[k]).map((k) => `<span style="width:${(100 * t[k]) / total}%;background:${color("t", k)}" title="${TONOS[k]}: ${t[k]}"></span>`).join("");
      const fuentes = Object.entries(n.fuentes).sort((a, b) => b[1] - a[1]).map(([f, c]) => `<span class="chip"><i style="background:${color("s", f)}"></i>${FUENTES[f] || f} ${num(c)}</span>`).join(" ");
      const ejemplos = n.ejemplos
        .map((e) => {
          const quien = e.fuente === "medios" ? e.quien : "@" + String(e.quien || "").replace(/^@/, "");
          const txt = `<b>${esc(quien)}</b>: ${esc(e.texto)}`;
          return `<li>${e.url ? `<a href="${esc(e.url)}" target="_blank" rel="noopener noreferrer">${txt}</a>` : txt}</li>`;
        })
        .join("");
      return `<article class="narrativa${clase}">
        <h3>${esc(n.titulo)}</h3>
        <p class="explica">${esc(n.explicacion)}</p>
        <p class="cifras"><span><b>${num(n.total)}</b> menciones</span><span>${tendencia}</span>${n.interacciones ? `<span>${num(n.interacciones)} interacciones</span>` : ""}</p>
        <div class="tonos" aria-label="Positivo ${t.positivo}, neutro ${t.neutro}, crítico ${t.critico}">${segs}</div>
        <p class="cifras">${fuentes}</p>
        <ul class="ejemplos">${ejemplos}</ul>
      </article>`;
    })
    .join("");
}

const ASPECTOS = ["Rapidez de la respuesta", "Llegada de la ayuda", "Presencia en territorio", "Coordinación entre instituciones", "Prevención y alertas", "Comunicación e información", "Liderazgo de Carolina Lozano"];
function pintarAspectos(filas) {
  const por = Object.fromEntries(ASPECTOS.map((a) => [a, { positivo: 0, critico: 0, neutro: 0 }]));
  for (const f of filas) if (por[f.aspecto] && f.tono in por[f.aspecto]) por[f.aspecto][f.tono] += f.n;
  const max = Math.max(1, ...ASPECTOS.map((a) => Math.max(por[a].positivo, por[a].critico)));
  const conDatos = ASPECTOS.filter((a) => por[a].positivo + por[a].critico);
  if (!conDatos.length) {
    $("aspectos").innerHTML = `<p class="vacio">Nada con estos filtros.</p>`;
    return;
  }
  $("aspectos").innerHTML = ASPECTOS.map((a) => {
    const p = por[a];
    const suma = p.positivo + p.critico;
    const saldo = suma ? Math.round((100 * p.positivo) / suma) : null;
    const veredicto = saldo === null ? "sin opiniones" : saldo >= 60 ? `${saldo}% dice que va bien` : saldo <= 40 ? `${100 - saldo}% dice que va mal` : "opiniones divididas";
    return `<div class="aspecto">
      <div class="lado bien"><small>${num(p.positivo)}</small><span class="b" style="width:${(85 * p.positivo) / max}%"></span></div>
      <div class="nombre">${esc(a)}<small>${veredicto}</small></div>
      <div class="lado mal"><span class="b" style="width:${(85 * p.critico) / max}%"></span><small>${num(p.critico)}</small></div>
    </div>`;
  }).join("");
}

// --------------------------------------------------------------- listas

function pintarLista(ul, piezas, mostrarInteracciones) {
  if (!piezas.length) {
    ul.innerHTML = `<li class="vacio">Nada con estos filtros.</li>`;
    return;
  }
  ul.innerHTML = piezas
    .map((p) => {
      const titulo = p.titulo || (p.texto ? p.texto.slice(0, 160) : p.resumen) || "(sin texto)";
      const detalle = p.titulo ? p.resumen : p.texto && p.resumen ? p.resumen : "";
      const quien = p.fuente === "medios" ? p.medio : [p.autor && "@" + String(p.autor).replace(/^@/, ""), p.fuente !== "medios" && FUENTES[p.fuente]].filter(Boolean).join(" · ");
      return `<li>
        <p class="meta">
          <span><b>${esc(quien || p.medio || "")}</b></span>
          <span>${esc(fechaCorta(p.fecha))}</span>
          ${p.tono ? `<span class="chip${p.tono === "critico" ? " critico" : ""}"><i style="background:${color("t", p.tono)}"></i>${TONOS[p.tono]}</span>` : ""}
          ${p.sobre && p.sobre !== "nino" ? `<span class="chip">${SOBRE[p.sobre]}</span>` : ""}
          ${p.tema ? `<span class="chip">${esc(p.tema)}</span>` : ""}
          ${mostrarInteracciones && p.interacciones ? `<span>${num(p.interacciones)} interacciones</span>` : ""}
        </p>
        ${p.url ? `<a class="titulo" href="${esc(p.url)}" target="_blank" rel="noopener noreferrer">${esc(titulo)}</a>` : `<p class="titulo">${esc(titulo)}</p>`}
        ${detalle ? `<p class="detalle">${esc(detalle)}</p>` : ""}
      </li>`;
    })
    .join("");
}

// --------------------------------------------------------------- gráficos

function listaDias(desde, hoy) {
  const dias = [];
  for (let t = Date.parse(desde); t <= Date.parse(hoy); t += 86400e3) dias.push(new Date(t).toISOString().slice(0, 10));
  return dias;
}
function nombreDia(dia, corto) {
  const d = new Date(dia + "T12:00:00Z");
  return d.toLocaleDateString("es-EC", corto ? { day: "numeric", month: "short", timeZone: "UTC" } : { weekday: "long", day: "numeric", month: "long", timeZone: "UTC" });
}
function leyenda(el, nombres, tipo) {
  el.innerHTML = Object.entries(nombres).map(([k, v]) => `<span><i style="background:${color(tipo, k)}"></i>${v}</span>`).join("");
}

// Barras apiladas por día. Una sola escala; huecos de 2 px entre segmentos (borde del color de la superficie).
function barrasPorDia(el, dias, filas, campo, nombres, tipo) {
  const claves = Object.keys(nombres);
  const datos = dias.map((dia) => {
    const fila = { dia, total: 0 };
    for (const k of claves) fila[k] = 0;
    for (const f of filas) if (f.dia === dia && f[campo] in fila) {
      fila[f[campo]] += f.n;
      fila.total += f.n;
    }
    return fila;
  });
  const max = Math.max(1, ...datos.map((d) => d.total));
  const paso = escalaBonita(max);
  const tope = Math.ceil(max / paso) * paso;
  const W = 600, H = 220, iz = 34, ab = 24, ar = 8;
  const ancho = (W - iz) / datos.length;
  const barra = Math.min(36, ancho * 0.62);
  const y = (v) => ar + (H - ar - ab) * (1 - v / tope);
  let svg = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(el.previousElementSibling?.previousElementSibling?.textContent || "")}">`;
  for (let v = 0; v <= tope; v += paso) {
    svg += `<line class="rejilla-linea" x1="${iz}" x2="${W}" y1="${y(v)}" y2="${y(v)}"/><text class="eje" x="${iz - 6}" y="${y(v) + 4}" text-anchor="end">${num(v)}</text>`;
  }
  const cadaCuanto = Math.ceil(datos.length / 8);
  datos.forEach((d, i) => {
    const x = iz + i * ancho + (ancho - barra) / 2;
    let base = 0;
    for (const k of claves) {
      if (!d[k]) continue;
      const y1 = y(base + d[k]), y0 = y(base);
      const esTope = base + d[k] === d.total;
      svg += esTope
        ? `<path class="seg" d="${tapaRedonda(x, y1, barra, y0 - y1, 4)}" fill="${color(tipo, k)}" stroke="var(--superficie)" stroke-width="2"/>`
        : `<rect class="seg" x="${x}" y="${y1}" width="${barra}" height="${y0 - y1}" fill="${color(tipo, k)}"/>`;
      base += d[k];
    }
    if (i % cadaCuanto === 0 || i === datos.length - 1)
      svg += `<text class="eje" x="${x + barra / 2}" y="${H - 6}" text-anchor="middle">${esc(nombreDia(d.dia, true))}</text>`;
    svg += `<rect class="zona" data-i="${i}" x="${iz + i * ancho}" y="0" width="${ancho}" height="${H - ab}"/>`;
  });
  svg += "</svg>";
  el.innerHTML = svg;
  el.querySelectorAll(".zona").forEach((z) => {
    const d = datos[+z.dataset.i];
    const html = `<b>${esc(nombreDia(d.dia))}</b>` + claves.map((k) => `<div><span><i style="background:${color(tipo, k)}"></i>${nombres[k]}</span><span>${num(d[k])}</span></div>`).join("") + `<div><span>Total</span><span>${num(d.total)}</span></div>`;
    tooltipEn(z, html);
  });
}
function tapaRedonda(x, y, w, h, r) {
  r = Math.min(r, h, w / 2);
  return `M${x},${y + h}V${y + r}Q${x},${y} ${x + r},${y}H${x + w - r}Q${x + w},${y} ${x + w},${y + r}V${y + h}Z`;
}
function escalaBonita(max) {
  const bruto = max / 4;
  const p = Math.pow(10, Math.floor(Math.log10(bruto)));
  for (const m of [1, 2, 5, 10]) if (m * p >= bruto) return Math.max(1, m * p);
  return Math.max(1, 10 * p);
}

function pintarTemas(filas) {
  const por = {};
  for (const f of filas) {
    const t = (por[f.tema || "Otro"] ||= { positivo: 0, neutro: 0, critico: 0, total: 0 });
    if (f.tono in t) t[f.tono] += f.n;
    t.total += f.n;
  }
  const lista = Object.entries(por).sort((a, b) => b[1].total - a[1].total).slice(0, 10);
  const max = Math.max(1, ...lista.map(([, t]) => t.total));
  $("g-temas").innerHTML = lista.length
    ? `<div class="leyenda">${Object.entries(TONOS).map(([k, v]) => `<span><i style="background:${color("t", k)}"></i>${v}</span>`).join("")}</div>` +
      lista
        .map(([tema, t], i) => {
          const segs = Object.keys(TONOS).filter((k) => t[k]).map((k) => `<span style="width:${(100 * t[k]) / max}%;background:${color("t", k)}"></span>`).join("");
          return `<div class="fila-barra" data-i="${i}"><span class="nombre" title="${esc(tema)}">${esc(tema)}</span><span class="pista">${segs}</span><span class="cifra">${num(t.total)}</span></div>`;
        })
        .join("")
    : `<p class="vacio">Nada con estos filtros.</p>`;
  $("g-temas").querySelectorAll(".fila-barra").forEach((el) => {
    const [tema, t] = lista[+el.dataset.i];
    tooltipEn(el, `<b>${esc(tema)}</b>` + Object.entries(TONOS).map(([k, v]) => `<div><span><i style="background:${color("t", k)}"></i>${v}</span><span>${num(t[k])}</span></div>`).join(""));
  });
}

function pintarProvincias(filas) {
  const max = Math.max(1, ...filas.map((f) => f.n));
  $("g-prov").innerHTML = filas.length
    ? filas
        .map((f) => `<div class="fila-barra"><span class="nombre">${esc(f.provincia)}</span><span class="pista"><span style="width:${(100 * f.n) / max}%;background:var(--s-medios)"></span></span><span class="cifra">${num(f.n)}${f.criticas ? `<small>${num(f.criticas)} crít.</small>` : ""}</span></div>`)
        .join("")
    : `<p class="vacio">Nada con estos filtros.</p>`;
}

// --------------------------------------------------------------- tooltip

const tip = $("tooltip");
function tooltipEn(el, html) {
  el.addEventListener("pointerenter", () => {
    tip.innerHTML = html;
    tip.hidden = false;
  });
  el.addEventListener("pointermove", (e) => {
    const r = tip.getBoundingClientRect();
    let x = e.clientX + 14, yy = e.clientY + 14;
    if (x + r.width > innerWidth - 8) x = e.clientX - r.width - 14;
    if (yy + r.height > innerHeight - 8) yy = e.clientY - r.height - 14;
    tip.style.left = Math.max(8, x) + "px";
    tip.style.top = Math.max(8, yy) + "px";
  });
  el.addEventListener("pointerleave", () => (tip.hidden = true));
}

leerURL();
pintarFiltros();
cargar();
setInterval(cargar, 10 * 60 * 1000);
