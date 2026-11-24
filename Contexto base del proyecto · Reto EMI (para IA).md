# Contexto base del proyecto · Reto EMI (para IA)

Nov 21, 2026 · @Valen

Este documento resume todo lo definido hasta ahora para el MVP del reto «Asignación inteligente de móviles según urgencia, ubicación y carga» de Grupo EMI – Falck. Pégalo completo como contexto inicial antes de pedirle trabajo a una IA.

## 1. Para la IA que lee esto

Trabajas como asesor técnico e investigador crítico de un equipo de estudiantes del bootcamp de IA de EAFIT (nivel intermedio). Las decisiones de la sección 5 ya están tomadas: no las reabras salvo que aportes evidencia nueva.

**Cómo trabajar:**

- Responde en español.
- Evalúa las propuestas con criterio propio: no las aceptes ni las rechaces por defecto. Si algo está mal, dilo y explica por qué.
- Separa siempre lo que es **hecho verificado**, **conclusión razonada**, **recomendación**, **hipótesis** e **información no verificada**.
- No inventes fuentes, cifras, resultados de pruebas ni contenido de archivos que no viste. Si no puedes verificar algo, dilo.
- Prefiere la solución más simple que cumpla los requisitos. No agregues complejidad sin justificarla.
- No modifiques archivos, no instales dependencias y no ejecutes comandos con efectos secundarios sin autorización explícita del equipo.

**Restricciones obligatorias del proyecto** (todas activas):

- Solo se usan los datos del reto, que son ficticios. Nunca datos reales de pacientes, afiliados ni colaboradores.
- No hay conexión ni integración con sistemas de EMI. El prototipo es una simulación independiente.
- No se publican cifras operativas como si fueran reales. Las marcas EMI y Falck se usan solo con revisión previa de la empresa.
- Hay acuerdo de confidencialidad: los datos del reto no se suben a repositorios ni a servicios externos.
- La herramienta sugiere; el despachador decide. No diagnostica ni asigna sola.

## 2. El reto

Grupo EMI – Falck necesita una herramienta que sugiera qué móvil enviar a cada servicio y muestre cómo esa decisión afecta el tiempo de respuesta y el costo. Hoy el despachador decide a mano y según su experiencia.

**La empresa.** Atención prehospitalaria por afiliación (emergencias, ambulancia, médico a domicilio, orientación telefónica, área protegida). Sede en Medellín. Un centro de despacho coordina la flota 24/7. Es parte del grupo danés Falck.

**El problema** (PDF, sección 02). Cuando entra un servicio ya clasificado, el despachador cruza a mano urgencia, ubicación del paciente, disponibilidad, posición y carga de cada móvil. Consecuencias: llegadas tarde en casos críticos, más kilómetros y costo, y carga mal repartida.

**Limitaciones que el PDF nombra** (sección 03):

- No hay recomendaciones automáticas.
- No se compara sistemáticamente costo contra tiempo de cada alternativa.
- No se anticipa cómo una asignación afecta la disponibilidad para los servicios siguientes.
- La calidad de la decisión varía según el despachador y la carga del momento.

**Lo que espera la empresa:** mejores tiempos en casos críticos, mejor uso de la flota, menos costos y decisiones consistentes. El archivo 07 del ZIP agrega: carga más pareja, ver costo y tiempo de cada alternativa, alertas de zona descubierta, orientación sobre cuándo enviar primero una VMD y explicar cada recomendación.

**Entregable:** un MVP (prototipo) que funciona como simulación independiente, con interfaz para que un empleado de EMI interactúe. El PDF no fija formato, fechas ni criterios de evaluación.

**Usuarios:** despachadores y paramédicos reguladores (usuarios directos), coordinadores de operación, tripulaciones y afiliados.

## 3. Datos disponibles y reglas del negocio

El ZIP del reto trae 8 archivos. Todos los datos son ficticios (generados por simulación); solo las comunas y municipios del Valle de Aburrá son reales.

