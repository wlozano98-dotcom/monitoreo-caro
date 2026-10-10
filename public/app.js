// Monitoreo de la Conversación Pública: tablero. Sin frameworks. Pide /api/tablero y dibuja todo en SVG/HTML.

const FUENTES = { medios: "Medios", youtube: "YouTube", x: "X", tiktok: "TikTok", facebook: "Facebook" };
const TONOS = { positivo: "Positivo", neutro: "Neutro", critico: "Crítico" };
const SOBRE = { carolina: "Carolina", secretaria: "Secretaría", nino: "El Niño" };
const ASPECTOS = ["Rapidez de la respuesta", "Llegada de la ayuda", "Presencia en territorio", "Coordinación entre instituciones", "Prevención y alertas", "Comunicación e información", "Liderazgo de Carolina Lozano"];
const ACTORES = ["Secretaría de Gestión de Riesgos", "Carolina Lozano", "Gobierno central", "Municipio o Prefectura", "Fuerzas Armadas y Policía", "Bomberos y Cruz Roja"];
// Niveles de la conversación con los mismos nombres que las alertas de la Secretaría.
const NIVELES = [
  { nombre: "Verde", color: "var(--n-verde)", texto_color: "var(--n-verde-texto)", hasta: 30 },
  { nombre: "Amarilla", color: "var(--n-amarilla)", texto_color: "var(--n-amarilla-texto)", hasta: 45 },
  { nombre: "Naranja", color: "var(--n-naranja)", texto_color: "var(--n-naranja-texto)", hasta: 60 },
  { nombre: "Roja", color: "var(--n-roja)", texto_color: "var(--n-roja-texto)", hasta: 101 },
];

const color = (tipo, clave) => `var(--${tipo}-${clave})`;
const estado = { fuente: "", sobre: "", tono: "", lista: "alertas", voces: "medios" };
let datos = null;
let hitos = []; // hechos grandes marcados por Claude: {dia, titulo, url, n (número), i (posición del día)}
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const num = (n) => Math.round(Number(n || 0)).toLocaleString("es-EC");
const icono = (id, clase = "icono") => `<svg class="${clase}" aria-hidden="true"><use href="#i-${id}"/></svg>`;

// --------------------------------------------------------------- filtros (se recuerdan en la URL)

function leerURL() {
  const p = new URLSearchParams(location.search);
  for (const k of ["fuente", "sobre", "tono"]) estado[k] = p.get(k) || "";
}
function escribirURL() {
  const p = new URLSearchParams();
  for (const k of ["fuente", "sobre", "tono"]) if (estado[k]) p.set(k, estado[k]);
  history.replaceState(null, "", (p.toString() ? "?" + p : location.pathname) + location.hash);
}
function pintarFiltros() {
  for (const k of ["fuente", "sobre", "tono"]) $("f-" + k).value = estado[k];
}
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
  const p = new URLSearchParams();
  for (const k of ["fuente", "sobre", "tono"]) if (estado[k]) p.set(k, estado[k]);
  document.body.style.cursor = "progress";
  try {
    const r = await fetch("/api/tablero?" + p, { cache: "no-store" });
    const d = await r.json();
    if (d.error) throw new Error(d.error);
    // Todo el tablero va pesado por alcance: n pasa a ser la suma de pesos; el número de piezas queda en `piezas`.
    for (const k of ["porDia", "temas", "aspectos", "actores", "necesidades", "provincias"])
      for (const f of d[k] || []) (f.piezas = f.n), (f.n = f.p ?? f.n);
    for (const f of d.provincias) (f.criticasPiezas = f.criticas), (f.criticas = f.pc ?? f.criticas);
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
  $("fecha-hoy").textContent = new Date(d.hoy + "T12:00:00Z").toLocaleDateString("es-EC", { weekday: "short", day: "numeric", month: "short", timeZone: "UTC" });
  $("periodo").textContent = `Todo el período: desde el ${nombreDia(d.desde, true)}`;
  const dias = listaDias(d.desde, d.hoy);
  hitos = (d.hitos || []).map((h, i) => ({ ...h, n: i + 1, i: dias.indexOf(h.dia) })).filter((h) => h.i >= 0);
  pintarHitos();
  pintarResumen(d.resumen);
  pintarNivel(d);
  pintarAgenda(d.agenda, d.agendaDias || []);
  pintarNarrativas(d.narrativas);
  pintarAspectos(d.aspectos, dias);
  pintarActores(d.actores, dias);
  pintarRumores(d.narrativas);
  pintarPedidos(d.necesidades);
  barrasPorDia($("g-volumen"), dias, d.porDia, "fuente", FUENTES, "s", "Menciones por día y fuente");
  barrasPorDia($("g-tono"), dias, d.porDia, "tono", TONOS, "t", "Tono por día");
  leyenda($("ley-fuentes"), FUENTES, "s");
  leyenda($("ley-tonos"), TONOS, "t");
  pintarProvincias(d.provincias);
  pintarVoces(d.voces);
  pintarPublicaciones(d);
  pintarDatosSecciones(d);
}

