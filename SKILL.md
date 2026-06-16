---
name: mundial-predictor
description: Predice el Mundial 2026 (probabilidad de campeon, avance por rondas, tabla de grupos en vivo) con un motor Elo evolutivo + Monte Carlo, y lo ACTUALIZA fecha a fecha con los resultados reales del torneo. Usala cuando Alejandro diga "actualiza el mundial", "cargar fecha del mundial", "como va el predictor", "quien va ganando el mundial", o quiera revisar/regenerar el panel. Proyecto PERSONAL.
---

# Mundial 2026 — Predictor (fecha a fecha)

Motor determinista ($0, sin alucinacion) + capa de analisis (vos, el agente) + panel HTML.
Disenado para acompanar TODO el torneo: cada fecha que se carga, las predicciones se recalculan solas.

## Arquitectura

- `data/teams.json` — 48 equipos por grupo, Elo semilla, esqueleto del bracket. **Estatico.**
- `data/fixtures.json` — calendario datado de la fase de grupos (72 partidos, fuente Wikipedia). **Estatico.**
- `data/players.json` — candidatos de consenso (con cuota/rating) a Bota de Oro, Guante de Oro y Mejor Joven. **Estatico** (actualizable si querés refrescar cuotas).
- `data/results.json` — ledger de resultados REALES (crece fecha a fecha). **Lo unico que editas normalmente.**
- `data/state.json` — estado calculado (lo escribe el motor).
- `data/evolution.json` — snapshot de prob. de campeon por fecha (curva de evolucion).
- `data/model_config.json` — knobs del motor (capa ataque/defensa `ad_weight`, localia `host_advantage_elo`). **Dormidos (0) por defecto**: el modelo es identico al Elo+Poisson puro. Validar por backtest antes de activar. Ver `MEJORAS-MOTOR.md`.
- `data/goals_history.json` — historial de goles pre-torneo por equipo (vacio; poblar con fuente, **nunca inventar**) para sembrar los ratings de ataque/defensa.
- `engine.py` — Elo evolutivo + Monte Carlo + prediccion por partido. Recalcula todo y regenera el panel.
- `panel.html` — panel con tabs: **Por fecha** (acordeon por dia, el dia activo abierto; cada partido
  jugado con resultado real o por jugar con prediccion 1X2 + marcador), **Campeon**, **Puntaje**,
  **Comparativa** (OLD Elo puro vs NEW con capa ataque/defensa, todos los partidos),
  **Evaluacion** (auto-backtest: Brier vs baseline + calibracion), **Premios**,
  **Avance**, **Grupos**, **Evolucion**, **Resultados**, **Metodologia**.

**Modelo mejorado como analista (decision 16-jun):** el **modelo mejorado** (Elo + capa ataque/defensa,
`ad_weight=0.5`) es el analista principal — las predicciones por fecha, grupos y campeon lo usan. La pestana
**Comparativa** deja ver el modelo Elo puro (OLD) vs el mejorado (NEW) lado a lado. El **juego de puntos**
(Puntaje) usa el mejorado **desde `scoring_modelo_desde` en adelante** (lo jugado antes queda con Elo puro).
Cada partido en **Por fecha** abre un **popup** (clic en la fila) que explica el pronostico: Elo, ratings
ataque/defensa y ultimos partidos de ambos equipos. Para volver al Elo puro en todo: `ad_weight=0`.

Cada partido por jugar trae P(gana local / empate / gana visita) y el marcador mas probable, calculados
analiticamente (Poisson sobre el Elo actual). Al cargar un resultado real, ese partido pasa de prediccion
a resultado y todo se recalcula.

**Tab Avance:** tabla de prob. de alcanzar cada ronda + **proyeccion del cuadro** (cruce mas probable
armado con los clasificados modales por grupo y el ganador estimado de cada llave via Elo). Es una
proyeccion puntual: cambia con cada resultado.

**Tab Premios:** **podio** (P de terminar 1°/2°/3°, con partido por el 3er puesto simulado) + estimacion
de **Bota de Oro / Guante de Oro / Mejor Joven**. Estos premios individuales = `consenso de mercado
(cuota/rating de players.json) × recorrido simulado del equipo`. Es heuristica, NO certeza: decirlo siempre.