| Archivo | Contenido |
| --- | --- |
| `00_Readme.docx` | Guía: diccionario de datos, escala EMI, tipos de móvil, fórmula del tiempo estimado, ideas y restricciones |
| `01_servicios_historicos.json` | 10.402 servicios del 16-mar al 30-abr-2026 (unos 226 al día), con clasificaciones, móviles, tiempos y estado de cierre |
| `02_moviles_y_bases.json` | 8 bases y 26 móviles: 5 TAM, 8 TAB, 13 VMD, con costo por km y por hora; 2 VMD en mantenimiento todo el periodo |
| `03_lineamientos_clasificacion_y_asignacion.docx` | Escala Manchester ↔ EMI, tiempos objetivo, matriz de compatibilidad, reglas R01–R07 y D01–D08, reclasificación |
| `04_proceso_despacho.docx` | Proceso actual, roles, estados de la móvil y casos especiales |
| `05_zonas_y_tiempos.xlsx` | 62 zonas (30 de demanda ALTA, 25 MEDIA, 7 BAJA), matriz de 3.844 pares de tiempos (valle y pico), factor de tráfico por día y hora, 10 centros de atención |
| `06_escenarios_referencia.xlsx` | 14 escenarios con 58 solicitudes, eventos y la decisión del despachador con el comentario del coordinador |
| `07_indicadores.xlsx` | 12 KPI con fórmula, meta y línea base, y los resultados esperados |

**Tiempos objetivo y móvil preferida** (documento 03):

| Código EMI | Manchester | Objetivo | Móvil preferida |
| --- | --- | --- | --- |
| 01 Emergencia | Rojo | 15 min | TAM (TAB si no hay TAM cercana) |
| 02 Urgencia | Naranja | 20 min | TAB (o TAM) |
| 07 Priorizado | Amarillo | 45 min | VMD (TAB si puede requerir traslado) |
| 03 Consulta | Verde | 90 min | VMD |
| 06 Consulta banal | Azul | 180 min | Orientación telefónica; si requiere visita, VMD |

**Matriz de compatibilidad:**

| Código | TAM | TAB | VMD |
| --- | --- | --- | --- |
| 01 | Preferida | Permitida (con apoyo VMD si es posible) | Solo estabilización |
| 02 | Permitida | Preferida | Solo estabilización |
| 07 | No recomendada | Permitida (si puede requerir traslado) | Preferida |
| 03 | No permitida | No recomendada | Preferida |
| 06 | No permitida | No permitida | Preferida |

**Reglas obligatorias:**

- **R01** Atender por prioridad 01 > 02 > 07 > 03 > 06; a igual prioridad, por orden de llegada.
- **R02** Los 01 y 02 se asignan de inmediato (máximo 2 min desde el paso a despacho).
- **R03** Solo TAM y TAB trasladan pacientes.
- **R04** Si para un 01 o 02 no hay ambulancia a tiempo y una VMD llega al menos 12 min antes, la VMD va como primer respondiente y se preasigna la primera ambulancia disponible.
- **R05** Una móvil fuera de servicio no se asigna.
- **R06** Una móvil en ruta a un 03 o 06 puede desviarse a un 01 o 02 cercano; el servicio original vuelve a la cola.
- **R07** Si un servicio se reclasifica, se aplican las reglas de la nueva clasificación.

**Reglas deseables** (donde la herramienta aporta más):

- **D01** Menor tiempo estimado de llegada, desde la posición actual y con el tráfico de la hora.
- **D02** Si dos opciones difieren en menos de 3 min, preferir la de menor costo.
- **D03** No dejar una zona de demanda ALTA sin ambulancia a 20 min o menos.
- **D04** Repartir la carga entre móviles del mismo tipo.
- **D05** No comprometer una TAM en un 02 si hay una TAB adecuada.
- **D06** En un 07 con posible traslado, considerar TAB.
- **D07** En un 01 atendido por TAB, enviar VMD de apoyo si hay una cercana.
- **D08** Las ambulancias en traslado pueden tardar en liberarse (retención de camilla).

**Fórmula del tiempo estimado** (Readme): tiempo en valle de la matriz × factor de tráfico del tipo de día y la hora.

**Calidad de datos:** cerca del 2 % de las llegadas están registradas tarde a propósito y 111 servicios (\~1 %) no tienen canal.

## 4. Hallazgos verificados en los datos

Estas cifras salen de análisis que el equipo hizo sobre el histórico (datos ficticios). Son hechos sobre esos datos, no sobre la operación real de EMI.