// Un dato clave en el título de cada sección, para leerlo aunque esté cerrada.
function pintarDatosSecciones(d) {
  const dato = (id, n, texto, rojo) => {
    const el = $("dato-" + id);
    el.className = "seccion-dato" + (rojo && n ? " rojo" : "");
    el.innerHTML = n ? `<b>${num(n)}</b>${texto}` : "";
  };
  const nar = d.narrativas?.narrativas || [];
  dato("narrativas-sec", nar.length, nar.length === 1 ? "narrativa" : "narrativas");
  const malos = ASPECTOS.filter((a) => {
    let b = 0, m = 0;
    for (const f of d.aspectos) if (f.aspecto === a) f.tono === "positivo" ? (b += f.n) : f.tono === "critico" ? (m += f.n) : 0;
    return m > b;
  }).length;
  dato("percepcion", malos, malos === 1 ? "aspecto va mal" : "aspectos van mal", true);
  const rum = d.narrativas?.rumores?.length || 0;
  dato("rumores-sec", rum, rum === 1 ? "rumor" : "rumores", true);
  const total = d.porDia.reduce((s, f) => s + f.piezas, 0);
  dato("volumen", total, "menciones");
  dato("quien", d.provincias.length, d.provincias.length === 1 ? "provincia" : "provincias");
  dato("publicado", d.alertas.length, d.alertas.length === 1 ? "alerta" : "alertas", true);
  if (d.alertas.length && !abiertas.tocado) $("publicado").open = true;
}

// Secciones abiertas: se recuerdan en este navegador.
const abiertas = { tocado: false };
function prepararSecciones() {
  let guardado = null;
  try {
    guardado = JSON.parse(localStorage.getItem("secciones") || "null");
  } catch {}
  const secciones = [...document.querySelectorAll("details.seccion")];
  if (guardado) {
    abiertas.tocado = true;
    for (const s of secciones) if (s.id in guardado) s.open = guardado[s.id];
  }
  const guardar = () => {
    abiertas.tocado = true;
    try {
      localStorage.setItem("secciones", JSON.stringify(Object.fromEntries(secciones.map((s) => [s.id, s.open]))));
    } catch {}
  };
  for (const s of secciones) s.querySelector("summary").addEventListener("click", () => setTimeout(guardar));
  $("abrir-todo").addEventListener("click", () => (secciones.forEach((s) => (s.open = true)), guardar()));
  $("cerrar-todo").addEventListener("click", () => (secciones.forEach((s) => (s.open = false)), guardar()));
}

// --------------------------------------------------------------- banda "Hoy"

function pintarResumen(r) {
  $("resumen").innerHTML = r && r.vinetas?.length ? r.vinetas.map((v) => `<li>${esc(v)}</li>`).join("") : `<li class="vacio">Todavía no hay resumen: aparece cuando la IA clasifica lo recogido.</li>`;
  const acciones = r?.acciones || [];
  $("acciones").innerHTML = acciones.length
    ? acciones.map((a) => `<li><b>${esc(a.accion)}</b><span>${esc(a.porque)}</span>${a.base_legal ? `<em class="ley">${esc(a.base_legal)}</em>` : ""}</li>`).join("")
    : `<li class="vacio">Aparecerán aquí 3 acciones sugeridas cuando la IA haya clasificado lo del día.</li>`;
  const quien = r?.autor === "Claude" ? "Análisis de Claude" : "Escrito por IA (Gemini)";
  $("resumen-pie").textContent = r ? `Últimas 24 horas · ${quien} ${hace(r.creado)} · no depende de los filtros.` : "";
}

