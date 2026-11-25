"""App Streamlit del MVP de asignación de móviles (fase 5 · P4).

Cuatro vistas con ``st.navigation``/``st.Page``:

1. Cola y panel de decisión (vista principal): selector de escenario y
   solicitud sobre el **estado real** del escenario (modo ``estado_real``,
   capturado con ``simulador.escenarios.reproducir(capturar_estados=...)``).
   Top 3 en tarjetas, decisión humana (Aceptar / Cambiar con motivo de la
   lista cerrada) registrada en ``resultados/registro_decisiones_app.csv``.
2. Control de flota: estado inicial del escenario editable y evaluación de
   una solicitud con esa flota (permite probar R06 poniendo una VMD
   ``EN_RUTA`` hacia un 06).
3. Reproductor de escenarios: línea de tiempo (eventos + solicitudes) y
   reloj para avanzar.
4. Resultados y confiabilidad: lee ``resultados/resumen.json``.

Reglas de la app: aviso «Entorno académico con datos ficticios» siempre
visible, sin APIs externas (el mapa usa ``tiles=None`` con un fondo simple,
funciona sin internet), sin datos personales. Modelo, tablas y configuración
se cargan una sola vez con ``st.cache_resource``; los estados de cada
escenario también se capturan una sola vez.
"""

from __future__ import annotations

import copy
import dataclasses
import json
import sys
import time
import tomllib
from pathlib import Path
from typing import Optional

import folium
import pandas as pd
import streamlit as st
from streamlit_folium import st_folium

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from contrato.objetos import Movil, Solicitud  # noqa: E402
from contrato.reglas import derivar_posible_traslado  # noqa: E402
from modelos.predictor import PredictorTiempos  # noqa: E402
from motor.despachador import GestorDecisiones, filtrar_aptas, recomendar  # noqa: E402
from simulador.escenarios import cargar_escenario, ids_escenarios, reproducir  # noqa: E402

AVISO = "Entorno académico con datos ficticios"

ESTADOS_MOVIL = ("DISPONIBLE", "RETORNANDO", "EN_RUTA", "EN_ATENCION", "EN_TRASLADO", "FUERA_SERVICIO")
CODIGOS = ("", "01", "02", "03", "06", "07")

DETALLE_LABELS = {
    "d01_tiempo_llegada": "D01 · Menor tiempo de llegada",
    "d02_costo": "D02 · Menor costo",
    "d03_cobertura_zonas_alta": "D03 · Cobertura de zonas ALTA",
    "d04_balance_carga": "D04 · Balance de carga",
    "d05_uso_eficiente_tipo_movil": "D05 · Uso eficiente del tipo de móvil",
    "d06_posible_traslado_tab": "D06 · Posible traslado con TAB",
    "d07_apoyo_medico_vmd": "D07 · Apoyo médico con VMD",
    "d08_retencion_camilla": "D08 · Retención de camilla (P90 de liberación)",
}


# --------------------------------------------------------------------------- #
# Recursos cacheados (una sola vez por sesión/servidor)
# --------------------------------------------------------------------------- #


@st.cache_resource(show_spinner="Cargando modelo y tablas…")
def cargar_recursos():
    predictor = PredictorTiempos.cargar(RAIZ / "modelos" / "predictor_emi.joblib")
    config = tomllib.loads((RAIZ / "config.toml").read_text(encoding="utf-8"))
    return predictor, predictor.tablas, config


@st.cache_resource(show_spinner="Reproduciendo el escenario (estado real)…")
def estados_escenario(escenario_id: str, _predictor, _config):
    """Escenario + fotos del estado real antes de cada decisión.

    Se cachea por escenario: cambiar de solicitud dentro de un escenario no
    vuelve a reproducir la línea de tiempo.
    """
    escenario = cargar_escenario(escenario_id)
    capturas: list[dict] = []
    reproducir(escenario, "estado_real", _config, _predictor, _predictor.tablas, capturar_estados=capturas)
    capturas.sort(key=lambda c: (c["minuto"], 0 if c["tipo"] == "solicitud" else 1))
    return escenario, capturas


def _gestor_app() -> GestorDecisiones:
    if "gestor_app" not in st.session_state:
        ruta = RAIZ / "resultados" / "registro_decisiones_app.csv"
        try:
            ruta.unlink(missing_ok=True)  # cada sesión arranca su propio registro
        except OSError:
            pass
        st.session_state.gestor_app = GestorDecisiones(ruta)
    return st.session_state.gestor_app


# --------------------------------------------------------------------------- #
# Utilidades de presentación
# --------------------------------------------------------------------------- #