| Hallazgo | Dato | Qué implica |
| --- | --- | --- |
| La fórmula del Readme ya es buena | Explica el 84 % de la variación del tiempo de viaje; error medio de 3,6 min | Todo modelo se compara contra ella |
| El ML mejora el tiempo de viaje | Gradient boosting con corte por fecha (último 20 % como prueba): error de 2,77 min frente a 3,64 de la fórmula, un 24 % menos. Prueba preliminar, sin ajustar parámetros | Usar IA en esta parte está justificado |
| Gran parte del tiempo de un 01 no depende del despacho | Medianas: triaje 5,2 min, salida 2,3 min, viaje 11,4 min | Asignar mejor no basta para llegar a 15 min; prometer mejora relativa |
| El P90 de los 01 (52,9 min) está inflado | 71 servicios pasaron de 03 a 01 en sitio (mediana de 58 min). Los 01 desde el triaje: P90 de 35,9 min y 30 % de cumplimiento | Medir esos dos grupos por separado |
| La liberación tras un traslado es muy incierta | Retención de camilla: p10 = 24, mediana = 53, p90 = 104,5 min | Predecir con intervalo tiene mucho valor (D08) |
| Las escalaciones vienen de verde o amarillo | 425 reclasificaciones en 422 servicios: 307 al alza en sitio (03→01: 71, 03→02: 156, 07→01: 23, 07→02: 57), 98 a la baja, 20 telefónicas. Ninguna desde 06 (azul) | El ejemplo «azul a rojo» no existe en los datos |
| Respuesta actual a una escalación | Ambulancia asignada en el mismo minuto; llega en mediana 10,3 min (p90 18,2) | Es la métrica del escenario ESC-06 |
| La escalación no se puede predecir | Con motivo y discriminador del triaje, AUC de 0,556 (casi azar). Solo escalan los casos atendidos primero por VMD (6 %) | No prometer un modelo que la anticipe |
| Los casos leves esperan mucho | Esperan más de 60 min el 34,7 % de los 03 y el 63,3 % de los 06 | Ahí importarían las notificaciones al afiliado |
| Cancelaciones | 186 cancelaciones por el usuario; 184 ya tenían móvil asignada | Hipótesis no comprobable: avisar podría reducirlas |
| Mayoría atendida en sitio | 7.962 servicios (76,5 %) terminan como ATENDIDO\_EN\_SITIO | Relevante para un futuro seguimiento clínico |
| Línea base de utilización | Entre 34 % y 42 %, con meta de 60–75 % (archivo 07) | Con la misma flota y demanda, la asignación casi no la mueve |

**Contradicciones entre documentos:**

- El PDF habla de datos reales anonimizados; el ZIP dice que todo es ficticio.
- El PDF prometía «turno o disponibilidad» y «capacidad» de las móviles; el archivo 02 no los trae.
- Las metas del archivo 07 no cuadran entre sí: que el 90 % de los 01 llegue en 15 min (KPI-03) equivale a un P90 de 15, pero el KPI-01 pide P90 ≤ 20. Lo mismo para los 02 (KPI-02 pide ≤ 30).
- La regla R06 permite desvíos (no los prohíbe); el documento 04 limita los desvíos de una móvil en ruta a un 01 o un 02. El Readme (§9) sugiere reasignar con más libertad.
- El rol APOYO\_MEDICO aparece en los escenarios, pero no en el diccionario del histórico.
- La descripción de ESC-02 dice factor 1,65; la tabla da 1,6 a las 18:00. Diferencia menor.

## 5. Decisiones tomadas

Estas son las decisiones vigentes. Cada una tiene su razón; si una IA propone cambiarla, debe traer evidencia nueva.