El Elo **evoluciona** aplicando cada resultado del ledger (K=60 estilo eloratings). Un equipo que rinde
mas de lo esperado sube su Elo -> sube su probabilidad. Ademas los puntos ya ganados entran en la
simulacion de los partidos de grupo que faltan. Doble efecto, correcto.

## Workflow: cargar una fecha nueva (lo que hara Alejandro contigo)

Cuando te pida actualizar (ej. "carga la fecha del mundial" / "actualiza con los partidos de hoy"):

1. **Buscar los resultados reales** de la(s) fecha(s) faltante(s) por web (WebSearch/WebFetch).
   Fuentes confiables: ESPN, NBC Sports, olympics.com, Wikipedia del grupo, sitio FIFA.
2. **REGLA DE ORO (anti-alucinacion):** NUNCA inventes un marcador. Solo cargas un partido si tenes
   el marcador FINAL confirmado con una fuente. Si un partido esta en curso, no termino, o no podes
   confirmarlo -> NO lo cargas, lo dejas pendiente y lo decis. Dato sin fuente = no entra.
3. **Agregar cada partido** a `data/results.json` -> array `partidos`, con este formato exacto:
   ```json
   {"fecha":"2026-06-15","fase":"grupos","grupo":"H","local":"Spain","visita":"Cape Verde",
    "gl":2,"gv":0,"fuente":"https://..."}
   ```
   - `fase`: grupos | dieciseisavos | octavos | cuartos | semis | tercer_puesto | final
   - En eliminatorias omiti `grupo`. Los nombres de equipo deben coincidir EXACTO con teams.json.
   - Actualiza tambien `_meta.ultima_fecha_cargada` a la fecha mas reciente cargada.
4. **Re-correr el motor:**
   ```bash
   cd ~/.claude/skills/mundial-predictor && python3 engine.py
   ```
   (agrega `--sims 20000` si queres mas precision; `--rebuild-evolution` para reconstruir la curva entera).
5. **Analizar el diff (tu valor agregado):** compara el top de campeon antes/despues y narra que cambio
   y por que (que equipo subio/bajo, sorpresas, grupos que se definieron). Esa es la lectura "fecha a fecha".
6. Ofrecele abrir/ver el `panel.html` actualizado.

## Reglas duras

- **Cero marcadores inventados.** Es la regla #1. Ante la duda, pendiente.
- **Cita la fuente** de cada resultado en el propio ledger (campo `fuente`).
- Las predicciones son **probabilisticas**, nunca certezas. Decilo siempre.
- No toques `teams.json` salvo que cambie algo estructural (no deberia).
- Si un equipo no clasifico de grupo y aparece un resultado de eliminatoria con un nombre que no
  esta en teams.json -> alerta, no fuerces.

## Limitaciones conocidas (decirlas, no esconderlas)

- **Bracket:** el esqueleto de Round of 32 esta en el **orden de arbol OFICIAL** (Wikipedia knockout
  stage), asi que los cruces de octavos/cuartos/semis/final son los reales y dos equipos del mismo grupo
  NO se cruzan antes de la final (verificado). Lo unico aproximado: la asignacion fina de cada 3er lugar
  a su slot (la tabla FIFA es deterministica recien al cerrar la fase de grupos); el motor la resuelve por
  matching respetando los grupos permitidos de cada slot.
- **Tiebreakers de grupo:** puntos -> dif. de gol -> goles a favor (simplificado; FIFA usa mas criterios).
- **Elo semilla** de eloratings.net (~11-jun-2026); el motor lo evoluciona desde ahi.
- Sin ventaja de localia (los anfitriones no tienen bonus de cancha en el modelo).

## Estado inicial (cargado al construir)

12 partidos verificados (11–14 jun). El 15-jun quedo pendiente (estaba en curso al construir).
Top campeon inicial: Spain ~28%, Argentina ~18%, France ~14%, England ~8%, Brazil ~5%.