def _etiqueta_captura(cap: dict) -> str:
    marca = " · RECLASIFICADA" if cap["tipo"] == "reclasificacion" else ""
    return f"min {cap['minuto']:>3.0f} · {cap['id_solicitud']} · código {cap['codigo']}{marca}"


def _movil_por_id(flota: list[Movil], id_movil: str) -> Movil:
    return next(m for m in flota if m.id_movil == id_movil)


def _validar_edicion_flota(df: pd.DataFrame, zonas_validas: set[str]) -> list[str]:
    """Valida la tabla editada de Control de flota (estado de la lista del
    documento 04, zona existente, `min_para_liberarse` >= 0). Devuelve la
    lista de errores encontrados; vacía si todo es válido."""
    errores = []
    estados_invalidos = sorted(set(df["estado"]) - set(ESTADOS_MOVIL))
    if estados_invalidos:
        errores.append(f"Estado no válido (documento 04): {', '.join(estados_invalidos)}.")
    zonas_invalidas = sorted(set(df["id_zona_actual"]) - zonas_validas)
    if zonas_invalidas:
        errores.append(f"Zona inexistente: {', '.join(zonas_invalidas)}.")
    negativos = df[df["min_para_liberarse"].notna() & (df["min_para_liberarse"] < 0)]
    if not negativos.empty:
        errores.append(f"`min_para_liberarse` negativo en: {', '.join(negativos['id_movil'])}.")
    codigos = {c for c in df["servicio_actual_codigo"] if c}
    codigos_invalidos = sorted(codigos - set(c for c in CODIGOS if c))
    if codigos_invalidos:
        errores.append(f"Código de servicio no válido: {', '.join(codigos_invalidos)}.")
    return errores


def _opciones_para_cambiar(solicitud: Solicitud, flota: list[Movil], top3, config: dict) -> dict[str, str]:
    """Móviles que puede ofrecer «Cambiar»: nunca ``FUERA_SERVICIO`` ni
    incompatibles con el código de la solicitud (``filtrar_aptas``, R03/R05 y
    la matriz de compatibilidad -- la misma que usa ``recomendar()``), más
    las del top 3 que no estén en ese conjunto (la VMD de R04, que
    ``filtrar_aptas`` excluye por defecto al ser ``SOLO_ESTABILIZACION``)."""
    derivada = dataclasses.replace(
        solicitud,
        posible_traslado=derivar_posible_traslado(solicitud.codigo, solicitud.motivo_consulta, solicitud.discriminador, config),
    )
    aptas = filtrar_aptas(derivada, flota)
    ids_top3 = {r.id_movil: r.puesto for r in top3}
    ids = {m.id_movil for m in aptas} | set(ids_top3)
    opciones = {}
    for id_movil in sorted(ids, key=lambda i: (ids_top3.get(i, 99), i)):
        movil = _movil_por_id(flota, id_movil)
        if id_movil in ids_top3:
            etiqueta = f"Puesto {ids_top3[id_movil]} · {id_movil} ({movil.tipo_movil})"
        else:
            etiqueta = f"{id_movil} ({movil.tipo_movil}) · fuera del top 3"
        opciones[etiqueta] = id_movil
    return opciones