| Tema | Decisión | Por qué |
| --- | --- | --- |
| Tipo de solución | App web de apoyo a la decisión: muestra las 3 mejores móviles con explicación y el despachador confirma o cambia | En salud el humano decide; el PDF pide sugerir, no automatizar |
| Arquitectura | «Predecir y luego decidir»: las reglas filtran, la IA predice tiempos, un puntaje ordena, el humano elige | Separa lo que es auditable (reglas) de lo que se aprende (tiempos) |
| Modelo núcleo | Gradient boosting para tiempo de llegada y liberación | Los árboles suelen ganar en datos tabulares de \~10.000 filas; ya mostró −24 % de error |
| Red neuronal | Se entrena como experimento comparado (MLP con embeddings de zona), sin prometer que gane | Muestra lo aprendido en el bootcamp sin comprometer el resultado |
| Línea base | La fórmula del Readme (matriz × factor) | Es coherente con los datos y fácil de explicar |
| Incertidumbre | Intervalos con predicción conformal (MAPIE) para la liberación | La retención varía de 24 a 104 min |
| Lo que no se usa | Ni aprendizaje por refuerzo, ni imitar al despachador, ni aprendizaje en línea | Riesgosos, opacos o copian el problema; se reentrena de forma periódica y con aprobación |
| Tiempos de viaje | Matriz × factor + corrección con ML. Sin OSRM ni otro motor de rutas | Un motor externo daría tiempos distintos a los del reto y no se podría validar |
| Datos externos | Sin datos de lluvia, movilidad ni festivos externos | El simulador no los contiene; los festivos ya están en el factor de tráfico |
| Mapa | Folium con teselas de OpenStreetMap y polígonos de comunas de GeoMedellín, solo visual. No usar mapas de sedes reales de EMI | Las bases del reto son ficticias; mezclar datos reales arriesga la confidencialidad |
| Ubicación | Se verifica la zona; no se captura la dirección exacta | El despacho la necesita, pero el reto excluye direcciones exactas |
| «Necesidades» | Solo operativas: posible traslado, varios pacientes, acceso difícil. Sin repetir el triaje clínico | El triaje ya lo hizo el paramédico; los datos de salud son sensibles |
| Insumos y novedades | Se reducen a un estado «no apta + motivo» | No están en ningún archivo del reto |
| Métrica principal | % de servicios dentro del tiempo objetivo (documento 03); P90 de apoyo; 01 reclasificados aparte | Resuelve la contradicción de metas del archivo 07 |
| Utilización 60–75 % | No se promete desde la asignación; el simulador ofrece un «qué pasa si» de móviles por franja | Con la misma flota y demanda, la asignación solo reparte la carga |
| Desvíos en ruta | Solo hacia un 01 o un 02. Desde un 03 o 06, normal (R06). Desde un 07, o de un 02 a un 01, como «propuesta extendida» con confirmación y una ganancia mínima de minutos | Respeta el documento 04 y evita que las móviles reboten entre servicios |
| Escalaciones | Recalcular la recomendación al instante, mostrar un plan B, reordenar la cola en reclasificaciones telefónicas y ofrecer las móviles que se liberan antes | Ya es parte del proceso (R07); el aporte es hacerlo más rápido y visible |
| Notificaciones al afiliado | Complemento, no núcleo: panel con mensajes simulados (llegada en rango, aviso de retraso, botón «empeoró» que deriva al triaje) | La competencia ya ofrece seguimiento; el usuario principal es el despachador |
| Seguimiento posterior | En el MVP: retroalimentación de la tripulación al cerrar (¿el tipo de móvil fue adecuado?). Seguimiento clínico: futuro | El clínico usa datos de salud y no se puede medir con estos datos |
| Factor diferencial | «Qué pierdo si envío esta móvil»: cobertura que queda y plan B, en minutos | Responde una limitación que el PDF nombra y casi no agranda el MVP |
| Despliegue | Demo local, repositorio privado, datos del reto fuera de Git | Acuerdo de confidencialidad |

## 6. Arquitectura, contrato de datos y stack

Todo pasa por el motor de decisión: los modelos le dan tiempos, el simulador le da solicitudes y flota, y la interfaz solo muestra lo que el motor devuelve.

**Flujo de una recomendación:**

1. Entra una solicitud clasificada y el estado de la flota (desde el simulador).
2. Se filtran las móviles con las reglas R01–R07.
3. La IA predice, para cada móvil apta, el tiempo de llegada y la hora de liberación, con rango.
4. Un puntaje combina tiempo frente al objetivo, costo, cobertura que queda y carga (D01–D08).
5. Se muestran las 3 mejores con una frase de explicación.
6. El despachador confirma o cambia, con un motivo elegido de una lista.
7. La decisión se registra, alimenta el tablero y hace avanzar la simulación.

**Estructura del repositorio:**

```text
reto-emi/
├── datos/            # NO se sube a Git
├── notebooks/        # exploración y entrenamiento
├── modelos/          # funciones de predicción y modelos guardados
├── motor/            # reglas, puntaje, cobertura, explicación
├── simulador/        # SimPy, escenarios, líneas base, métricas
├── app/              # Streamlit, una página por pantalla
├── tests/            # pytest
├── contrato/         # objetos y ejemplos en JSON
├── resultados/       # salidas de las pruebas; fuente única de cifras
├── config.toml       # pesos, umbrales y costos
└── requirements.txt  # versiones fijas
```

**Objetos del contrato:**

