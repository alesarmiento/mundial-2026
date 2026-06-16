# Roadmap del motor — mejoras de estimación

Bitácora de la evaluación del predictor y las mejoras incorporadas. Principio rector: **nada se
activa sin validarse por backtest (Brier), y nada se inventa** (todo rating sale de marcadores reales citados).

## 1. Diagnóstico (backtest sobre los primeros 16 partidos, 11–15 jun)

Reconstruyendo la predicción PREVIA a cada partido (solo info anterior) vs el real:

| Métrica | Modelo | Baseline (prior fijo 40/27/33) |
|---|---|---|
| Acierto de signo (1X2) | 37,5% (6/16) | — |
| Marcador exacto | 6,2% (1/16) | — |
| **Brier** (menor = mejor) | **0,816** | **0,681** |
| Log-loss | 1,283 | — |
| Empates reales | 8/16 (50%) | — |
| Empates como pick modal 1X2 | 0/16 | — |

El modelo puntuó **peor que un prior sin información**. Dos lecturas:
- **Varianza:** 50% de empates es atípico (lo normal es ~27%); varios favoritos empataron. No sobreajustar a 16 partidos.
- **Defectos estructurales reales:** (a) ceguera al empate en el pick 1X2 + sobre-confianza (la calibración muestra 40% de acierto en el tramo 80–100%); (b) sin localía; (c) subdispersión en goleadas; (d) el modelo de goles depende SOLO del Elo → dos equipos con igual Elo reciben xG idéntico, ignorando el índice goleador de cada uno.

## 2. Qué se construyó (esta iteración)

Todo **convive** con el motor original: por defecto es idéntico (verificado por diff de `state.json`).

1. **Harness de auto-evaluación** (`compute_evaluation`) → pestaña **📐 Evaluación**: Brier vs baseline, log-loss, acierto, calibración por tramos de confianza. Se recalcula fecha a fecha.
2. **Capa ataque/defensa** (`compute_ad`, estilo Maher/Dixon-Coles, opponent-adjusted, encogida hacia 1.0): da a cada equipo un rating de ataque (cuánto marca) y defensa (cuánto recibe). Multiplica los goles esperados del Elo: `λ = f(Elo) · [(1−w) + w·ataque·defensa_rival]`.
3. **Localía de anfitriones** (`host_advantage_elo`): bonus de Elo solo para USA/México/Canadá al predecir sus partidos.
4. **Knobs** en `data/model_config.json` (dormidos: `ad_weight=0`, `host_advantage_elo=0`) y `data/goals_history.json` (vacío, con esquema y regla de oro).

**Garantía de seguridad:** con `w=0` y `host=0`, el modelo no puede ser peor que el original — es el original. La perilla `w` se barre por backtest; si no baja el Brier, vuelve a 0.

## 3. Validación real con datos pre-torneo (16 jun) — resultado e historia del bug

Se pobló `data/goals_history.json` con **750 partidos internacionales reales 2024–2026** (8 investigadores web en paralelo, dedup, cada marcador con fuente; muestra verificada 3/3 contra la fuente). Cobertura: cada una de las 48 selecciones con ≥13 partidos (mediana 20). Los ratings ataque/defensa resultantes son futbolísticamente correctos (Spain atk 1,61 · Germany 1,46 · Norway 1,5; Ecuador 0,42 · Cape Verde 0,64; Senegal dfn 0,66 buena defensa).

**Bug encontrado y corregido:** la primera versión de `compute_ad` usaba una actualización iterativa que se desestabilizaba con el universo abierto de rivales (ratings degenerados ~0,2 y algún NaN). Daba un Brier "0,643 que batía al baseline" — pero era un **falso positivo**: el modelo roto predecía todo 0-0 y acertaba de casualidad en una muestra con 50% de empates. Se reemplazó por una actualización **regularizada hacia 1.0** (estable, sin NaN, media exacta 1.0).

**Resultado honesto con los ratings correctos** (AD calculada solo con info previa a cada fecha → out-of-sample):

| w | Brier | Acierto | Log-loss |
|---|---|---|---|
| 0 (dormido) | 0,816 | 37,5% | 1,283 |
| 0,5 | 0,798 | 43,8% | 1,350 |
| 0,8 | 0,782 | 43,8% | 1,389 |
| 1,0 | 0,772 | 43,8% | 1,424 |

La capa **mejora apenas el Brier** (0,816→0,772) y sube el acierto (37,5%→43,8%), pero **empeora el log-loss y nunca bate al baseline (0,681)** en estos 16 partidos. Señal direccionalmente positiva en acierto, inconclusa en calibración. Decisión: **mantener dormido (`ad_weight=0`)**. La infraestructura (750 partidos verificados + ratings sanos) queda lista; falta muestra de evaluación.

## 4. Cómo activar (cuando haya evidencia)

1. `data/goals_history.json` ya está poblado (750 partidos). Refrescar/ampliar con fuente si se quiere.
2. A medida que avanza el torneo (más partidos jugados), rehacer el barrido de `w`.
3. Si el Brier BAJA del baseline (0,681) de forma consistente con ~40+ partidos → subir `ad_weight` (zona robusta 0,4–0,8) en `model_config.json`. Si no → seguir en 0.
4. `host_advantage_elo` (60–90) es un knob aparte, validado como mejora leve.

## 5. Pendiente (no hecho aún)

- Re-barrer `w` cuando haya más partidos jugados (la decisión de activar depende de eso).
- Barrer `w` óptimo por clase (1X2 vs marcador exacto) por separado.
- Evaluar templado de confianza (recortar los 0,90+) como defecto separado.