def _tarjeta(recomendacion, flota: list[Movil], config: dict, objetivo: float) -> None:
    movil = _movil_por_id(flota, recomendacion.id_movil)
    ok = recomendacion.cumple_objetivo
    margen = objetivo - recomendacion.llegada.minutos
    estado_texto = f"✓ Cumple objetivo (+{margen:.0f} min)" if ok else f"✗ No cumple (−{abs(margen):.0f} min)"
    st.markdown(f"#### {movil.id_movil} · {movil.tipo_movil} · {estado_texto}")
    st.caption(f"Puesto {recomendacion.puesto} · rol {recomendacion.rol_asignado}")
    if recomendacion.cobertura.zonas_descubiertas:
        plan_b = (
            f" Plan B: {recomendacion.cobertura.plan_b_movil} a {recomendacion.cobertura.plan_b_minutos:.0f} min."
            if recomendacion.cobertura.plan_b_movil
            else " Sin ninguna ambulancia disponible cerca."
        )
        st.warning(
            f"⚠️ Deja {len(recomendacion.cobertura.zonas_descubiertas)} zona(s) ALTA a más de "
            f"{config['umbrales']['cobertura_min']:.0f} min (peor: {recomendacion.cobertura.peor_zona}).{plan_b}"
        )
    else:
        st.success("No deja zonas ALTA descubiertas.")
    if recomendacion.apoyo_medico_sugerido:
        st.info(
            f"D07 · Apoyo médico sugerido: **{recomendacion.apoyo_medico_sugerido}** "
            f"({recomendacion.apoyo_medico_llegada.minutos:.0f} min)."
        )
    st.markdown(
        f"**Costo estimado:** ${recomendacion.costo_estimado:,.0f} · **Llegada:** {recomendacion.llegada.minutos:.0f} min  "
        f"<span style='color:#888'>(P10–P90: {recomendacion.llegada.minutos_bajo:.0f}–{recomendacion.llegada.minutos_alto:.0f})</span>",
        unsafe_allow_html=True,
    )
    st.markdown(f"**Puntaje:** {recomendacion.puntaje:.3f}")
    st.markdown(f"**Por qué:** {recomendacion.explicacion}")
    with st.expander("Detalle del puntaje (D01–D08)"):
        if recomendacion.detalle_puntaje:
            filas = [
                {
                    "Deseable": DETALLE_LABELS[k],
                    "Peso": config["pesos_puntaje"].get(k),
                    "Contribución": recomendacion.detalle_puntaje.get(k, 0.0),
                }
                for k in DETALLE_LABELS
            ]
            st.dataframe(pd.DataFrame(filas), hide_index=True, width="stretch")
            st.caption(
                f"Suma ponderada (con costo): {sum(recomendacion.detalle_puntaje.values()):.3f}. "
                "En 01/02 el orden usa el puntaje sin D02 + bonus de compatibilidad; el valor mostrado es el "
                "que ordenó. Una etiqueta NO RECOMENDADA aplica además ×0,5."
            )
        else:
            st.caption("Sin desglose de puntaje para esta recomendación (R07 o política sin puntaje).")


def _mapa_offline(tablas, solicitud: Solicitud, flota: list[Movil], top3, con_fondo: bool = False) -> folium.Map:
    """``con_fondo=False`` (por defecto): ``tiles=None``, un rectángulo gris
    simple de fondo, funciona sin internet. ``con_fondo=True``: tiles de
    OpenStreetMap (requiere internet); si la construcción falla por
    cualquier motivo, se vuelve al modo sin fondo sin romper la vista (la
    descarga de los tiles ocurre en el navegador, fuera del alcance de este
    try/except, pero una tile que no carga en el navegador solo deja un
    recuadro en blanco -- no rompe la página)."""
    zonas = tablas.zonas.set_index("id_zona")
    centro = zonas.loc[solicitud.id_zona]
    mapa = None
    if con_fondo:
        try:
            mapa = folium.Map(
                location=[float(centro["lat_centroide"]), float(centro["lon_centroide"])],
                zoom_start=12,
                tiles="OpenStreetMap",
                zoom_control=True,
                attribution_control=True,
            )
        except Exception:
            con_fondo = False  # vuelve al modo sin fondo, sin romper la vista
    if mapa is None:
        mapa = folium.Map(
            location=[float(centro["lat_centroide"]), float(centro["lon_centroide"])],
            zoom_start=12,
            tiles=None,  # sin tiles externos: la demo funciona sin internet
            zoom_control=True,
            attribution_control=False,
        )

    if not con_fondo:
        folium.Rectangle(
            bounds=[
                [float(zonas["lat_centroide"].min()), float(zonas["lon_centroide"].min())],
                [float(zonas["lat_centroide"].max()), float(zonas["lon_centroide"].max())],
            ],
            color="#cccccc",
            weight=1,
            fill=True,
            fill_color="#f4f4f4",
            fill_opacity=0.7,
        ).add_to(mapa)

    # Zonas ALTA que quedarían descubiertas con el puesto 1.
    descubiertas = top3[0].cobertura.zonas_descubiertas if top3 else []
    for id_zona in descubiertas:
        if id_zona not in zonas.index:
            continue
        z = zonas.loc[id_zona]
        folium.CircleMarker(
            location=[float(z["lat_centroide"]), float(z["lon_centroide"])],
            radius=11,
            color="#b71c1c",
            weight=2,
            fill=True,
            fill_color="#ef9a9a",
            fill_opacity=0.55,
            tooltip=f"Zona ALTA descubierta: {id_zona}",
        ).add_to(mapa)

    # Zona de la solicitud.
    folium.CircleMarker(
        location=[float(centro["lat_centroide"]), float(centro["lon_centroide"])],
        radius=15,
        color="#0d47a1",
        weight=3,
        fill=True,
        fill_color="#90caf9",
        fill_opacity=0.9,
        tooltip=f"Solicitud {solicitud.id_solicitud} · zona {solicitud.id_zona}",
    ).add_to(mapa)

    # Móviles del top 3, en su zona actual.
    colores = {1: "#2e7d32", 2: "#1565c0", 3: "#ef6c00"}
    for rec in top3:
        movil = _movil_por_id(flota, rec.id_movil)
        if movil.id_zona_actual not in zonas.index:
            continue
        z = zonas.loc[movil.id_zona_actual]
        folium.CircleMarker(
            location=[float(z["lat_centroide"]), float(z["lon_centroide"])],
            radius=8,
            color=colores.get(rec.puesto, "#555555"),
            weight=2,
            fill=True,
            fill_color=colores.get(rec.puesto, "#555555"),
            fill_opacity=0.85,
            tooltip=f"P{rec.puesto} · {rec.id_movil} ({movil.tipo_movil}) · {rec.llegada.minutos:.0f} min",
        ).add_to(mapa)
    return mapa