| Objeto | Campos mínimos |
| --- | --- |
| Solicitud | id, hora, zona, código EMI y color Manchester, motivo, estado, posible traslado |
| Móvil | id, tipo (TAM, TAB, VMD), estado, zona actual, base, hora estimada en que queda libre, servicios del turno |
| Predicción | minutos estimados, rango bajo y alto, modelo usado |
| Recomendación | puesto (1 a 3), móvil, llegada con rango, costo estimado, cobertura que queda, plan B, reglas aplicadas, explicación |
| Evento | hora, tipo (nueva solicitud, reclasificación, liberación, cancelación, decisión), datos |

**Funciones que conectan los módulos:**

```python
predecir_llegada(zona_origen, zona_destino, hora, tipo_movil) -> Prediccion
predecir_liberacion(solicitud, movil) -> Prediccion
recomendar(solicitud, flota, hora, config) -> list[Recomendacion]  # máximo 3
impacto_cobertura(flota, candidata, hora) -> Cobertura
cargar_escenario(id_escenario) -> Estado
avanzar(estado, decision) -> Estado
correr(politica, desde, hasta) -> Resultados
```

Los objetos se definen con `dataclasses` (sin librerías nuevas). Las variables de los modelos son solo las que existen al decidir: nunca la distancia recorrida ni horas posteriores.

**Stack:**

| Uso | Herramienta |
| --- | --- |
| Exploración y entrenamiento | Python 3.10+, Jupyter o Colab, pandas |
| Modelos | scikit-learn (gradient boosting), TensorFlow/Keras (red neuronal), MAPIE v1 (intervalos) |
| Simulador | SimPy |
| Interfaz | Streamlit con `st.navigation` y `st.Page`, Folium con streamlit-folium |
| Pruebas | pytest y GitHub Actions |
| Modelos guardados | joblib y .keras |
| Configuración | `config.toml` y `requirements.txt` con versiones fijas |
| Código | GitHub privado |

Quitados del stack original: OSRM, datos de lluvia, movilidad y festivos externos. La GPU de Colab no hace falta. Ojo: MAPIE v1 cambió sus clases (`MapieRegressor` pasó a `SplitConformalRegressor`, entre otras), así que los tutoriales viejos no funcionan.

## 7. Funciones del MVP y factor diferencial

El MVP tiene seis pantallas y un factor diferencial: mostrar, junto a cada opción, qué se pierde al elegirla.

**Pantallas:**

1. **Cola de solicitudes:** ordenada por prioridad, con código y color, tiempo en cola frente al objetivo y aviso cuando se acerca al límite.
2. **Panel de la solicitud:** tres tarjetas con llegada en rango, costo, cobertura que queda, plan B y etiqueta «recomendada» o «no recomendada»; la explicación en una frase; botones Confirmar y Cambiar.
3. **Mapa:** móviles por estado y zonas de demanda ALTA coloreadas por minutos hasta la ambulancia más cercana.
4. **Control de móviles:** estado y marca «no apta + motivo», que el motor respeta.
5. **Tablero:** cumplimiento por clase, P90, carga por móvil, tiempo con zonas descubiertas y comparación entre la asignación actual y la recomendada.
6. **Reproductor de escenarios:** elegir ESC-01 a ESC-14 y mover un reloj simulado.

**Factor diferencial: «qué pierdo si envío esta móvil».** Para cada candidata:

1. Tomar la foto actual de la flota (posiciones, estados, matriz × factor de la hora).
2. Quitar esa móvil, como si ya se hubiera enviado.
3. Recalcular la ambulancia más cercana a cada zona de demanda ALTA y a la zona del paciente.
4. Comparar antes y después: minutos perdidos, zonas que pasan de 20 min (D03) y plan B si el caso escala.
5. Sumarlo al puntaje y convertirlo en una frase, por ejemplo «deja San Javier a 24 min».

Usa solo datos del reto (archivos 02 y 05). Son unas 26 × 62 consultas por solicitud, que se calculan en milisegundos. Un solo cálculo da tres cosas: la alerta de zona descubierta, el plan B y la explicación.

**Por qué es el diferencial:** responde la limitación del PDF «no se anticipa cómo una asignación afecta la disponibilidad para los siguientes servicios». En la literatura, la regla «la ambulancia libre más cercana» dio cerca de 2,7 veces más llegadas tarde que la política óptima en un sistema real holandés (Jagtenberg y otros). Para EMI, la mejora se mide en la simulación; no se promete.

