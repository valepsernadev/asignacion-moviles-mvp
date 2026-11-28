/* =====================================================================
   Motor provisional (fase F1) del prototipo de despacho asistido.
   - Reglas R01–R07 filtran, la fórmula del Readme predice (matriz × factor),
     un puntaje con D01–D08 ordena y se devuelven las 3 mejores opciones.
   - Respeta los objetos del contrato: Solicitud, Movil, Prediccion,
     Recomendacion, Evento. Cuando P1/P2/P3 entreguen las piezas reales,
     estas funciones se reemplazan sin tocar la interfaz.
   ===================================================================== */
(function (root) {
  'use strict';

  const CLASES = {
    '01': { nombre: 'Emergencia', color: 'Rojo', obj: 15, prio: 0 },
    '02': { nombre: 'Urgencia', color: 'Naranja', obj: 20, prio: 1 },
    '07': { nombre: 'Priorizado', color: 'Amarillo', obj: 45, prio: 2 },
    '03': { nombre: 'Consulta', color: 'Verde', obj: 90, prio: 3 },
    '06': { nombre: 'Consulta banal', color: 'Azul', obj: 180, prio: 4 },
  };

  // Matriz de compatibilidad del documento 03
  const COMPAT = {
    '01': { TAM: 'PREF', TAB: 'PERM', VMD: 'ESTAB' },
    '02': { TAM: 'PERM', TAB: 'PREF', VMD: 'ESTAB' },
    '07': { TAM: 'NOREC', TAB: 'PERM_TRASLADO', VMD: 'PREF' },
    '03': { TAM: 'NOPERM', TAB: 'NOREC', VMD: 'PREF' },
    '06': { TAM: 'NOPERM', TAB: 'NOPERM', VMD: 'PREF' },
  };

  const TIPOS = { TAM: 'ambulancia medicalizada', TAB: 'ambulancia básica', VMD: 'vehículo médico domiciliario' };

  // Espejo de config.toml: pesos y umbrales (P2 los ajusta allá, no en el código)
  const CONFIG = {
    pesos: {
      '01': { eta: 1, retraso: 8, costo: 0.04, cobertura: 0.5, carga: 0.4 },
      '02': { eta: 1, retraso: 6, costo: 0.06, cobertura: 0.7, carga: 0.4 },
      '07': { eta: 0.4, retraso: 3, costo: 0.2, cobertura: 1, carga: 0.6 },
      '03': { eta: 0.15, retraso: 2, costo: 0.35, cobertura: 1.2, carga: 0.8 },
      '06': { eta: 0.1, retraso: 1, costo: 0.4, cobertura: 1.2, carga: 0.8 },
    },
    penalCompat: { PREF: 0, PERM: 4, NOREC: 25 },
    penalD05: 10,
    penalDesvio: 3,
    umbralCobertura: 20,      // D03
    cobertura: { porZona: 4, porMinuto: 0.3, tope: 25 },
    ventanaR04: 12,           // R04
    difD02: 3,                // D02
    rango: { bajo: 0.85, alto: 1.25 },
    esperaMaxPreasignacion: 45,
    retencionMediana: 53,     // D08 (histórico: p10 24, mediana 53, p90 104)
  };

  const MOTIVOS_TRASLADO_07 = ['Caídas', 'Heridas', 'Trauma craneal'];

  // ---------- contexto ----------
  function crearContexto(D) {
    const zIdx = {};
    D.zonas.forEach((z, i) => { zIdx[z.id] = i; });
    const zona = {};
    D.zonas.forEach((z) => { zona[z.id] = z; });
    const base = {};
    D.bases.forEach((b) => { base[b.id_base] = b; });
    const movil = {};
    D.moviles.forEach((m) => { movil[m.id_movil] = m; });
    const alta = D.zonas.filter((z) => z.d === 'A').map((z) => z.id);
    const pctTraslado = {};
    D.linea_base.forEach((r) => { pctTraslado[r.clasificacion] = r.pct_traslado; });
    return { D, zIdx, zona, base, movil, alta, pctTraslado };
  }

  function escenario(ctx, id) { return ctx.D.escenarios.find((e) => e.id_escenario === id); }

  function horaDe(esc, m) {
    const [f, h] = esc.fecha_hora_inicio.split(' ');
    const [Y, M, Dd] = f.split('-').map(Number);
    const [hh, mm] = h.split(':').map(Number);
    return new Date(Y, M - 1, Dd, hh, mm + m);
  }

  function factor(ctx, esc, m) {
    const t = horaDe(esc, m);
    const arr = ctx.D.F[esc.tipo_dia] || ctx.D.F.LUNES_A_VIERNES;
    return arr[t.getHours()];
  }

  // ---------- modelos (provisional: fórmula del Readme) ----------
  function predecirLlegada(ctx, zo, zd, esc, m) {
    const i = ctx.zIdx[zo], j = ctx.zIdx[zd];
    const f = factor(ctx, esc, m);
    const min = ctx.D.T[i][j] * f;
    return {
      minutos: min,
      bajo: Math.max(1, Math.floor(min * CONFIG.rango.bajo)),
      alto: Math.ceil(min * CONFIG.rango.alto),
      km: ctx.D.K[i][j],
      modelo: 'Fórmula del Readme (provisional)',
    };
  }

  function duracionAtencion(ctx, clas, tipo) {
    return ctx.D.dur_atencion[clas + '|' + tipo] || 30;
  }

  function predecirLiberacion(mv, m) {
    if (mv.libreEn == null) return null;
    const w = Math.max(0, mv.libreEn - m);
    if (mv.estado === 'EN_TRASLADO') {
      return { minutos: w, bajo: Math.max(0, Math.round(w * 0.6)), alto: Math.round(w * 1.6 + 5), modelo: 'Estimado de liberación (provisional)' };
    }
    return { minutos: w, bajo: Math.max(0, w - 5), alto: w + 10, modelo: 'Estimado de liberación (provisional)' };
  }

  // ---------- estado del escenario ----------
  function cargarEscenario(ctx, escId) {
    const esc = escenario(ctx, escId);
    const estado = {
      esc, minuto: 0, moviles: {}, solicitudes: {}, log: [], decisiones: [],
      eventosPend: ctx.D.eventos.filter((e) => e.id_escenario === escId).map((e) => Object.assign({}, e)),
      llegadasPend: ctx.D.solicitudes.filter((s) => s.id_escenario === escId).map((s) => Object.assign({}, s)),
      metricas: { minDescubiertos: 0, zonaMinDescubiertas: 0 },
      fin: esc.duracion_min,
    };
    ctx.D.estado_inicial.filter((r) => r.id_escenario === escId).forEach((r) => {
      const info = ctx.movil[r.id_movil];
      const b = ctx.base[r.id_base];
      const mv = {
        id: r.id_movil, tipo: r.tipo_movil, base: r.id_base, baseNombre: b.nombre_base, baseZona: b.id_zona,
        estado: r.estado, zona: r.id_zona_actual, nota: r.nota || '',
        costoKm: info.costo_km, costoHora: info.costo_hora,
        libreEn: null, retornoEn: null, llegaEn: null, origen: null, salida: null,
        servicio: null, rol: null, siguiente: null, servicios: 0, km: 0, costo: 0,
        apta: r.estado !== 'FUERA_SERVICIO', motivoNoApta: r.estado === 'FUERA_SERVICIO' ? (r.nota || 'Mantenimiento') : null,
        marcadaPorUsuario: false,
      };
      if (r.estado === 'EN_ATENCION' || r.estado === 'EN_TRASLADO') mv.libreEn = r.min_para_liberarse || 0;
      if (r.estado === 'RETORNANDO') mv.retornoEn = Math.round(predecirLlegada(ctx, mv.zona, mv.baseZona, esc, 0).minutos);
      estado.moviles[mv.id] = mv;
    });
    procesarMinuto(ctx, estado);
    return estado;
  }

  function listaSolicitudes(estado) { return Object.values(estado.solicitudes); }

  function completa(s) { return !!(s.zona && s.clas && CLASES[s.clas]); }
  function porCompletar(estado) {
    return listaSolicitudes(estado).filter((s) => s.estado === 'cola' && !completa(s))
      .sort((a, b) => ((a.clas && CLASES[a.clas] ? CLASES[a.clas].prio : 9) - (b.clas && CLASES[b.clas] ? CLASES[b.clas].prio : 9)) || (a.minLlegada - b.minLlegada));
  }
  function cola(estado) {
    return listaSolicitudes(estado)
      .filter((s) => s.estado === 'cola' && completa(s))
      .sort((a, b) => (CLASES[a.clas].prio - CLASES[b.clas].prio) || (a.minCola - b.minCola));
  }

  function registrar(estado, tipo, texto, datos) {
    const ev = { hora: estado.minuto, tipo, texto, datos: datos || {} };
    estado.log.push(ev);
    return ev;
  }

  function posicionActual(mv, m) {
    if (mv.estado !== 'EN_RUTA') return mv.zona;
    const total = Math.max(1, mv.llegaEn - mv.salida);
    return (m - mv.salida) < total / 2 ? mv.origen : mv.zona;
  }

  function disponibleAhora(mv) {
    return mv.apta && (mv.estado === 'DISPONIBLE' || mv.estado === 'RETORNANDO') && !mv.siguiente;
  }

  function esAmbulancia(tipo) { return tipo === 'TAM' || tipo === 'TAB'; }

  function posibleTraslado(sol) {
    if (sol.clas === '01' || sol.clas === '02') return true;
    if (!sol.motivo) return false;
    if (sol.clas === '07') {
      if (MOTIVOS_TRASLADO_07.includes(sol.motivo)) return true;
      if (sol.motivo === 'Diarrea y vómitos' && /deshidrat/i.test(sol.discriminador || '')) return true;
    }
    return false;
  }

  function hash(s) { let h = 0; for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) % 1000; return h; }

  function necesitaTraslado(ctx, sol) {
    if (sol.trasladoDecidido != null) return sol.trasladoDecidido;
    const p = ctx.pctTraslado[sol.clas] || 0;
    sol.trasladoDecidido = (hash(sol.id) % 100) < p;
    return sol.trasladoDecidido;
  }

  function centroMasCercano(ctx, zonaId, esc, m) {
    let best = null;
    ctx.D.centros.forEach((c) => {
      const t = predecirLlegada(ctx, zonaId, c.zona, esc, m).minutos;
      if (!best || t < best.t) best = { c, t };
    });
    return best;
  }

  // ---------- transiciones ----------
  function despachar(ctx, estado, mv, sol, rol) {
    const m = estado.minuto;
    const desde = posicionActual(mv, m);
    const p = predecirLlegada(ctx, desde, sol.zona, estado.esc, m);
    mv.estado = 'EN_RUTA';
    mv.origen = desde;
    mv.zona = sol.zona;
    mv.salida = m;
    mv.llegaEn = m + Math.max(1, Math.round(p.minutos));
    mv.servicio = sol.id;
    mv.rol = rol;
    mv.siguiente = null;
    mv.servicios += 1;
    mv.km += p.km;
    const horas = (p.minutos + duracionAtencion(ctx, sol.clas, mv.tipo)) / 60;
    mv.costo += p.km * mv.costoKm + horas * mv.costoHora;
    sol.enRuta = sol.enRuta || [];
    sol.enRuta.push({ movil: mv.id, rol, llegaEn: mv.llegaEn });
  }

  function finalizar(ctx, estado, mv) {
    const m = estado.minuto;
    const sol = mv.servicio ? estado.solicitudes[mv.servicio] : null;
    mv.servicio = null; mv.rol = null; mv.libreEn = null; mv.llegaEn = null;
    if (sol) {
      const activos = Object.values(estado.moviles).filter((x) => x.servicio === sol.id);
      if (!activos.length && sol.estado !== 'cola') sol.estado = 'cerrada';
    }
    if (mv.zona === mv.baseZona) { mv.estado = 'DISPONIBLE'; mv.retornoEn = null; }
    else {
      mv.estado = 'RETORNANDO';
      mv.retornoEn = m + Math.max(1, Math.round(predecirLlegada(ctx, mv.zona, mv.baseZona, estado.esc, m).minutos));
    }
    activarSiguiente(ctx, estado, mv);
  }

  function activarSiguiente(ctx, estado, mv) {
    if (!mv.siguiente || !mv.apta) return;
    const sig = mv.siguiente;
    const sol = estado.solicitudes[sig.sol];
    mv.siguiente = null;
    if (!sol || sol.estado === 'cancelada' || sol.estado === 'cerrada') return;
    despachar(ctx, estado, mv, sol, sig.rol);
    registrar(estado, 'decision', `${mv.id} se liberó y sale hacia ${sol.id} (estaba preasignada).`, { movil: mv.id, sol: sol.id });
  }

  function llegar(ctx, estado, mv) {
    const m = estado.minuto;
    const sol = estado.solicitudes[mv.servicio];
    if (sol && sol.estado === 'cancelada') { finalizar(ctx, estado, mv); return; }
    mv.estado = 'EN_ATENCION';
    mv.llegaEn = m;
    if (!sol) { mv.libreEn = m + 20; return; }
    sol.llegadas.push({ movil: mv.id, tipo: mv.tipo, rol: mv.rol, min: m });
    if (sol.primeraLlegada == null) sol.primeraLlegada = m;
    if (sol.necesitaAmb && esAmbulancia(mv.tipo) && sol.ambLlegada == null) {
      sol.ambLlegada = m;
      Object.values(estado.moviles).forEach((x) => {
        if (x.servicio === sol.id && x.tipo === 'VMD' && x.estado === 'EN_ATENCION') x.libreEn = m + 5;
      });
    }
    if (sol.estado !== 'cola') sol.estado = 'en_atencion';
    if (mv.rol === 'PRIMER_RESPONDIENTE_ESTABILIZACION') {
      const ambYa = sol.llegadas.some((l) => esAmbulancia(l.tipo));
      mv.libreEn = ambYa ? m + 5 : null;
    } else {
      mv.libreEn = m + Math.round(duracionAtencion(ctx, sol.clas, mv.tipo));
      if (esAmbulancia(mv.tipo)) {
        Object.values(estado.moviles).forEach((x) => {
          if (x.servicio === sol.id && x.rol === 'PRIMER_RESPONDIENTE_ESTABILIZACION' && x.estado === 'EN_ATENCION') x.libreEn = m + 5;
        });
      }
    }
    registrar(estado, 'llegada', `${mv.id} llegó a ${sol.id} (${m - sol.minLlegada} min desde la solicitud).`, { movil: mv.id, sol: sol.id });
  }

  function iniciarTraslado(ctx, estado, mv, sol) {
    const m = estado.minuto;
    const c = centroMasCercano(ctx, mv.zona, estado.esc, m);
    mv.estado = 'EN_TRASLADO';
    mv.zona = c.c.zona;
    mv.libreEn = m + Math.round(c.t) + CONFIG.retencionMediana;
    if (sol) sol.destino = c.c.nombre;
    registrar(estado, 'traslado', `${mv.id} traslada a ${c.c.nombre}; se estima libre en ~${Math.round(c.t) + CONFIG.retencionMediana} min (D08).`, { movil: mv.id, sol: sol && sol.id });
  }

  function terminarAtencion(ctx, estado, mv, traslado) {
    const sol = mv.servicio ? estado.solicitudes[mv.servicio] : null;
    const puede = sol && esAmbulancia(mv.tipo) && mv.rol !== 'PRIMER_RESPONDIENTE_ESTABILIZACION';
    const quiere = traslado == null ? (puede && necesitaTraslado(ctx, sol)) : traslado;
    if (puede && quiere) iniciarTraslado(ctx, estado, mv, sol);
    else finalizar(ctx, estado, mv);
  }

  function transiciones(ctx, estado) {
    const m = estado.minuto;
    Object.values(estado.moviles).forEach((mv) => {
      if (mv.estado === 'EN_RUTA' && m >= mv.llegaEn) {
        llegar(ctx, estado, mv);
      } else if (mv.estado === 'EN_ATENCION' && mv.libreEn != null && m >= mv.libreEn) {
        terminarAtencion(ctx, estado, mv, null);
      } else if (mv.estado === 'EN_TRASLADO' && mv.libreEn != null && m >= mv.libreEn) {
        registrar(estado, 'liberacion', `${mv.id} quedó libre tras el traslado.`, { movil: mv.id });
        finalizar(ctx, estado, mv);
      } else if (mv.estado === 'RETORNANDO' && mv.retornoEn != null && m >= mv.retornoEn) {
        mv.estado = 'DISPONIBLE'; mv.zona = mv.baseZona; mv.retornoEn = null;
      }
    });
  }

  // ---------- panel de la tripulación ----------
  function tripulacion(ctx, estado, id, accion, dato) {
    const mv = estado.moviles[id];
    const m = estado.minuto;
    const sol = mv.servicio ? estado.solicitudes[mv.servicio] : null;
    if (accion === 'llegue' && mv.estado === 'EN_RUTA') {
      llegar(ctx, estado, mv);
      return registrar(estado, 'tripulacion', `${id} reportó llegada al sitio.`, { movil: id, sol: sol && sol.id });
    }
    if (accion === 'termine' && mv.estado === 'EN_ATENCION') {
      if (sol && !mv.servicio) return null;
      if (mv.rol === 'PRIMER_RESPONDIENTE_ESTABILIZACION' && sol && !sol.llegadas.some((l) => esAmbulancia(l.tipo))) {
        return registrar(estado, 'alerta', `${id} no puede terminar: espera la ambulancia que trasladará al paciente (R04).`, { movil: id, alerta: true });
      }
      if (sol) sol.trasladoDecidido = !!dato;
      terminarAtencion(ctx, estado, mv, !!dato);
      return registrar(estado, 'tripulacion', `${id} reportó fin de la atención${dato ? ' con traslado' : ''}.`, { movil: id, sol: sol && sol.id });
    }
    if (accion === 'libre' && mv.estado === 'EN_TRASLADO') {
      finalizar(ctx, estado, mv);
      return registrar(estado, 'tripulacion', `${id} entregó al paciente y quedó libre.`, { movil: id });
    }
    if (accion === 'reclasificar' && sol && mv.estado === 'EN_ATENCION') {
      return aplicarEvento(ctx, estado, { tipo_evento: 'RECLASIFICACION_EN_SITIO', id_solicitud: sol.id, id_movil: id, nueva_clasificacion: dato, detalle: `Reportado por la tripulación de ${id}` });
    }
    if (accion === 'novedad') { marcarNoApta(ctx, estado, id, dato); return registrar(estado, 'tripulacion', `${id} reportó una novedad: ${dato}.`, { movil: id, alerta: true }); }
    if (accion === 'disponible') { marcarApta(ctx, estado, id); return registrar(estado, 'tripulacion', `${id} reportó que vuelve a estar disponible.`, { movil: id }); }
    return null;
  }

  function aplicarEvento(ctx, estado, e) {
    const m = estado.minuto;
    const sol = e.id_solicitud ? estado.solicitudes[e.id_solicitud] : null;
    if (e.tipo_evento === 'MOVIL_LIBERADA') {
      let mv = e.id_movil ? estado.moviles[e.id_movil] : null;
      if (sol) {
        const atiende = Object.values(estado.moviles).find((x) => x.servicio === sol.id && x.estado === 'EN_ATENCION');
        if (atiende) mv = atiende;
      }
      if (mv && (mv.estado === 'EN_ATENCION' || mv.estado === 'EN_TRASLADO')) {
        if (sol) sol.trasladoDecidido = false;
        finalizar(ctx, estado, mv);
        return registrar(estado, 'liberacion', `${mv.id} quedó libre: ${e.detalle}.`, { movil: mv.id, sol: sol && sol.id });
      }
      return registrar(estado, 'info', `Evento del escenario: ${e.detalle}.`, {});
    }
    if (e.tipo_evento === 'RECLASIFICACION_EN_SITIO' && sol) {
      const antes = sol.clas;
      sol.clas = e.nueva_clasificacion;
      sol.historial.push({ min: m, de: antes, a: sol.clas, origen: 'En sitio' });
      const sube = CLASES[sol.clas].prio < CLASES[antes].prio;
      const vmd = Object.values(estado.moviles).find((x) => x.servicio === sol.id && x.tipo === 'VMD' && x.estado === 'EN_ATENCION');
      if (sube && (sol.clas === '01' || sol.clas === '02') && vmd) {
        sol.necesitaAmb = true; sol.reclasMin = m; sol.estado = 'cola'; sol.minCola = m; sol.detalleReclas = e.detalle;
        vmd.rol = 'PRIMER_RESPONDIENTE_ESTABILIZACION'; vmd.libreEn = null;
        return registrar(estado, 'reclasificacion', `${sol.id} se reclasificó en sitio de ${antes} a ${sol.clas}: ${e.detalle}. Se necesita ambulancia; ${vmd.id} acompaña hasta que llegue.`, { sol: sol.id, alerta: true });
      }
      if (!sube) sol.trasladoDecidido = false;
      return registrar(estado, 'reclasificacion', `${sol.id} se reclasificó en sitio de ${antes} a ${sol.clas}: ${e.detalle}.`, { sol: sol.id });
    }
    if (e.tipo_evento === 'RECLASIFICACION_TELEFONICA' && sol) {
      const antes = sol.clas;
      sol.clas = e.nueva_clasificacion;
      sol.historial.push({ min: m, de: antes, a: sol.clas, origen: 'Telefónica' });
      return registrar(estado, 'reclasificacion', `Reclasificación telefónica de ${sol.id}: de ${antes} a ${sol.clas} (${e.detalle}). La cola se reordenó.`, { sol: sol.id, alerta: sol.clas === '01' || sol.clas === '02' });
    }
    if (e.tipo_evento === 'CANCELACION' && sol) {
      sol.estado = 'cancelada'; sol.cancelada = m;
      Object.values(estado.moviles).forEach((x) => {
        if (x.siguiente && x.siguiente.sol === sol.id) x.siguiente = null;
        if (x.servicio === sol.id) {
          const pos = posicionActual(x, m);
          x.zona = pos; x.servicio = null; x.rol = null; x.llegaEn = null;
          x.estado = pos === x.baseZona ? 'DISPONIBLE' : 'RETORNANDO';
          x.retornoEn = m + Math.max(1, Math.round(predecirLlegada(ctx, pos, x.baseZona, estado.esc, m).minutos));
        }
      });
      return registrar(estado, 'cancelacion', `${sol.id} cancelada por el usuario: ${e.detalle}.`, { sol: sol.id });
    }
    if (e.tipo_evento === 'REASIGNACION') {
      return registrar(estado, 'referencia', `En la operación real: ${e.detalle}. Aquí decide el usuario.`, {});
    }
    return registrar(estado, 'info', e.detalle || e.tipo_evento, {});
  }

  function registrarSolicitud(estado, datos) {
    estado.manuales = (estado.manuales || 0) + 1;
    const id = 'REG-' + String(estado.manuales).padStart(2, '0');
    nuevaSolicitud(estado, {
      id_solicitud: id, minuto_llegada: estado.minuto, id_zona: datos.zona || null, comuna: datos.comuna || null, municipio: datos.municipio || null,
      clasificacion_inicial: datos.clas || null, escala_manchester: datos.clas ? CLASES[datos.clas].color.toUpperCase() : null,
      motivo_consulta: datos.motivo || null, discriminador: datos.discriminador || null, canal: datos.canal || null,
    });
    estado.solicitudes[id].manual = true;
    return estado.solicitudes[id];
  }

  function completarZona(ctx, estado, solId, zona) {
    const s = estado.solicitudes[solId];
    const z = ctx.zona[zona];
    s.zona = zona; s.comuna = z.co; s.municipio = z.mu; s.zonaVerificada = estado.minuto;
    registrar(estado, 'info', `${solId}: zona verificada (${z.n}). Ya se pueden calcular las opciones.`, { sol: solId });
  }

  function devolverATriaje(estado, solId) {
    const s = estado.solicitudes[solId];
    s.estado = 'devuelta';
    registrar(estado, 'info', `${solId} se devolvió a triaje porque llegó sin clasificación.`, { sol: solId });
  }

  function nuevaSolicitud(estado, r) {
    const s = {
      id: r.id_solicitud, minLlegada: r.minuto_llegada, minCola: r.minuto_llegada,
      zona: r.id_zona, comuna: r.comuna, municipio: r.municipio,
      clas: r.clasificacion_inicial, clasIni: r.clasificacion_inicial, manchester: r.escala_manchester,
      motivo: r.motivo_consulta, discriminador: r.discriminador, canal: r.canal || null,
      estado: 'cola', asignaciones: [], llegadas: [], primeraLlegada: null,
      historial: [], necesitaAmb: false, reclasMin: null, ambLlegada: null, trasladoDecidido: null,
    };
    estado.solicitudes[s.id] = s;
    if (!completa(s)) {
      const falta = [!s.clas || !CLASES[s.clas] ? 'clasificación' : null, !s.zona ? 'zona' : null].filter(Boolean).join(' y ');
      registrar(estado, 'solicitud', `Llegó ${s.id} sin ${falta}. Quedó en "Por completar".`, { sol: s.id, alerta: true, incompleta: true });
      return;
    }
    registrar(estado, 'solicitud', `Nueva solicitud ${s.id}: ${s.clas} ${CLASES[s.clas].nombre.toLowerCase()} en ${s.comuna}.`, { sol: s.id, alerta: s.clas === '01' || s.clas === '02' });
  }

  function procesarMinuto(ctx, estado) {
    const m = estado.minuto;
    transiciones(ctx, estado);
    estado.llegadasPend.filter((r) => r.minuto_llegada === m).forEach((r) => nuevaSolicitud(estado, r));
    estado.eventosPend.filter((e) => e.minuto === m).forEach((e) => aplicarEvento(ctx, estado, e));
    // varios pacientes en el mismo punto
    const sols = listaSolicitudes(estado);
    sols.forEach((s) => {
      s.variosPacientes = !!s.zona && sols.some((o) => o !== s && o.zona === s.zona && Math.abs(o.minLlegada - s.minLlegada) <= 5);
    });
    const cov = coberturaZonas(ctx, estado, null);
    const desc = cov.filter((c) => c.min > CONFIG.umbralCobertura).length;
    if (desc > 0) estado.metricas.minDescubiertos += 1;
    estado.metricas.zonaMinDescubiertas += desc;
    estado.coberturaActual = cov;
  }

  function avanzar(ctx, estado, n) {
    const evs = [];
    for (let k = 0; k < (n || 1); k++) {
      const antes = estado.log.length;
      estado.minuto += 1;
      procesarMinuto(ctx, estado);
      evs.push.apply(evs, estado.log.slice(antes));
    }
    return evs;
  }

  // ---------- cobertura (factor diferencial) ----------
  function ambulanciasDisponibles(estado, excluir) {
    return Object.values(estado.moviles).filter((mv) => esAmbulancia(mv.tipo) && disponibleAhora(mv) && !(excluir && excluir.includes(mv.id)));
  }

  function coberturaZonas(ctx, estado, excluir) {
    const ambs = ambulanciasDisponibles(estado, excluir);
    return ctx.alta.map((z) => {
      let best = { min: Infinity, movil: null };
      ambs.forEach((a) => {
        const t = predecirLlegada(ctx, a.zona, z, estado.esc, estado.minuto).minutos;
        if (t < best.min) best = { min: t, movil: a.id };
      });
      return { zona: z, min: best.min, movil: best.movil };
    });
  }

  function impactoCobertura(ctx, estado, idsCandidata, sol) {
    const U = CONFIG.umbralCobertura;
    const antes = estado.coberturaActual || coberturaZonas(ctx, estado, null);
    const quita = idsCandidata.filter((id) => { const mv = estado.moviles[id]; return esAmbulancia(mv.tipo) && disponibleAhora(mv); });
    const despues = quita.length ? coberturaZonas(ctx, estado, quita) : antes;
    const nuevas = [];
    let extra = 0, maxPerdidos = 0;
    despues.forEach((d, i) => {
      const a = antes[i];
      const exA = Math.max(0, Math.min(a.min, 90) - U), exD = Math.max(0, Math.min(d.min, 90) - U);
      extra += exD - exA;
      if (d.min > U && a.min <= U) nuevas.push({ zona: d.zona, min: d.min, antes: a.min });
      if (isFinite(d.min) && isFinite(a.min)) maxPerdidos = Math.max(maxPerdidos, d.min - a.min);
    });
    const cc = CONFIG.cobertura;
    const penal = Math.min(cc.tope, cc.porZona * nuevas.length + cc.porMinuto * extra);
    // plan B: ambulancia más cercana a la zona del paciente sin la candidata
    let planB = null;
    if (sol) {
      ambulanciasDisponibles(estado, idsCandidata).forEach((a) => {
        const t = predecirLlegada(ctx, a.zona, sol.zona, estado.esc, estado.minuto).minutos;
        if (!planB || t < planB.min) planB = { movil: a.id, tipo: a.tipo, min: t };
      });
    }
    return { antes, despues, nuevasDescubiertas: nuevas.sort((x, y) => y.min - x.min), penalizacion: penal, maxPerdidos, planB };
  }

  // ---------- recomendar ----------
  function compatDe(sol, tipo) {
    let c = COMPAT[sol.clas][tipo];
    if (c === 'PERM_TRASLADO') c = posibleTraslado(sol) ? 'PERM' : 'NOREC';
    return c;
  }

  function evaluarCandidata(ctx, estado, sol, mv, opts) {
    opts = opts || {};
    const m = estado.minuto;
    const comp = compatDe(sol, mv.tipo);
    if (!mv.apta) return { excluida: `No apta: ${mv.motivoNoApta}` };
    if (sol.necesitaAmb && mv.tipo === 'VMD') return { excluida: 'Ya hay médico en el sitio; se necesita ambulancia' };
    if (comp === 'NOPERM') return { excluida: `${mv.tipo} no está permitida para un ${sol.clas}` };
    if (comp === 'ESTAB') return { excluida: `VMD solo estabiliza en un ${sol.clas} (R04, D07)`, estab: true };
    let tipoOp = 'directa', espera = 0, desde = mv.zona, rangoEspera = [0, 0];
    if (disponibleAhora(mv)) {
      tipoOp = 'directa';
    } else if (mv.estado === 'EN_RUTA') {
      const actual = estado.solicitudes[mv.servicio];
      if (actual && actual.id === sol.id) return { excluida: 'Ya va hacia esta solicitud' };
      if ((sol.clas === '01' || sol.clas === '02') && actual && (actual.clas === '03' || actual.clas === '06')) {
        tipoOp = 'desvio'; desde = posicionActual(mv, m);
      } else return { excluida: `En ruta a ${actual ? actual.id + ' (' + actual.clas + ')' : 'otro servicio'}` };
    } else if (mv.estado === 'EN_ATENCION' || mv.estado === 'EN_TRASLADO') {
      if (mv.siguiente) return { excluida: `Ya preasignada a ${mv.siguiente.sol}` };
      const lib = predecirLiberacion(mv, m);
      if (!lib) return { excluida: 'En el sitio, sin hora de liberación' };
      if (lib.minutos > CONFIG.esperaMaxPreasignacion && !opts.sinLimite) return { excluida: `Se libera en ~${lib.minutos} min`, liberaEn: lib.minutos };
      tipoOp = 'preasignacion'; espera = lib.minutos; rangoEspera = [lib.bajo, lib.alto];
    } else if (mv.siguiente) {
      return { excluida: `Ya preasignada a ${mv.siguiente.sol}` };
    } else {
      return { excluida: mv.estado };
    }
    const p = predecirLlegada(ctx, desde, sol.zona, estado.esc, m);
    const eta = espera + p.minutos;
    const llegada = {
      minutos: eta,
      bajo: Math.max(1, Math.floor(rangoEspera[0] + p.bajo)),
      alto: Math.ceil(rangoEspera[1] + p.alto),
      modelo: p.modelo,
    };
    const horas = (p.minutos + duracionAtencion(ctx, sol.clas, mv.tipo)) / 60;
    const costo = p.km * mv.costoKm + horas * mv.costoHora;
    const imp = impactoCobertura(ctx, estado, [mv.id], sol);
    return { mv, comp, tipoOp, espera, llegada, km: p.km, costo, imp };
  }

  function puntuar(sol, c, hayTabATiempo) {
    const w = CONFIG.pesos[sol.clas];
    const obj = CLASES[sol.clas].obj;
    const reglas = ['D01'];
    let s = w.eta * c.llegada.minutos + w.retraso * Math.max(0, c.llegada.minutos - obj) + w.costo * (c.costo / 1000) +
      w.cobertura * Math.max(0, c.imp.penalizacion) + w.carga * c.mv.servicios + (CONFIG.penalCompat[c.comp] || 0);
    if (c.imp.penalizacion > 0 || c.imp.nuevasDescubiertas.length) reglas.push('D03');
    if (sol.clas === '02' && c.mv.tipo === 'TAM' && hayTabATiempo) { s += CONFIG.penalD05; reglas.push('D05'); }
    if (sol.clas === '07' && c.mv.tipo === 'TAB' && posibleTraslado(sol)) reglas.push('D06');
    if (c.tipoOp === 'desvio') { s += CONFIG.penalDesvio; reglas.push('R06'); }
    if (c.tipoOp === 'preasignacion') { reglas.push('D08'); s += w.eta * 0.5 * (c.llegada.alto - c.llegada.minutos) + 2; }
    if (c.mv.servicios > 0) reglas.push('D04');
    return { s, reglas };
  }

  function nombreZona(ctx, id) { const z = ctx.zona[id]; return z ? z.n : id; }
  function fmtMin(x) { return isFinite(x) ? Math.round(x) : '–'; }
  function fmtCosto(x) { return '$' + Math.round(x / 1000) + ' mil'; }

  function frase(ctx, sol, op, mejorEta, ref) {
    const obj = CLASES[sol.clas].obj;
    const eta = Math.round(op.llegada.minutos);
    const partes = [];
    if (op.tipo === 'estabilizacion') {
      if (!op.ambulancia) return `No hay ambulancia elegible. La ${op.movil.id} llega en ${eta} min a estabilizar; asigne la primera ambulancia que se libere (R04).`;
      return `Ninguna ambulancia llega a tiempo (la primera, ${op.ambulancia.id}, en ${fmtMin(op.ambulancia.eta)} min). La ${op.movil.id}${op.desvioDe ? ', que iba a una consulta,' : ''} llega ${fmtMin(op.ambulancia.eta - op.llegada.minutos)} min antes a estabilizar y ${op.ambulancia.id} queda preasignada (R04).`;
    }
    if (op.tipo === 'preasignacion') partes.push(`Está ocupada y se libera en ~${Math.round(op.espera)} min; llegaría en ${eta} min`);
    else if (op.tipo === 'desvio') partes.push(`Va hacia una ${op.desvioDe.clas === '06' ? 'consulta banal' : 'consulta'} (${op.desvioDe.id}); si se desvía llega en ${eta} min y esa consulta vuelve a la cola (R06)`);
    else if (ref && ref !== op && Math.abs(op.llegada.minutos - ref.llegada.minutos) < 1.5) {
      const dc = Math.round((op.costo - ref.costo) / 1000);
      partes.push(`Llega casi igual que la recomendada (${eta} min)` + (Math.abs(dc) >= 2 ? ` y cuesta $${Math.abs(dc)} mil ${dc > 0 ? 'más' : 'menos'}` : '') + (op.cargaTurno > ref.cargaTurno ? `; lleva ${op.cargaTurno} servicios en el turno (D04)` : ''));
    }
    else if (Math.abs(op.llegada.minutos - mejorEta) < 0.5) partes.push(`Es la ${op.movil.tipo} que llega antes: ${eta} min frente a un objetivo de ${obj}`);
    else {
      const d = Math.round(op.llegada.minutos - mejorEta);
      partes.push(`Llega en ${eta} min, ${d} min después de la más rápida${op.reglas.includes('D02') ? ', pero cuesta menos (D02)' : ''}`);
    }
    if (op.comp === 'NOREC') partes.push(`no se recomienda una ${op.movil.tipo} para un ${sol.clas}`);
    if (op.reglas.includes('D05')) partes.push('compromete una TAM habiendo TAB a tiempo (D05)');
    const nd = op.cobertura.nuevasDescubiertas;
    if (nd.length) partes.push(`deja ${nombreZona(ctx, nd[0].zona)} a ${fmtMin(nd[0].min)} min de una ambulancia${nd.length > 1 ? ` y ${nd.length - 1} zona${nd.length > 2 ? 's' : ''} más sobre 20` : ''}`);
    else if (esAmbulancia(op.movil.tipo) && op.tipo !== 'preasignacion') partes.push('no deja zonas ALTA sin ambulancia a 20 min');
    if (eta > obj && op.tipo !== 'estabilizacion') partes.push(`supera el objetivo por ${eta - obj} min`);
    let t = partes.join('; ');
    return t.charAt(0).toUpperCase() + t.slice(1) + '.';
  }

  function recomendar(ctx, estado, solId, opts) {
    opts = opts || {};
    const sol = estado.solicitudes[solId];
    if (!completa(sol)) {
      return { solicitud: sol.id, hora: estado.minuto, opciones: [], todas: [], excluidas: [], bloqueo: !sol.clas || !CLASES[sol.clas] ? 'clasificacion' : 'zona' };
    }
    const obj = CLASES[sol.clas].obj;
    const elegibles = [], excluidas = [];
    Object.values(estado.moviles).forEach((mv) => {
      const r = evaluarCandidata(ctx, estado, sol, mv, opts);
      if (r.excluida) excluidas.push({ movil: { id: mv.id, tipo: mv.tipo }, motivo: r.excluida, estab: !!r.estab, liberaEn: r.liberaEn });
      else elegibles.push(r);
    });
    const hayTab = elegibles.some((c) => c.mv.tipo === 'TAB' && c.llegada.minutos <= obj);
    elegibles.forEach((c) => {
      const p = puntuar(sol, c, hayTab);
      c.puntaje = p.s; c.reglas = p.reglas;
    });
    elegibles.sort((a, b) => a.puntaje - b.puntaje);
    const mejorEta = elegibles.length ? Math.min.apply(null, elegibles.map((c) => c.llegada.minutos)) : Infinity;
    // D02: si la más rápida y otra difieren < 3 min, preferir la de menor costo
    if (elegibles.length > 1) {
      const a = elegibles[0], b = elegibles[1];
      if (b.llegada.minutos < a.llegada.minutos + 0.01 && Math.abs(a.llegada.minutos - b.llegada.minutos) < CONFIG.difD02 && a.costo < b.costo) a.reglas.push('D02');
      if (a.llegada.minutos > mejorEta && a.llegada.minutos - mejorEta < CONFIG.difD02) a.reglas.push('D02');
    }
    const aOpcion = (c) => ({
      movil: { id: c.mv.id, tipo: c.mv.tipo },
      moviles: [{ id: c.mv.id, rol: rolPara(sol, c.mv.tipo) }],
      tipo: c.tipoOp, comp: c.comp, espera: c.espera,
      llegada: c.llegada, costo: c.costo, km: c.km,
      cobertura: c.imp, planB: c.imp.planB,
      reglas: Array.from(new Set(c.reglas)), puntaje: c.puntaje,
      desvioDe: c.tipoOp === 'desvio' ? estado.solicitudes[c.mv.servicio] : null,
      cargaTurno: c.mv.servicios,
    });
    let opciones = elegibles.map(aOpcion);
    // R04: VMD como primer respondiente
    if ((sol.clas === '01' || sol.clas === '02') && !sol.necesitaAmb) {
      const ambs = opciones.filter((o) => esAmbulancia(o.movil.tipo));
      const mejorAmb = ambs.slice().sort((x, y) => x.llegada.minutos - y.llegada.minutos)[0];
      let mejorV = null;
      Object.values(estado.moviles).forEach((mv) => {
        if (mv.tipo !== 'VMD' || !mv.apta) return;
        let desvio = null;
        if (!disponibleAhora(mv)) {
          const act = mv.estado === 'EN_RUTA' ? estado.solicitudes[mv.servicio] : null;
          if (!act || !(act.clas === '03' || act.clas === '06')) return;
          desvio = act;
        }
        const p = predecirLlegada(ctx, posicionActual(mv, estado.minuto), sol.zona, estado.esc, estado.minuto);
        if (!mejorV || p.minutos < mejorV.p.minutos) mejorV = { mv, p, desvio };
      });
      if (mejorV && (!mejorAmb || (mejorAmb.llegada.minutos > obj && mejorV.p.minutos <= mejorAmb.llegada.minutos - CONFIG.ventanaR04))) {
        const ids = [mejorV.mv.id].concat(mejorAmb ? [mejorAmb.movil.id] : []);
        const imp = impactoCobertura(ctx, estado, ids, sol);
        const horas = (mejorV.p.minutos + duracionAtencion(ctx, sol.clas, 'VMD')) / 60;
        const combo = {
          movil: { id: mejorV.mv.id, tipo: 'VMD' },
          moviles: [{ id: mejorV.mv.id, rol: 'PRIMER_RESPONDIENTE_ESTABILIZACION' }].concat(mejorAmb ? [{ id: mejorAmb.movil.id, rol: 'ATENCION_Y_TRASLADO' }] : []),
          ambulancia: mejorAmb ? { id: mejorAmb.movil.id, tipo: mejorAmb.movil.tipo, eta: mejorAmb.llegada.minutos, bajo: mejorAmb.llegada.bajo, alto: mejorAmb.llegada.alto } : null,
          tipo: 'estabilizacion', comp: 'PREF', espera: 0,
          llegada: { minutos: mejorV.p.minutos, bajo: mejorV.p.bajo, alto: mejorV.p.alto, modelo: mejorV.p.modelo },
          costo: mejorV.p.km * mejorV.mv.costoKm + horas * mejorV.mv.costoHora + (mejorAmb ? mejorAmb.costo : 0),
          km: mejorV.p.km + (mejorAmb ? mejorAmb.km : 0),
          cobertura: imp, planB: imp.planB, reglas: ['R04', 'D01'], puntaje: -Infinity, desvioDe: null,
        };
        opciones = [combo].concat(opciones);
      }
    }
    // D07: VMD de apoyo para un 01 atendido por TAB
    let apoyo = null;
    const yaHayVmd = Object.values(estado.moviles).some((x) => x.tipo === 'VMD' && x.servicio === sol.id);
    if (sol.clas === '01' && !sol.necesitaAmb && !yaHayVmd && opciones[0] && opciones[0].movil.tipo === 'TAB' && opciones[0].tipo !== 'estabilizacion') {
      Object.values(estado.moviles).forEach((mv) => {
        if (mv.tipo !== 'VMD' || !disponibleAhora(mv)) return;
        const p = predecirLlegada(ctx, mv.zona, sol.zona, estado.esc, estado.minuto);
        if (p.minutos <= obj + 5 && (!apoyo || p.minutos < apoyo.min)) apoyo = { id: mv.id, min: p.minutos };
      });
      if (apoyo) opciones[0].reglas.push('D07');
    }
    const top = opciones.slice(0, 3).map((o, i) => {
      o.puesto = i + 1;
      o.etiqueta = i === 0 ? (o.comp === 'NOREC' ? 'Única opción (no recomendada)' : 'Recomendada') : (o.comp === 'NOREC' ? 'No recomendada' : 'Alternativa');
      o.explicacion = frase(ctx, sol, o, mejorEta, opciones[0]);
      return o;
    });
    if (top[0] && apoyo) top[0].apoyo = apoyo;
    opciones.forEach((o) => { if (!o.explicacion) o.explicacion = frase(ctx, sol, o, mejorEta, opciones[0]); });
    const res = { solicitud: sol.id, hora: estado.minuto, opciones: top, todas: opciones, excluidas };
    if (!top.length && !opts.sinLimite) {
      const amplio = recomendar(ctx, estado, solId, { sinLimite: true });
      res.sinUnidades = true;
      res.primerasEnLiberarse = amplio.todas.filter((o) => o.tipo === 'preasignacion').sort((a, b) => a.llegada.minutos - b.llegada.minutos).slice(0, 3);
    }
    return res;
  }

  // Competencia: otras solicitudes igual o más urgentes cuya primera opción usa la misma móvil
  function competencia(ctx, estado, solId, opcion) {
    const sol = estado.solicitudes[solId];
    const ids = opcion.moviles.map((x) => x.id);
    const out = [];
    cola(estado).forEach((o) => {
      if (o.id === solId || CLASES[o.clas].prio > CLASES[sol.clas].prio) return;
      const r = recomendar(ctx, estado, o.id);
      const t = r.opciones[0];
      if (!t || !t.moviles.some((x) => ids.includes(x.id))) return;
      const alt = r.todas.find((x) => !x.moviles.some((y) => ids.includes(y.id)));
      out.push({ sol: o, top: t, alternativa: alt || null });
    });
    return out;
  }

  // Corregir una asignación mientras la móvil va en ruta o está preasignada
  function puedeCorregir(estado, solId) {
    return Object.values(estado.moviles).some((x) => (x.servicio === solId && x.estado === 'EN_RUTA') || (x.siguiente && x.siguiente.sol === solId));
  }
  function corregirAsignacion(ctx, estado, solId) {
    const m = estado.minuto;
    const sol = estado.solicitudes[solId];
    const liberadas = [];
    Object.values(estado.moviles).forEach((x) => {
      if (x.siguiente && x.siguiente.sol === solId) { x.siguiente = null; liberadas.push(x.id); }
      if (x.servicio === solId && x.estado === 'EN_RUTA') {
        const pos = posicionActual(x, m);
        x.zona = pos; x.servicio = null; x.rol = null; x.llegaEn = null; x.servicios = Math.max(0, x.servicios - 1);
        x.estado = pos === x.baseZona ? 'DISPONIBLE' : 'RETORNANDO';
        x.retornoEn = m + Math.max(1, Math.round(predecirLlegada(ctx, pos, x.baseZona, estado.esc, m).minutos));
        liberadas.push(x.id);
      }
    });
    if (!liberadas.length) return null;
    const enSitio = Object.values(estado.moviles).some((x) => x.servicio === solId);
    if (enSitio) apoyoAPrimerRespondiente(estado, sol);
    sol.estado = 'cola'; sol.minCola = m; sol.corregida = (sol.corregida || 0) + 1;
    if (!enSitio) sol.enRuta = [];
    estado.decisiones.push({ hora: m, solicitud: solId, clas: sol.clas, moviles: liberadas, tipo: 'correccion', politica: 'usuario' });
    registrar(estado, 'decision', `Se corrigió la asignación de ${solId}: ${liberadas.join(' y ')} queda${liberadas.length > 1 ? 'n' : ''} libre${liberadas.length > 1 ? 's' : ''} y la solicitud vuelve a la cola.`, { sol: solId });
    return liberadas;
  }

  function rolPara(sol, tipo) {
    if (tipo === 'VMD') return 'ATENCION';
    if (sol.necesitaAmb) return 'TRASLADO';
    return (sol.clas === '01' || sol.clas === '02') ? 'ATENCION_Y_TRASLADO' : 'ATENCION';
  }

  // ---------- decisión ----------
  function asignar(ctx, estado, solId, opcion, extra) {
    extra = extra || {};
    const sol = estado.solicitudes[solId];
    const m = estado.minuto;
    const ids = [];
    opcion.moviles.forEach(({ id, rol }) => {
      const mv = estado.moviles[id];
      if (!mv.apta) throw new Error('Intento de asignar una móvil no apta: ' + id);
      ids.push(id);
      if ((opcion.tipo === 'desvio' || opcion.desvioDe) && mv.estado === 'EN_RUTA' && mv.servicio !== sol.id) {
        const prev = estado.solicitudes[mv.servicio];
        if (prev) {
          prev.estado = 'cola'; prev.minCola = m; prev.desviada = true;
          prev.enRuta = (prev.enRuta || []).filter((x) => x.movil !== mv.id);
          registrar(estado, 'decision', `${mv.id} se desvía de ${prev.id} a ${sol.id}; ${prev.id} vuelve a la cola con prioridad ${prev.clas} (R06).`, { sol: prev.id });
        }
        mv.servicios -= 1;
        despachar(ctx, estado, mv, sol, rol);
      } else if (disponibleAhora(mv)) {
        despachar(ctx, estado, mv, sol, rol);
      } else {
        mv.siguiente = { sol: sol.id, rol };
      }
    });
    if (extra.apoyo) {
      const mv = estado.moviles[extra.apoyo];
      if (mv && disponibleAhora(mv)) { despachar(ctx, estado, mv, sol, 'APOYO_MEDICO'); ids.push(mv.id); }
    }
    sol.estado = 'asignada';
    sol.asignaciones.push({ min: m, moviles: ids, tipo: opcion.tipo, puesto: opcion.puesto || null });
    const d = {
      hora: m, solicitud: sol.id, clas: sol.clas, moviles: ids, puestoElegido: opcion.puesto || null,
      recomendada: extra.recomendada || null, coincide: extra.recomendada ? extra.recomendada === opcion.movil.id : null,
      motivo: extra.motivo || null, politica: extra.politica || 'usuario', eta: opcion.llegada.minutos,
    };
    estado.decisiones.push(d);
    const txt = opcion.tipo === 'estabilizacion'
      ? `${sol.id}: ${ids[0]} va como primer respondiente y ${ids[1] || 'la primera ambulancia libre'} queda preasignada.`
      : `${sol.id} asignada a ${ids.join(' + ')} (${opcion.tipo === 'preasignacion' ? 'preasignada, ' : ''}llega en ~${Math.round(opcion.llegada.minutos)} min).`;
    registrar(estado, 'decision', txt + (extra.motivo ? ` Cambio: ${extra.motivo}.` : ''), { sol: sol.id });
    return d;
  }

  // Si a una solicitud solo le queda una VMD de apoyo, esa VMD pasa a primer respondiente y la solicitud vuelve a la cola
  function sinAtencionPrincipal(estado, s) {
    return !Object.values(estado.moviles).some((x) => (x.servicio === s.id && x.rol !== 'APOYO_MEDICO') || (x.siguiente && x.siguiente.sol === s.id));
  }
  function apoyoAPrimerRespondiente(estado, s) {
    const ids = [];
    Object.values(estado.moviles).forEach((x) => {
      if (x.servicio === s.id && x.rol === 'APOYO_MEDICO') { x.rol = 'PRIMER_RESPONDIENTE_ESTABILIZACION'; if (x.estado === 'EN_ATENCION') x.libreEn = null; ids.push(x.id); }
    });
    return ids.length ? ` ${ids.join(' y ')} sigue como primer respondiente hasta que llegue la ambulancia.` : '';
  }

  function marcarNoApta(ctx, estado, id, motivo) {
    const mv = estado.moviles[id];
    const m = estado.minuto;
    mv.apta = false; mv.motivoNoApta = motivo; mv.marcadaPorUsuario = true;
    if (mv.siguiente) {
      const s = estado.solicitudes[mv.siguiente.sol];
      mv.siguiente = null;
      if (s && sinAtencionPrincipal(estado, s)) { const extra = apoyoAPrimerRespondiente(estado, s); s.estado = 'cola'; s.minCola = m; registrar(estado, 'alerta', `${id} marcada no apta; ${s.id} vuelve a la cola.${extra}`, { sol: s.id, alerta: true }); }
    }
    if (mv.estado === 'EN_RUTA') {
      const s = estado.solicitudes[mv.servicio];
      mv.zona = posicionActual(mv, m); mv.servicio = null; mv.rol = null; mv.llegaEn = null;
      mv.estado = 'DETENIDA';
      if (s && sinAtencionPrincipal(estado, s)) { const extra = apoyoAPrimerRespondiente(estado, s); s.estado = 'cola'; s.minCola = m; registrar(estado, 'alerta', `${id} se detuvo en ruta (${motivo}); ${s.id} vuelve a la cola.${extra}`, { sol: s.id, alerta: true }); }
    }
    registrar(estado, 'novedad', `${id} marcada como no apta: ${motivo}.`, { movil: id });
  }

  function marcarApta(ctx, estado, id) {
    const mv = estado.moviles[id];
    if (mv.estado === 'FUERA_SERVICIO') return;
    mv.apta = true; mv.motivoNoApta = null; mv.marcadaPorUsuario = false;
    if (mv.estado === 'DETENIDA') {
      const m = estado.minuto;
      mv.estado = mv.zona === mv.baseZona ? 'DISPONIBLE' : 'RETORNANDO';
      mv.retornoEn = m + Math.max(1, Math.round(predecirLlegada(ctx, mv.zona, mv.baseZona, estado.esc, m).minutos));
    }
    registrar(estado, 'novedad', `${id} vuelve a estar apta.`, { movil: id });
  }

  // ---------- métricas y políticas ----------
  function metricas(ctx, estado, opciones) {
    const parcial = opciones && opciones.parcial;
    const sols = listaSolicitudes(estado).filter((s) => {
      if (!completa(s) || s.estado === 'devuelta') return false;
      if (!parcial) return true;
      const c = s.necesitaAmb ? s.clasIni : s.clas;
      return s.primeraLlegada != null || (estado.minuto - s.minLlegada) > CLASES[c].obj;
    });
    const res = { porClase: {}, criticas: { n: 0, dentro: 0, suma: 0, max: 0 }, escalaciones: [], canceladas: 0, sinLlegada: 0 };
    sols.forEach((s) => {
      if (s.estado === 'cancelada' && s.primeraLlegada == null) { res.canceladas += 1; return; }
      const c = s.necesitaAmb ? s.clasIni : s.clas;
      const obj = CLASES[c].obj;
      let t = s.primeraLlegada != null ? s.primeraLlegada - s.minLlegada : null;
      if (t == null) { res.sinLlegada += 1; t = estado.minuto - s.minLlegada; }
      const g = res.porClase[c] || (res.porClase[c] = { n: 0, dentro: 0, tiempos: [] });
      g.n += 1; if (s.primeraLlegada != null && t <= obj) g.dentro += 1; g.tiempos.push(t);
      if (c === '01' || c === '02') {
        res.criticas.n += 1; if (s.primeraLlegada != null && t <= obj) res.criticas.dentro += 1;
        res.criticas.suma += t; res.criticas.max = Math.max(res.criticas.max, t);
      }
      if (s.reclasMin != null) res.escalaciones.push({ sol: s.id, min: s.ambLlegada != null ? s.ambLlegada - s.reclasMin : null });
    });
    const total = sols.filter((s) => !(s.estado === 'cancelada' && s.primeraLlegada == null));
    const dentro = Object.values(res.porClase).reduce((a, g) => a + g.dentro, 0);
    res.pctDentro = total.length ? (100 * dentro) / total.length : null;
    res.pctCriticasDentro = res.criticas.n ? (100 * res.criticas.dentro) / res.criticas.n : null;
    res.promCriticas = res.criticas.n ? res.criticas.suma / res.criticas.n : null;
    res.km = Object.values(estado.moviles).reduce((a, m) => a + m.km, 0);
    res.costo = Object.values(estado.moviles).reduce((a, m) => a + m.costo, 0);
    res.minDescubiertos = estado.metricas.minDescubiertos;
    res.correcciones = estado.decisiones.filter((d) => d.tipo === 'correccion').length;
    res.cambios = estado.decisiones.filter((d) => d.tipo !== 'correccion' && d.coincide === false).length;
    res.noAptasAsignadas = estado.decisiones.filter((d) => d.tipo !== 'correccion' && d.moviles.some((id) => !estado.moviles[id].apta && !estado.moviles[id].marcadaPorUsuario)).length;
    const porTipo = {};
    Object.values(estado.moviles).forEach((m) => { (porTipo[m.tipo] = porTipo[m.tipo] || []).push(m.servicios); });
    res.cargaPorTipo = porTipo;
    return res;
  }

  function decidirPolitica(ctx, estado, politica, decisionesHist) {
    const m = estado.minuto;
    if (politica === 'historica') {
      decisionesHist.filter((d) => d.minuto_asignacion === m).forEach((d) => {
        const sol = estado.solicitudes[d.id_solicitud];
        const mv = estado.moviles[d.id_movil];
        if (!sol || !mv || sol.estado === 'cancelada') return;
        const yaVa = Object.values(estado.moviles).some((x) => x.id === mv.id && x.servicio === sol.id);
        if (yaVa) return;
        let tipo = disponibleAhora(mv) ? 'directa' : 'preasignacion';
        if (mv.estado === 'EN_RUTA' && mv.servicio && mv.servicio !== sol.id) tipo = 'desvio';
        const p = predecirLlegada(ctx, posicionActual(mv, m), sol.zona, estado.esc, m);
        asignar(ctx, estado, sol.id, { movil: { id: mv.id, tipo: mv.tipo }, moviles: [{ id: mv.id, rol: d.rol }], tipo, llegada: p }, { politica });
      });
      return;
    }
    let guard = 0;
    while (guard++ < 20) {
      const pend = cola(estado);
      let hizo = false;
      for (const sol of pend) {
        const crit = sol.clas === '01' || sol.clas === '02';
        const rec = recomendar(ctx, estado, sol.id);
        let op = null;
        if (politica === 'motor') {
          op = rec.opciones[0];
          if (op && !crit && op.tipo === 'preasignacion' && op.espera > 10) op = null;
          if (op) asignar(ctx, estado, sol.id, op, { politica, recomendada: op.movil.id, apoyo: op.apoyo ? op.apoyo.id : null });
        } else {
          const directas = rec.todas.filter((o) => o.tipo === 'directa' && o.comp !== 'NOREC');
          const pool = directas.length ? directas : rec.todas.filter((o) => o.tipo === 'directa');
          op = pool.slice().sort((a, b) => a.llegada.minutos - b.llegada.minutos)[0] || null;
          if (!op && crit) op = rec.todas.filter((o) => o.tipo === 'preasignacion').sort((a, b) => a.llegada.minutos - b.llegada.minutos)[0] || null;
          if (op) asignar(ctx, estado, sol.id, op, { politica });
        }
        if (op) { hizo = true; break; }
      }
      if (!hizo) break;
    }
  }

  function correr(ctx, escId, politica, extraMin) {
    const estado = cargarEscenario(ctx, escId);
    const hist = ctx.D.decisiones.filter((d) => d.id_escenario === escId);
    const fin = estado.esc.duracion_min + (extraMin == null ? 60 : extraMin);
    decidirPolitica(ctx, estado, politica, hist);
    while (estado.minuto < fin) {
      avanzar(ctx, estado, 1);
      decidirPolitica(ctx, estado, politica, hist);
      const abiertas = listaSolicitudes(estado).filter((s) => s.estado === 'cola' || s.primeraLlegada == null && s.estado !== 'cancelada');
      if (estado.minuto >= estado.esc.duracion_min && !abiertas.length && !estado.llegadasPend.some((r) => r.minuto_llegada > estado.minuto)) break;
    }
    return { estado, metricas: metricas(ctx, estado) };
  }

  // Compara la recomendación del motor con cada decisión del despachador (archivo 06).
  // Reproduce las decisiones históricas y, antes de aplicar cada una, calcula qué habría sugerido el motor.
  function compararConDespachador(ctx, escId) {
    const estado = cargarEscenario(ctx, escId);
    const hist = ctx.D.decisiones.filter((d) => d.id_escenario === escId);
    const alLlegar = {};
    const filas = [];
    const fin = estado.esc.duracion_min + 30;
    const evaluar = () => {
      listaSolicitudes(estado).forEach((s) => {
        if (s.minLlegada === estado.minuto && !alLlegar[s.id] && s.estado === 'cola') alLlegar[s.id] = recomendar(ctx, estado, s.id);
      });
      hist.filter((d) => d.minuto_asignacion === estado.minuto).forEach((d) => {
        const sol = estado.solicitudes[d.id_solicitud];
        if (!sol) return;
        filas.push({ d, rec: recomendar(ctx, estado, sol.id), recLlegada: alLlegar[sol.id] || null, clas: sol.clas });
      });
      decidirPolitica(ctx, estado, 'historica', hist);
    };
    evaluar();
    while (estado.minuto < fin) { avanzar(ctx, estado, 1); evaluar(); }
    return filas;
  }

  const API = {
    CLASES, COMPAT, CONFIG, TIPOS, crearContexto, escenario, horaDe, factor, predecirLlegada, predecirLiberacion,
    cargarEscenario, avanzar, cola, porCompletar, completa, recomendar, competencia, puedeCorregir, corregirAsignacion,
    tripulacion, registrarSolicitud, completarZona, devolverATriaje, asignar, impactoCobertura, coberturaZonas, marcarNoApta, marcarApta,
    metricas, correr, compararConDespachador, posibleTraslado, posicionActual, disponibleAhora, esAmbulancia,
    nombreZona, fmtCosto, duracionAtencion,
  };
  if (typeof module !== 'undefined' && module.exports) module.exports = API; else root.Motor = API;
})(typeof window !== 'undefined' ? window : globalThis);