def _aviso():
    st.caption(f"⚠️ **{AVISO}** · los datos son simulados y no corresponden a la operación real.")


# --------------------------------------------------------------------------- #
# Vista 1 · Cola y panel de decisión
# --------------------------------------------------------------------------- #


def vista_principal() -> None:
    _aviso()
    st.title("🚑 Cola y panel de decisión")
    predictor, tablas, config = cargar_recursos()
    escenario_id = st.selectbox("Escenario", ids_escenarios(), index=ids_escenarios().index("ESC-03"), key="esc_principal")
    escenario, capturas = estados_escenario(escenario_id, predictor, config)

    if st.session_state.get("_esc_actual") != escenario_id:
        st.session_state._esc_actual = escenario_id
        st.session_state.idx = 0
        st.session_state.decisiones = {}

    def _ir_a(n: int) -> None:
        """Cambia de punto de decisión. El selector usa una clave que incluye
        el índice (ver abajo), así que al avanzar se crea un widget nuevo con
        el índice correcto, sin reescribir el estado de un widget existente
        (prohibido por Streamlit)."""
        st.session_state.idx = n
        st.rerun()

    st.caption(
        f"{escenario.nombre} · {escenario.tipo_dia} · inicio {escenario.fecha_hora_inicio} · "
        f"{len(capturas)} puntos de decisión. Reproducción en modo **estado_real**: la flota es la del "
        "escenario (estado inicial + eventos del archivo); tu decisión queda registrada."
    )

    if not capturas:
        st.warning("Este escenario no tiene solicitudes.")
        return

    idx = int(st.session_state.get("idx", 0))
    if idx >= len(capturas):
        st.success("✅ Escenario completado.")
        _resumen_sesion(_ir_a)
        return

    seleccion = st.selectbox(
        "Solicitud",
        options=list(range(len(capturas))),
        index=idx,
        format_func=lambda i: _etiqueta_captura(capturas[i]),
        key=f"sel_solicitud_{escenario_id}_{idx}",
    )
    if seleccion != idx:
        # El usuario navegó con el selector: se adopta sin rerun (las fotos
        # de estado ya están calculadas y son deterministas).
        st.session_state.idx = seleccion
        idx = seleccion
    cap = capturas[idx]
    solicitud: Solicitud = cap["solicitud"]
    flota: list[Movil] = cap["flota"]

    t0 = time.perf_counter()
    top3 = recomendar(solicitud, flota, solicitud.hora, config, predictor, tablas)
    duracion = time.perf_counter() - t0

    st.divider()
    st.subheader(
        f"{solicitud.id_solicitud} · código {solicitud.codigo} · {solicitud.escala_manchester} · "
        f"zona {solicitud.id_zona} · {solicitud.hora[11:16]}"
    )
    st.caption(
        f"Punto {idx + 1} de {len(capturas)} · minuto {cap['minuto']:.0f} · "
        f"«{solicitud.motivo_consulta} / {solicitud.discriminador}» · "
        f"posible traslado: {'sí' if solicitud.posible_traslado else 'no'} · "
        f"top 3 calculado en {duracion:.2f} s"
    )
    if cap["tipo"] == "reclasificacion":
        st.info("Este punto corresponde a una **reclasificación** (R07): se aplican las reglas del nuevo código.")

    clave = f"{escenario_id}|{idx}"
    decision_previa = st.session_state.decisiones.get(clave)

    if top3:
        columnas = st.columns(len(top3))
        for columna, recomendacion in zip(columnas, top3):
            with columna:
                with st.container(border=True):
                    _tarjeta(recomendacion, flota, config, config["objetivos_min"][solicitud.codigo])
        st.markdown("**Mapa:** zona de la solicitud, móviles del top 3 y zonas ALTA descubiertas.")
        con_fondo = st.toggle(
            "🌐 Fondo de mapa (requiere internet)", value=False, key=f"fondo_mapa_{escenario_id}_{idx}"
        )
        st_folium(
            _mapa_offline(tablas, solicitud, flota, top3, con_fondo=con_fondo),
            height=380,
            use_container_width=True,
            returned_objects=[],
        )
        st.caption("Azul: solicitud · verde/azul/naranja: puestos 1/2/3 · rojo: zonas ALTA que quedarían descubiertas.")
    else:
        st.warning("No hay móviles compatibles ni una opción de R04 para esta solicitud.")

    st.divider()
    if decision_previa is not None:
        st.info(
            f"Decisión registrada: **{decision_previa['resultado']}** · móvil {decision_previa['id_movil']}"
            + (f" · motivo {decision_previa['motivo']}" if decision_previa.get("motivo") else "")
        )
        _boton_siguiente(idx, len(capturas), _ir_a)
        return

    if not top3:
        _boton_siguiente(idx, len(capturas), _ir_a)
        return

    opciones = _opciones_para_cambiar(solicitud, flota, top3, config)
    with st.form(key=f"form_decision_{escenario_id}_{idx}"):
        etiquetas = list(opciones)
        elegida = st.radio("Móvil a enviar si cambias (solo móviles aptas)", etiquetas, index=0)
        motivo = st.selectbox(
            "Motivo del cambio (obligatorio si eliges otra móvil)",
            config["retroalimentacion"]["motivos_cambio"],
        )
        col_a, col_b = st.columns(2)
        aceptar = col_a.form_submit_button("✅ Aceptar recomendación", width="stretch")
        cambiar = col_b.form_submit_button("🔁 Cambiar", width="stretch")

    if aceptar or cambiar:
        if cambiar and opciones[elegida] == top3[0].id_movil:
            st.error("Para cambiar, elige una móvil distinta del puesto 1.")
            return
        id_movil = top3[0].id_movil if aceptar else opciones[elegida]
        motivo_final = None if aceptar else motivo
        decision = _gestor_app().registrar_decision(
            solicitud, top3, hora_decision=solicitud.hora, id_movil_elegido=id_movil, motivo_cambio=motivo_final
        )
        st.session_state.decisiones[clave] = {
            "resultado": decision.resultado,
            "id_movil": decision.id_movil_elegido,
            "motivo": decision.motivo_cambio,
        }
        _ir_a(min(idx + 1, len(capturas)))