**Ejemplo de la maqueta del panel** (datos ficticios): servicio 03 en Laureles, objetivo de 90 min.

| Opción | Llega en | Costo | Cobertura que queda | Plan B si escala a 01 |
| --- | --- | --- | --- | --- |
| VMD-014 (recomendada) | 9 min (7–12) | $38 mil | Sin cambios | TAB-07 a 11 min |
| TAB-07 (no recomendada para un 03) | 7 min (6–9) | $61 mil | San Javier pasa de 9 a 24 min | TAM-03 a 16 min |
| VMD-021 | 15 min (12–19) | $35 mil | Sin cambios | TAB-07 a 11 min |

**Complementos si sobra tiempo:** notificaciones simuladas al afiliado y retroalimentación de la tripulación al cerrar el servicio.

## 8. Validación y métricas

El MVP se valida en cuatro capas y todas las cifras del pitch salen de una sola carpeta, `resultados/`, generada con un comando (`python correr_todo.py`).

1. **Modelos.** Corte por fecha: primeras semanas para entrenar, últimas para probar. Se comparan fórmula, gradient boosting y red neuronal por error medio, en general y por zona y franja, con un mínimo de casos por grupo. Se comprueba que los rangos aciertan tantas veces como prometen.
2. **Simulación.** Se reproducen 1 o 2 semanas del histórico con tres políticas: la móvil más cercana, la decisión histórica y la recomendación del motor. Semilla fija.
3. **Escenarios del coordinador.** En cuántas de las 10 decisiones «discutibles» o con alternativa del archivo 06 coincide la herramienta con el coordinador. Es la validación más creíble, porque usa el criterio de la empresa.
4. **Usuarios.** Prueba cualitativa con 5 personas (ideal, de operación de EMI) que resuelven tres tareas pensando en voz alta: hora pico (ESC-03), móvil no apta y reclasificación en sitio (ESC-06).

**Métricas:**

- **Principal:** % de servicios dentro del tiempo objetivo por clase, con los 01 del triaje y los 01 reclasificados por separado.
- **De apoyo:** P90 del tiempo de respuesta, km, costo, reparto de carga (KPI-06), tiempo con zonas ALTA descubiertas y tiempo desde una reclasificación hasta que llega la ambulancia.
- **Prueba automática, no resultado:** cero asignaciones a móviles no aptas (pytest en cada cambio).

**Reglas para comunicar resultados:**

- Se promete mejora relativa frente a la línea base, nunca llegar a 15 min en todos los 01.
- Siempre se dice que las cifras vienen de datos ficticios y de una simulación.
- Si la red neuronal no gana, se reporta tal cual.

## 9. Equipo, fases y forma de trabajo

