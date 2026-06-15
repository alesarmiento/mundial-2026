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

5. **Si hubo cambios:** correr `python3 engine.py` (regenera `index.html`), luego
   `git add -A && git commit -m "auto: actualizar Mundial" && git push`. GitHub Pages republica solo.

6. **Auto-ritmo:** programar el próximo despertar para después del próximo bloque de partidos del
   calendario (no chequear en horas sin partidos). En días sin partidos, dormir hasta el siguiente día con fixture.

## Notas
- Los premios y la proyección de bracket se recalculan solos al correr el motor.
- Las eliminatorias empiezan ~28-jun; ahí los partidos del ledger usan `fase` (no `grupo`).
- Panel en vivo: https://alesarmiento.github.io/mundial-2026/
