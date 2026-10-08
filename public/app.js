// Monitoreo El Niño: tablero. Sin frameworks. Pide /api/tablero y dibuja todo en SVG/HTML.

const FUENTES = { medios: "Medios", youtube: "YouTube", x: "X", tiktok: "TikTok", facebook: "Facebook" };
const TONOS = { positivo: "Positivo", neutro: "Neutro", critico: "Crítico" };
const SOBRE = { carolina: "Carolina", secretaria: "Secretaría", nino: "El Niño" };
const ASPECTOS = ["Rapidez de la respuesta", "Llegada de la ayuda", "Presencia en territorio", "Coordinación entre instituciones", "Prevención y alertas", "Comunicación e información", "Liderazgo de Carolina Lozano"];
const ACTORES = ["Secretaría de Gestión de Riesgos", "Carolina Lozano", "Presidencia y Gobierno central", "Ministerios", "Municipio o Prefectura", "Fuerzas Armadas y Policía", "Bomberos y Cruz Roja"];
// Niveles de la conversación con los mismos nombres que las alertas de la Secretaría.
const NIVELES = [
  { nombre: "Verde", color: "var(--n-verde)", hasta: 30, texto: "Conversación tranquila" },
  { nombre: "Amarilla", color: "var(--n-amarilla)", hasta: 45, texto: "Hay que estar atentos" },
  { nombre: "Naranja", color: "var(--n-naranja)", hasta: 60, texto: "Críticas en aumento" },
  { nombre: "Roja", color: "var(--n-roja)", hasta: 101, texto: "Crisis de opinión" },
];

const color = (tipo, clave) => `var(--${tipo}-${clave})`;
const estado = { dias: 7, fuente: "", sobre: "", tono: "", lista: "alertas", voces: "medios" };
let datos = null;
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const num = (n) => Number(n || 0).toLocaleString("es-EC");
const icono = (id, clase = "icono") => `<svg class="${clase}" aria-hidden="true"><use href="#i-${id}"/></svg>`;

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
  history.replaceState(null, "", (p.toString() ? "?" + p : location.pathname) + location.hash);
}
function pintarFiltros() {
  document.querySelectorAll("[data-dias]").forEach((b) => b.setAttribute("aria-pressed", String(+b.dataset.dias === estado.dias)));
  for (const k of ["fuente", "sobre", "tono"]) $("f-" + k).value = estado[k];
}
document.querySelectorAll("[data-dias]").forEach((b) => b.addEventListener("click", () => ((estado.dias = +b.dataset.dias), cambiar())));
for (const k of ["fuente", "sobre", "tono"]) $("f-" + k).addEventListener("change", (e) => ((estado[k] = e.target.value), cambiar()));
function cambiar() {
  pintarFiltros();
  escribirURL();
  cargar();
}
function pestanas(atributo, clave, alCambiar) {
  document.querySelectorAll(`[data-${atributo}]`).forEach((b) =>
    b.addEventListener("click", () => {
      estado[clave] = b.dataset[atributo];
      document.querySelectorAll(`[data-${atributo}]`).forEach((x) => x.setAttribute("aria-selected", String(x === b)));
      alCambiar();
    }),
  );
}
pestanas("lista", "lista", () => datos && pintarPublicaciones(datos));
pestanas("voces", "voces", () => datos && pintarVoces(datos.voces));

// --------------------------------------------------------------- carga

