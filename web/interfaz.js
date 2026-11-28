(async function () {
'use strict';
// Fase 7.1: los datos ya no van en un <script id="datos"> inline (ver
// CLAUDE.md, decisión 45) -- se piden a la API. El resto del archivo no
// cambia: sigue siendo exactamente el mismo código, en el mismo orden,
// solo que ahora espera a que lleguen los datos antes de usarlos.
const D = await fetch('/api/datos').then((r) => r.json());
const M = window.Motor;
const ctx = M.crearContexto(D);
const C = M.CLASES;

const $ = (s, r) => (r || document).querySelector(s);
const esc = (t) => String(t == null ? '' : t).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const r0 = (x) => (x == null || !isFinite(x) ? '–' : Math.round(x));
const r1 = (x) => (x == null || !isFinite(x) ? '–' : (Math.round(x * 10) / 10).toLocaleString('es-CO'));
const pesos = (x) => '$' + Math.round(x / 1000).toLocaleString('es-CO') + ' mil';
const zn = (id) => (id ? M.nombreZona(ctx, id) : 'zona sin verificar');
const corto = (id) => String(id).replace(/^ESC-\d+-/, '');
const NOMBRE_TIPO = { TAM: 'Ambulancia medicalizada', TAB: 'Ambulancia básica', VMD: 'Médico domiciliario' };
const LETRA = { TAM: 'M', TAB: 'B', VMD: 'D' };
const ESTADO_TXT = {
  DISPONIBLE: 'Disponible en base', RETORNANDO: 'Disponible, regresando', EN_RUTA: 'En ruta', EN_ATENCION: 'En atención',
  EN_TRASLADO: 'En traslado', FUERA_SERVICIO: 'Fuera de servicio', DETENIDA: 'Detenida (no apta)',
};
const REGLAS_TXT = {
  R04: 'R04: VMD como primer respondiente y ambulancia preasignada', R06: 'R06: desvío desde una consulta 03 o 06',
  D01: 'D01: menor tiempo de llegada desde la posición actual', D02: 'D02: diferencia menor de 3 min, gana el menor costo',
  D03: 'D03: cobertura de zonas ALTA a 20 min', D04: 'D04: reparto de carga', D05: 'D05: no comprometer una TAM en un 02',
  D06: 'D06: 07 con posible traslado', D07: 'D07: VMD de apoyo en un 01 con TAB', D08: 'D08: liberación incierta tras traslado',
};
const MOTIVOS_CAMBIO = [
  'Hay una condición de acceso en la zona', 'Indicación del coordinador', 'Prefiero conservar cobertura en otra zona',
  'La tripulación reporta otra posición', 'Varios pacientes en el mismo punto', 'Corrección de una asignación', 'Otro motivo operativo',
];
const MOTIVOS_NO_APTA = [
  'Falla mecánica', 'Accidente de tránsito', 'Insumos o equipos agotados', 'Tripulación incompleta', 'Limpieza o desinfección', 'Otro motivo operativo',
];
// Motivos y discriminadores del documento 03
const MOTIVOS = {
  '01': [['Dolor torácico', 'Shock'], ['Disnea en adulto', 'Respiración inadecuada'], ['Adulto con alteración de conciencia', 'Paciente que no responde'], ['Paro / colapso', 'Sin pulso'], ['Alergia', 'Compromiso de vía aérea'], ['Hemorragia', 'Hemorragia exanguinante'], ['Déficit neurológico', 'Déficit neurológico agudo con alteración de conciencia']],
  '02': [['Dolor torácico', 'Dolor precordial o cardiaco'], ['Convulsiones', 'Convulsión activa o reciente'], ['Asma / disnea', 'Saturación baja'], ['Diabetes', 'Hipoglicemia'], ['Desmayo / colapso', 'Alteración de conciencia transitoria'], ['Intoxicación', 'Ingesta de alto riesgo'], ['Disnea en adulto', 'Dificultad respiratoria marcada'], ['Cefalea', 'Inicio súbito y dolor intenso']],
  '07': [['Dolor abdominal en adulto', 'Dolor moderado'], ['Disnea en adulto', 'Fiebre con dificultad respiratoria leve'], ['Hipertensión', 'Cifras elevadas con síntomas leves'], ['Trauma craneal', 'Pérdida de conciencia breve recuperada'], ['Heridas', 'Sangrado no controlable con presión leve'], ['Problema de salud mental', 'Angustia marcada'], ['Caídas', 'Deformidad o dolor moderado en extremidad'], ['Diarrea y vómitos', 'Signos de deshidratación']],
  '03': [['Adulto con mal estado general', 'Fiebre'], ['Síntomas respiratorios', 'Tos y congestión sin dificultad respiratoria'], ['Diarrea y vómitos', 'Vómito o diarrea sin deshidratación'], ['Problemas urinarios', 'Disuria'], ['Dolor de espalda', 'Dolor leve a moderado reciente'], ['Cefalea', 'Dolor leve a moderado'], ['Problemas en extremidades', 'Dolor leve tras torcedura'], ['Erupciones cutáneas', 'Prurito']],
  '06': [['Síntomas respiratorios', 'Síntomas leves de resfriado'], ['Problemas oculares', 'Ojo rojo sin dolor ni pérdida visual'], ['Dolor abdominal en adulto', 'Malestar leve de larga evolución'], ['Solicitud administrativa', 'Renovación de fórmula'], ['Erupciones cutáneas', 'Problema reciente leve'], ['Adulto con mal estado general', 'Sin discriminadores de mayor nivel']],
};
const CODIGOS = ['01', '02', '07', '03', '06'];
const COLOR_CLASE = { '01': ['#c62828', '#fff'], '02': ['#ef8a24', '#17202a'], '07': ['#f2c52c', '#17202a'], '03': ['#24804a', '#fff'], '06': ['#2c6cc4', '#fff'] };
const esUrgente = (s) => s.clas === '01' || s.clas === '02';

const ui = {
  escId: 'ESC-03', estado: null, sel: null, opSel: 0, preview: null, cambiar: false, cambioSel: null, motivo: '',
  apoyo: true, play: false, timer: null, vista: 'despacho', zoom: 'urbana', politicas: null, comparacion: {}, escVista: 'ESC-03',
  noAptaAbierta: null, urgMin: false, urgId: null, ultima: null, pendiente: null, rec: null, tripSel: null, tripPaso: null,
  mapa: { filtros: { disp: true, serv: true, noapta: true, sol: true, rutas: true }, movilSel: null, vb: null, noApta: false },
};

// ---------- tiempo ----------
function hora(m) { const t = M.horaDe(ui.estado.esc, m); return String(t.getHours()).padStart(2, '0') + ':' + String(t.getMinutes()).padStart(2, '0'); }
function dia(m) { return M.horaDe(ui.estado.esc, m).toLocaleDateString('es-CO', { weekday: 'long', day: 'numeric', month: 'short' }); }

// ---------- avisos y tooltip ----------
const ICONO_ALERTA = '<svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true"><path d="M8 1.5 15 14H1z" fill="#c58a00"/><path d="M8 6v4" stroke="#fff" stroke-width="1.8" stroke-linecap="round"/><circle cx="8" cy="12" r="1" fill="#fff"/></svg>';
const ICONO_OK = '<svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true"><circle cx="8" cy="8" r="7" fill="#fff" fill-opacity=".2"/><path d="m4.5 8.2 2.3 2.3 4.7-4.9" stroke="#fff" stroke-width="1.8" fill="none" stroke-linecap="round"/></svg>';
function aviso(texto, alerta, accion) {
  const el = document.createElement('div');
  el.className = 'aviso' + (alerta ? ' alerta' : '');
  el.innerHTML = (alerta ? ICONO_ALERTA : ICONO_OK) + '<div>' + esc(texto) + (accion ? ` <button class="aviso-accion" data-corregir="${accion.sol}">${esc(accion.texto)}</button>` : '') + '</div>';
  $('#avisos').prepend(el);
  setTimeout(() => el.remove(), accion ? 10000 : alerta ? 6000 : 3500);
  while ($('#avisos').children.length > 3) $('#avisos').lastChild.remove();
}
const tip = $('#tip');
document.addEventListener('mousemove', (e) => {
  const t = e.target.closest('[data-tip]');
  if (!t) { tip.style.display = 'none'; return; }
  tip.innerHTML = t.getAttribute('data-tip');
  tip.style.display = 'block';
  const w = tip.offsetWidth, h = tip.offsetHeight;
  let x = e.clientX + 14, y = e.clientY + 14;
  if (x + w > window.innerWidth - 8) x = e.clientX - w - 14;
  if (y + h > window.innerHeight - 8) y = e.clientY - h - 14;
  tip.style.left = x + 'px'; tip.style.top = y + 'px';
});

// ---------- carga y reloj ----------
function cargar(escId) {
  pausar();
  ui.escId = escId; ui.escVista = escId;
  ui.estado = M.cargarEscenario(ctx, escId);
  Object.assign(ui, { sel: null, opSel: 0, preview: null, cambiar: false, cambioSel: null, motivo: '', apoyo: true, politicas: null, urgMin: false, urgId: null, ultima: null, pendiente: null, tripPaso: null });
  ui.mapa.movilSel = null; ui.mapa.vb = null;
  $('#sel-esc').value = escId;
  if ($('#dlg-confirmar').open) $('#dlg-confirmar').close();
  autoSeleccion();
  render();
}

function pendientes() {
  const e = ui.estado;
  const inc = M.porCompletar(e);
  return inc.filter(esUrgente).concat(M.cola(e)).concat(inc.filter((s) => !esUrgente(s)));
}
function urgencias() { return pendientes().filter(esUrgente).sort((a, b) => (C[a.clas].prio - C[b.clas].prio) || (a.minCola - b.minCola)); }

function autoSeleccion() {
  const lista = pendientes();
  if (!ui.sel || !lista.find((s) => s.id === ui.sel)) { ui.sel = lista[0] ? lista[0].id : null; resetDecision(); }
}
function resetDecision() { ui.opSel = 0; ui.cambiar = false; ui.cambioSel = null; ui.motivo = ''; ui.apoyo = true; ui.preview = null; }

function procesarEventos(evs) {
  let pausa = false;
  evs.forEach((e) => {
    if (['solicitud', 'reclasificacion', 'cancelacion', 'alerta', 'liberacion', 'referencia', 'tripulacion', 'info'].includes(e.tipo)) aviso(`${hora(e.hora)}  ${e.texto}`, !!e.datos.alerta);
    if (e.datos.alerta) pausa = true;
    const s = e.datos.sol && ui.estado.solicitudes[e.datos.sol];
    if (s && e.datos.alerta && esUrgente(s) && s.estado === 'cola') ui.urgMin = false;
    if (e.tipo === 'reclasificacion' && e.datos.alerta && e.datos.sol) { ui.sel = e.datos.sol; resetDecision(); }
  });
  return pausa;
}

function paso(n) {
  const evs = M.avanzar(ctx, ui.estado, n);
  const pausa = procesarEventos(evs);
  ui.politicas = null;
  autoSeleccion();
  if (pausa && $('#chk-pausa').checked) pausar();
  render();
}

function pausar() { ui.play = false; clearInterval(ui.timer); ui.timer = null; const b = $('#btn-play'); if (b) b.textContent = 'Reproducir'; }
function reproducir() {
  if (ui.play) return pausar();
  ui.play = true; $('#btn-play').textContent = 'Pausar';
  ui.timer = setInterval(() => {
    if ($('#dlg-confirmar').open || $('#dlg-registro').open) return;
    if (ui.estado.minuto >= ui.estado.esc.duracion_min + 60) return pausar();
    paso(1);
  }, 900);
}

// ---------- render general ----------
function render() {
  renderBarra();
  renderUrgencias();
  document.querySelectorAll('.vista').forEach((v) => { v.hidden = v.id !== 'v-' + ui.vista; });
  document.querySelectorAll('.nav button').forEach((b) => b.setAttribute('aria-current', b.dataset.vista === ui.vista ? 'page' : 'false'));
  if (ui.vista === 'despacho') { renderCola(); renderPanel(); renderMapa(); }
  if (ui.vista === 'moviles') renderMoviles();
  if (ui.vista === 'tripulacion') renderTripulacion();
  if (ui.vista === 'tablero') renderTablero();
  if (ui.vista === 'escenarios') renderEscenarios();
}

function renderBarra() {
  const e = ui.estado;
  $('#reloj-hora').textContent = hora(e.minuto);
  $('#reloj-dia').textContent = dia(e.minuto);
  $('#reloj-min').textContent = `minuto ${e.minuto} de ${e.esc.duracion_min}`;
  $('#reloj-trafico').textContent = `Tráfico ×${M.factor(ctx, e.esc, e.minuto).toLocaleString('es-CO')}`;
}

// ---------- reglas de tiempo ----------
function reglaEspera(transc, obj) {
  const max = obj * 1.5;
  const p = Math.min(1, transc / max) * 100;
  const cls = transc > obj ? 'vencido' : transc >= obj * 0.75 ? 'cerca' : '';
  return `<div class="regla" aria-hidden="true"><div class="lleno ${cls}" style="width:${p}%"></div><div class="obj" style="left:${(100 / 1.5).toFixed(2)}%"></div></div>`;
}
function reglaRango(bajo, alto, est, obj, sel) {
  const max = Math.max(obj * 1.5, alto * 1.05);
  const a = (bajo / max) * 100, b = (alto / max) * 100, c = (est / max) * 100;
  return `<div class="regla" aria-hidden="true"><div class="rango ${sel ? 'sel' : ''}" style="left:${a}%;width:${Math.max(1.5, b - a)}%"></div><div class="punto" style="left:calc(${c}% - 1px)"></div><div class="obj" style="left:${(obj / max) * 100}%"></div></div>`;
}
function tiempoDesde(s) { return ui.estado.minuto - (s.necesitaAmb ? s.reclasMin : s.minLlegada); }

// ---------- cola ----------
function filaCola(s) {
  const m = ui.estado.minuto;
  if (!M.completa(s)) {
    const sinClas = !s.clas || !C[s.clas];
    return `<li><button class="fila-cola incompleta" data-sol="${s.id}" aria-pressed="${s.id === ui.sel}">
      ${sinClas ? '<span class="chip sin">?</span>' : `<span class="chip c${s.clas}">${s.clas}</span>`}
      <span><span class="t">${sinClas ? 'Sin clasificación' : 'Falta verificar la zona'}</span><span class="s">${esc(corto(s.id))}, hace ${m - s.minLlegada} min${s.motivo ? ', ' + esc(s.motivo) : ''}</span></span>
      <span class="regla-wrap"><span class="aviso-limite vencido">${ICONO_ALERTA} ${sinClas ? 'Devolver a triaje' : 'Verificar la zona para recomendar'}</span></span></button></li>`;
  }
  const obj = C[s.clas].obj, t = m - s.minCola, tTot = tiempoDesde(s);
  let av = '';
  if (esUrgente(s) && t >= 2) av = `<span class="aviso-limite vencido">${ICONO_ALERTA} Lleva ${t} min sin asignar (R02 pide 2)</span>`;
  else if (esUrgente(s)) av = `<span class="aviso-limite">${ICONO_ALERTA} Asignar de inmediato (R02)</span>`;
  else if (tTot > obj) av = `<span class="aviso-limite vencido">${ICONO_ALERTA} Superó el objetivo de ${obj} min</span>`;
  else if (tTot >= obj * 0.75) av = `<span class="aviso-limite">${ICONO_ALERTA} Cerca del límite</span>`;
  const extra = s.necesitaAmb ? 'Necesita ambulancia tras reclasificación' : s.corregida ? 'Asignación corregida, elegir otra móvil' : s.desviada ? 'Volvió a la cola por un desvío' : esc(s.motivo || 'Sin motivo registrado');
  return `<li><button class="fila-cola" data-sol="${s.id}" aria-pressed="${s.id === ui.sel}">
    <span class="chip c${s.clas}" aria-label="Clasificación ${s.clas}, ${C[s.clas].color}">${s.clas}</span>
    <span><span class="t">${esc(zn(s.zona))}</span><span class="s">${extra}</span></span>
    <span class="regla-wrap">${reglaEspera(tTot, obj)}<span class="regla-lbl"><span>${tTot} de ${obj} min</span><span>${esc(corto(s.id))}</span></span>${av ? `<div style="margin-top:5px">${av}</div>` : ''}</span>
  </button></li>`;
}

function renderCola() {
  const e = ui.estado, m = e.minuto;
  const inc = M.porCompletar(e), cola = M.cola(e);
  $('#cola-n').textContent = cola.length + inc.length ? `${cola.length + inc.length} en espera` : '';
  let html = '';
  if (inc.length) html += `<li class="sub-cola">Por completar (${inc.length})</li>` + inc.map(filaCola).join('');
  if (cola.length) html += (inc.length ? `<li class="sub-cola">Listas para asignar (${cola.length})</li>` : '') + cola.map(filaCola).join('');
  if (!html) html = `<li class="vacio">No hay solicitudes en espera. Avance el reloj o registre una solicitud.</li>`;
  $('#cola').innerHTML = html;
  const curso = Object.values(e.solicitudes).filter((s) => s.estado === 'asignada' || s.estado === 'en_atencion');
  $('#en-curso').innerHTML = curso.length ? `<div class="subtitulo">En curso (${curso.length})</div><ul class="curso">${curso.map((s) => {
    const mvs = Object.values(e.moviles).filter((x) => x.servicio === s.id || (x.siguiente && x.siguiente.sol === s.id));
    const desc = mvs.map((x) => {
      if (x.siguiente && x.siguiente.sol === s.id) return `${x.id} preasignada`;
      if (x.estado === 'EN_RUTA') return `${x.id} llega en ${Math.max(0, x.llegaEn - m)} min`;
      if (x.estado === 'EN_TRASLADO') return `${x.id} en traslado`;
      return `${x.id} en atención`;
    }).join(', ');
    const puede = M.puedeCorregir(e, s.id);
    return `<li><span class="chip c${s.clas}">${s.clas}</span><span><b>${esc(zn(s.zona))}</b> <span class="d">${esc(corto(s.id))}</span><br><span class="d">${esc(desc || 'Cerrando')}</span>${puede ? `<br><button class="enlace" data-corregir="${s.id}">Corregir asignación</button>` : ''}</span></li>`;
  }).join('')}</ul>` : '';
}

// ---------- bloque de decisión (panel y ventana de urgencias) ----------
function textoPerdida(op) {
  const nd = op.cobertura.nuevasDescubiertas;
  if (op.tipo === 'preasignacion') return { cls: 'ok', t: 'Sin cambios ahora; queda reservada al liberarse' };
  if (!M.esAmbulancia(op.movil.tipo) && op.tipo !== 'estabilizacion') return { cls: 'ok', t: 'Sin cambios: no es ambulancia' };
  if (!nd.length) {
    const p = op.cobertura.maxPerdidos;
    return { cls: 'ok', t: p >= 1 ? `Ninguna zona ALTA pasa de 20 min (la más afectada pierde ${r0(p)} min)` : 'Sin cambios en la cobertura' };
  }
  const z = nd[0];
  return { cls: 'mal', t: `${zn(z.zona)} pasa de ${r0(z.antes)} a ${r0(z.min)} min` + (nd.length > 1 ? ` y ${nd.length - 1} zona${nd.length > 2 ? 's' : ''} más pasa${nd.length > 2 ? 'n' : ''} de 20` : '') };
}
function textoPlanB(op, sol) {
  if (!op.planB) return 'Sin ambulancia libre';
  const pre = op.movil.tipo === 'VMD' || op.tipo === 'estabilizacion' ? (sol.clas === '01' ? 'Siguiente ambulancia' : 'Si escala a 01') : 'Siguiente ambulancia';
  return `${pre}: ${op.planB.movil} a ${r0(op.planB.min)} min`;
}
function etiquetaOp(op) {
  const cls = op.etiqueta.startsWith('Recomendada') ? 'rec' : /no recomendada/i.test(op.etiqueta) ? 'no' : 'alt';
  return `<span class="etiqueta-op ${cls}">${esc(op.etiqueta)}</span>`;
}
function subMovil(op) {
  const mv = ui.estado.moviles[op.movil.id];
  if (op.tipo === 'estabilizacion') return `VMD primer respondiente${op.ambulancia ? ` + ${op.ambulancia.id} preasignada` : ''}${op.desvioDe ? ', desvío desde ' + corto(op.desvioDe.id) : ''}`;
  if (op.tipo === 'preasignacion') return `${NOMBRE_TIPO[op.movil.tipo]}, ocupada: se libera en ~${r0(op.espera)} min`;
  if (op.tipo === 'desvio') return `${NOMBRE_TIPO[op.movil.tipo]}, desvío desde ${corto(op.desvioDe.id)} (${op.desvioDe.clas})`;
  return `${NOMBRE_TIPO[op.movil.tipo]}, ${mv.estado === 'RETORNANDO' ? 'regresando por ' + zn(mv.zona) : 'en ' + mv.baseNombre}`;
}
function quienes(op) { return op.tipo === 'estabilizacion' ? op.moviles.map((x) => x.id).join(' + ') : op.movil.id; }

function htmlOpcion(op, i, obj, sol, sel) {
  const pr = textoPerdida(op);
  const ll = op.llegada;
  const amb = op.tipo === 'estabilizacion' && op.ambulancia ? `<small>Ambulancia en ${op.ambulancia.bajo}–${op.ambulancia.alto} min</small>` : '';
  return `<div class="op ${sel ? 'sel' : ''}" data-op="${i}" role="radio" aria-checked="${sel}" tabindex="0">
    <span class="op-radio" aria-hidden="true"></span>
    <div class="op-mv"><div class="op-id"><b>${op.movil.id}</b><span>${op.movil.tipo}</span>${etiquetaOp(op)}</div><small>${esc(subMovil(op))}</small></div>
    <div class="op-lleg"><b>${ll.bajo}–${ll.alto} min</b>${amb}${reglaRango(ll.bajo, ll.alto, ll.minutos, obj, sel)}</div>
    <div class="op-costo"><b>${pesos(op.costo)}</b><small>${r1(op.km)} km</small></div>
    <div class="op-perdida ${pr.cls}"><span class="k">Qué se pierde</span>${pr.cls === 'mal' ? ICONO_ALERTA : ''}<span>${esc(pr.t)}</span></div>
    <div class="op-planb"><span class="k">Plan B</span>${esc(textoPlanB(op, sol))}</div>
  </div>`;
}

function htmlCompletar(sol, enModal) {
  const sinClas = !sol.clas || !C[sol.clas];
  if (sinClas) {
    return `<div class="completar"><div class="alerta-caja">${ICONO_ALERTA}<div><b>Llegó sin clasificación.</b> Este sistema no clasifica: la clasificación la hace el paramédico de triaje con la escala Manchester. Mientras no tenga código, no entra a la cola ni recibe recomendaciones.</div></div>
      <div class="acciones"><button class="btn primario" data-devolver="${sol.id}">Devolver a triaje</button><span class="nota">Queda registrada como devuelta.</span></div></div>`;
  }
  const opciones = D.zonas.slice().sort((a, b) => a.n.localeCompare(b.n, 'es')).map((z) => `<option value="${z.id}">${esc(z.n)} (${esc(z.mu)})</option>`).join('');
  return `<div class="completar"><div class="alerta-caja">${ICONO_ALERTA}<div><b>Falta verificar la zona.</b> Sin zona no se puede calcular quién llega antes. Confírmela con quien llamó (barrio, comuna o municipio) y elíjala de la lista. No se captura la dirección exacta.</div></div>
    <div class="motivo-cambio" style="padding:0 18px"><label for="sel-zona-${enModal ? 'm' : 'p'}">Zona del paciente</label>
    <select id="sel-zona-${enModal ? 'm' : 'p'}" class="sel-zona"><option value="">Elija la zona</option>${opciones}</select>
    <button class="btn primario" data-completar-zona="${sol.id}">Confirmar zona</button></div></div>`;
}

function htmlDecision(sol, rec, enModal) {
  const obj = C[sol.clas].obj;
  if (!rec.opciones.length) {
    const prim = rec.primerasEnLiberarse || [];
    return `<div class="sin-unidades"><div class="alerta-caja">${ICONO_ALERTA}<div><b>No hay móviles que puedan atender ahora ni liberarse en menos de 45 min.</b> La solicitud sigue en la cola con su alerta de tiempo. Puede preasignar la primera que se libere o esperar.</div></div>
      ${prim.length ? `<div class="opciones" role="list">${prim.map((op, i) => `<div class="op" role="listitem"><span></span>
        <div class="op-mv"><div class="op-id"><b>${op.movil.id}</b><span>${op.movil.tipo}</span></div><small>${esc(subMovil(op))}</small></div>
        <div class="op-lleg"><b>${op.llegada.bajo}–${op.llegada.alto} min</b>${reglaRango(op.llegada.bajo, op.llegada.alto, op.llegada.minutos, obj, false)}</div>
        <div class="op-costo"><button class="btn" data-preasignar="${i}">Preasignar</button></div></div>`).join('')}</div>` : '<p class="vacio">Ninguna móvil compatible se va a liberar. Revise el control de móviles o pida apoyo al coordinador.</p>'}
      <details class="excluidas" style="margin:10px 18px"><summary>Por qué no aparece cada móvil (${rec.excluidas.length})</summary><ul>${rec.excluidas.map((x) => `<li><b>${x.movil.id}</b> ${x.movil.tipo}: ${esc(x.motivo)}</li>`).join('')}</ul></details>
      ${enModal ? '<div class="acciones"><button class="btn js-minimizar">Esperar y atender desde el panel</button><span class="nota">La alerta sigue visible en la franja roja.</span></div>' : ''}</div>`;
  }
  const ops = rec.opciones;
  if (ui.opSel >= ops.length) ui.opSel = 0;
  const op = ops[ui.opSel];
  const comp = M.competencia(ctx, ui.estado, sol.id, op);
  const compTxt = comp.length ? `<div class="alerta-caja competencia">${ICONO_ALERTA}<div><b>${esc(quienes(op))} también es la primera opción de ${comp.map((c) => `${corto(c.sol.id)} (${c.sol.clas}, ${esc(zn(c.sol.zona))})`).join(' y ')}.</b> ${comp.map((c) => c.alternativa ? `Si la asigna aquí, ${corto(c.sol.id)} pasa a ${esc(quienes(c.alternativa))} a ${r0(c.alternativa.llegada.minutos)} min (hoy ${r0(c.top.llegada.minutos)}).` : `${corto(c.sol.id)} se quedaría sin otra opción.`).join(' ')}</div></div>` : '';
  const reglas = op.reglas.map((r) => `<span class="regla-chip" data-tip="${esc(REGLAS_TXT[r] || r)}">${r}</span>`).join('');
  const apoyo = op.apoyo ? `<label class="apoyo"><input type="checkbox" class="chk-apoyo" ${ui.apoyo ? 'checked' : ''}> Enviar también ${op.apoyo.id} (VMD) como apoyo médico, llega en ~${r0(op.apoyo.min)} min (D07)</label>` : '';
  const sinMotivo = !sol.motivo ? `<p class="modelo-nota">Llegó sin motivo de consulta: la recomendación usa solo el código ${sol.clas}${sol.clas === '07' ? ' y no puede marcar un posible traslado' : ''}.</p>` : '';
  return `
    <div class="opciones-cab" aria-hidden="true"><span></span><span>Móvil</span><span>Llega en</span><span>Costo estimado</span></div>
    <div class="opciones" role="radiogroup" aria-label="Las tres mejores opciones">${ops.map((o, i) => htmlOpcion(o, i, obj, sol, i === ui.opSel)).join('')}</div>
    <p class="por-que">${esc(op.explicacion)}</p>
    ${compTxt}
    <div class="reglas-chips">${reglas}</div>
    ${apoyo}${sinMotivo}
    <p class="modelo-nota">Llegada: ${esc(op.llegada.modelo)}. La línea vertical de cada barra es el objetivo de ${obj} min.</p>
    <div class="acciones">
      <button class="btn primario js-confirmar">Confirmar ${esc(quienes(op))}</button>
      <button class="btn js-cambiar" aria-expanded="${ui.cambiar}">${ui.cambiar ? 'Cerrar cambio' : 'Cambiar'}</button>
      ${enModal ? '<button class="btn js-minimizar">Atender desde el panel</button>' : ''}
      <span class="nota">${ui.opSel === 0 ? 'Opción recomendada por el motor.' : 'Eligió una alternativa: se registrará como cambio.'}</span>
    </div>
    ${ui.cambiar ? htmlCambiar(rec, sol) : ''}`;
}

function htmlCambiar(rec, sol) {
  const lista = rec.todas.map((op, i) => {
    const pr = textoPerdida(op);
    return `<label><input type="radio" name="cambio" value="${i}" ${ui.cambioSel === i ? 'checked' : ''}>
      <span><b>${op.movil.id}</b> ${op.movil.tipo}${op.tipo === 'estabilizacion' ? ' + amb.' : ''}</span>
      <span>${esc(pr.t)}<br><small style="color:var(--muted)">${esc(op.tipo === 'preasignacion' ? 'Ocupada, se libera en ~' + r0(op.espera) + ' min' : op.tipo === 'desvio' ? 'Desvío R06' : op.comp === 'NOREC' ? 'No recomendada para un ' + sol.clas : '')}</small></span>
      <span style="text-align:right"><b>${op.llegada.bajo}–${op.llegada.alto}</b> min<br><small style="color:var(--muted)">${pesos(op.costo)}</small></span>
    </label>`;
  }).join('');
  const excl = rec.excluidas.map((x) => `<li><b>${x.movil.id}</b> ${x.movil.tipo}: ${esc(x.motivo)}</li>`).join('');
  return `<div class="cambiar">
    <h3>Elegir otra móvil</h3>
    <div class="lista-cambio" role="radiogroup" aria-label="Móviles elegibles">${lista}</div>
    <details class="excluidas"><summary>Móviles que no se pueden asignar (${rec.excluidas.length})</summary><ul>${excl}</ul></details>
    <div class="motivo-cambio">
      <label>Motivo del cambio <select class="sel-motivo"><option value="">Elija un motivo de la lista</option>${MOTIVOS_CAMBIO.map((t) => `<option ${ui.motivo === t ? 'selected' : ''}>${t}</option>`).join('')}</select></label>
      <button class="btn primario js-confirmar-cambio" ${ui.cambioSel == null || !ui.motivo ? 'disabled' : ''}>Revisar y confirmar</button>
    </div>
  </div>`;
}

function htmlCabecera(sol, enModal, total, idx) {
  const completa = M.completa(sol);
  const obj = completa ? C[sol.clas].obj : null;
  const tTot = completa ? tiempoDesde(sol) : ui.estado.minuto - sol.minLlegada;
  const etq = [];
  if (completa && M.posibleTraslado(sol)) etq.push('<span class="etq">Posible traslado</span>');
  if (sol.variosPacientes) etq.push('<span class="etq fuerte">Varios pacientes en el mismo punto</span>');
  sol.historial.forEach((h) => etq.push(`<span class="etq fuerte">Reclasificada ${h.origen.toLowerCase()}: ${h.de} a ${h.a}, ${hora(h.min)}</span>`));
  if (sol.desviada) etq.push('<span class="etq">Volvió a la cola por un desvío (R06)</span>');
  if (sol.corregida) etq.push('<span class="etq">Asignación corregida</span>');
  if (sol.manual) etq.push(`<span class="etq">Registrada a mano${sol.canal ? ', canal ' + esc(sol.canal.toLowerCase()) : ''}</span>`);
  const chip = sol.clas && C[sol.clas] ? `<span class="chip grande c${sol.clas}" aria-label="Clasificación ${sol.clas}">${sol.clas}</span>` : '<span class="chip grande sin">?</span>';
  const titulo = completa ? `${C[sol.clas].nombre} en ${esc(zn(sol.zona))}` : (sol.clas && C[sol.clas] ? `${C[sol.clas].nombre} sin zona verificada` : 'Solicitud sin clasificar');
  return `<div class="sol-cab">
    ${chip}
    <div>
      ${enModal ? `<div class="urg-cuenta">${total > 1 ? `Urgencia ${idx} de ${total} sin asignar` : 'Urgencia sin asignar'}</div>` : ''}
      <h1>${titulo}</h1>
      <div class="motivo">${sol.motivo ? esc(sol.motivo) + ': ' + esc(sol.discriminador || 'sin discriminador') + '.' : 'Sin motivo registrado.'}${sol.clas && C[sol.clas] ? ` Manchester ${C[sol.clas].color.toLowerCase()}${sol.municipio ? ', ' + esc(sol.municipio) : ''}.` : ''}</div>
      <div class="etiquetas">${etq.join('')}</div>
    </div>
    <div class="reloj-sol"><b>${tTot} min</b><span>desde la ${sol.necesitaAmb ? 'reclasificación' : 'solicitud'}${obj ? ', objetivo ' + obj : ''}</span></div>
  </div>`;
}

function htmlAlertaSol(sol) {
  const e = ui.estado, m = e.minuto;
  if (sol.necesitaAmb) {
    const vmd = Object.values(e.moviles).find((x) => x.servicio === sol.id && x.tipo === 'VMD');
    return `<div class="alerta-caja">${ICONO_ALERTA}<div><b>El caso escaló en el sitio: ${esc((sol.detalleReclas || '').replace(/^./, (c) => c.toLowerCase()))}.</b> ${vmd ? `${vmd.id} acompaña al paciente.` : ''} Se recalcularon las opciones solo con ambulancias; el tiempo se mide desde la reclasificación (${hora(sol.reclasMin)}).</div></div>`;
  }
  const yaVan = Object.values(e.moviles).filter((x) => x.servicio === sol.id);
  if (yaVan.length) {
    const txt = yaVan.map((x) => `${x.id} (${x.tipo}, ${x.estado === 'EN_RUTA' ? 'llega en ' + Math.max(0, x.llegaEn - m) + ' min' : 'en el sitio'})`).join(' y ');
    return `<div class="alerta-caja">${ICONO_ALERTA}<div><b>Ya hay quien atienda mientras tanto:</b> ${txt} como primer respondiente. Falta asignar la ambulancia.${m - sol.minCola >= 2 ? ` Lleva ${m - sol.minCola} min en cola.` : ''}</div></div>`;
  }
  if (M.completa(sol) && esUrgente(sol) && m - sol.minCola >= 2) return `<div class="alerta-caja">${ICONO_ALERTA}<div>Este ${sol.clas} lleva ${m - sol.minCola} min en cola. R02 pide asignarlo en máximo 2 min.</div></div>`;
  return '';
}

function renderPanel() {
  const e = ui.estado, box = $('#panel-sol');
  const sol = ui.sel ? e.solicitudes[ui.sel] : null;
  if (!sol) {
    const proxima = e.llegadasPend.filter((r) => r.minuto_llegada > e.minuto).sort((a, b) => a.minuto_llegada - b.minuto_llegada)[0];
    box.innerHTML = `<div class="sol-cab"><div></div><div><h1>Sin solicitudes por asignar</h1><div class="motivo">${proxima ? `La siguiente solicitud del escenario entra a las ${hora(proxima.minuto_llegada)}. Use +1 min o Reproducir.` : 'El escenario ya no trae más solicitudes. Revise el tablero, registre una solicitud o cargue otro escenario.'}</div></div></div>`;
    ui.rec = null;
    return;
  }
  if ($('#dlg-urgencia').open && ui.urgId === sol.id) {
    box.innerHTML = `${htmlCabecera(sol, false)}<div class="vacio">Esta urgencia se está atendiendo en la ventana central.</div>`;
    return;
  }
  if (!M.completa(sol)) { box.innerHTML = htmlCabecera(sol, false) + htmlCompletar(sol, false); ui.rec = null; return; }
  ui.rec = M.recomendar(ctx, e, sol.id);
  box.innerHTML = htmlCabecera(sol, false) + htmlAlertaSol(sol) + htmlDecision(sol, ui.rec, false);
}

// ---------- ventana central de urgencias ----------
function renderUrgencias() {
  const dlg = $('#dlg-urgencia');
  const lista = urgencias();
  const banner = $('#banner-urg');
  if (!lista.length) {
    if (dlg.open) dlg.close();
    ui.urgId = null; ui.urgMin = false; banner.hidden = true;
    return;
  }
  if (ui.urgMin) {
    if (dlg.open) dlg.close();
    banner.hidden = false;
    banner.innerHTML = `${ICONO_ALERTA}<span><b>${lista.length} urgencia${lista.length > 1 ? 's' : ''} sin asignar</b> (${lista.map((s) => `${s.clas} ${esc(zn(s.zona))}`).join(', ')})</span><button class="btn" data-abrir-urg>Atender ahora</button>`;
    return;
  }
  banner.hidden = true;
  if (!ui.urgId || !lista.find((s) => s.id === ui.urgId)) { ui.urgId = lista[0].id; ui.sel = ui.urgId; resetDecision(); }
  if (ui.sel !== ui.urgId) { ui.sel = ui.urgId; resetDecision(); }
  const sol = ui.estado.solicitudes[ui.urgId];
  const idx = 1;
  let cuerpo;
  if (!M.completa(sol)) { cuerpo = htmlCompletar(sol, true); ui.rec = null; }
  else { ui.rec = M.recomendar(ctx, ui.estado, sol.id); cuerpo = htmlAlertaSol(sol) + htmlDecision(sol, ui.rec, true); }
  const otras = lista.filter((s) => s.id !== sol.id);
  const scroll = dlg.querySelector('.dlg-urg') ? dlg.querySelector('.dlg-urg').scrollTop : 0;
  dlg.className = 'dlg-urgencia c' + (sol.clas || 'x');
  const ult = ui.ultima && ui.ultima.sol !== sol.id && ui.estado.solicitudes[ui.ultima.sol].estado === 'asignada' && M.puedeCorregir(ui.estado, ui.ultima.sol) ? `<div class="urg-ultima">Acaba de asignar ${esc(ui.ultima.texto)}. <button class="enlace" data-corregir="${ui.ultima.sol}">Corregir esa asignación</button></div>` : '';
  const espera = otras.length ? `<div class="urg-espera"><b>Después de esta:</b> ${otras.map((s) => `<span class="chip c${s.clas || 'x'}">${s.clas || '?'}</span> ${esc(s.zona ? zn(s.zona) : 'zona sin verificar')}, ${ui.estado.minuto - s.minLlegada} min`).join('; ')}</div>` : '';
  dlg.innerHTML = `<div class="dlg-urg">${ult}${htmlCabecera(sol, true, lista.length, idx)}${espera}${cuerpo}</div>`;
  if (!dlg.open) { dlg.showModal(); const b = dlg.querySelector('.js-confirmar'); if (b) b.focus(); }
  dlg.querySelector('.dlg-urg').scrollTop = scroll;
}

// ---------- confirmación en dos pasos ----------
function abrirConfirmacion(op, motivo) {
  const sol = ui.estado.solicitudes[ui.sel];
  pausar();
  const apoyo = op.apoyo && ui.apoyo ? op.apoyo.id : null;
  ui.pendiente = { solId: sol.id, op, motivo, apoyo };
  const pr = op.cobertura ? textoPerdida(op) : { cls: 'ok', t: 'Sin cambios ahora' };
  const obj = C[sol.clas].obj;
  const ll = op.llegada;
  $('#dlg-confirmar').innerHTML = `<div class="dlg">
    <h2>¿Asignar ${esc(quienes(op))}${apoyo ? ' + ' + apoyo : ''}?</h2>
    <dl class="resumen">
      <dt>Solicitud</dt><dd><span class="chip c${sol.clas}">${sol.clas}</span> ${C[sol.clas].nombre} en ${esc(zn(sol.zona))} (${esc(corto(sol.id))})</dd>
      <dt>Móvil</dt><dd>${esc(quienes(op))}: ${esc(subMovil(op))}</dd>
      <dt>Llegada</dt><dd><b>${ll.bajo}–${ll.alto} min</b> frente a un objetivo de ${obj} min${ll.alto > obj ? ' (puede superar el objetivo)' : ''}</dd>
      <dt>Qué se pierde</dt><dd class="${pr.cls === 'mal' ? 'mal' : ''}">${esc(pr.t)}</dd>
      ${motivo ? `<dt>${ui.rec && ui.rec.opciones.length ? 'Cambio frente a la recomendada' : 'Motivo'}</dt><dd>${esc(motivo)}</dd>` : ''}
    </dl>
    <p class="nota-dlg">La tripulación verá el servicio en su panel apenas confirme. Mientras la móvil vaya en ruta, podrá corregir la asignación desde "En curso".</p>
    <div class="dlg-acciones"><button class="btn" id="btn-volver">Volver</button><button class="btn primario" id="btn-si-asignar">Sí, asignar ${esc(quienes(op))}</button></div>
  </div>`;
  $('#dlg-confirmar').showModal();
  $('#btn-si-asignar').focus();
}

function confirmarPendiente() {
  const p = ui.pendiente; if (!p) return;
  const e = ui.estado, sol = e.solicitudes[p.solId];
  const recomendada = ui.rec && ui.rec.opciones[0] ? ui.rec.opciones[0].movil.id : null;
  try {
    M.asignar(ctx, e, sol.id, p.op, { recomendada, motivo: p.motivo, apoyo: p.apoyo });
  } catch (err) { $('#dlg-confirmar').close(); aviso('No se pudo asignar: ' + err.message, true); render(); return; }
  $('#dlg-confirmar').close();
  aviso(`${corto(sol.id)} asignada a ${quienes(p.op)}${p.apoyo ? ' + ' + p.apoyo : ''}.`, false, { sol: sol.id, texto: 'Corregir' });
  ui.ultima = { sol: sol.id, texto: `${corto(sol.id)} a ${quienes(p.op)}${p.apoyo ? ' + ' + p.apoyo : ''}` };
  ui.pendiente = null; ui.sel = null; ui.urgId = null; ui.politicas = null;
  resetDecision();
  autoSeleccion();
  render();
}

function corregir(solId) {
  const e = ui.estado;
  const lib = M.corregirAsignacion(ctx, e, solId);
  if (!lib) { aviso('Ya no se puede corregir: la móvil llegó al sitio.', true); render(); return; }
  aviso(`${corto(solId)}: ${lib.join(' y ')} queda libre. Elija otra móvil.`, true);
  ui.sel = solId; resetDecision(); ui.motivo = 'Corrección de una asignación'; ui.urgMin = false; ui.politicas = null; ui.ultima = null;
  if (esUrgente(e.solicitudes[solId])) ui.urgId = solId;
  if (ui.vista !== 'despacho' && !esUrgente(e.solicitudes[solId])) ui.vista = 'despacho';
  render();
}

// ---------- mapa ----------
const MAPA = D.mapa;
const zonaXY = {}; D.zonas.forEach((z) => { zonaXY[z.id] = z; });
function bucket(min) { return min <= 10 ? 'c1' : min <= 15 ? 'c2' : min <= 20 ? 'c3' : 'c4'; }
const AFUERA = ['Z-GIR-01', 'Z-COP-01', 'Z-CAL-01'];
function vistaMapa(sol) {
  if (ui.mapa.vb) return ui.mapa.vb;
  if (ui.zoom === 'urbana' && !(sol && AFUERA.includes(sol.zona))) return [22, 88, 286, 470];
  if (ui.zoom === 'sol' && sol && sol.zona) { const z = zonaXY[sol.zona]; return [z.x - 95, z.y - 120, 190, 240]; }
  return [0, 0, MAPA.w, MAPA.h];
}
function etiquetasComuna() {
  const g = {};
  D.zonas.forEach((z) => { (g[z.co] = g[z.co] || []).push(z); });
  return Object.entries(g).map(([n, zs]) => ({ n, x: zs.reduce((a, z) => a + z.x, 0) / zs.length, y: zs.reduce((a, z) => a + z.y, 0) / zs.length }));
}
const LBL_COMUNA = etiquetasComuna();
function categoriaMovil(mv) {
  if (!mv.apta) return 'noapta';
  if (M.disponibleAhora(mv)) return 'disp';
  return 'serv';
}
function posDibujo(mv, m) {
  if (mv.estado === 'EN_RUTA') {
    const a = zonaXY[mv.origen], b = zonaXY[mv.zona];
    const f = Math.max(0, Math.min(1, (m - mv.salida) / Math.max(1, mv.llegaEn - mv.salida)));
    return { x: a.x + (b.x - a.x) * f, y: a.y + (b.y - a.y) * f, zona: f < 0.5 ? mv.origen : mv.zona };
  }
  const z = zonaXY[mv.zona];
  return { x: z.x, y: z.y, zona: mv.zona };
}

function renderMapa() {
  const e = ui.estado, m = e.minuto, sol = ui.sel ? e.solicitudes[ui.sel] : null;
  const F = ui.mapa.filtros;
  const vb = vistaMapa(sol);
  const u = vb[2] / 400;
  const cov = e.coberturaActual || M.coberturaZonas(ctx, e, null);
  const covMap = {}; cov.forEach((c) => { covMap[c.zona] = c; });
  let prev = null;
  if (ui.rec && sol && M.completa(sol)) prev = ui.preview != null && ui.rec.opciones[ui.preview] ? ui.rec.opciones[ui.preview] : ui.rec.opciones[ui.opSel] || null;
  const despues = {};
  if (prev) prev.cobertura.despues.forEach((c) => { despues[c.zona] = c; });

  const zonas = D.zonas.map((z) => {
    const alta = z.d === 'A';
    let cls = 'zona ' + (alta ? 'alta ' : 'baja ');
    let min = alta ? covMap[z.id].min : null, cambio = false;
    if (alta && prev && despues[z.id]) {
      const d = despues[z.id].min;
      if (Math.abs(d - min) >= 1) cambio = bucket(d) !== bucket(min) || d > 20;
      min = d;
    }
    if (alta) cls += bucket(min) + (cambio ? ' cambio' : '');
    const t = alta ? `${esc(z.n)}: demanda ALTA. Ambulancia libre más cercana a ${r0(min)} min` : `${esc(z.n)}: demanda ${z.d === 'M' ? 'media' : 'baja'}`;
    return `<path class="${cls}" d="${z.p}" data-tip="${t}"/>`;
  }).join('');
  const lblCambios = prev ? D.zonas.filter((z) => z.d === 'A' && despues[z.id] && despues[z.id].min > 20 && covMap[z.id].min <= 20)
    .map((z) => `<text class="lbl-cambio" x="${z.x}" y="${z.y + 4 * u}" font-size="${11 * u}" style="stroke-width:${3 * u}px" text-anchor="middle">${r0(despues[z.id].min)}</text>`).join('') : '';
  const lbls = LBL_COMUNA.map((l) => `<text class="lbl-comuna" x="${l.x.toFixed(1)}" y="${(l.y + 18 * u).toFixed(1)}" font-size="${10 * u}" text-anchor="middle">${esc(l.n)}</text>`).join('');
  const bases = D.bases.map((b) => { const z = zonaXY[b.id_zona]; const k = 13 * u; return `<rect x="${z.x - k / 2}" y="${z.y - k / 2}" width="${k}" height="${k}" fill="none" stroke="#17202a" stroke-width="${1.2 * u}" data-tip="${esc(b.nombre_base)}"/>`; }).join('');
  const centros = D.centros.map((c) => { const z = zonaXY[c.zona]; const a = 3 * u, x0 = z.x + 7 * u, y0 = z.y - 13 * u; return `<path d="M${x0} ${y0}h${a}v${-a}h${a}v${a}h${a}v${a}h${-a}v${a}h${-a}v${-a}h${-a}z" fill="#fff" stroke="#17202a" stroke-width="${0.9 * u}" data-tip="${esc(c.nombre)} (centro de atención ficticio)"/>`; }).join('');

  const porZona = {};
  const mvs = Object.values(e.moviles).map((mv) => {
    const p = posDibujo(mv, m);
    let x = p.x, y = p.y;
    if (mv.estado !== 'EN_RUTA') {
      const k = porZona[mv.zona] = (porZona[mv.zona] || 0) + 1;
      const ang = (k - 2) * 1.25 - 0.4, rad = k === 1 ? 0 : 12.5 * u;
      x += Math.cos(ang) * rad; y += Math.sin(ang) * rad;
    }
    return { mv, x, y, cat: categoriaMovil(mv) };
  });
  const visible = (p) => F[p.cat];
  const enPrev = prev ? prev.moviles.map((x) => x.id) : [];
  let rutas = '';
  if (F.rutas) {
    rutas = mvs.filter((p) => p.mv.estado === 'EN_RUTA' && visible(p)).map((p) => { const z = zonaXY[p.mv.zona]; return `<line x1="${p.x}" y1="${p.y}" x2="${z.x}" y2="${z.y}" stroke="#6e52a8" stroke-width="${1.6 * u}" stroke-linecap="round"/>`; }).join('')
      + mvs.filter((p) => p.mv.siguiente && visible(p)).map((p) => { const s = e.solicitudes[p.mv.siguiente.sol]; if (!s || !s.zona) return ''; const z = zonaXY[s.zona]; return `<line x1="${p.x}" y1="${p.y}" x2="${z.x}" y2="${z.y}" stroke="#66717c" stroke-width="${1.4 * u}" stroke-dasharray="${2 * u} ${3 * u}"/>`; }).join('');
  }
  const lineaPrev = sol && sol.zona && prev ? mvs.filter((p) => enPrev.includes(p.mv.id)).map((p) => { const z = zonaXY[sol.zona]; return `<line x1="${p.x}" y1="${p.y}" x2="${z.x}" y2="${z.y}" stroke="#4b2e83" stroke-width="${2.2 * u}" stroke-dasharray="${5 * u} ${4 * u}"/>`; }).join('') : '';
  const marcas = mvs.filter((p) => visible(p) || enPrev.includes(p.mv.id) || p.mv.id === ui.mapa.movilSel).map((p) => {
    const mv = p.mv;
    let fill = '#17202a', stroke = '#ffffff', txt = '#ffffff';
    if (mv.estado === 'RETORNANDO') { fill = '#ffffff'; stroke = '#17202a'; txt = '#17202a'; }
    if (mv.estado === 'EN_RUTA') fill = '#6e52a8';
    if (mv.estado === 'EN_ATENCION' || mv.estado === 'EN_TRASLADO') fill = '#9aa6b1';
    if (!mv.apta) { fill = '#ffffff'; stroke = '#9aa6b1'; txt = '#9aa6b1'; }
    const r = 7.5 * u;
    const destacado = enPrev.includes(mv.id) || mv.id === ui.mapa.movilSel;
    const t = `<b>${mv.id}</b> ${NOMBRE_TIPO[mv.tipo]}<br>${ESTADO_TXT[mv.estado] || mv.estado}${mv.apta ? '' : ': ' + esc(mv.motivoNoApta)}<br>${esc(zn(M.posicionActual(mv, m)))}<br>Clic para ver la ficha`;
    return `<g class="mk" data-movil="${mv.id}" data-tip="${t}">${destacado ? `<circle cx="${p.x}" cy="${p.y}" r="${r + 4 * u}" fill="none" stroke="#4b2e83" stroke-width="${2.4 * u}"/>` : ''}
      <circle cx="${p.x}" cy="${p.y}" r="${r + 3 * u}" fill="transparent"/>
      <circle cx="${p.x}" cy="${p.y}" r="${r}" fill="${fill}" stroke="${stroke}" stroke-width="${1.6 * u}"/>
      <text x="${p.x}" y="${p.y + 3.6 * u}" text-anchor="middle" font-size="${10 * u}" font-weight="700" fill="${txt}" style="pointer-events:none">${LETRA[mv.tipo]}</text>
      ${vb[2] < 170 ? `<text class="lbl-movil" x="${p.x + r + 2 * u}" y="${p.y + 3.4 * u}" font-size="${9.5 * u}" style="stroke-width:${2.6 * u}px">${mv.id.slice(4)}</text>` : ''}
      ${!mv.apta ? `<line x1="${p.x - r * 0.7}" y1="${p.y + r * 0.7}" x2="${p.x + r * 0.7}" y2="${p.y - r * 0.7}" stroke="#9aa6b1" stroke-width="${1.5 * u}"/>` : ''}</g>`;
  }).join('');
  const pines = !F.sol ? '' : Object.values(e.solicitudes).filter((s) => s.zona && !['cerrada', 'cancelada', 'devuelta'].includes(s.estado)).map((s) => {
    const z = zonaXY[s.zona];
    const selc = s.id === ui.sel;
    const colores = COLOR_CLASE[s.clas] || ['#66717c', '#fff'];
    const w = 26 * u, h = 17 * u, y0 = z.y - 7 * u - h;
    const estadoTxt = s.estado === 'cola' ? 'En cola' : s.estado === 'asignada' ? 'Asignada, móvil en camino' : 'En atención';
    const nom = C[s.clas] ? `${s.clas} ${C[s.clas].nombre}` : 'Sin clasificación';
    return `<g data-tip="<b>${s.id}</b><br>${nom}, ${esc(zn(s.zona))}<br>${esc(s.motivo || 'Sin motivo')}<br>${estadoTxt}" ${s.estado === 'cola' ? `data-sol="${s.id}" style="cursor:pointer"` : ''}>
      ${selc ? `<rect x="${z.x - w / 2 - 3 * u}" y="${y0 - 3 * u}" width="${w + 6 * u}" height="${h + 6 * u}" rx="${5 * u}" fill="#fff" stroke="#4b2e83" stroke-width="${2.4 * u}"/>` : ''}
      <path d="M${z.x} ${z.y} l${-4.5 * u} ${-7.5 * u} h${9 * u} z" fill="${colores[0]}"/>
      <rect x="${z.x - w / 2}" y="${y0}" width="${w}" height="${h}" rx="${3 * u}" fill="${colores[0]}" ${s.estado !== 'cola' ? 'fill-opacity=".5"' : ''}/>
      <text x="${z.x}" y="${y0 + h * 0.72}" text-anchor="middle" font-size="${11 * u}" font-weight="700" fill="${colores[1]}">${C[s.clas] ? s.clas : '?'}</text></g>`;
  }).join('');

  const cuenta = { disp: 0, serv: 0, noapta: 0 };
  mvs.forEach((p) => { cuenta[p.cat] += 1; });
  const nSol = Object.values(e.solicitudes).filter((s) => s.zona && ['cola', 'asignada', 'en_atencion'].includes(s.estado)).length;
  const chips = [['disp', `Disponibles (${cuenta.disp})`], ['serv', `En servicio (${cuenta.serv})`], ['noapta', `No aptas (${cuenta.noapta})`], ['sol', `Solicitudes (${nSol})`], ['rutas', 'Rutas']]
    .map(([k, t]) => `<button class="filtro" data-filtro="${k}" aria-pressed="${F[k]}">${t}</button>`).join('');

  const desc = cov.filter((c) => c.min > 20).sort((a, b) => b.min - a.min);
  const descTxt = desc.length ? `<b>Ahora, ${desc.length} zona${desc.length > 1 ? 's' : ''} ALTA a más de 20 min:</b> ${desc.slice(0, 5).map((c) => `${esc(zn(c.zona))} (${isFinite(c.min) ? r0(c.min) + ' min' : 'sin ambulancia libre'})`).join(', ')}${desc.length > 5 ? ` y ${desc.length - 5} más` : ''}.` : '<b>Ahora, todas las zonas ALTA tienen una ambulancia libre a 20 min o menos.</b>';
  const prevTxt = prev && sol ? (() => {
    const nd = prev.cobertura.nuevasDescubiertas;
    return `<div class="preview-cab">Vista previa si envía ${esc(quienes(prev))}: ${nd.length ? nd.map((z) => `${esc(zn(z.zona))} pasa de ${r0(z.antes)} a ${r0(z.min)} min`).slice(0, 3).join('; ') + '.' : 'ninguna zona ALTA queda a más de 20 min por esta decisión.'}</div>`;
  })() : '';

  $('#mapa-wrap').innerHTML = `<div class="filtros" role="group" aria-label="Qué mostrar en el mapa">${chips}</div>${prevTxt}
    <div class="mapa-caja">
    <svg class="mapa" id="svg-mapa" viewBox="${vb.join(' ')}" role="img" aria-label="Mapa de zonas, móviles y solicitudes del Valle de Aburrá">
      <defs><pattern id="trama" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><rect width="6" height="6" fill="#f6e3dd"/><line x1="0" y1="0" x2="0" y2="6" stroke="#8a1f1f" stroke-width="1.6"/></pattern></defs>
      ${zonas}${lbls}${lblCambios}${bases}${centros}${rutas}${lineaPrev}${marcas}${pines}
    </svg>
    <div class="zoom-ctl"><button data-zoomrel="0.7" aria-label="Acercar">+</button><button data-zoomrel="1.4" aria-label="Alejar">−</button></div>
    <p class="ayuda-mapa">Rueda del mouse para acercar, arrastre para mover. Clic en una móvil para ver su ficha.</p>
    </div>
    ${fichaMovil()}
    <p class="descubiertas">${descTxt}</p>
    <div class="leyenda">
      <div><h4>Zonas de demanda ALTA: minutos a la ambulancia libre más cercana</h4>
        <div class="fila"><span class="sw" style="background:var(--cov1)"></span>10 o menos</div>
        <div class="fila"><span class="sw" style="background:var(--cov2)"></span>De 10 a 15</div>
        <div class="fila"><span class="sw" style="background:var(--cov3)"></span>De 15 a 20</div>
        <div class="fila"><svg width="14" height="12"><rect width="14" height="12" fill="url(#trama)"/></svg>Más de 20 (D03)</div>
        <div class="fila"><span class="sw" style="background:#f1f4f6;border:1px solid var(--rule)"></span>Demanda media o baja</div>
      </div>
      <div><h4>Móviles (M medicalizada, B básica, D domiciliario)</h4>
        <div class="fila"><svg width="14" height="14"><circle cx="7" cy="7" r="6" fill="#17202a"/></svg>Disponible en base</div>
        <div class="fila"><svg width="14" height="14"><circle cx="7" cy="7" r="5.5" fill="#fff" stroke="#17202a" stroke-width="1.5"/></svg>Disponible, regresando</div>
        <div class="fila"><svg width="14" height="14"><circle cx="7" cy="7" r="6" fill="#6e52a8"/></svg>En ruta (línea hacia el paciente)</div>
        <div class="fila"><svg width="14" height="14"><circle cx="7" cy="7" r="6" fill="#9aa6b1"/></svg>En atención o traslado</div>
        <div class="fila"><svg width="14" height="14"><line x1="1" y1="7" x2="13" y2="7" stroke="#66717c" stroke-width="1.5" stroke-dasharray="2 3"/></svg>Preasignada</div>
        <div class="fila"><svg width="14" height="14"><circle cx="7" cy="7" r="5.5" fill="#fff" stroke="#9aa6b1" stroke-width="1.5"/><line x1="3" y1="11" x2="11" y2="3" stroke="#9aa6b1" stroke-width="1.5"/></svg>No apta o fuera de servicio</div>
      </div>
    </div>`;
  document.querySelectorAll('.mapa-herr button[data-zoom]').forEach((b) => b.setAttribute('aria-pressed', !ui.mapa.vb && b.dataset.zoom === ui.zoom));
}

function fichaMovil() {
  const id = ui.mapa.movilSel; if (!id) return '';
  const e = ui.estado, m = e.minuto, mv = e.moviles[id];
  const sol = mv.servicio ? e.solicitudes[mv.servicio] : null;
  const sig = mv.siguiente ? e.solicitudes[mv.siguiente.sol] : null;
  const lib = M.predecirLiberacion(mv, m);
  let servicio = 'Sin servicio asignado';
  if (sol) servicio = `<span class="chip c${sol.clas}">${sol.clas}</span> ${esc(corto(sol.id))} en ${esc(zn(sol.zona))}${mv.estado === 'EN_RUTA' ? `, llega en ${Math.max(0, mv.llegaEn - m)} min` : ''}`;
  else if (sig) servicio = `Preasignada a <span class="chip c${sig.clas}">${sig.clas}</span> ${esc(corto(sig.id))}`;
  const acciones = mv.estado === 'FUERA_SERVICIO' ? '' : !mv.apta
    ? `<button class="btn" data-apta="${mv.id}">Marcar apta</button>`
    : ui.mapa.noApta ? `<span class="no-apta-form"><select class="sel-noapta-mapa" aria-label="Motivo"><option value="">Motivo</option>${MOTIVOS_NO_APTA.map((x) => `<option>${x}</option>`).join('')}</select><button class="btn primario" data-guardar-noapta-mapa="${mv.id}">Guardar</button></span>`
    : `<button class="btn" data-noapta-mapa="${mv.id}">Marcar no apta</button>`;
  return `<div class="ficha" aria-live="polite">
    <div class="ficha-cab"><b>${mv.id}</b> ${NOMBRE_TIPO[mv.tipo]} (${mv.tipo}), ${esc(mv.baseNombre)}<button class="cerrar" data-cerrar-ficha aria-label="Cerrar ficha">×</button></div>
    <dl><dt>Estado</dt><dd>${ESTADO_TXT[mv.estado] || mv.estado}${mv.apta ? '' : ': ' + esc(mv.motivoNoApta)}</dd>
    <dt>Posición</dt><dd>${esc(zn(M.posicionActual(mv, m)))}</dd>
    <dt>Servicio</dt><dd>${servicio}</dd>
    <dt>Libre en</dt><dd>${M.disponibleAhora(mv) ? 'Ahora' : lib ? `${lib.bajo}–${lib.alto} min` : mv.estado === 'EN_RUTA' ? 'Al terminar el servicio' : '–'}</dd>
    <dt>Servicios del turno</dt><dd>${mv.servicios}</dd></dl>
    <div class="ficha-acc">${acciones}<button class="btn" data-ir-trip="${mv.id}">Abrir panel de tripulación</button></div></div>`;
}

// ---------- control de móviles ----------
function glyphMovil(mv) {
  let fill = '#17202a', stroke = '#fff';
  if (mv.estado === 'RETORNANDO') { fill = '#fff'; stroke = '#17202a'; }
  if (mv.estado === 'EN_RUTA') fill = '#6e52a8';
  if (mv.estado === 'EN_ATENCION' || mv.estado === 'EN_TRASLADO') fill = '#9aa6b1';
  if (!mv.apta) { fill = '#fff'; stroke = '#9aa6b1'; }
  return `<svg width="14" height="14" aria-hidden="true"><circle cx="7" cy="7" r="5.5" fill="${fill}" stroke="${stroke}" stroke-width="1.5"/></svg>`;
}
function renderMoviles() {
  const e = ui.estado, m = e.minuto;
  const lista = Object.values(e.moviles);
  const res = ['TAM', 'TAB', 'VMD'].map((t) => {
    const de = lista.filter((x) => x.tipo === t);
    return `<div><b>${de.filter((x) => M.disponibleAhora(x)).length} de ${de.length}</b><span>${NOMBRE_TIPO[t]} (${t}) disponibles ahora</span></div>`;
  }).join('');
  const noAptas = lista.filter((x) => !x.apta).length;
  const filas = ['TAM', 'TAB', 'VMD'].map((t) => `<tr class="grupo"><td colspan="8">${NOMBRE_TIPO[t]} (${t})</td></tr>` + lista.filter((x) => x.tipo === t).map((mv) => {
    const lib = M.predecirLiberacion(mv, m);
    const libre = M.disponibleAhora(mv) ? 'Ahora' : mv.estado === 'EN_RUTA' ? `Llega en ${Math.max(0, mv.llegaEn - m)} min` : lib ? `${lib.bajo}–${lib.alto} min` : mv.siguiente ? 'Preasignada' : '–';
    const sol = mv.servicio ? e.solicitudes[mv.servicio] : null;
    const servicio = sol ? `<span class="chip c${sol.clas}">${sol.clas}</span> ${corto(sol.id)}` : mv.siguiente ? `Preasignada a ${corto(mv.siguiente.sol)}` : (mv.nota && mv.servicios === 0 && (mv.estado === 'EN_ATENCION' || mv.estado === 'EN_TRASLADO') ? esc(mv.nota) : '');
    let apta;
    if (mv.estado === 'FUERA_SERVICIO') apta = `<span class="motivo-txt">No apta: ${esc(mv.motivoNoApta)}</span>`;
    else if (!mv.apta) apta = `<span class="motivo-txt">No apta: ${esc(mv.motivoNoApta)}</span> <button class="btn" data-apta="${mv.id}">Marcar apta</button>`;
    else if (ui.noAptaAbierta === mv.id) apta = `<span class="no-apta-form"><select id="sel-noapta" aria-label="Motivo"><option value="">Motivo</option>${MOTIVOS_NO_APTA.map((x) => `<option>${x}</option>`).join('')}</select><button class="btn primario" data-guardar-noapta="${mv.id}">Guardar</button><button class="btn" data-cancelar-noapta>Cancelar</button></span>`;
    else apta = `<button class="btn" data-noapta="${mv.id}">Marcar no apta</button>`;
    return `<tr><td><b>${mv.id}</b></td><td>${esc(mv.baseNombre)}</td><td><span class="estado-mv">${glyphMovil(mv)}${ESTADO_TXT[mv.estado] || mv.estado}</span></td>
      <td>${esc(zn(M.posicionActual(mv, m)))}</td><td>${libre}</td><td>${servicio}</td><td class="num">${mv.servicios}</td><td>${apta}</td></tr>`;
  }).join('')).join('');
  $('#v-moviles').innerHTML = `<div class="panel">
    <header><h2>Control de móviles</h2><span class="nota">${hora(m)}, ${noAptas} no apta${noAptas === 1 ? '' : 's'}</span></header>
    <p class="lead">Marque una móvil como no apta cuando tenga una novedad. El motor la excluye desde la siguiente recomendación y, si iba en ruta, devuelve su servicio a la cola. La tripulación también puede reportarlo desde su panel.</p>
    <div class="resumen-flota">${res}</div>
    <div class="cuerpo"><table class="tabla">
      <thead><tr><th>Móvil</th><th>Base</th><th>Estado</th><th>Zona actual</th><th>Libre en</th><th>Servicio</th><th class="num">Servicios del turno</th><th>Aptitud</th></tr></thead>
      <tbody>${filas}</tbody></table></div></div>`;
}

// ---------- panel de la tripulación ----------
function renderTripulacion() {
  const e = ui.estado, m = e.minuto;
  const lista = Object.values(e.moviles);
  if (!ui.tripSel) { const c = lista.find((x) => x.servicio) || lista[0]; ui.tripSel = c.id; }
  const mv = e.moviles[ui.tripSel];
  const sol = mv.servicio ? e.solicitudes[mv.servicio] : null;
  const sig = mv.siguiente ? e.solicitudes[mv.siguiente.sol] : null;
  const izq = ['TAM', 'TAB', 'VMD'].map((t) => `<li class="sub-cola">${NOMBRE_TIPO[t]}</li>` + lista.filter((x) => x.tipo === t).map((x) => `<li><button class="fila-trip" data-trip="${x.id}" aria-pressed="${x.id === mv.id}">${glyphMovil(x)}<b>${x.id}</b><span>${x.servicio ? `<span class="chip c${e.solicitudes[x.servicio].clas}">${e.solicitudes[x.servicio].clas}</span> ` : ''}${ESTADO_TXT[x.estado] || x.estado}</span></button></li>`).join('')).join('');

  let tarjeta = '', botones = '';
  const B = (accion, texto, cls, dato) => `<button class="tbtn ${cls || ''}" data-tacc="${accion}" ${dato != null ? `data-tdato="${esc(dato)}"` : ''}>${texto}</button>`;
  if (sol) {
    const llegada = mv.estado === 'EN_RUTA' ? `<p class="t-meta">Llegada estimada en ${Math.max(0, mv.llegaEn - m)} min</p>` : '';
    const nec = [M.posibleTraslado(sol) ? 'Posible traslado' : null, sol.variosPacientes ? 'Varios pacientes en el punto' : null, mv.rol === 'PRIMER_RESPONDIENTE_ESTABILIZACION' ? 'Estabilizar y esperar la ambulancia' : null, mv.rol === 'APOYO_MEDICO' ? 'Apoyo médico a la ambulancia' : null].filter(Boolean);
    tarjeta = `<div class="t-servicio c${sol.clas}"><div class="t-cod"><span class="chip grande c${sol.clas}">${sol.clas}</span><div><b>${C[sol.clas].nombre}</b><br>${esc(zn(sol.zona))}, ${esc(sol.municipio || '')}</div></div>
      <p>${esc(sol.motivo || 'Sin motivo registrado')}</p>${nec.length ? `<p class="t-meta">${nec.join('. ')}.</p>` : ''}${llegada}</div>`;
  }
  if (!mv.apta) {
    tarjeta = `<div class="t-novedad">${ICONO_ALERTA}<div><b>No disponible</b><br>${esc(mv.motivoNoApta)}</div></div>` + tarjeta;
    botones = mv.estado === 'FUERA_SERVICIO' ? '<p class="t-meta">En mantenimiento programado.</p>' : B('disponible', 'Volver a estar disponible', 'ok');
  } else if (ui.tripPaso === 'novedad') {
    botones = '<p class="t-pregunta">¿Qué pasó?</p>' + MOTIVOS_NO_APTA.map((x) => B('novedad', x, '', x)).join('') + B('cancelar', 'Cancelar', 'sec');
  } else if (ui.tripPaso === 'empeoro') {
    botones = '<p class="t-pregunta">¿Cuál es la nueva clasificación?</p>' + CODIGOS.filter((c) => C[c].prio < C[sol.clas].prio).map((c) => B('reclasificar', `${c} ${C[c].nombre}`, 'c' + c, c)).join('') + B('cancelar', 'Cancelar', 'sec');
  } else if (ui.tripPaso === 'mejoro') {
    botones = '<p class="t-pregunta">¿Cuál es la nueva clasificación?</p>' + CODIGOS.filter((c) => C[c].prio > C[sol.clas].prio).map((c) => B('reclasificar', `${c} ${C[c].nombre}`, '', c)).join('') + B('cancelar', 'Cancelar', 'sec');
  } else if (mv.estado === 'EN_RUTA') {
    const minimo = mv.salida + Math.ceil(0.6 * (mv.llegaEn - mv.salida));
    botones = m >= minimo ? B('llegue', 'Llegué al sitio', 'ok')
      : `<button class="tbtn ok" disabled>Llegué al sitio</button><p class="t-meta">Llegada estimada a las ${hora(mv.llegaEn)}. En el simulador este botón se activa a las ${hora(minimo)} para no registrar una llegada imposible en el tablero; en la operación real siempre está activo.</p>`;
  } else if (mv.estado === 'EN_ATENCION' && sol) {
    if (M.esAmbulancia(mv.tipo) && mv.rol !== 'PRIMER_RESPONDIENTE_ESTABILIZACION') botones = B('termine', 'Terminé: sin traslado', 'ok', '') + B('termine', 'Terminé: trasladar al paciente', 'ok', '1');
    else botones = B('termine', 'Terminé la atención', 'ok', '');
    if (C[sol.clas].prio > 0) botones += B('empeoro', 'El caso es más grave', 'alerta');
    if (C[sol.clas].prio < 4) botones += B('mejoro', 'El caso es menos grave', 'sec');
  } else if (mv.estado === 'EN_ATENCION') {
    botones = B('termine', 'Terminé la atención', 'ok', '');
  } else if (mv.estado === 'EN_TRASLADO') {
    tarjeta += `<div class="t-servicio"><p><b>Trasladando al paciente</b></p><p class="t-meta">Al entregarlo en urgencias, avise para quedar disponible.</p></div>`;
    botones = B('libre', 'Entregué al paciente: quedo libre', 'ok');
  } else {
    tarjeta = sig ? `<div class="t-servicio c${sig.clas}"><p><b>Servicio en espera</b></p><p><span class="chip c${sig.clas}">${sig.clas}</span> ${esc(zn(sig.zona))}. Saldrá apenas termine lo que está haciendo.</p></div>`
      : `<div class="t-libre"><b>Disponible</b><p>${mv.estado === 'RETORNANDO' ? 'Regresando a ' + esc(mv.baseNombre) : 'En ' + esc(mv.baseNombre)}. Espere la próxima asignación.</p></div>`;
  }
  if (mv.apta && !ui.tripPaso) botones += B('pedirnovedad', 'Reportar novedad', 'sec');
  const ult = e.log.filter((x) => x.datos && x.datos.movil === mv.id).slice(-4).reverse().map((x) => `<li><span>${hora(x.hora)}</span> ${esc(x.texto)}</li>`).join('');

  $('#v-tripulacion').innerHTML = `<div class="trip">
    <div class="panel"><header><h2>Móviles</h2><span class="nota">Elija la móvil para ver su panel</span></header><ul class="lista-trip">${izq}</ul></div>
    <div class="trip-centro">
      <div class="telefono" role="region" aria-label="Panel de la tripulación de ${mv.id}">
        <div class="t-cab"><b>${mv.id}</b><span>${mv.tipo}, ${esc(mv.baseNombre)}</span><span class="t-hora">${hora(m)}</span></div>
        <div class="t-cuerpo">${tarjeta}<div class="t-botones">${botones}</div></div>
      </div>
    </div>
    <div class="panel trip-nota"><header><h2>Cómo funciona</h2></header>
      <div class="cuerpo"><p>Es lo que vería la tripulación en el celular o la tableta de la móvil: solo el servicio asignado y botones grandes, sin texto libre ni datos clínicos.</p>
      <p>Cada botón actualiza al instante la cola, el mapa y el tablero del despachador. Si la tripulación no reporta, el simulador avanza los estados con los tiempos típicos del histórico.</p>
      <p>Un caso más grave abre la ventana de urgencias del despachador con las ambulancias disponibles. Una novedad saca la móvil de las recomendaciones y, si iba en ruta, devuelve el servicio a la cola.</p>
      ${ult ? `<h3>Lo último de ${mv.id}</h3><ul class="t-log">${ult}</ul>` : ''}</div></div>
  </div>`;
}

function accionTripulacion(accion, dato) {
  const e = ui.estado, id = ui.tripSel;
  if (accion === 'pedirnovedad') { ui.tripPaso = 'novedad'; renderTripulacion(); return; }
  if (accion === 'empeoro' || accion === 'mejoro') { ui.tripPaso = accion; renderTripulacion(); return; }
  if (accion === 'cancelar') { ui.tripPaso = null; renderTripulacion(); return; }
  const antes = e.log.length;
  M.tripulacion(ctx, e, id, accion, accion === 'termine' ? dato === '1' : dato);
  ui.tripPaso = null; ui.politicas = null;
  const pausa = procesarEventos(e.log.slice(antes));
  if (pausa && $('#chk-pausa').checked) pausar();
  autoSeleccion();
  render();
}

// ---------- tablero ----------
const POLITICAS = [
  { id: 'historica', nombre: 'Despachador (archivo 06)', color: 'var(--s1)', forma: 'circulo' },
  { id: 'motor', nombre: 'Motor: opción recomendada', color: 'var(--s2)', forma: 'cuadro' },
  { id: 'cercana', nombre: 'La más cercana', color: 'var(--s3)', forma: 'rombo' },
];
function marcaForma(forma, x, y, color, tipAttr) {
  if (forma === 'cuadro') return `<rect x="${x - 5}" y="${y - 5}" width="10" height="10" rx="1.5" fill="${color}" stroke="#fff" stroke-width="2" ${tipAttr}/>`;
  if (forma === 'rombo') return `<path d="M${x} ${y - 6.5}L${x + 6.5} ${y}L${x} ${y + 6.5}L${x - 6.5} ${y}Z" fill="${color}" stroke="#fff" stroke-width="2" ${tipAttr}/>`;
  return `<circle cx="${x}" cy="${y}" r="5.5" fill="${color}" stroke="#fff" stroke-width="2" ${tipAttr}/>`;
}
function iconoForma(p) { return `<svg width="14" height="14" aria-hidden="true">${marcaForma(p.forma, 7, 7, p.color, '')}</svg>`; }
function calcularPoliticas() {
  if (ui.politicas && ui.politicas.esc === ui.escId) return ui.politicas;
  const out = { esc: ui.escId };
  POLITICAS.forEach((p) => { out[p.id] = M.correr(ctx, ui.escId, p.id); });
  ui.politicas = out;
  return out;
}
function renderTablero() {
  const P = calcularPoliticas();
  const e = ui.estado;
  const mU = M.metricas(ctx, e, { parcial: true });
  const usadas = e.decisiones.length > 0;
  const nTot = ctx.D.solicitudes.filter((x) => x.id_escenario === ui.escId).length;
  const nCuenta = Object.values(e.solicitudes).filter((x) => M.completa(x) && x.estado !== 'devuelta' && (x.primeraLlegada != null || (e.minuto - x.minLlegada) > C[x.necesitaAmb ? x.clasIni : x.clas].obj)).length;
  const cols = [{ id: 'usuario', nombre: `Sus decisiones (${nCuenta} de ${nTot} solicitudes)`, m: mU }].concat(POLITICAS.map((p) => ({ id: p.id, nombre: p.nombre, m: P[p.id].metricas, forma: p })));
  const filasMet = [
    { n: '01 y 02 dentro del objetivo', f: (m) => m.pctCriticasDentro, fmt: (x) => x == null ? '–' : r0(x) + ' %', mejor: 'max' },
    { n: 'Llegada promedio en 01 y 02', f: (m) => m.promCriticas, fmt: (x) => x == null ? '–' : r1(x) + ' min', mejor: 'min' },
    { n: 'Todas las clases dentro del objetivo', f: (m) => m.pctDentro, fmt: (x) => x == null ? '–' : r0(x) + ' %', mejor: 'max' },
    { n: 'Minutos con alguna zona ALTA a más de 20 min', f: (m) => m.minDescubiertos, fmt: (x) => r0(x), mejor: 'min' },
    { n: 'Kilómetros', f: (m) => m.km, fmt: (x) => r1(x), mejor: 'min' },
    { n: 'Costo estimado', f: (m) => m.costo, fmt: (x) => pesos(x), mejor: 'min' },
    { n: 'De la reclasificación a la ambulancia', f: (m) => m.escalaciones.length ? m.escalaciones[0].min : null, fmt: (x) => x == null ? '–' : r0(x) + ' min', mejor: 'min' },
    { n: 'Asignaciones a móviles no aptas', f: (m) => m.noAptasAsignadas, fmt: (x) => r0(x), mejor: null },
    { n: 'Elecciones distintas a la recomendada', f: (m) => m.cambios, fmt: (x) => r0(x), mejor: null, solo: 'usuario' },
    { n: 'Correcciones de asignación', f: (m) => m.correcciones, fmt: (x) => r0(x), mejor: null, solo: 'usuario' },
  ];
  const tabla = `<table class="tabla"><thead><tr><th>Indicador</th>${cols.map((c) => `<th class="num">${c.forma ? iconoForma(c.forma) + ' ' : ''}${esc(c.nombre)}</th>`).join('')}</tr></thead><tbody>
    ${filasMet.map((f) => {
      const vals = cols.slice(1).map((c) => f.f(c.m)).filter((v) => v != null && isFinite(v));
      const best = f.mejor === 'max' ? Math.max.apply(null, vals) : f.mejor === 'min' ? Math.min.apply(null, vals) : null;
      return `<tr><td>${f.n}</td>${cols.map((c, i) => {
        if (f.solo && c.id !== f.solo) return '<td class="num">–</td>';
        const v = f.f(c.m);
        const esMejor = i > 0 && best != null && v != null && Math.abs(v - best) < 1e-9 && vals.length > 1 && vals.some((x) => Math.abs(x - best) > 1e-9);
        return `<td class="num ${esMejor ? 'mejor' : ''}">${i === 0 && !usadas ? '–' : f.fmt(v)}</td>`;
      }).join('')}</tr>`;
    }).join('')}</tbody></table>`;
  const sols = ctx.D.solicitudes.filter((s) => s.id_escenario === ui.escId);
  const filasG = sols.map((s) => ({ s, obj: C[s.clasificacion_inicial].obj, vals: POLITICAS.map((p) => { const so = P[p.id].estado.solicitudes[s.id_solicitud]; return !so || so.primeraLlegada == null ? null : so.primeraLlegada - so.minLlegada; }) }));
  const maxX = Math.max(30, ...filasG.flatMap((f) => f.vals.filter((v) => v != null)), ...filasG.map((f) => Math.min(f.obj, 60))) * 1.08;
  const anchoMain = Math.max(640, document.querySelector('main').clientWidth - 72);
  const W = anchoMain, L = 190, R = 24, rowH = 34, top = 28, H = top + filasG.length * rowH + 30;
  const X = (v) => L + (v / maxX) * (W - L - R);
  const step = maxX > 120 ? 30 : maxX > 60 ? 15 : 10;
  let ticks = ''; for (let t = 0; t <= maxX; t += step) ticks += `<line x1="${X(t)}" x2="${X(t)}" y1="${top - 6}" y2="${H - 26}" stroke="#e7ecef"/><text x="${X(t)}" y="${H - 10}" text-anchor="middle" font-size="11" fill="#66717c">${t}</text>`;
  const rows = filasG.map((f, i) => {
    const y = top + i * rowH + rowH / 2;
    const objX = f.obj <= maxX ? `<line x1="${X(f.obj)}" x2="${X(f.obj)}" y1="${y - 12}" y2="${y + 12}" stroke="#17202a" stroke-width="2"/>` : '';
    const dots = f.vals.map((v, j) => v == null ? '' : marcaForma(POLITICAS[j].forma, X(v), y + (j - 1) * 8, POLITICAS[j].color, `data-tip="<b>${f.s.id_solicitud}</b><br>${esc(POLITICAS[j].nombre)}: llega en ${r0(v)} min<br>Objetivo ${f.obj} min"`)).join('');
    return `<g><text x="${L - 10}" y="${y + 4}" text-anchor="end" font-size="12" fill="#17202a">${corto(f.s.id_solicitud)}  ${f.s.clasificacion_inicial}  ${esc(f.s.comuna.replace(/^\d+ - /, ''))}</text><line x1="${L}" x2="${W - R}" y1="${y}" y2="${y}" stroke="#f0f3f5"/>${objX}${dots}</g>`;
  }).join('');
  const grafica = `<svg class="grafica" viewBox="0 0 ${W} ${H}" role="img" aria-label="Minutos desde la solicitud hasta la primera llegada, por solicitud y política"><text x="${L}" y="14" font-size="11" fill="#66717c">Minutos desde la solicitud hasta la primera llegada (la raya negra es el objetivo de la clase)</text>${ticks}${rows}</svg>`;

  const H1 = D.hist_clases;
  const anchoMedio = Math.max(420, (anchoMain - 16) / 2 - 8);
  const Wb = anchoMedio, Lb = 150, rh = 30, hb = 20 + H1.length * rh + 26;
  const Xb = (v) => Lb + (v / 100) * (Wb - Lb - 60);
  let tb = ''; [0, 25, 50, 75, 100].forEach((t) => { tb += `<line x1="${Xb(t)}" x2="${Xb(t)}" y1="12" y2="${hb - 24}" stroke="#e7ecef"/><text x="${Xb(t)}" y="${hb - 8}" text-anchor="middle" font-size="11" fill="#66717c">${t} %</text>`; });
  const barras = H1.map((h, i) => {
    const y = 18 + i * rh, w = Xb(h.cumple) - Lb;
    return `<g data-tip="<b>${esc(h.label)}</b><br>${r1(h.cumple)} % dentro de ${h.obj} min<br>${h.n.toLocaleString('es-CO')} servicios<br>Mediana ${r1(h.med)} min, P90 ${r1(h.p90)} min"><text x="${Lb - 10}" y="${y + 14}" text-anchor="end" font-size="12" fill="#17202a">${esc(h.label)}</text>
      <path d="M${Lb} ${y + 3}h${Math.max(0, w - 4)}a4 4 0 0 1 4 4v10a4 4 0 0 1 -4 4h-${Math.max(0, w - 4)}z" fill="${h.k.startsWith('01') ? '#c62828' : '#3f4a55'}"/><text x="${Lb + w + 6}" y="${y + 15}" font-size="12" font-weight="650" fill="#17202a">${r0(h.cumple)} %</text></g>`;
  }).join('');
  const meta = `<line x1="${Xb(90)}" x2="${Xb(90)}" y1="14" y2="${18 + 3 * rh - 4}" stroke="#17202a" stroke-width="1.5"/><text x="${Xb(90)}" y="10" text-anchor="middle" font-size="11" fill="#17202a">meta 90 % (01 y 02)</text>`;
  const graf1 = `<svg class="grafica" viewBox="0 0 ${Wb} ${hb}" role="img" aria-label="Porcentaje de servicios dentro del tiempo objetivo por clase">${tb}${meta}${barras}</svg>`;
  const Wp = anchoMedio, Lp = 150, hp = hb, maxP = 100;
  const Xp = (v) => Lp + (Math.min(v, maxP) / maxP) * (Wp - Lp - 40);
  let tp = ''; [0, 20, 40, 60, 80, 100].forEach((t) => { tp += `<line x1="${Xp(t)}" x2="${Xp(t)}" y1="12" y2="${hp - 24}" stroke="#e7ecef"/><text x="${Xp(t)}" y="${hp - 8}" text-anchor="middle" font-size="11" fill="#66717c">${t}</text>`; });
  const dotsP = H1.map((h, i) => {
    const y = 18 + i * rh + 11;
    return `<g data-tip="<b>${esc(h.label)}</b><br>Mediana ${r1(h.med)} min<br>P90 ${r1(h.p90)} min<br>Objetivo ${h.obj} min"><text x="${Lp - 10}" y="${y + 4}" text-anchor="end" font-size="12" fill="#17202a">${esc(h.label)}</text>
      <line x1="${Xp(h.med)}" x2="${Xp(h.p90)}" y1="${y}" y2="${y}" stroke="#9aa6b1" stroke-width="2"/><circle cx="${Xp(h.med)}" cy="${y}" r="4" fill="#9aa6b1" stroke="#fff" stroke-width="2"/><circle cx="${Xp(h.p90)}" cy="${y}" r="5.5" fill="#17202a" stroke="#fff" stroke-width="2"/>
      ${h.obj <= maxP ? `<line x1="${Xp(h.obj)}" x2="${Xp(h.obj)}" y1="${y - 9}" y2="${y + 9}" stroke="#c62828" stroke-width="2"/>` : `<text x="${Xp(maxP) + 4}" y="${y + 4}" font-size="11" fill="#66717c">obj. ${h.obj}</text>`}
      <text x="${Xp(h.p90) + 9}" y="${y + 4}" font-size="12" font-weight="650" fill="#17202a">${r0(h.p90)}</text></g>`;
  }).join('');
  const graf2 = `<svg class="grafica" viewBox="0 0 ${Wp} ${hp}" role="img" aria-label="Mediana y P90 del tiempo de respuesta frente al objetivo por clase">${tp}${dotsP}</svg>`;
  const hm = D.hist_moviles;
  const ids = Object.keys(hm).sort((a, b) => { const o = { TAM: 0, TAB: 1, VMD: 2 }; return (o[ctx.movil[a].tipo_movil] - o[ctx.movil[b].tipo_movil]) || (hm[b].util - hm[a].util); });
  const Wc = anchoMain, Hc = 250, Lc = 40, Bc = 200, n = ids.length, bw = Math.min(22, (Wc - Lc - 20) / n - 6), slot = (Wc - Lc - 20) / n;
  const Yc = (v) => Bc - (v / 100) * (Bc - 20);
  let tc = ''; [0, 25, 50, 75, 100].forEach((t) => { tc += `<line x1="${Lc}" x2="${Wc - 10}" y1="${Yc(t)}" y2="${Yc(t)}" stroke="#e7ecef"/><text x="${Lc - 6}" y="${Yc(t) + 4}" text-anchor="end" font-size="11" fill="#66717c">${t}</text>`; });
  const banda = `<rect x="${Lc}" y="${Yc(75)}" width="${Wc - 10 - Lc}" height="${Yc(60) - Yc(75)}" fill="#efeaf7"/><text x="${Wc - 12}" y="${Yc(75) - 4}" text-anchor="end" font-size="11" fill="#4b2e83">meta 60–75 %</text><line x1="${Lc}" x2="${Wc - 10}" y1="${Yc(85)}" y2="${Yc(85)}" stroke="#4b2e83" stroke-width="1"/><text x="${Lc + 4}" y="${Yc(85) - 4}" font-size="11" fill="#4b2e83">tope 85 %</text>`;
  let prevTipo = null;
  const barrasC = ids.map((id, i) => {
    const x = Lc + 10 + i * slot + (slot - bw) / 2, v = hm[id].util, y = Yc(v), tipo = ctx.movil[id].tipo_movil;
    const sep = prevTipo && prevTipo !== tipo ? `<line x1="${x - (slot - bw) / 2 - 1}" x2="${x - (slot - bw) / 2 - 1}" y1="20" y2="${Bc + 30}" stroke="#d5dce2"/>` : '';
    const grupo = prevTipo !== tipo ? `<text x="${x}" y="${Bc + 36}" font-size="11.5" font-weight="650" fill="#3f4a55">${tipo}</text>` : '';
    prevTipo = tipo;
    return `${sep}${grupo}<g data-tip="<b>${id}</b> ${tipo}<br>Utilización ${r1(v)} %<br>${hm[id].servicios} servicios en el periodo"><path d="M${x} ${Bc}V${y + 4}a4 4 0 0 1 4 -4h${bw - 8}a4 4 0 0 1 4 4V${Bc}z" fill="#3f4a55"/><text x="${x + bw / 2}" y="${Bc + 14}" text-anchor="middle" font-size="9.5" fill="#66717c">${id.slice(-2)}</text></g>`;
  }).join('');
  const graf3 = `<svg class="grafica" viewBox="0 0 ${Wc} ${Hc}" role="img" aria-label="Utilización de cada móvil en el histórico">${banda}${tc}<line x1="${Lc}" x2="${Wc - 10}" y1="${Bc}" y2="${Bc}" stroke="#9aa6b1"/>${barrasC}</svg>`;
  const ret = D.retencion;
  $('#v-tablero').innerHTML = `<div class="tablero">
    <div class="panel span-12"><header><h2>${esc(ui.escId)}: ${esc(e.esc.nombre)}</h2><span class="nota">Simulación en el navegador con el motor provisional</span></header>
      <p class="lead">Mismo escenario, cuatro formas de asignar. En negrita, la mejor de las tres políticas automáticas en cada fila. Sus decisiones cuentan solo las solicitudes que ya tuvieron llegada o que ya superaron su objetivo.</p>
      <div class="cuerpo">${tabla}</div>
      <div class="leyenda-graf" style="margin-top:14px">${POLITICAS.map((p) => `<span>${iconoForma(p)}${esc(p.nombre)}</span>`).join('')}</div>
      <div class="cuerpo">${grafica}</div>
      <p class="fuente">Fuente: archivo 06 (escenarios) y archivo 05 (tiempos). Cifras ficticias de una simulación; no son resultados de la operación.</p></div>
    <div class="panel span-6"><header><h2>Cumplimiento del tiempo objetivo por clase</h2><span class="nota">Histórico</span></header>
      <p class="lead">Los 01 que llegaron reclasificados desde una consulta se separan de los 01 del triaje: el promedio de los dos esconde que el problema está en las escalaciones.</p>
      <div class="cuerpo">${graf1}</div><p class="fuente">Archivo 01, 16 mar a 30 abr de 2026, sin limpiar las llegadas registradas tarde. P1 reemplaza estas cifras con los datos limpios.</p></div>
    <div class="panel span-6"><header><h2>Mediana y P90 del tiempo de respuesta</h2><span class="nota">Histórico, minutos</span></header>
      <p class="lead">Punto gris: mediana. Punto negro: P90. Raya roja: objetivo de la clase.</p>
      <div class="cuerpo">${graf2}</div><p class="fuente">Archivo 01. Retención de camilla tras un traslado: p10 ${r0(ret[0])} min, mediana ${r0(ret[1])} min, p90 ${r0(ret[2])} min.</p></div>
    <div class="panel span-12"><header><h2>Carga por móvil</h2><span class="nota">Histórico, % del tiempo comprometida</span></header>
      <p class="lead">La utilización está entre 24 % y 53 %, lejos de la meta de 60–75 %. Con la misma flota y demanda, asignar mejor reparte la carga pero no sube el promedio: eso depende de cuántas móviles hay por franja.</p>
      <div class="cuerpo">${graf3}</div><p class="fuente">Archivo 01 y archivo 07 (KPI-05). Las móviles MOV-012 y MOV-024 estuvieron en mantenimiento todo el periodo.</p></div>
  </div>`;
}

// ---------- escenarios ----------
function compararCon(escId) { if (!ui.comparacion[escId]) ui.comparacion[escId] = M.compararConDespachador(ctx, escId); return ui.comparacion[escId]; }
const BASES_PISTA = ['Centro', 'Poblado', 'Laureles', 'Norte', 'Bello', 'Envigado', 'Itagüí', 'Robledo'];
function esDiscutible(c) { return /discutible|alternativa|aunque|pudo/i.test(c || ''); }
function coincideConAlternativa(comentario, recs) {
  const txt = comentario.includes('Alternativa:') ? comentario.split('Alternativa:')[1] : comentario;
  const ids = txt.match(/MOV-\d{3}/g) || [];
  const tipo = (txt.match(/\b(TAM|TAB|VMD)\b/) || [])[1];
  const base = BASES_PISTA.find((b) => txt.includes(b));
  return recs.filter(Boolean).some((rec) => {
    const top = rec.opciones[0]; if (!top) return false;
    const tops = top.moviles.map((x) => x.id);
    if (ids.length) {
      if (ids.some((i) => tops.includes(i))) return true;
      return ids.some((i) => { const alt = rec.todas.find((o) => o.movil.id === i); return alt && top.movil.tipo === alt.movil.tipo && top.llegada.minutos <= alt.llegada.minutos + 0.5; });
    }
    if (/preasign/i.test(txt)) return top.tipo === 'estabilizacion' && !!top.ambulancia;
    if (tipo) return tops.some((i) => ctx.movil[i].tipo_movil === tipo && (!base || ctx.base[ctx.movil[i].id_base].nombre_base.includes(base)));
    return false;
  });
}
function renderEscenarios() {
  const lista = D.escenarios.map((s) => {
    const n = D.decisiones.filter((d) => d.id_escenario === s.id_escenario && esDiscutible(d.comentario_coordinador)).length;
    return `<li><button data-escvista="${s.id_escenario}" aria-pressed="${s.id_escenario === ui.escVista}"><span class="id">${s.id_escenario}</span><span class="nom">${esc(s.nombre)}</span>
      <span class="desc">${s.n_solicitudes} solicitud${s.n_solicitudes > 1 ? 'es' : ''}${n ? `, ${n} decisión${n > 1 ? 'es' : ''} discutible${n > 1 ? 's' : ''} o con alternativa` : ''}</span></button></li>`;
  }).join('');
  const s = M.escenario(ctx, ui.escVista);
  const filas = compararCon(ui.escVista);
  let coinc = 0, nDisc = 0, coincDisc = 0, n1 = 0;
  const trs = filas.map(({ d, rec, recLlegada, clas }) => {
    const top = rec.opciones[0];
    const ids = top ? top.moviles.map((x) => x.id) : [];
    const idsLl = recLlegada && recLlegada.opciones[0] ? recLlegada.opciones[0].moviles.map((x) => x.id) : [];
    const comentario = d.comentario_coordinador || '';
    const disc = esDiscutible(comentario);
    const conAlt = disc && coincideConAlternativa(comentario, [rec, recLlegada]);
    let estadoTxt, cls;
    if (conAlt) { estadoTxt = 'Coincide con la alternativa del coordinador'; cls = 'alt'; }
    else if (ids.includes(d.id_movil) || (d.orden_movil > 1 && idsLl.includes(d.id_movil))) { estadoTxt = d.orden_movil > 1 && !ids.includes(d.id_movil) ? 'El motor ya la proponía al llegar la solicitud' : 'Coincide con el despachador'; cls = 'si'; }
    else { estadoTxt = 'Propone otra móvil'; cls = 'no'; }
    if (d.orden_movil === 1) { n1++; if (cls === 'si' || ids.includes(d.id_movil)) coinc++; }
    if (disc) { nDisc++; if (conAlt) coincDisc++; }
    return `<tr><td>${corto(d.id_solicitud)}<br><small style="color:var(--muted)">min ${d.minuto_asignacion}${d.orden_movil > 1 ? ', 2.ª móvil' : ''}</small></td><td><span class="chip c${clas}">${clas}</span></td>
      <td><b>${d.id_movil}</b> ${d.tipo_movil}, ${r1(d.tiempo_estimado_llegada_min)} min<br><small style="color:var(--muted)">${esc(d.justificacion_despachador)}</small></td>
      <td style="max-width:260px">${disc ? '<span class="marca-disc">Discutible o con alternativa</span>' : ''}${esc(comentario)}</td>
      <td>${top ? `<b>${ids.join(' + ')}</b>, ${r0(top.llegada.minutos)} min<br><small style="color:var(--muted)">${esc(top.explicacion)}</small>` : '–'}</td>
      <td><span class="coincide ${cls}">${estadoTxt}</span></td></tr>`;
  }).join('');
  $('#v-escenarios').innerHTML = `<div class="escenarios">
    <div class="panel"><header><h2>Escenarios de referencia</h2><span class="nota">Archivo 06</span></header><ul class="lista-esc">${lista}</ul></div>
    <div class="panel esc-det"><div style="padding:16px 18px 6px;display:flex;justify-content:space-between;gap:16px;align-items:flex-start">
        <div><h2>${s.id_escenario}: ${esc(s.nombre)}</h2><p class="objetivo">${esc(s.descripcion)}</p><p class="objetivo"><b>Qué se evalúa:</b> ${esc(s.objetivo_aprendizaje)}</p></div>
        <button class="btn plum" data-cargar="${s.id_escenario}">${ui.escId === s.id_escenario ? 'Volver a cargar en Despacho' : 'Cargar en Despacho'}</button></div>
      <div class="tiles"><div class="tile"><span>Coincide con el despachador</span><b>${coinc} de ${n1}</b><small>primera móvil de cada solicitud</small></div>
        <div class="tile"><span>Decisiones discutibles o con alternativa</span><b>${nDisc ? coincDisc + ' de ' + nDisc : '0'}</b><small>${nDisc ? 'en las que el motor propone lo que sugiere el coordinador' : 'el coordinador marcó todas como correctas'}</small></div></div>
      <div class="cuerpo"><table class="tabla"><thead><tr><th>Solicitud</th><th>Clase</th><th>Despachador</th><th>Coordinador</th><th>Motor en ese momento</th><th></th></tr></thead><tbody>${trs}</tbody></table></div>
      <p class="fuente">La recomendación se calcula con la flota tal como estaba cuando decidió el despachador; para las alternativas que el coordinador ubica al llegar la solicitud, también con la flota de ese momento. Las decisiones del archivo 06 son una referencia, no la respuesta óptima. Los pesos provisionales se ajustaron revisando estos mismos escenarios: esta coincidencia no es una validación independiente.</p>
    </div></div>`;
}

// ---------- registro de solicitud ----------
function abrirRegistro() {
  pausar();
  const zonas = D.zonas.slice().sort((a, b) => a.n.localeCompare(b.n, 'es')).map((z) => `<option value="${z.id}">${esc(z.n)} (${esc(z.mu)})</option>`).join('');
  $('#dlg-registro').innerHTML = `<form class="dlg" method="dialog" id="form-registro" novalidate>
    <h2>Registrar solicitud</h2>
    <p class="nota-dlg">Simula lo que entrega el paramédico de triaje a despachos. En la operación real llegaría sola desde el sistema de la empresa; este formulario solo existe en el MVP.</p>
    <div class="campos">
      <label>Zona del paciente<select name="zona"><option value="">Elija la zona</option>${zonas}</select></label>
      <label>Clasificación<select name="clas"><option value="">Elija el código</option>${CODIGOS.map((c) => `<option value="${c}">${c} ${C[c].nombre} (${C[c].color.toLowerCase()})</option>`).join('')}</select></label>
      <label>Motivo y discriminador<select name="motivo" disabled><option value="">Primero elija la clasificación</option></select></label>
      <label>Canal<select name="canal"><option value="TELEFONO">Teléfono</option><option value="APP">App</option><option value="WHATSAPP">WhatsApp</option></select></label>
    </div>
    <p class="error-form" id="error-registro" hidden></p>
    <div class="dlg-acciones"><button type="button" class="btn" id="btn-cancelar-registro">Cancelar</button><button type="submit" class="btn primario">Registrar</button></div>
    <div class="probar"><b>Probar datos incompletos</b><span>Simula que el sistema externo envía una solicitud con un dato faltante.</span>
      <button type="button" class="btn" data-incompleta="zona">Llega un 02 sin zona</button><button type="button" class="btn" data-incompleta="clas">Llega una solicitud sin clasificación</button></div>
  </form>`;
  $('#dlg-registro').showModal();
}
function registrar(datos) {
  const e = ui.estado;
  const s = M.registrarSolicitud(e, datos);
  procesarEventos(e.log.slice(-1));
  ui.sel = s.id; resetDecision(); ui.politicas = null;
  if (esUrgente(s)) ui.urgMin = false;
  ui.vista = 'despacho';
  render();
}

// ---------- eventos de interfaz ----------
function opcionActual() { return ui.rec && ui.rec.opciones[ui.opSel]; }
document.addEventListener('click', (ev) => {
  const t = ev.target;
  const nav = t.closest('.nav button'); if (nav) { ui.vista = nav.dataset.vista; render(); return; }
  if (t.closest('#btn-volver')) { $('#dlg-confirmar').close(); ui.pendiente = null; return; }
  if (t.closest('#btn-si-asignar')) { confirmarPendiente(); return; }
  const fs = t.closest('[data-sol]'); if (fs && !t.closest('#dlg-urgencia')) {
    const id = fs.dataset.sol;
    if ($('#dlg-urgencia').open) return;
    ui.sel = id; resetDecision(); ui.vista = 'despacho';
    if (esUrgente(ui.estado.solicitudes[id])) { ui.urgMin = false; ui.urgId = id; }
    render(); return;
  }
  const fo = t.closest('.op[data-op]'); if (fo) { ui.opSel = Number(fo.dataset.op); ui.preview = null; render(); return; }
  if (t.closest('.js-confirmar')) { const op = opcionActual(); if (op) abrirConfirmacion(op, ui.opSel === 0 ? null : 'Eligió la opción ' + (ui.opSel + 1) + ' del top 3'); return; }
  if (t.closest('.js-cambiar')) { ui.cambiar = !ui.cambiar; render(); return; }
  if (t.closest('.js-confirmar-cambio')) { const op = ui.rec.todas[ui.cambioSel]; if (op && ui.motivo) abrirConfirmacion(op, ui.motivo); return; }
  if (t.closest('.js-minimizar')) { ui.urgMin = true; render(); return; }
  if (t.closest('[data-abrir-urg]')) { ui.urgMin = false; render(); return; }
  const pre = t.closest('[data-preasignar]'); if (pre) { const op = ui.rec.primerasEnLiberarse[Number(pre.dataset.preasignar)]; abrirConfirmacion(op, 'Sin unidades: preasignar la primera que se libera'); return; }
  const cz = t.closest('[data-completar-zona]'); if (cz) {
    const sel = cz.parentElement.querySelector('.sel-zona');
    if (!sel.value) { sel.focus(); aviso('Elija la zona antes de confirmar.', true); return; }
    M.completarZona(ctx, ui.estado, cz.dataset.completarZona, sel.value); ui.politicas = null; render(); return;
  }
  const dv = t.closest('[data-devolver]'); if (dv) { M.devolverATriaje(ui.estado, dv.dataset.devolver); aviso(`${corto(dv.dataset.devolver)} devuelta a triaje.`, false); ui.sel = null; autoSeleccion(); render(); return; }
  const cr = t.closest('[data-corregir]'); if (cr) { corregir(cr.dataset.corregir); return; }
  const am = t.closest('[data-ampliar]'); if (am) { const g = $('#v-despacho'); const on = !g.classList.contains('mapa-grande'); g.classList.toggle('mapa-grande', on); am.setAttribute('aria-pressed', on); am.textContent = on ? 'Reducir' : 'Ampliar'; renderMapa(); return; }
  const z = t.closest('[data-zoom]'); if (z) { ui.zoom = z.dataset.zoom; ui.mapa.vb = null; renderMapa(); return; }
  const zr = t.closest('[data-zoomrel]'); if (zr) { zoomRel(Number(zr.dataset.zoomrel)); return; }
  const fl = t.closest('[data-filtro]'); if (fl) { const k = fl.dataset.filtro; ui.mapa.filtros[k] = !ui.mapa.filtros[k]; renderMapa(); return; }
  const mk = t.closest('[data-movil]'); if (mk && !arrastre.movio) { ui.mapa.movilSel = mk.dataset.movil; ui.mapa.noApta = false; renderMapa(); return; }
  if (t.closest('[data-cerrar-ficha]')) { ui.mapa.movilSel = null; renderMapa(); return; }
  const nam = t.closest('[data-noapta-mapa]'); if (nam) { ui.mapa.noApta = true; renderMapa(); return; }
  const gnm = t.closest('[data-guardar-noapta-mapa]'); if (gnm) {
    const motivo = $('.sel-noapta-mapa').value; if (!motivo) { $('.sel-noapta-mapa').focus(); return; }
    const antes = ui.estado.log.length;
    M.marcarNoApta(ctx, ui.estado, gnm.dataset.guardarNoaptaMapa, motivo); ui.mapa.noApta = false; ui.politicas = null;
    procesarEventos(ui.estado.log.slice(antes)); autoSeleccion(); render(); return;
  }
  const it = t.closest('[data-ir-trip]'); if (it) { ui.tripSel = it.dataset.irTrip; ui.tripPaso = null; ui.vista = 'tripulacion'; render(); return; }
  const na = t.closest('[data-noapta]'); if (na) { ui.noAptaAbierta = na.dataset.noapta; renderMoviles(); return; }
  if (t.closest('[data-cancelar-noapta]')) { ui.noAptaAbierta = null; renderMoviles(); return; }
  const gn = t.closest('[data-guardar-noapta]'); if (gn) {
    const motivo = $('#sel-noapta').value; if (!motivo) { $('#sel-noapta').focus(); return; }
    const antes = ui.estado.log.length;
    M.marcarNoApta(ctx, ui.estado, gn.dataset.guardarNoapta, motivo); ui.noAptaAbierta = null; ui.politicas = null;
    procesarEventos(ui.estado.log.slice(antes)); autoSeleccion(); render(); return;
  }
  const ap = t.closest('[data-apta]'); if (ap) { M.marcarApta(ctx, ui.estado, ap.dataset.apta); aviso(`${ap.dataset.apta} vuelve a estar apta.`, false); render(); return; }
  const tr = t.closest('[data-trip]'); if (tr) { ui.tripSel = tr.dataset.trip; ui.tripPaso = null; renderTripulacion(); return; }
  const ta = t.closest('[data-tacc]'); if (ta) { accionTripulacion(ta.dataset.tacc, ta.dataset.tdato); return; }
  const ev2 = t.closest('[data-escvista]'); if (ev2) { ui.escVista = ev2.dataset.escvista; renderEscenarios(); return; }
  const cg = t.closest('[data-cargar]'); if (cg) { cargar(cg.dataset.cargar); ui.vista = 'despacho'; render(); return; }
  if (t.closest('#btn-cancelar-registro')) { $('#dlg-registro').close(); return; }
  const inc = t.closest('[data-incompleta]'); if (inc) {
    $('#dlg-registro').close();
    if (inc.dataset.incompleta === 'zona') registrar({ clas: '02', motivo: 'Convulsiones', discriminador: 'Convulsión activa o reciente', canal: 'TELEFONO' });
    else registrar({ zona: 'Z-MED-09-02', canal: 'APP' });
    return;
  }
});
document.addEventListener('submit', (ev) => {
  if (ev.target.id !== 'form-registro') return;
  ev.preventDefault();
  const f = ev.target;
  const faltan = [];
  if (!f.zona.value) faltan.push('la zona');
  if (!f.clas.value) faltan.push('la clasificación');
  const err = $('#error-registro');
  if (faltan.length) { err.hidden = false; err.textContent = `Falta ${faltan.join(' y ')}. Sin ese dato no se puede recomendar una móvil.`; return; }
  const [motivo, discriminador] = f.motivo.value ? f.motivo.value.split('|') : [null, null];
  const z = ctx.zona[f.zona.value];
  $('#dlg-registro').close();
  registrar({ zona: f.zona.value, comuna: z.co, municipio: z.mu, clas: f.clas.value, motivo, discriminador, canal: f.canal.value });
});
document.addEventListener('change', (ev) => {
  const t = ev.target;
  if (t.name === 'cambio') { ui.cambioSel = Number(t.value); document.querySelectorAll('.js-confirmar-cambio').forEach((b) => { b.disabled = !(ui.cambioSel != null && ui.motivo); }); return; }
  if (t.classList.contains('sel-motivo')) { ui.motivo = t.value; document.querySelectorAll('.js-confirmar-cambio').forEach((b) => { b.disabled = !(ui.cambioSel != null && ui.motivo); }); return; }
  if (t.classList.contains('chk-apoyo')) { ui.apoyo = t.checked; return; }
  if (t.id === 'sel-esc') { cargar(t.value); return; }
  if (t.form && t.form.id === 'form-registro') { const er = $('#error-registro'); if (er) er.hidden = true; }
  if (t.name === 'clas' && t.form && t.form.id === 'form-registro') {
    const m = t.form.motivo;
    m.disabled = !t.value;
    m.innerHTML = t.value ? '<option value="">Sin motivo (opcional)</option>' + MOTIVOS[t.value].map(([a, b]) => `<option value="${esc(a)}|${esc(b)}">${esc(a)}: ${esc(b)}</option>`).join('') : '<option value="">Primero elija la clasificación</option>';
  }
});
document.addEventListener('mouseover', (ev) => {
  const fo = ev.target.closest('.op[data-op]');
  if (fo && ui.vista === 'despacho' && !$('#dlg-urgencia').open) { const i = Number(fo.dataset.op); if (ui.preview !== i) { ui.preview = i; renderMapa(); } }
});
document.addEventListener('mouseout', (ev) => {
  const fo = ev.target.closest('.op[data-op]');
  if (fo && !(ev.relatedTarget && ev.relatedTarget.closest && ev.relatedTarget.closest('.op[data-op]')) && ui.preview != null) { ui.preview = null; renderMapa(); }
});
$('#dlg-urgencia').addEventListener('cancel', (ev) => { ev.preventDefault(); ui.urgMin = true; render(); });
$('#dlg-confirmar').addEventListener('close', () => { ui.pendiente = null; });

// zoom y arrastre del mapa
function vbActual() { return vistaMapa(ui.sel ? ui.estado.solicitudes[ui.sel] : null).slice(); }
function zoomRel(f, cx, cy) {
  const v = vbActual();
  const w = Math.max(80, Math.min(MAPA.w * 1.2, v[2] * f)), h = w * (v[3] / v[2]);
  const px = cx == null ? 0.5 : cx, py = cy == null ? 0.5 : cy;
  ui.mapa.vb = [v[0] + (v[2] - w) * px, v[1] + (v[3] - h) * py, w, h];
  renderMapa();
}
const arrastre = { activo: false, movio: false, x: 0, y: 0, vb: null };
$('#mapa-wrap').addEventListener('wheel', (ev) => {
  const svg = ev.target.closest('#svg-mapa'); if (!svg) return;
  ev.preventDefault();
  const r = svg.getBoundingClientRect();
  zoomRel(ev.deltaY > 0 ? 1.15 : 0.87, (ev.clientX - r.left) / r.width, (ev.clientY - r.top) / r.height);
}, { passive: false });
$('#mapa-wrap').addEventListener('pointerdown', (ev) => {
  const svg = ev.target.closest('#svg-mapa'); if (!svg) return;
  Object.assign(arrastre, { activo: true, movio: false, x: ev.clientX, y: ev.clientY, vb: vbActual(), w: svg.getBoundingClientRect().width });
});
window.addEventListener('pointermove', (ev) => {
  if (!arrastre.activo) return;
  const dx = ev.clientX - arrastre.x, dy = ev.clientY - arrastre.y;
  if (!arrastre.movio && Math.hypot(dx, dy) < 4) return;
  arrastre.movio = true;
  const k = arrastre.vb[2] / arrastre.w;
  ui.mapa.vb = [arrastre.vb[0] - dx * k, arrastre.vb[1] - dy * k, arrastre.vb[2], arrastre.vb[3]];
  const svg = $('#svg-mapa'); if (svg) svg.setAttribute('viewBox', ui.mapa.vb.join(' '));
});
window.addEventListener('pointerup', () => { if (arrastre.activo) { arrastre.activo = false; if (arrastre.movio) { renderMapa(); setTimeout(() => { arrastre.movio = false; }, 0); } } });

$('#btn-play').addEventListener('click', reproducir);
$('#btn-1').addEventListener('click', () => paso(1));
$('#btn-5').addEventListener('click', () => paso(5));
$('#btn-reset').addEventListener('click', () => cargar(ui.escId));
$('#btn-registrar').addEventListener('click', abrirRegistro);
$('#btn-acerca').addEventListener('click', () => $('#dlg-acerca').showModal());
$('#btn-cerrar-acerca').addEventListener('click', () => $('#dlg-acerca').close());
document.addEventListener('keydown', (ev) => {
  const op = ev.target.closest && ev.target.closest('.op[data-op]');
  if (op && (ev.key === 'Enter' || ev.key === ' ')) { ev.preventDefault(); ui.opSel = Number(op.dataset.op); render(); const n = document.querySelector('.op.sel'); if (n) n.focus(); return; }
  if (ev.target.matches('input, select, textarea, button') || document.querySelector('dialog[open]')) return;
  if (ev.key === ' ' && ui.vista === 'despacho') { ev.preventDefault(); reproducir(); }
});

// ---------- inicio ----------
$('#sel-esc').innerHTML = D.escenarios.map((s) => `<option value="${s.id_escenario}">${s.id_escenario}  ${esc(s.nombre)}</option>`).join('');
cargar('ESC-03');
window.__ui = ui;
})();

