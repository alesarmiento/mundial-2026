# Rutina automática — Mundial 2026 predictor

Esta rutina actualiza el sistema y republica el panel cada vez que cierran partidos.
Se ejecuta en la nube (auto-ritmo: despertar cuando deberían haber terminado partidos).

## Pasos en cada ejecución

1. **Mirar el calendario y el estado.** Lee `data/fixtures.json` (calendario) y
   `data/results.json` (`_meta.ultima_fecha_cargada` + partidos ya cargados). Hoy = fecha actual.
   Identificá qué partidos del calendario, con fecha <= hoy, AÚN no están en el ledger.

2. **Buscar resultados confirmados** de esos partidos por web (ESPN, NBC, olympics.com, FIFA, BBC).
   **REGLA DE ORO (anti-alucinación): NUNCA inventes un marcador.** Solo cargás un partido si tenés
   el marcador FINAL confirmado con una fuente. Si está en curso, no empezó o no se puede confirmar,
   NO lo cargás (queda para la próxima vez). Dato sin fuente = no entra.

3. **Agregar** cada partido confirmado a `data/results.json` → array `partidos`, formato:
   `{"fecha":"YYYY-MM-DD","fase":"grupos","grupo":"X","local":"A","visita":"B","gl":n,"gv":m,"fuente":"URL"}`
   - Eliminatorias: `fase` ∈ dieciseisavos|octavos|cuartos|semis|tercer_puesto|final, sin `grupo`.
   - Nombres EXACTOS como en `data/teams.json`. Actualizá `_meta.ultima_fecha_cargada`.

4. **Si NO hubo ningún resultado nuevo confirmado → terminar sin commitear** (no hacer deploys vacíos).

5. **Si hubo cambios:** correr `python3 engine.py`. Una sola corrida **recalcula TODO el sistema**:
   la fuerza Elo de cada selección, las probabilidades de campeón y de avance por ronda, los premios
   (goleador/arquero/joven), la proyección del cuadro de eliminatorias Y el **puntaje de la polla del
   modelo** (suma los puntos del/los partido(s) nuevo(s); cada partido se puntúa con el pronóstico PREVIO
   al partido, sin mirar el resultado). Un solo partido puede mover todo.
   **Luego, SIEMPRE correr también `python3 generar-ultima-fecha.py`** para regenerar la vista
   `ultima-fecha.html` (la página "Mi estimación / última fecha" con los pronósticos de Alejandro y su
   puntaje de participación). El generador lee el `state.json` recién calculado + los picks fijos del
   usuario, así que la participación se actualiza sola con cada resultado real. **No editar los picks**
   (están fijos en el script; solo Alejandro los cambia). Luego
   `git add -A && git commit -m "auto: actualizar Mundial" && git push`. GitHub Pages republica solo.
   *(Equivalente: `./deploy.sh`, que ya corre el motor + el generador + commit + push.)*

6. **Reporte final en palabras simples** (para Alejandro, no técnico): qué partido(s) cargaste con su
   marcador; cómo se movieron las probabilidades (quién subió/bajó, si cambió el favorito); cómo quedó el
   puntaje (ganado y en juego); y que publicaste. Si no hubo nada nuevo, decir "sin novedades".

6. **Auto-ritmo:** programar el próximo despertar para después del próximo bloque de partidos del
   calendario (no chequear en horas sin partidos). En días sin partidos, dormir hasta el siguiente día con fixture.

## Análisis del día: mercado + capa de IA (scouting)

En el **mismo paso** en que se analizan las cuotas del día (`data/market.json`), poblar también la
**capa de inteligencia cualitativa** `data/scouting.json` para los partidos del día. Son hermanas:
una es la visión del mercado, la otra la lectura del analista.

- Para cada partido del día, investigar por web (ESPN, NBC, sitios oficiales, Sports Mole, Rotowire):
  **alineación probable/confirmada, bajas/lesiones/suspensiones, contexto** y una **lectura corta + lean**.
- **REGLA DE ORO (igual que el mercado y los resultados): NADA sin fuente.** Si una baja o un XI no se
  puede confirmar, marcarlo "en duda" o no incluirlo. NUNCA inventar nombres, lesiones ni alineaciones.
  Citar las URLs en `fuentes`.
- Alineaciones: `estado_alineacion="probable"` hasta ~60 min antes del pitazo; al confirmarse, pasar a
  `"confirmada"` y actualizar el XI real.
- **Esta capa SOLO se muestra en el modal — NO modifica el motor, ni las probabilidades, ni el puntaje.**
  El engine la pasa tal cual al panel. Decisión de diseño (19-jun): mantener el motor 100% determinista.
- Ver el contrato de campos en `data/scouting.json` (`_meta`).

## Notas
- Los premios y la proyección de bracket se recalculan solos al correr el motor.
- **NO toques `data/picks.json`** (picks de torneo congelados para el puntaje) — solo se edita results.json.
- En eliminatorias que se definan por penales, agregá el campo `"ganador":"Equipo"` al partido en el ledger.
- **Al cerrar el torneo:** creá `data/awards_actual.json` con `{"goleador":"Nombre","arquero":"Nombre","joven":"Nombre"}` (los ganadores oficiales reales) para que el puntaje resuelva esos 3 premios.
- Las eliminatorias empiezan ~28-jun; ahí los partidos del ledger usan `fase` (no `grupo`).
- Panel en vivo: https://alesarmiento.github.io/mundial-2026/