async function cargar() {
  const p = new URLSearchParams({ dias: estado.dias });
  for (const k of ["fuente", "sobre", "tono"]) if (estado[k]) p.set(k, estado[k]);
  document.body.style.cursor = "progress";
  try {
    const r = await fetch("/api/tablero?" + p);
    const d = await r.json();
    if (d.error) throw new Error(d.error);
    datos = d;
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
function tendencia(hoy, ayer, buenaSiSube = false) {
  const dif = hoy - ayer;
  if (!hoy && !ayer) return `<span class="tendencia igual">sin novedad en 48 h</span>`;
  if (dif > 0) return `<span class="tendencia sube${buenaSiSube ? " buena" : ""}">${icono("sube")}creciendo</span>`;
  if (dif < 0) return `<span class="tendencia baja">${icono("baja")}bajando</span>`;
  return `<span class="tendencia igual">${icono("igual")}estable</span>`;
}
function barraTonos(t) {
  const total = (t.positivo || 0) + (t.neutro || 0) + (t.critico || 0) || 1;
  const segs = Object.keys(TONOS).filter((k) => t[k]).map((k) => `<span style="width:${(100 * t[k]) / total}%;background:${color("t", k)}"></span>`).join("");
  return `<div class="tonos" role="img" aria-label="Positivo ${t.positivo || 0}, neutro ${t.neutro || 0}, crítico ${t.critico || 0}">${segs}</div>`;
}
function quienDe(p) {
  if (p.fuente === "medios") return p.medio || p.quien || "";
  const a = p.autor || p.quien;
  return a ? "@" + String(a).replace(/^@/, "") : p.medio || "";
}

function pintar(d) {
  const viejo = d.corrida && Date.now() - Date.parse(d.corrida.fin) > 3 * 3600e3;
  $("estado").innerHTML = d.corrida
    ? `<span class="punto${viejo ? " viejo" : ""}"></span>Actualizado <b>${esc(hace(d.corrida.fin))}</b>${d.pendientes ? ` · ${num(d.pendientes)} por clasificar` : ""}`
    : "Sin corridas todavía";
  $("fecha-hoy").textContent = new Date(d.hoy + "T12:00:00Z").toLocaleDateString("es-EC", { weekday: "long", day: "numeric", month: "long", timeZone: "UTC" });
  pintarResumen(d.resumen);
  pintarNivel(d);
  pintarNarrativas(d.narrativas);
  pintarAspectos(d.aspectos);
  pintarActores(d.actores);
  pintarRumores(d.narrativas);
  pintarPedidos(d.necesidades);
  const dias = listaDias(d.desde, d.hoy);
  barrasPorDia($("g-volumen"), dias, d.porDia, "fuente", FUENTES, "s", "Menciones por día y fuente");
  barrasPorDia($("g-tono"), dias, d.porDia, "tono", TONOS, "t", "Tono por día");
  leyenda($("ley-fuentes"), FUENTES, "s");
  leyenda($("ley-tonos"), TONOS, "t");
  pintarProvincias(d.provincias);
  pintarVoces(d.voces);
  pintarPublicaciones(d);
}

// --------------------------------------------------------------- banda "Hoy"

function pintarResumen(r) {
  $("resumen").innerHTML = r && r.vinetas?.length ? r.vinetas.map((v) => `<li>${esc(v)}</li>`).join("") : `<li class="vacio">Todavía no hay resumen: aparece cuando la IA clasifica lo recogido.</li>`;
  const acciones = r?.acciones || [];
  $("acciones").innerHTML = acciones.length
    ? acciones.map((a) => `<li><b>${esc(a.accion)}</b><span>${esc(a.porque)}</span></li>`).join("")
    : `<li class="vacio">Aparecerán aquí 3 acciones sugeridas cuando la IA haya clasificado lo del día.</li>`;
  $("acciones-caja").querySelector("h3").innerHTML = `${icono("chispa")}Qué conviene hacer hoy`;
  $("resumen-pie").textContent = r ? `Últimas 24 horas · escrito por IA ${hace(r.creado)} · no depende de los filtros.` : "";
}

function pintarNivel(d) {
  const hoy = { total: 0, critico: 0, carolina: 0, carolinaCritico: 0, alertas: 0 };
  const ayer = { total: 0, critico: 0 };
  for (const f of d.totales) {
    const b = f.es_hoy ? hoy : ayer;
    b.total += f.n;
    if (f.tono === "critico") b.critico += f.n;
    if (f.es_hoy && f.alerta) hoy.alertas += f.n;
    if (f.es_hoy && f.sobre === "carolina") {
      hoy.carolina += f.n;
      if (f.tono === "critico") hoy.carolinaCritico += f.n;
    }
  }
  const pct = hoy.total ? Math.round((100 * hoy.critico) / hoy.total) : 0;
  // Las alertas suben un nivel: 1 o 2 alertas → al menos naranja; 3 o más → roja.
  let i = NIVELES.findIndex((n) => pct < n.hasta);
  if (hoy.alertas >= 3) i = 3;
  else if (hoy.alertas >= 1) i = Math.max(i, 2);
  const nivel = NIVELES[i];
  const sinDatos = !hoy.total;
  $("nivel").innerHTML = sinDatos ? "—" : `<i style="background:${nivel.color}"></i>${nivel.nombre}`;
  $("nivel-detalle").textContent = sinDatos ? "Sin piezas clasificadas hoy" : `${nivel.texto}. ${pct}% de lo de hoy es crítico${hoy.alertas ? ` y hay ${hoy.alertas} alerta${hoy.alertas > 1 ? "s" : ""}` : ""}.`;
  requestAnimationFrame(() => {
    const alto = sinDatos ? 0 : Math.max(3, pct);
    $("agua").style.height = alto + "%";
    $("marca-nivel").style.bottom = `calc(${alto}% + 9px)`;
    $("marca-nivel").textContent = sinDatos ? "" : pct + "%";
  });
  const dif = hoy.total - ayer.total;
  const cambio = dif === 0 ? "igual que ayer" : `${dif > 0 ? "+" : "−"}${num(Math.abs(dif))} frente a ayer`;
  $("cifras-hoy").innerHTML = `
    <div><dt>Menciones</dt><dd>${num(hoy.total)}<small>${cambio}</small></dd></div>
    <div><dt>Sobre Carolina</dt><dd>${num(hoy.carolina)}<small>${num(hoy.carolinaCritico)} críticas</small></dd></div>
    <div><dt>Alertas</dt><dd>${num(hoy.alertas)}<small>hoy</small></dd></div>`;

  const n = d.alertas.length;
  const aviso = $("aviso-alertas");
  aviso.hidden = !n;
  aviso.innerHTML = n ? `${icono("alerta")}<span>${n} alerta${n > 1 ? "s" : ""} en ${d.dias === 1 ? "el día" : `los últimos ${d.dias} días`}: críticas fuertes o noticias que piden reacción</span>${icono("flecha")}` : "";
  aviso.onclick = () => {
    document.querySelector('[data-lista="alertas"]').click();
  };
  $("n-alertas").innerHTML = n ? `<span class="cuenta">${n}</span>` : "";
}

// --------------------------------------------------------------- narrativas y rumores

function ejemplosHTML(ejemplos) {
  return ejemplos
    .map((e) => {
      const txt = `<b>${esc(quienDe(e))}</b> · ${esc(FUENTES[e.fuente] || e.fuente)}<br>${esc(e.texto)}`;
      return `<li>${e.url ? `<a href="${esc(e.url)}" target="_blank" rel="noopener noreferrer">${txt}</a>` : txt}</li>`;
    })
    .join("");
}

function pintarNarrativas(nar) {
  const el = $("narrativas");
  const lista = nar?.narrativas || [];
  if (!lista.length) {
    el.innerHTML = `<li class="vacio">Todavía no hay suficientes ideas para agrupar.</li>`;
    return;
  }
  $("narrativas-pie").textContent = `Lo que más se repite en medios y redes en los últimos 3 días. Agrupado por IA ${hace(nar.creado)}; no depende de los filtros.`;
  el.innerHTML = lista
    .map((n) => {
      const t = n.tonos;
      const total = t.positivo + t.neutro + t.critico || 1;
      const mayoriaPositiva = t.positivo / total >= 0.5;
      const fuentes = Object.entries(n.fuentes).sort((a, b) => b[1] - a[1]).map(([f, c]) => `<span class="chip"><i style="background:${color("s", f)}"></i>${FUENTES[f] || f} ${num(c)}</span>`).join("");
      return `<li class="narrativa">
        <div>
          <h3>${esc(n.titulo)}</h3>
          <p class="explica">${esc(n.explicacion)}</p>
        </div>
        <div class="datos">
          <p class="total"><b>${num(n.total)}</b><span>menciones</span>${tendencia(n.ultimas24, n.previas24, mayoriaPositiva)}</p>
          ${barraTonos(t)}
          <p class="fuentes">${fuentes}</p>
        </div>
        ${n.ejemplos.length ? `<details><summary>${icono("flecha")}Ver ejemplos</summary><ul class="ejemplos">${ejemplosHTML(n.ejemplos)}</ul></details>` : ""}
      </li>`;
    })
    .join("");
}

function pintarRumores(nar) {
  const lista = nar?.rumores || [];
  $("rumores").innerHTML = lista.length
    ? lista
        .map((r) => {
          const ej = r.ejemplos[0];
          return `<li class="rumor">
            <div class="cabeza">${icono("alerta")}<h3>${esc(r.titulo)}</h3></div>
            <p class="explica">${esc(r.explicacion)}</p>
            <p class="meta"><span>${num(r.total)} ${r.total === 1 ? "pieza" : "piezas"}</span>${tendencia(r.ultimas24, r.previas24)}${ej?.url ? `<a href="${esc(ej.url)}" target="_blank" rel="noopener noreferrer">Ver dónde circula ${icono("enlace")}</a>` : ""}</p>
          </li>`;
        })
        .join("")
    : `<li class="vacio">No se detectan rumores en los últimos 3 días.</li>`;
}

// --------------------------------------------------------------- percepción, atribución y pedidos

function pintarAspectos(filas) {
  const por = Object.fromEntries(ASPECTOS.map((a) => [a, { positivo: 0, critico: 0, neutro: 0 }]));
  for (const f of filas) if (por[f.aspecto] && f.tono in por[f.aspecto]) por[f.aspecto][f.tono] += f.n;
  const max = Math.max(1, ...ASPECTOS.map((a) => Math.max(por[a].positivo, por[a].critico)));
  $("aspectos").innerHTML = ASPECTOS.map((a) => {
    const p = por[a];
    const suma = p.positivo + p.critico;
    const bien = suma ? Math.round((100 * p.positivo) / suma) : null;
    const veredicto = bien === null ? `<small>sin opiniones</small>` : bien >= 60 ? `<small class="bien">${bien}% dice que va bien</small>` : bien <= 40 ? `<small class="mal">${100 - bien}% dice que va mal</small>` : `<small>opiniones divididas</small>`;
    return `<div class="aspecto${suma ? "" : " sin-datos"}" data-a="${esc(a)}">
      <div class="nombre"><span>${esc(a)}</span>${veredicto}</div>
      <div class="lado bien"><small>${num(p.positivo)}</small><span class="b" style="width:${(88 * p.positivo) / max}%"></span></div>
      <div class="lado mal"><span class="b" style="width:${(88 * p.critico) / max}%"></span><small>${num(p.critico)}</small></div>
    </div>`;
  }).join("");
  $("aspectos").querySelectorAll(".aspecto").forEach((el) => {
    const p = por[el.dataset.a];
    tooltipEn(el, `<b>${esc(el.dataset.a)}</b><div><span><i style="background:var(--t-positivo)"></i>Va bien</span><span>${num(p.positivo)}</span></div><div><span><i style="background:var(--t-critico)"></i>Va mal</span><span>${num(p.critico)}</span></div><div><span>Neutras</span><span>${num(p.neutro)}</span></div>`);
  });
}

function barrasPorTono(el, filas, campo, orden) {
  const por = {};
  for (const f of filas) {
    const k = f[campo];
    if (!k) continue;
    const t = (por[k] ||= { positivo: 0, neutro: 0, critico: 0, total: 0 });
    if (f.tono in t) t[f.tono] += f.n;
    t.total += f.n;
  }
  const lista = (orden || Object.keys(por)).filter((k) => por[k]).sort((a, b) => por[b].total - por[a].total).slice(0, 10);
  const max = Math.max(1, ...lista.map((k) => por[k].total));
  el.innerHTML = lista.length
    ? lista
        .map((k, i) => {
          const t = por[k];
          const segs = Object.keys(TONOS).filter((x) => t[x]).map((x) => `<span style="width:${(100 * t[x]) / max}%;background:${color("t", x)}"></span>`).join("");
          return `<div class="fila-barra" data-i="${i}"><span class="nombre" title="${esc(k)}">${esc(k)}</span><span class="pista">${segs}</span><span class="cifra">${num(t.total)}${t.critico ? `<small>${num(t.critico)} crít.</small>` : ""}</span></div>`;
        })
        .join("")
    : `<p class="vacio">Nada con estos filtros.</p>`;
  el.querySelectorAll(".fila-barra").forEach((fila) => {
    const k = lista[+fila.dataset.i];
    tooltipEn(fila, `<b>${esc(k)}</b>` + Object.entries(TONOS).map(([x, v]) => `<div><span><i style="background:${color("t", x)}"></i>${v}</span><span>${num(por[k][x])}</span></div>`).join(""));
  });
}

function pintarActores(filas) {
  leyenda($("ley-actores"), TONOS, "t");
  barrasPorTono($("actores"), filas, "actor", ACTORES);
}

function pintarPedidos(filas) {
  const por = {};
  for (const f of filas) {
    const p = (por[f.necesidad] ||= { total: 0, provincias: {} });
    p.total += f.n;
    if (f.provincia) p.provincias[f.provincia] = (p.provincias[f.provincia] || 0) + f.n;
  }
  const lista = Object.entries(por).sort((a, b) => b[1].total - a[1].total).slice(0, 9);
  const max = Math.max(1, ...lista.map(([, p]) => p.total));
  $("pedidos").innerHTML = lista.length
    ? lista
        .map(([nec, p]) => {
          const provs = Object.entries(p.provincias).sort((a, b) => b[1] - a[1]).slice(0, 3).map(([pr, n]) => `${pr} (${num(n)})`).join(", ");
          return `<div class="fila-barra"><span class="nombre">${esc(nec)}</span><span class="pista"><span style="width:${(100 * p.total) / max}%;background:var(--s-medios)"></span></span><span class="cifra">${num(p.total)}</span>${provs ? `<span class="sub">Sobre todo en ${esc(provs)}</span>` : ""}</div>`;
        })
        .join("")
    : `<p class="vacio">Nada con estos filtros.</p>`;
}

function pintarProvincias(filas) {
  const max = Math.max(1, ...filas.map((f) => f.n));
  $("g-prov").innerHTML = filas.length
    ? filas
        .map((f) => {
          const crit = f.criticas || 0;
          return `<div class="fila-barra"><span class="nombre">${esc(f.provincia)}</span><span class="pista">${crit ? `<span style="width:${(100 * crit) / max}%;background:var(--t-critico)"></span>` : ""}${f.n - crit ? `<span style="width:${(100 * (f.n - crit)) / max}%;background:var(--t-neutro)"></span>` : ""}</span><span class="cifra">${num(f.n)}${crit ? `<small>${num(crit)} crít.</small>` : ""}</span></div>`;
        })
        .join("")
    : `<p class="vacio">Nada con estos filtros.</p>`;
}

function pintarVoces(voces) {
  const deMedios = estado.voces === "medios";
  const filas = voces.filter((v) => (v.fuente === "medios") === deMedios).slice(0, 10);
  $("voces").innerHTML = filas.length
    ? `<thead><tr><th>${deMedios ? "Medio" : "Cuenta"}</th><th class="num">${deMedios ? "Piezas" : "Interacciones"}</th><th>Tono</th></tr></thead><tbody>` +
      filas
        .map((v) => {
          const t = { positivo: v.positivas || 0, critico: v.criticas || 0, neutro: v.n - (v.positivas || 0) - (v.criticas || 0) };
          const nombre = deMedios ? v.quien : "@" + String(v.quien || "").replace(/^@/, "");
          const sub = deMedios ? "" : `${FUENTES[v.fuente] || v.fuente}${v.nombre && v.nombre !== v.quien ? " · " + v.nombre : ""} · ${num(v.n)} ${v.n === 1 ? "publicación" : "publicaciones"}`;
          return `<tr><td class="quien"><b>${esc(nombre)}</b>${sub ? `<small>${esc(sub)}</small>` : ""}</td><td class="num">${num(deMedios ? v.n : v.inter)}</td><td>${barraTonos(t)}</td></tr>`;
        })
        .join("") +
      "</tbody>"
    : `<tbody><tr><td class="vacio">Nada con estos filtros.</td></tr></tbody>`;
}

// --------------------------------------------------------------- publicaciones

function pintarPublicaciones(d) {
  const listas = { alertas: d.alertas, redes: d.redes, noticias: d.piezas };
  const piezas = listas[estado.lista] || [];
  const ul = $("lista");
  if (!piezas.length) {
    ul.innerHTML = `<li class="vacio">${estado.lista === "alertas" ? "No hay alertas con estos filtros." : "Nada con estos filtros."}</li>`;
    return;
  }
  ul.innerHTML = piezas
    .map((p) => {
      const titulo = p.titulo || (p.texto ? p.texto.slice(0, 200) : p.resumen) || "(sin texto)";
      const detalle = p.titulo ? p.resumen : p.texto && p.resumen ? p.resumen : "";
      return `<li>
        <p class="meta">
          <b>${esc(quienDe(p))}</b>${p.fuente !== "medios" ? `<span>${FUENTES[p.fuente]}</span>` : ""}
          <span>${esc(fechaCorta(p.fecha))}</span>
          ${p.tono ? `<span class="chip${p.tono === "critico" ? " critico" : ""}"><i style="background:${color("t", p.tono)}"></i>${TONOS[p.tono]}</span>` : ""}
          ${p.sobre && p.sobre !== "nino" ? `<span class="chip">${SOBRE[p.sobre]}</span>` : ""}
          ${p.tema ? `<span class="chip">${esc(p.tema)}</span>` : ""}
          ${p.provincia ? `<span class="chip">${esc(p.provincia)}</span>` : ""}
          ${p.interacciones && p.fuente !== "medios" ? `<span>${num(p.interacciones)} interacciones</span>` : ""}
        </p>
        ${p.url ? `<a class="titulo" href="${esc(p.url)}" target="_blank" rel="noopener noreferrer">${esc(titulo)}${icono("enlace")}</a>` : `<p class="titulo">${esc(titulo)}</p>`}
        ${detalle ? `<p class="detalle">${esc(detalle)}</p>` : ""}
      </li>`;
    })
    .join("");
}

// --------------------------------------------------------------- gráficos por día

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

// Barras apiladas por día: una sola escala, 2 px de superficie entre segmentos, tapa redondeada arriba.
function barrasPorDia(el, dias, filas, campo, nombres, tipo, titulo) {
  const claves = Object.keys(nombres);
  const serie = dias.map((dia) => {
    const fila = { dia, total: 0 };
    for (const k of claves) fila[k] = 0;
    for (const f of filas)
      if (f.dia === dia && f[campo] in fila) {
        fila[f[campo]] += f.n;
        fila.total += f.n;
      }
    return fila;
  });
  const max = Math.max(1, ...serie.map((d) => d.total));
  const paso = escalaBonita(max);
  const tope = Math.ceil(max / paso) * paso;
  const W = 600, H = 220, iz = 34, ab = 24, ar = 8;
  const ancho = (W - iz) / serie.length;
  const barra = Math.min(34, ancho * 0.6);
  const y = (v) => ar + (H - ar - ab) * (1 - v / tope);
  let svg = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(titulo)}">`;
  for (let v = paso; v <= tope; v += paso) svg += `<line class="rejilla-linea" x1="${iz}" x2="${W}" y1="${y(v)}" y2="${y(v)}"/><text class="eje" x="${iz - 6}" y="${y(v) + 4}" text-anchor="end">${num(v)}</text>`;
  svg += `<line class="base" x1="${iz}" x2="${W}" y1="${y(0)}" y2="${y(0)}"/><text class="eje" x="${iz - 6}" y="${y(0) + 4}" text-anchor="end">0</text>`;
  const cadaCuanto = Math.ceil(serie.length / 8);
  serie.forEach((d, i) => {
    const x = iz + i * ancho + (ancho - barra) / 2;
    let base = 0;
    for (const k of claves) {
      if (!d[k]) continue;
      const y1 = y(base + d[k]), y0 = y(base);
      const alto = Math.max(0, y0 - y1 - (base ? 2 : 0));
      const esTope = base + d[k] === d.total;
      svg += esTope ? `<path d="${tapaRedonda(x, y1, barra, alto, 4)}" fill="${color(tipo, k)}"/>` : `<rect x="${x}" y="${y1}" width="${barra}" height="${alto}" fill="${color(tipo, k)}"/>`;
      base += d[k];
    }
    if (i % cadaCuanto === 0 || i === serie.length - 1) svg += `<text class="eje" x="${x + barra / 2}" y="${H - 6}" text-anchor="middle">${esc(nombreDia(d.dia, true))}</text>`;
    svg += `<rect class="zona" data-i="${i}" x="${iz + i * ancho}" y="0" width="${ancho}" height="${H - ab}"/>`;
  });
  el.innerHTML = svg + "</svg>";
  el.querySelectorAll(".zona").forEach((z) => {
    const d = serie[+z.dataset.i];
    tooltipEn(z, `<b>${esc(nombreDia(d.dia))}</b>` + claves.map((k) => `<div><span><i style="background:${color(tipo, k)}"></i>${nombres[k]}</span><span>${num(d[k])}</span></div>`).join("") + `<div><span>Total</span><span>${num(d.total)}</span></div>`);
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