def _boton_siguiente(idx: int, total: int, ir_a) -> None:
    if idx + 1 < total:
        if st.button("➡️ Siguiente solicitud", type="primary"):
            ir_a(idx + 1)
    else:
        if st.button("✅ Finalizar recorrido", type="primary"):
            ir_a(total)


def _resumen_sesion(ir_a) -> None:
    decisiones = st.session_state.get("decisiones", {})
    aceptadas = {k: d for k, d in decisiones.items() if d["resultado"] == "ACEPTADA"}
    cambiadas = {k: d for k, d in decisiones.items() if d["resultado"] == "CAMBIADA"}
    st.write(f"**{len(decisiones)} decisión(es)** en este escenario: {len(aceptadas)} aceptada(s), {len(cambiadas)} cambiada(s).")
    if aceptadas:
        st.markdown("**Aceptadas:**")
        for clave, d in aceptadas.items():
            st.markdown(f"- {clave.split('|')[1]} → {d['id_movil']}")
    if cambiadas:
        st.markdown("**Cambiadas (con motivo):**")
        for clave, d in cambiadas.items():
            st.markdown(f"- {clave.split('|')[1]} → {d['id_movil']} · motivo: **{d['motivo']}**")
    if decisiones:
        st.metric("Tasa de aceptación de este escenario", f"{100 * len(aceptadas) / len(decisiones):.0f} %")
    if st.button("🔁 Reiniciar escenario"):
        st.session_state.decisiones = {}
        ir_a(0)


# --------------------------------------------------------------------------- #
# Vista 2 · Control de flota
# --------------------------------------------------------------------------- #