El plan supone 5 personas con roles fijos y cinco fases sin fechas; el detalle paso a paso está en la [guía de trabajo](https://claude.ai/artifact/NRL3tG948s4rFKtWKko4kC).

| Rol | Es dueño de |
| --- | --- |
| P1 · Datos y modelos | Limpieza, variables, fórmula, gradient boosting, red neuronal, intervalos (`modelos/`) |
| P2 · Motor de decisión e integrador | Reglas, puntaje, factor diferencial, explicaciones, contrato y rama `main` (`motor/`) |
| P3 · Simulador y validación | SimPy, escenarios, líneas base, métricas y pruebas (`simulador/`, `tests/`) |
| P4 · Interfaz | App en Streamlit con las seis pantallas (`app/`) |
| P5 · Producto, UX y marketing | Recorridos, bocetos, pruebas con usuarios, pitch y guión de la demo |

Con 3 personas: P1+P3, P2, P4+P5. Con 4: P4+P5 juntos. Con 6: P3 se divide en simulador y pruebas.

**Fases y puntos de integración:**

| Fase | Termina con |
| --- | --- |
| F0 · Arranque | I0: contrato de datos acordado, repositorio creado, datos de prueba listos |
| F1 · Piezas con datos de prueba | I1: la app abre ESC-03 de punta a punta con versiones provisionales |
| F2 · Piezas reales | I2: modelos reales, motor completo, 14 escenarios corriendo |
| F3 · Integración y pruebas | I3 (a mitad de F3): congelamiento; solo arreglos |
| F4 · Demo y pitch | Dos ensayos sin fallos y video de respaldo |

**Reglas de trabajo:**

- En F0 cada módulo publica una versión provisional que respeta el contrato: los modelos devuelven la fórmula del Readme, el motor devuelve las 3 móviles compatibles más cercanas y el simulador carga solo ESC-03.
- Una rama por tarea (`p1/...`, `p4/...`); todo entra a `main` por pull request revisado por el integrador y con pruebas en verde.
- Solo el integrador cambia el contrato; cada cambio se anota en el README.
- Pesos y umbrales solo en `config.toml`.
- Los modelos entrenados en Colab se copian a `modelos/` con una nota de versión.

## 10. Fuera de alcance, supuestos y preguntas abiertas

Lo que sigue no está en el MVP o todavía no está confirmado; una IA no debe tratarlo como requisito.

**Fuera del alcance del MVP:**

- Integración con el sistema de despacho de EMI o con cualquier sistema real.
- Asignación automática sin confirmación humana, y cualquier diagnóstico o triaje clínico.
- App real de notificaciones al afiliado (solo mensajes simulados) y seguimiento clínico posterior.
- Predecir qué casos van a escalar (los datos no lo sostienen).
- Aprendizaje por refuerzo y aprendizaje en línea.
- Motores de rutas externos y datos externos de clima o movilidad.
- Publicar la demo en internet.

**Supuestos vigentes:**

- El equipo es de 5 personas.
- La demo corre en un computador del equipo.
- El acompañante de operación de EMI que ofrece el PDF estará disponible para resolver dudas.

**Preguntas abiertas** (para el acompañante de EMI o para el equipo):

- Fechas de entrega y criterios de evaluación de la hackatón. El archivo 07 menciona una «hackatón 3», lo que sugiere varias etapas.
- Cuál meta de KPI rige oficialmente cuando se contradicen (el equipo usa el % dentro del objetivo).
- Si los desvíos desde un 07, o de un 02 hacia un 01, son aceptables.
- Si la cobertura de EMI se define por un perímetro de ciudad y si quieren una alerta cuando un servicio queda fuera.
- Si la app actual de EMI ya muestra el seguimiento en vivo al afiliado.
- Si EMI puede poner despachadores para las pruebas de uso.
- Pendiente interno: la sección 9 de la pizarra (maqueta del factor diferencial) no se pudo agregar porque la pizarra está compartida de forma pública.

## 11. Glosario y enlaces

| Término | Significado |
| --- | --- |
| TAM | Ambulancia medicalizada (transporte asistencial medicalizado) |
| TAB | Ambulancia básica (transporte asistencial básico) |
| VMD | Vehículo con médico a domicilio; no traslada pacientes |
| Códigos EMI | 01 emergencia, 02 urgencia, 07 priorizado, 03 consulta, 06 consulta banal |
| Escala Manchester | Triaje de cinco colores: rojo, naranja, amarillo, verde, azul |
| Reclasificación | Cambio de código de un servicio: telefónica (el afiliado vuelve a llamar) o en sitio (la tripulación), al alza o a la baja |
| Retención de camilla | Tiempo que una ambulancia espera en urgencias tras entregar al paciente |
| Primer respondiente | VMD que llega antes a estabilizar mientras llega la ambulancia (R04) |
| Zona de demanda ALTA | Una de las 30 zonas del archivo 05 con más demanda; la regla D03 pide cubrirlas a 20 min o menos |
| P90 | Tiempo dentro del cual llega el 90 % de los servicios |
| Contrato de datos | Los cinco objetos y funciones que conectan los módulos (sección 6) |
| Plan B | Ambulancia que respondería si el caso escala, con sus minutos |

**Enlaces del equipo:**

- [Pizarra con los diagramas de decisiones](https://claude.ai/artifact/1jCWWL4KyvLLCszsYxMYZ9)
- [Guía de trabajo del MVP (roles, pasos, integración y pruebas)](https://claude.ai/artifact/NRL3tG948s4rFKtWKko4kC)

**Fuentes externas usadas en las decisiones:**

- [Grinsztajn y otros (2022): los árboles superan al deep learning en datos tabulares](https://arxiv.org/abs/2207.08815)
- [Jagtenberg y otros: la regla «la más cercana» frente a la política óptima](https://core.ac.uk/download/301650233.pdf)
- [MAPIE v1: notas de la versión](https://mapie.readthedocs.io/en/latest/getting-started/v1-release-notes/)
- [Streamlit: apps de varias páginas](https://docs.streamlit.io/develop/concepts/multipage-apps/overview)