function pintarNivel(d) {
  const hoy = { total: 0, critico: 0, carolina: 0, carolinaCritico: 0, alertas: 0, peso: 0, pesoCritico: 0 };
  const ayer = { total: 0, critico: 0 };
  for (const f of d.totales) {
    const b = f.es_hoy ? hoy : ayer;
    b.total += f.n;
    if (f.tono === "critico") b.critico += f.n;
    if (f.es_hoy) (hoy.peso += f.p), f.tono === "critico" && (hoy.pesoCritico += f.p);
    if (f.es_hoy && f.alerta) hoy.alertas += f.n;
    if (f.es_hoy && f.sobre === "carolina") {
      hoy.carolina += f.n;
      if (f.tono === "critico") hoy.carolinaCritico += f.n;
    }
  }
  // Pesado por alcance: una crítica vista por miles pesa más que un tuit sin eco.
  const pct = hoy.peso ? Math.round((100 * hoy.pesoCritico) / hoy.peso) : 0;
  // Un solo indicador: % de lo de 24 h que critica a la Secretaría o a Carolina. Barra y nivel dicen lo mismo.
  const puntaje = pct;
  const i = NIVELES.findIndex((n) => puntaje < n.hasta);
  const nivel = NIVELES[i];
  const sinDatos = !hoy.total;
  $("nivel").textContent = sinDatos ? "—" : nivel.nombre;
  $("nivel").style.color = sinDatos ? "" : nivel.texto_color;
  $("termo-bulbo").style.background = sinDatos ? "" : nivel.color;
  $("nivel-detalle").textContent = sinDatos
    ? "Sin piezas clasificadas en 24 horas"
    : `${pct}% del alcance de las últimas 24 h critica a la Secretaría o a Carolina (${num(hoy.critico)} de ${num(hoy.total)} piezas)`;
  requestAnimationFrame(() => {
    const ancho = sinDatos ? 0 : Math.max(2, puntaje);
    $("agua").style.clipPath = `inset(0 ${100 - ancho}% 0 0 round 999px)`;
    $("marca-nivel").style.left = ancho + "%";
    $("marca-nivel").hidden = sinDatos;
  });
  const dif = hoy.total - ayer.total;
  const cambio = dif === 0 ? "igual que ayer" : `${dif > 0 ? "+" : "−"}${num(Math.abs(dif))} vs. ayer`;
  $("cifras-hoy").innerHTML = `
    <div><dt>Menciones 24 h</dt><dd>${num(hoy.total)}<small>${cambio}</small></dd></div>
    <div><dt>Sobre Carolina</dt><dd>${num(hoy.carolina)}<small>${num(hoy.carolinaCritico)} críticas</small></dd></div>
    <div><dt>Alertas</dt><dd>${num(hoy.alertas)}<small>24 horas</small></dd></div>`;

  const n = d.alertas.length;
  const aviso = $("aviso-alertas");
  aviso.hidden = !n;
  aviso.innerHTML = n ? `${icono("alerta")}<span>${n} alerta${n > 1 ? "s" : ""} desde el ${esc(nombreDia(d.desde, true))}: ver cuáles</span>${icono("flecha")}` : "";
  aviso.onclick = () => {
    $("publicado").open = true;
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
  $("narrativas-pie").textContent = `Lo que más se repite en medios y redes en los últimos 3 días. ${nar.autor === "Claude" ? "Análisis de Claude" : "Agrupado por IA (Gemini)"} ${hace(nar.creado)}; no depende de los filtros.`;
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
          ${apuntaA(n.actores)}
        </div>
        <div class="datos">
          <p class="total"><b>${num(n.total)}</b><span>menciones</span>${tendencia(n.ultimas24, n.previas24, mayoriaPositiva)}</p>
          ${n.porDia ? curvaNarrativa(n.porDia) : ""}
          ${barraTonos(t)}
          <p class="fuentes">${fuentes}</p>
        </div>
        ${n.ejemplos.length ? `<details><summary>${icono("flecha")}Ver ejemplos</summary><ul class="ejemplos">${ejemplosHTML(n.ejemplos)}</ul></details>` : ""}
      </li>`;
    })
    .join("");
}

// A quién apunta una narrativa (el actor más nombrado en sus piezas).
function apuntaA(actores) {
  const top = Object.entries(actores || {}).sort((a, b) => b[1] - a[1])[0];
  return top ? `<p class="apunta">Apunta a: <b>${esc(top[0])}</b></p>` : "";
}

// Piezas por día de una narrativa: una columna por día con su número arriba y la fecha abajo.
function curvaNarrativa(porDia) {
  const dias = Object.keys(porDia).sort();
  if (dias.length < 2) return "";
  const serie = listaDias(dias[0], dias[dias.length - 1]).map((d) => [d, porDia[d] || 0]);
  const max = Math.max(1, ...serie.map(([, v]) => v));
  return `<div class="curva" aria-label="Menciones por día">${serie
    .map(([d, v]) => `<div><b>${num(v)}</b><span class="col"><i style="height:${Math.max(v ? 8 : 0, (100 * v) / max)}%"></i></span><small>${esc(nombreDia(d, true))}</small></div>`)
    .join("")}</div>`;
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

// Día a día de un aspecto o actor: cuántas piezas dicen que va bien (arriba) y que va mal (abajo).
function serieDias(dias, filas, campo, clave) {
  const por = Object.fromEntries(dias.map((d) => [d, { dia: d, positivo: 0, critico: 0, neutro: 0 }]));
  for (const f of filas) if (f[campo] === clave && por[f.dia] && f.tono in por[f.dia]) por[f.dia][f.tono] += f.n;
  return dias.map((d) => por[d]);
}
// Ola día a día: arriba (azul) las piezas que dicen que va bien, abajo (rojo) las que dicen que va mal.
// Misma escala en todas las filas de un panel, para poder compararlas.
function ola(serie, max) {
  const W = 320, H = 56, mitad = 28, alto = 26, n = serie.length;
  const x = (i) => (n === 1 ? W / 2 : 6 + (i * (W - 12)) / (n - 1));
  const curva = (signo, campo) => {
    const ys = serie.map((d) => mitad - signo * (alto * d[campo]) / max);
    let p = `M${x(0)},${mitad}L${x(0)},${ys[0]}`;
    for (let i = 1; i < n; i++) {
      const xm = (x(i - 1) + x(i)) / 2;
      p += `C${xm},${ys[i - 1]} ${xm},${ys[i]} ${x(i)},${ys[i]}`;
    }
    return p + `L${x(n - 1)},${mitad}Z`;
  };
  return `<div class="ola-caja"><svg class="ola" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" role="img" aria-label="Día a día: ${serie.map((d) => `${nombreDia(d.dia, true)} ${d.positivo} bien, ${d.critico} mal`).join("; ")}">
    <path d="${curva(1, "positivo")}" fill="var(--t-positivo)" fill-opacity=".75"/>
    <path d="${curva(-1, "critico")}" fill="var(--t-critico)" fill-opacity=".75"/>
    <line class="base" x1="0" x2="${W}" y1="${mitad}" y2="${mitad}"/>
    ${hitos.map((h) => `<line class="hito" x1="${x(h.i)}" x2="${x(h.i)}" y1="0" y2="${H}"/>`).join("")}</svg>
    ${hitos.map((h) => `<span class="hito-num" style="left:${(100 * x(h.i)) / W}%" title="${esc(nombreDia(h.dia, true) + ": " + h.titulo)}">${h.n}</span>`).join("")}
    <p class="ola-fechas"><span>${esc(nombreDia(serie[0].dia, true))}</span><span>${esc(nombreDia(serie[n - 1].dia, true))}</span></p></div>`;
}
function maxSerie(series) {
  return Math.max(1, ...Object.values(series).flatMap((s) => s.map((d) => Math.max(d.positivo, d.critico))));
}
function botonPiezas(tipo, valor) {
  return `<button type="button" class="ver-piezas" data-tipo="${tipo}" data-valor="${esc(valor)}" aria-expanded="false">${icono("flecha")}Ver noticias</button><ul class="piezas-de" hidden></ul>`;
}
// "Ver noticias": pide las piezas de ese aspecto o actor y las muestra con su pastilla de tono.
async function verPiezas(boton) {
  const lista = boton.nextElementSibling;
  const abrir = boton.getAttribute("aria-expanded") !== "true";
  boton.setAttribute("aria-expanded", String(abrir));
  lista.hidden = !abrir;
  if (!abrir || lista.dataset.cargado) return;
  lista.innerHTML = `<li class="vacio">Cargando…</li>`;
  const p = new URLSearchParams({ tipo: boton.dataset.tipo, valor: boton.dataset.valor });
  for (const k of ["fuente", "sobre", "tono"]) if (estado[k]) p.set(k, estado[k]);
  try {
    const { piezas } = await (await fetch("/api/piezas?" + p, { cache: "no-store" })).json();
    lista.dataset.cargado = "1";
    lista.innerHTML = piezas.length
      ? piezas
          .map((x) => {
            const titulo = x.titulo || x.resumen || "(sin texto)";
            const pastilla = `<span class="pastilla-tono ${x.tono}">${x.tono === "positivo" ? "Va bien" : x.tono === "critico" ? "Va mal" : "Neutra"}</span>`;
            const meta = `${esc(quienDe(x))} · ${esc(FUENTES[x.fuente] || x.fuente)} · ${esc(fechaCorta(x.fecha))}${x.vistas ? ` · ${num(x.vistas)} vistas` : ""}`;
            return `<li>${pastilla}<div>${x.url ? `<a href="${esc(x.url)}" target="_blank" rel="noopener noreferrer">${esc(titulo)}</a>` : esc(titulo)}<small>${meta}</small>${botonCorregir({ ...x, tono: x.tono_sngr ?? x.tono })}</div></li>`;
          })
          .join("")
      : `<li class="vacio">Nada con estos filtros.</li>`;
  } catch (e) {
    lista.innerHTML = `<li class="vacio">No se pudo cargar.</li>`;
  }
}
for (const id of ["aspectos", "actores"]) $(id).addEventListener("click", (e) => e.target.closest(".ver-piezas") && verPiezas(e.target.closest(".ver-piezas")));

// "51 pts · 17 piezas": puntos de alcance y cuántas piezas son.
const punt = (p, n) => `${num(p)} pts · ${num(n || 0)} ${n === 1 ? "pieza" : "piezas"}`;

// Lista de hitos (numerados como en los gráficos), con enlace a la noticia.
function pintarHitos() {
  const html = hitos
    .map((h) => `<li><span class="hito-num">${h.n}</span><span>${esc(nombreDia(h.dia, true))} · ${h.url ? `<a href="${esc(h.url)}" target="_blank" rel="noopener noreferrer">${esc(h.titulo)}</a>` : esc(h.titulo)}</span></li>`)
    .join("");
  document.querySelectorAll("[data-hitos]").forEach((el) => ((el.innerHTML = html), (el.hidden = !hitos.length)));
}

function pintarAspectos(filas, dias) {
  const por = Object.fromEntries(ASPECTOS.map((a) => [a, { positivo: 0, critico: 0, neutro: 0 }]));
  for (const f of filas)
    if (por[f.aspecto] && f.tono in por[f.aspecto]) (por[f.aspecto][f.tono] += f.n), (por[f.aspecto]["n_" + f.tono] = (por[f.aspecto]["n_" + f.tono] || 0) + f.piezas);
  const series = Object.fromEntries(ASPECTOS.map((a) => [a, serieDias(dias, filas, "aspecto", a)]));
  const max = Math.max(1, ...ASPECTOS.map((a) => Math.max(por[a].positivo, por[a].critico)));
  const maxDia = maxSerie(series);
  $("aspectos").innerHTML = ASPECTOS.map((a) => {
    const p = por[a];
    const suma = p.positivo + p.critico;
    const bien = suma ? Math.round((100 * p.positivo) / suma) : null;
    const veredicto = bien === null ? `<small>sin opiniones</small>` : bien >= 60 ? `<small class="bien">${bien}% dice que va bien</small>` : bien <= 40 ? `<small class="mal">${100 - bien}% dice que va mal</small>` : `<small>opiniones divididas</small>`;
    return `<div class="aspecto${suma ? "" : " sin-datos"}" data-a="${esc(a)}">
      <div class="nombre"><span>${esc(a)}</span>${veredicto}</div>
      <div class="lado bien"><small>${num(p.positivo)}</small><span class="b" style="width:${(88 * p.positivo) / max}%"></span></div>
      <div class="lado mal"><span class="b" style="width:${(88 * p.critico) / max}%"></span><small>${num(p.critico)}</small></div>
      ${suma ? `<div class="debajo">${ola(series[a], maxDia)}${botonPiezas("aspecto", a)}</div>` : ""}
    </div>`;
  }).join("");
  $("aspectos").querySelectorAll(".aspecto .lado").forEach((el) => {
    const a = el.closest(".aspecto").dataset.a, p = por[a];
    tooltipEn(el, `<b>${esc(a)}</b><div><span><i style="background:var(--t-positivo)"></i>Va bien</span><span>${punt(p.positivo, p.n_positivo)}</span></div><div><span><i style="background:var(--t-critico)"></i>Va mal</span><span>${punt(p.critico, p.n_critico)}</span></div><div><span>Neutras</span><span>${punt(p.neutro, p.n_neutro)}</span></div>`);
  });
}

function pintarActores(filas, dias) {
  const por = {};
  for (const f of filas) {
    const t = (por[f.actor] ||= { positivo: 0, neutro: 0, critico: 0, total: 0 });
    if (f.tono in t) (t[f.tono] += f.n), (t["n_" + f.tono] = (t["n_" + f.tono] || 0) + f.piezas);
    t.total += f.n;
  }
  por["Carolina Lozano"] ||= { positivo: 0, neutro: 0, critico: 0, total: 0 };
  const lista = ACTORES.filter((k) => por[k]).sort((a, b) => por[b].total - por[a].total);
  const series = Object.fromEntries(lista.map((k) => [k, serieDias(dias, filas, "actor", k)]));
  const max = Math.max(1, ...lista.map((k) => por[k].total));
  const maxDia = maxSerie(series);
  leyenda($("ley-actores"), TONOS, "t");
  $("actores").innerHTML = lista
    .map((k) => {
      const t = por[k];
      const segs = Object.keys(TONOS).filter((x) => t[x]).map((x) => `<span style="width:${(100 * t[x]) / max}%;background:${color("t", x)}"></span>`).join("");
      return `<div class="actor" data-a="${esc(k)}">
        <div class="fila-barra"><span class="nombre" title="${esc(k)}">${esc(k)}</span><span class="pista">${segs}</span><span class="cifra">${num(t.total)} pts${t.critico ? `<small>${num(t.critico)} crít.</small>` : ""}</span></div>
        <div class="debajo">${t.positivo + t.critico ? ola(series[k], maxDia) : ""}${botonPiezas("actor", k)}</div>
      </div>`;
    })
    .join("");
  $("actores").querySelectorAll(".actor .fila-barra").forEach((fila) => {
    const k = fila.closest(".actor").dataset.a;
    tooltipEn(fila, `<b>${esc(k)}</b>` + Object.entries(TONOS).map(([x, v]) => `<div><span><i style="background:${color("t", x)}"></i>${v}</span><span>${punt(por[k][x], por[k]["n_" + x])}</span></div>`).join(""));
  });
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

// El Niño en la agenda nacional: ranking de temas de las últimas 24 h (todos los titulares de los medios del país),
// el % de titulares sobre El Niño día a día y lo más buscado en Google.
function pintarAgenda(a, dias) {
  $("agenda-caja").hidden = !a;
  if (!a) return;
  const temas = a.temas.filter((t) => t.n);
  const nino = temas.find((t) => t.nino);
  const puesto = nino ? temas.indexOf(nino) + 1 : 0;
  const pct = (n, total) => (total ? Math.round((100 * n) / total) : 0);
  $("agenda-sub").textContent = `Temas más publicados por ${a.medios} medios del país en las últimas 24 horas (${num(a.total)} titulares; los sueltos no entran al ranking). Actualizado ${hace(a.creado)}.`;
  $("agenda-puesto").innerHTML = nino
    ? `<b>${puesto}.º</b>de ${temas.length} temas · ${pct(nino.n, a.total)}% de los titulares del país`
    : `<b>—</b>El Niño no aparece entre los temas de hoy`;
  const lista = temas.slice(0, 10);
  if (nino && puesto > 10) lista.push(nino);
  const max = Math.max(1, ...lista.map((t) => t.n));
  $("agenda-temas").innerHTML = lista
    .map((t) => `<div class="fila-barra${t.nino ? " nino" : ""}"><span class="nombre" title="${esc(t.tema)}">${esc(t.tema)}</span><span class="pista"><span style="width:${(100 * t.n) / max}%;background:${t.nino ? "var(--acento)" : "var(--t-neutro)"}"></span></span><span class="cifra">${num(t.n)}</span></div>`)
    .join("");
  $("agenda-temas").querySelectorAll(".fila-barra").forEach((fila, i) => {
    const t = lista[i];
    tooltipEn(fila, `<b>${esc(t.tema)}</b><div><span>Titulares</span><span>${num(t.n)} · ${pct(t.n, a.total)}%</span></div><div><span>Medios</span><span>${num(t.medios)}</span></div>` + (t.ejemplos || []).map((e) => `<p class="tip-ej">${esc(e.titulo)} <i>(${esc(e.medio)})</i></p>`).join(""));
  });

  // Día a día: % de titulares sobre El Niño y su puesto entre los temas de ese día (solo días con datos suficientes).
  const por = {};
  for (const f of dias) {
    const d = (por[f.dia] ||= { dia: f.dia, total: 0, nino: 0, temas: [] });
    d.total += f.n;
    if (f.nino) d.nino += f.n;
    else if (f.tema) d.temas.push(f.n);
  }
  const serie = Object.values(por)
    .filter((d) => d.total >= 50)
    .slice(-14)
    .map((d) => ({ ...d, pct: (100 * d.nino) / d.total, puesto: d.nino ? 1 + d.temas.filter((n) => n > d.nino).length : 0 }));
  const W = 320, H = 96, techo = Math.max(10, ...serie.map((d) => d.pct)) * 1.15;
  const x = (i) => ((i + 0.5) * W) / serie.length; // centrado bajo cada etiqueta de día
  const y = (v) => H - 4 - ((H - 8) * v) / techo;
  const pts = serie.map((d, i) => `${x(i)},${y(d.pct)}`).join(" ");
  $("agenda-dias").innerHTML = serie.length
    ? `${serie.length < 2 ? "" : `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" role="img" aria-label="${esc(serie.map((d) => `${nombreDia(d.dia, true)}: ${Math.round(d.pct)}%`).join("; "))}">
        <polygon class="area" points="${x(0)},${H} ${pts} ${x(serie.length - 1)},${H}"/><polyline class="linea" points="${pts}"/>
      </svg>`}
      <p class="dias">${serie.map((d) => `<span><b>${Math.round(d.pct)}%</b>${esc(nombreDia(d.dia, true))}${d.puesto ? ` · ${d.puesto}.º` : ""}</span>`).join("")}</p>`
    : `<p class="vacio">Empieza a contar desde hoy.</p>`;

  const volumen = (b) => parseInt(String(b.trafico).replace(/\D/g, "")) || 0; // "50000+" -> 50000
  const bus = [...(a.busquedas || [])].sort((p, q) => volumen(q) - volumen(p)).slice(0, 8);
  $("agenda-busquedas").innerHTML = bus.length
    ? bus.map((b) => `<li class="${b.nino ? "nino" : ""}" title="${esc(b.noticia)}"><span class="termino">${esc(b.termino)}</span><span class="trafico">${num(volumen(b))}+</span></li>`).join("")
    : `<li class="vacio">Sin datos de Google ahora.</li>`;
}

function pintarProvincias(filas) {
  const max = Math.max(1, ...filas.map((f) => f.n));
  $("g-prov").innerHTML = filas.length
    ? filas
        .map((f) => {
          const crit = f.criticas || 0;
          return `<div class="fila-barra"><span class="nombre">${esc(f.provincia)}</span><span class="pista">${crit ? `<span style="width:${(100 * crit) / max}%;background:var(--t-critico)"></span>` : ""}${f.n - crit ? `<span style="width:${(100 * (f.n - crit)) / max}%;background:var(--t-neutro)"></span>` : ""}</span><span class="cifra">${num(f.n)}</span></div>`;
        })
        .join("")
    : `<p class="vacio">Nada con estos filtros.</p>`;
  $("g-prov").querySelectorAll(".fila-barra").forEach((fila, i) => {
    const f = filas[i];
    const crit = f.criticas || 0;
    tooltipEn(fila, `<b>${esc(f.provincia)}</b><div><span><i style="background:var(--t-critico)"></i>Críticas</span><span>${punt(crit, f.criticasPiezas)}</span></div><div><span><i style="background:var(--t-neutro)"></i>Resto</span><span>${punt(f.n - crit, f.piezas - (f.criticasPiezas || 0))}</span></div><div><span>Total</span><span>${punt(f.n, f.piezas)}</span></div>`);
  });
}

function pintarVoces(voces) {
  const deMedios = estado.voces === "medios";
  const filas = voces.filter((v) => (v.fuente === "medios") === deMedios).slice(0, 10);
  $("voces").innerHTML = filas.length
    ? `<thead><tr><th>${deMedios ? "Medio" : "Cuenta"}</th><th class="num">${deMedios ? "Piezas" : "Alcance"}</th><th>Tono</th></tr></thead><tbody>` +
      filas
        .map((v) => {
          const t = { positivo: v.positivas || 0, critico: v.criticas || 0, neutro: v.n - (v.positivas || 0) - (v.criticas || 0) };
          const nombre = deMedios ? v.quien : "@" + String(v.quien || "").replace(/^@/, "");
          const sub = deMedios ? "" : `${FUENTES[v.fuente] || v.fuente}${v.nombre && v.nombre !== v.quien ? " · " + v.nombre : ""} · ${num(v.n)} ${v.n === 1 ? "publicación" : "publicaciones"}${v.seguidores ? ` · ${num(v.seguidores)} seguidores` : ""}`;
          const cifra = deMedios ? num(v.n) : v.vistas ? `${num(v.vistas)}<small>vistas · ${num(v.inter)} interacc.</small>` : `${num(v.inter)}<small>interacciones</small>`;
          return `<tr><td class="quien"><b>${esc(nombre)}</b>${sub ? `<small>${esc(sub)}</small>` : ""}</td><td class="num">${cifra}</td><td>${barraTonos(t)}</td></tr>`;
        })
        .join("") +
      "</tbody>"
    : `<tbody><tr><td class="vacio">Nada con estos filtros.</td></tr></tbody>`;
}

// --------------------------------------------------------------- corregir una clasificación

// Cualquiera puede corregir (decisión de Andrés). La corrección cuenta de inmediato en la base, el tablero la muestra
// cuando vence la caché (5 min) y Gemini la recibe como ejemplo en las próximas corridas.
function botonCorregir(p) {
  if (!p.id) return "";
  const datos = { id: p.id, tono: p.tono || "neutro", actor: p.actor || "Ninguno", tono_actor: p.tono_actor || "neutro", aspecto: p.aspecto || "Ninguno" };
  return `<button type="button" class="corregir" data-pieza="${esc(JSON.stringify(datos))}">¿Mal clasificada? Corregir</button>`;
}
function opciones(lista, actual, nombres = {}) {
  return lista.map((v) => `<option value="${esc(v)}"${v === actual ? " selected" : ""}>${esc(nombres[v] || v)}</option>`).join("");
}
function abrirCorregir(boton) {
  const p = JSON.parse(boton.dataset.pieza);
  const tonos = { positivo: "Positivo", neutro: "Neutro", critico: "Crítico" };
  const form = document.createElement("form");
  form.className = "form-corregir";
  form.innerHTML = `
    <label><span>Tono hacia la Secretaría y Carolina</span><select name="tono">${opciones(Object.keys(tonos), p.tono, tonos)}</select></label>
    <label><span>¿A quién apunta?</span><select name="actor">${opciones([...ACTORES, "Ninguno"], p.actor)}</select></label>
    <label><span>Tono hacia ese actor</span><select name="tono_actor">${opciones(Object.keys(tonos), p.tono_actor, tonos)}</select></label>
    <label><span>Aspecto de la respuesta</span><select name="aspecto">${opciones([...ASPECTOS, "Ninguno"], p.aspecto)}</select></label>
    <label class="check"><input type="checkbox" name="fuera"> No tiene que ver con el tema (sacarla del tablero)</label>
    <div class="botones"><button type="submit">Guardar</button><button type="button" class="cancelar">Cancelar</button><span class="msj" role="status"></span></div>`;
  boton.hidden = true;
  boton.after(form);
  form.querySelector(".cancelar").onclick = () => (form.remove(), (boton.hidden = false));
  form.onsubmit = async (e) => {
    e.preventDefault();
    const f = new FormData(form);
    const cambios = {};
    for (const k of ["tono", "actor", "tono_actor", "aspecto"]) if (f.get(k) !== p[k]) cambios[k] = f.get(k);
    if (f.get("fuera")) cambios.relevante = "0";
    const msj = form.querySelector(".msj");
    if (!Object.keys(cambios).length) return (msj.textContent = "No cambiaste nada.");
    msj.textContent = "Guardando…";
    try {
      const r = await (await fetch("/api/corregir", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ id: p.id, cambios }) })).json();
      if (r.error) throw new Error(r.error);
      form.innerHTML = `<p class="msj ok">Corregido, gracias. Se verá en el tablero en unos minutos y la IA aprenderá del ejemplo.</p>`;
    } catch (err) {
      msj.textContent = "No se pudo guardar: " + err.message;
    }
  };
}
document.addEventListener("click", (e) => {
  const b = e.target.closest(".corregir");
  if (b) abrirCorregir(b);
});

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
          ${p.vistas ? `<span>${num(p.vistas)} vistas</span>` : ""}
          ${p.interacciones && p.fuente !== "medios" ? `<span>${num(p.interacciones)} interacciones</span>` : ""}
        </p>
        ${p.url ? `<a class="titulo" href="${esc(p.url)}" target="_blank" rel="noopener noreferrer">${esc(titulo)}${icono("enlace")}</a>` : `<p class="titulo">${esc(titulo)}</p>`}
        ${detalle ? `<p class="detalle">${esc(detalle)}</p>` : ""}
        ${botonCorregir(p)}
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
  for (const h of hitos) {
    const cx = iz + h.i * ancho + ancho / 2;
    svg += `<line class="hito" x1="${cx}" x2="${cx}" y1="${ar + 10}" y2="${H - ab}"/><circle class="hito-circ" cx="${cx}" cy="${ar + 2}" r="8"/><text class="hito-txt" x="${cx}" y="${ar + 6}" text-anchor="middle">${h.n}</text>`;
  }
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
  // Solo con mouse: en el celular cada toque abría la cajita y estorbaba.
  if (!matchMedia("(hover: hover) and (pointer: fine)").matches) return;
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
prepararSecciones();
cargar();
setInterval(cargar, 10 * 60 * 1000);