def vista_flota() -> None:
    _aviso()
    st.title("🚐 Control de flota")
    predictor, tablas, config = cargar_recursos()
    escenario_id = st.selectbox("Escenario", ids_escenarios(), index=ids_escenarios().index("ESC-03"), key="flota_esc")
    escenario = cargar_escenario(escenario_id)
    st.caption("Estado **inicial** del escenario (puedes editarlo para probar hipótesis; no modifica el archivo).")
    st.warning(
        "Sandbox: una VMD `EN_RUTA` con código de servicio 06 u 03 permite probar el desvío R06 en una "
        "solicitud 01/02 de la evaluación de abajo."
    )

    flota = copy.deepcopy(escenario.flota_inicial)
    datos = pd.DataFrame(
        [
            {
                "id_movil": m.id_movil,
                "tipo_movil": m.tipo_movil,
                "estado": m.estado,
                "id_zona_actual": m.id_zona_actual,
                "id_base": m.id_base,
                "min_para_liberarse": m.min_para_liberarse,
                "servicio_actual_codigo": m.servicio_actual_codigo or "",
                "costo_km": m.costo_km,
                "costo_hora": m.costo_hora,
                "activo": m.activo,
            }
            for m in flota
        ]
    )
    zonas_validas = sorted(tablas.zonas["id_zona"])
    editado = st.data_editor(
        datos,
        hide_index=True,
        width="stretch",
        disabled=["id_movil", "tipo_movil", "id_base", "costo_km", "costo_hora"],
        column_config={
            "estado": st.column_config.SelectboxColumn(options=ESTADOS_MOVIL, required=True),
            "id_zona_actual": st.column_config.SelectboxColumn(options=zonas_validas, required=True),
            "servicio_actual_codigo": st.column_config.SelectboxColumn(options=CODIGOS),
            "min_para_liberarse": st.column_config.NumberColumn(min_value=0.0, step=1.0),
        },
        key=f"editor_flota_{escenario_id}",
    )

    errores = _validar_edicion_flota(editado, set(zonas_validas))
    if errores:
        for error in errores:
            st.error(f"⚠️ {error}")
        st.info("Corrige la tabla para poder evaluar una solicitud: no se recalcula nada mientras haya errores.")
        return

    # Reconstruye la flota con lo editado (ya validado).
    flota_editada: list[Movil] = []
    for _, fila in editado.iterrows():
        original = next(m for m in flota if m.id_movil == fila["id_movil"])
        flota_editada.append(
            Movil(
                id_movil=original.id_movil,
                tipo_movil=original.tipo_movil,
                estado=fila["estado"],
                id_zona_actual=fila["id_zona_actual"],
                id_base=original.id_base,
                costo_km=original.costo_km,
                costo_hora=original.costo_hora,
                activo=original.activo,
                min_para_liberarse=fila["min_para_liberarse"] if pd.notna(fila["min_para_liberarse"]) else None,
                servicio_actual_codigo=fila["servicio_actual_codigo"] or None,
                servicio_actual_id=(f"MANUAL-{escenario_id}" if fila["estado"] == "EN_RUTA" else None),
            )
        )

    st.divider()
    st.subheader("Evaluar una solicitud con esta flota")
    mapa_solicitudes = {f"{s.id_solicitud} · código {s.codigo} · {s.id_zona}": s for s in escenario.solicitudes}
    etiqueta = st.selectbox("Solicitud", list(mapa_solicitudes), key=f"sol_flota_{escenario_id}")
    solicitud = mapa_solicitudes[etiqueta]
    if st.button("Calcular top 3", type="primary"):
        top3 = recomendar(solicitud, flota_editada, solicitud.hora, config, predictor, tablas)
        if not top3:
            st.warning("Sin recomendaciones con esta flota.")
        else:
            resumen = pd.DataFrame(
                [
                    {
                        "puesto": r.puesto,
                        "id_movil": r.id_movil,
                        "tipo": _movil_por_id(flota_editada, r.id_movil).tipo_movil,
                        "rol": r.rol_asignado,
                        "P50_llegada_min": round(r.llegada.minutos, 1),
                        "cumple_objetivo": r.cumple_objetivo,
                        "reglas": ", ".join(r.reglas_aplicadas),
                        "preasignada": r.ambulancia_preasignada,
                        "servicio_interrumpido": r.servicio_interrumpido_id,
                        "zonas_alta_descubiertas": len(r.cobertura.zonas_descubiertas),
                        "costo": r.costo_estimado,
                    }
                    for r in top3
                ]
            )
            st.dataframe(resumen, hide_index=True, width="stretch")
            st.caption(top3[0].explicacion)


# --------------------------------------------------------------------------- #
# Vista 3 · Reproductor de escenarios
# --------------------------------------------------------------------------- #


def vista_reproductor() -> None:
    _aviso()
    st.title("⏱️ Reproductor de escenarios")
    predictor, tablas, config = cargar_recursos()
    escenario_id = st.selectbox("Escenario", ids_escenarios(), index=ids_escenarios().index("ESC-03"), key="rep_esc")
    escenario, capturas = estados_escenario(escenario_id, predictor, config)
    st.caption(f"{escenario.nombre} · duración {escenario.duracion_min} min · {len(escenario.eventos)} eventos")

    filas = [
        {"minuto": ev["minuto"], "tipo": f"EVENTO · {ev['tipo_evento']}",
         "detalle": f"{ev['id_solicitud'] or ''} {ev['id_movil'] or ''} · {ev['detalle']}".strip()}
        for ev in escenario.eventos
    ]
    filas += [
        {"minuto": cap["minuto"], "tipo": "SOLICITUD" if cap["tipo"] == "solicitud" else "RECLASIFICACIÓN",
         "detalle": f"{cap['id_solicitud']} · código {cap['codigo']} · {cap['solicitud'].id_zona}"}
        for cap in capturas
    ]
    linea = pd.DataFrame(filas).sort_values(["minuto", "tipo"]).reset_index(drop=True)

    minuto = st.slider("Minuto del escenario", 0, int(escenario.duracion_min), 0, step=1)
    visibles = linea[linea["minuto"] <= minuto]
    st.dataframe(visibles, hide_index=True, width="stretch")
    st.caption(f"{len(visibles)} de {len(linea)} elementos hasta el minuto {minuto}.")

    previas = [cap for cap in capturas if cap["minuto"] <= minuto]
    if not previas:
        st.info("Aún no ha entrado ninguna solicitud.")
        return
    cap = previas[-1]
    solicitud, flota = cap["solicitud"], cap["flota"]
    top3 = recomendar(solicitud, flota, solicitud.hora, config, predictor, tablas)
    st.subheader(f"Última decisión hasta el minuto {minuto}: {solicitud.id_solicitud} (código {solicitud.codigo})")
    if top3:
        r = top3[0]
        st.markdown(
            f"**Puesto 1:** {r.id_movil} · P50 **{r.llegada.minutos:.0f} min** "
            f"(P10–P90 {r.llegada.minutos_bajo:.0f}–{r.llegada.minutos_alto:.0f}) · "
            f"{'✓ cumple objetivo' if r.cumple_objetivo else '✗ no cumple objetivo'} · "
            f"puntaje {r.puntaje:.3f} · {', '.join(r.reglas_aplicadas)}"
        )
        st.caption(r.explicacion)
    else:
        st.warning("El motor no tiene recomendación para ese punto.")


# --------------------------------------------------------------------------- #
# Vista 4 · Resultados y confiabilidad
# --------------------------------------------------------------------------- #


def vista_resultados() -> None:
    _aviso()
    st.title("📊 Resultados y confiabilidad")
    ruta = RAIZ / "resultados" / "resumen.json"
    if not ruta.exists():
        st.warning("No existe `resultados/resumen.json`. Ejecuta `python correr_todo.py` y vuelve a abrir esta vista.")
        return
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    er = datos["estado_real_resumen_principal"]
    simuladas = datos["politicas_simuladas"]
    coordinador = datos["comparacion_coordinador"]

    st.subheader("Comparación con el despachador (misma vara)")
    c1, c2, c3 = st.columns(3)
    c1.metric("01/02 cumplen — motor", f"{er['cumple_objetivo_01_02_pct_motor_P50']:.1f} %")
    c2.metric("01/02 cumplen — despachador, mismo modelo", f"{er['cumple_objetivo_01_02_pct_despachador_P50_mismo_modelo']:.1f} %")
    c3.metric("01/02 cumplen — estimación del despachador", f"{er['cumple_objetivo_01_02_pct_despachador_estimacion_mas_espera']:.1f} %")
    st.caption(er["nota_base_de_tiempo"])
    c1, c2, c3 = st.columns(3)
    c1.metric("Coincidencia puesto 1", f"{er['coincide_puesto1_despachador_pct']:.1f} %")
    c2.metric("Coincidencia top 3", f"{er['coincide_top3_despachador_pct']:.1f} %")
    c3.metric("Tasa de aceptación (gestor)", f"{er['tasa_aceptacion_gestor_pct']:.1f} %" if er["tasa_aceptacion_gestor_pct"] is not None else "—")

    st.subheader("Comparación con el coordinador")
    c1, c2 = st.columns(2)
    c1.metric(
        "Alternativa del coordinador incluida en el top 3",
        f"{coordinador['n_motor_incluye_alternativa']}/{coordinador['n_con_alternativa_identificable']}",
    )
    c2.metric(
        "… y es el puesto 1 del motor",
        f"{coordinador['n_motor_puesto1_es_alternativa']}/{coordinador['n_con_alternativa_identificable']}",
    )
    st.caption(
        f"{coordinador['n_casos_marcados']} casos marcados; {coordinador['n_sin_id_en_el_comentario']} sin "
        "alternativa identificable en el texto libre (no se pueden comparar automáticamente)."
    )

    st.subheader("Motor frente a la política «más cercana»")
    tabla = pd.DataFrame(
        [
            {
                "política": modo,
                "01/02 cumplen objetivo %": datos_modo["cumple_objetivo_01_02_pct"],
                "zonas ALTA descubiertas (prom.)": datos_modo["zonas_alta_descubiertas_promedio"],
                "costo estimado promedio": datos_modo["costo_estimado_promedio"],
            }
            for modo, datos_modo in simuladas.items()
        ]
    )
    st.dataframe(tabla, hide_index=True, width="stretch")
    st.caption(
        "La coincidencia con el despachador no se muestra para los modos simulados: no es comparable "
        "(la flota diverge de la realidad por las propias decisiones simuladas)."
    )

    st.subheader("Ejemplo de cobertura preservada: ESC-08")
    st.markdown(
        "En **ESC-08-S01 (código 02)** el motor prefirió la TAB MOV-020 (puntaje 0.653, 2 zonas ALTA "
        "descubiertas) antes que el TAM MOV-006, que era la más rápida (7.8 min) pero dejaba 5 zonas ALTA "
        "descubiertas. Como el 02 se cumplía igual (17.4 ≤ 20), **MOV-006 quedó libre** y en **ESC-08-S02 "
        "(código 01, minuto 29)** el motor lo usó: **7.3 min, cumple el objetivo de 15**. La política "
        "«más cercana» había gastado MOV-006 en S01 (quedaría ocupado hasta ~min 44) y en S02 solo tenía "
        "MOV-019 (18.2 min, no cumple). Es el único caso 01/02 donde el motor cumple y «más cercana» no."
    )

    st.subheader("Métricas del modelo")
    viaje = datos["metricas_modelo"]["viaje"]
    liberacion = datos["metricas_modelo"]["liberacion"]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Viaje: MAE modelo", f"{viaje['mae_modelo']:.2f} min")
    c2.metric("Viaje: MAE fórmula", f"{viaje['mae_formula']:.2f} min")
    c3.metric("Viaje: mejora vs fórmula", f"{viaje['mejora_pct_mae_vs_formula']:.1f} %")
    c4.metric("Viaje: R²", f"{viaje['r2_modelo']:.3f}")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Liberación: MAE", f"{liberacion['mae_modelo']:.2f} min")
    c2.metric("Liberación: R²", f"{liberacion['r2_modelo']:.3f}")
    c3.metric("Cobertura P10–P90 (viaje)", f"{viaje['cobertura_empirica_p10_p90_calibrada']:.1%}")
    c4.metric("Cobertura P10–P90 (liberación)", f"{liberacion['cobertura_empirica_p10_p90']:.1%}")


# --------------------------------------------------------------------------- #
# Punto de entrada
# --------------------------------------------------------------------------- #


def _registro_sidebar() -> None:
    gestor: Optional[GestorDecisiones] = st.session_state.get("gestor_app")
    st.sidebar.divider()
    st.sidebar.subheader("Registro de decisiones (sesión)")
    if gestor is None or not gestor.ruta_csv.exists():
        st.sidebar.caption("Sin decisiones registradas todavía.")
        return
    registro = pd.read_csv(gestor.ruta_csv, dtype=str)
    tasa = gestor.tasa_aceptacion()
    st.sidebar.metric("Tasa de aceptación", f"{tasa:.1f} %" if tasa is not None else "—")
    with st.sidebar.expander(f"{len(registro)} decisión(es)"):
        st.dataframe(
            registro[["id_solicitud", "resultado", "id_movil_elegido", "motivo_cambio"]],
            hide_index=True,
            width="stretch",
        )


def main() -> None:
    st.set_page_config(page_title="Asignación de móviles · EMI", page_icon="🚑", layout="wide")
    st.sidebar.title("Asignación de móviles")
    st.sidebar.warning(f"⚠️ {AVISO}")
    st.sidebar.caption("Herramienta de apoyo: sugiere; el despachador decide.")
    paginas = [
        st.Page(vista_principal, title="Cola y decisión", icon="🚑", default=True),
        st.Page(vista_flota, title="Control de flota", icon="🚐"),
        st.Page(vista_reproductor, title="Reproductor de escenarios", icon="⏱️"),
        st.Page(vista_resultados, title="Resultados y confiabilidad", icon="📊"),
    ]
    st.navigation(paginas).run()
    _registro_sidebar()


if __name__ == "__main__":
    main()
