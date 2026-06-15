#!/usr/bin/env python3
"""
Mundial 2026 — Motor de prediccion (Elo evolutivo + Monte Carlo).

Diseno: data-driven y re-corrible durante TODO el torneo.
  - teams.json   : grupos, Elo semilla, esqueleto del bracket (estatico)
  - results.json : ledger de resultados REALES (crece fecha a fecha)
  - El Elo evoluciona aplicando cada resultado del ledger.
  - Monte Carlo simula lo que falta -> probabilidades de avance y de campeon.
  - Cada corrida regenera panel.html y registra un snapshot en evolution.json.

Uso:
  python3 engine.py                 # corre con N por defecto, regenera panel
  python3 engine.py --sims 20000    # mas simulaciones (mas preciso, mas lento)
  python3 engine.py --rebuild-evolution   # reconstruye la curva fecha a fecha

Sin dependencias externas (solo stdlib).
"""

import json, os, sys, math, random
from collections import defaultdict
from itertools import combinations

random.seed(42)  # reproducible: misma data -> mismo panel

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")

# ---------- carga ----------
def load(name):
    with open(os.path.join(DATA, name), encoding="utf-8") as f:
        return json.load(f)

def save(name, obj):
    with open(os.path.join(DATA, name), "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)

# ---------- Elo ----------
def expected(ra, rb):
    return 1.0 / (1.0 + 10 ** ((rb - ra) / 400.0))

def elo_after(results, seed):
    """Aplica cada resultado cronologicamente. K=60 (mundial), ajustado por dif de goles."""
    elo = dict(seed)
    for m in sorted(results, key=lambda x: x["fecha"]):
        a, b = m["local"], m["visita"]
        if a not in elo or b not in elo:
            continue
        gl, gv = m["gl"], m["gv"]
        sa = 1.0 if gl > gv else (0.5 if gl == gv else 0.0)
        gd = abs(gl - gv)
        g = 1.0 if gd <= 1 else (1.5 if gd == 2 else (11 + gd) / 8.0)
        ea = expected(elo[a], elo[b])
        delta = 60 * g * (sa - ea)
        elo[a] += delta
        elo[b] -= delta
    return elo

# ---------- modelo de partido ----------
def sample_goals(ra, rb):
    """Marcador via Poisson; goles esperados derivados de la dif de Elo."""
    diff = ra - rb
    sup = diff / 150.0                      # ventaja de goles esperada
    base = 1.35
    la = max(0.18, base + sup / 2.0)
    lb = max(0.18, base - sup / 2.0)
    return _poisson(la), _poisson(lb)

def _poisson(lam):
    L = math.exp(-lam); k = 0; p = 1.0
    while True:
        k += 1; p *= random.random()
        if p <= L:
            return k - 1

def ko_winner(a, ra, b, rb):
    """Eliminatoria: ganador via expectativa Elo (empate -> penales, leve sesgo Elo)."""
    return a if random.random() < expected(ra, rb) else b

def _lambdas(ra, rb):
    sup = (ra - rb) / 150.0
    base = 1.35
    return max(0.18, base + sup / 2.0), max(0.18, base - sup / 2.0)

def match_pred(home, away, elo):
    """Prediccion analitica de un partido: P(gana local/empate/gana visita) + marcador mas probable."""
    if home not in elo or away not in elo:
        return None
    la, lb = _lambdas(elo[home], elo[away])
    pa = [math.exp(-la) * la ** i / math.factorial(i) for i in range(9)]
    pb = [math.exp(-lb) * lb ** j / math.factorial(j) for j in range(9)]
    pH = pD = pA = 0.0
    best, bestp = (0, 0), -1.0
    for i in range(9):
        for j in range(9):
            p = pa[i] * pb[j]
            if i > j: pH += p
            elif i == j: pD += p
            else: pA += p
            if p > bestp: bestp, best = p, (i, j)
    s = pH + pD + pA
    return {"pH": round(100 * pH / s, 1), "pD": round(100 * pD / s, 1),
            "pA": round(100 * pA / s, 1), "score": [best[0], best[1]],
            "xgH": round(la, 2), "xgA": round(lb, 2)}

def build_por_fecha(teams, results, elo, fixtures, anchor):
    """Vista por dia: cada partido con resultado real (si jugado) o prediccion (si por jugar)."""
    played = {frozenset((m["local"], m["visita"])): m for m in results}
    by_date = defaultdict(list)
    seen = set()
    for fx in fixtures:
        h, a = fx["home"], fx["away"]
        key = frozenset((h, a)); seen.add(key)
        e = {"home": h, "away": a, "grupo": fx.get("grupo"), "fase": fx.get("fase", "grupos")}
        r = played.get(key)
        if r:
            e["jugado"] = True
            if r["local"] == h: e["gl"], e["gv"] = r["gl"], r["gv"]
            else: e["gl"], e["gv"] = r["gv"], r["gl"]
            e["fuente"] = r.get("fuente")
        else:
            e["jugado"] = False
            e["pred"] = match_pred(h, a, elo)
        by_date[fx["date"]].append(e)
    # resultados sin fixture en el calendario (p.ej. eliminatorias cargadas a mano)
    for m in results:
        if frozenset((m["local"], m["visita"])) not in seen:
            by_date[m["fecha"]].append({"home": m["local"], "away": m["visita"],
                "grupo": m.get("grupo"), "fase": m.get("fase"), "jugado": True,
                "gl": m["gl"], "gv": m["gv"], "fuente": m.get("fuente")})
    dates = sorted(by_date)
    out = []
    for d in dates:
        ms = by_date[d]
        out.append({"fecha": d, "jugados": sum(1 for x in ms if x["jugado"]),
                    "total": len(ms), "partidos": ms})
    # fecha activa: primera fecha >= anchor con algun partido sin jugar; si no, la ultima
    pend = [o["fecha"] for o in out if o["jugados"] < o["total"]]
    activa = next((f for f in pend if f >= anchor), (pend[0] if pend else (dates[-1] if dates else None)))
    return out, activa

# ---------- premios individuales (consenso x recorrido simulado) ----------
def expected_matches(probs):
    """Partidos esperados por equipo = 3 de grupo + esperanza de partidos de eliminatoria."""
    em = {}
    for t, p in probs.items():
        ko = (p["r32"] + p["octavos"] + p["cuartos"] + p["semis"] + p["final"]) / 100.0
        bronce = max(0.0, p["semis"] - p["final"]) / 100.0   # perdedor de semi juega 3er puesto
        em[t] = 3.0 + ko + bronce
    return em

def estimate_awards(players, probs, em, elo):
    if not players:
        return {}
    def fin(rows):
        s = sum(w for _, w in rows) or 1.0
        out = [{"jugador": c["jugador"], "equipo": c["equipo"], "odds": c.get("odds", ""),
                "prob": round(100 * w / s, 1)} for c, w in rows]
        return sorted(out, key=lambda x: x["prob"], reverse=True)
    # Goleador: rating x partidos esperados (mas juega, mas chances)
    gole = [(c, c["rating"] * em[c["equipo"]]) for c in players.get("goleador", []) if c["equipo"] in em]
    # Arquero: rating x recorrido profundo x solidez defensiva (Elo)
    arq = []
    for c in players.get("arquero", []):
        t = c["equipo"]
        if t not in probs: continue
        deep = probs[t]["cuartos"] / 100.0 + 0.05
        defn = max(0.2, (elo[t] - 1500) / 700.0)
        arq.append((c, c["rating"] * deep * defn))
    # Joven: rating x exposicion (partidos esperados)
    jov = [(c, c["rating"] * em[c["equipo"]]) for c in players.get("joven", []) if c["equipo"] in em]
    return {"goleador": fin(gole), "arquero": fin(arq), "joven": fin(jov)}

# ---------- proyeccion del cuadro de eliminatorias (cruce modal) ----------
def projected_bracket(teams, probs, elo):
    grupos = teams["grupos"]; skeleton = teams["r32_skeleton"]
    g1 = {g: max(ts, key=lambda t: probs[t]["grupo1"]) for g, ts in grupos.items()}
    g2 = {g: max(ts, key=lambda t: probs[t]["g2"]) for g, ts in grupos.items()}
    thirdq = {t: max(0.0, probs[t]["r32"] - probs[t]["top2"]) for t in probs}
    group_third = {g: max(ts, key=lambda t: thirdq[t]) for g, ts in grupos.items()}
    used = set(g1.values()) | set(g2.values())
    assign, taken = {}, set()
    for s in [s for s in skeleton if s["away"].startswith("3:")]:
        allowed = s["away"].split(":")[1].split(",")
        cand = [g for g in allowed if g not in taken and group_third[g] not in used]
        if not cand:
            cand = [g for g in allowed if g not in taken]
        cand.sort(key=lambda g: thirdq[group_third[g]], reverse=True)
        if cand:
            assign[s["slot"]] = group_third[cand[0]]; taken.add(cand[0])
        else:
            assign[s["slot"]] = None
    def res(code):
        if code.startswith("3:"): return None
        return g1[code[1]] if code[0] == "1" else g2[code[1]]
    pairs = []
    for s in skeleton:
        h = res(s["home"])
        a = assign[s["slot"]] if s["away"].startswith("3:") else res(s["away"])
        pairs.append((h, a))
    bracket = []
    for nm in ["Dieciseisavos", "Octavos", "Cuartos", "Semifinal", "Final"]:
        matches, winners = [], []
        for h, a in pairs:
            if h and a:
                ph = round(100 * expected(elo[h], elo[a]), 1)
                w = h if ph >= 50 else a
                matches.append({"home": h, "away": a, "pHome": ph, "pAway": round(100 - ph, 1), "winner": w})
            else:
                w = h or a or "?"
                matches.append({"home": h or "?", "away": a or "?", "pHome": None, "pAway": None, "winner": w})
            winners.append(w)
        bracket.append({"ronda": nm, "partidos": matches})
        if len(winners) <= 1:
            break
        pairs = [(winners[i], winners[i + 1]) for i in range(0, len(winners), 2)]
    champion = bracket[-1]["partidos"][0]["winner"] if bracket else None
    return {"rondas": bracket, "campeon_proyectado": champion}

# ---------- standings de grupos (con resultados reales) ----------
def base_table(grupos):
    t = {}
    for g, teams in grupos.items():
        for tm in teams:
            t[tm] = {"grupo": g, "pj": 0, "pts": 0, "gf": 0, "gc": 0}
    return t

def apply_group_results(table, results):
    played = set()
    for m in results:
        if m.get("fase") != "grupos":
            continue
        a, b, gl, gv = m["local"], m["visita"], m["gl"], m["gv"]
        if a not in table or b not in table:
            continue
        for tm, gf, gc in ((a, gl, gv), (b, gv, gl)):
            table[tm]["pj"] += 1; table[tm]["gf"] += gf; table[tm]["gc"] += gc
            table[tm]["pts"] += 3 if gf > gc else (1 if gf == gc else 0)
        played.add(frozenset((a, b)))
    return played

def all_group_fixtures(grupos):
    fx = []
    for g, teams in grupos.items():
        for a, b in combinations(teams, 2):
            fx.append((g, a, b))
    return fx

def rank_key(s):
    return (s["pts"], s["gf"] - s["gc"], s["gf"])

# ---------- una simulacion ----------
def simulate_once(grupos, elo, base, played, fixtures, skeleton):
    # copia mutable de la tabla
    tab = {tm: dict(v) for tm, v in base.items()}
    for g, a, b in fixtures:
        if frozenset((a, b)) in played:
            continue
        gl, gv = sample_goals(elo[a], elo[b])
        for tm, gf, gc in ((a, gl, gv), (b, gv, gl)):
            tab[tm]["pts"] += 3 if gf > gc else (1 if gf == gc else 0)
            tab[tm]["gf"] += gf; tab[tm]["gc"] += gc

    # ordenar cada grupo
    winners, runners, thirds = {}, {}, []
    for g, teams in grupos.items():
        order = sorted(teams, key=lambda t: rank_key(tab[t]), reverse=True)
        winners[g] = order[0]; runners[g] = order[1]
        thirds.append((g, order[2], rank_key(tab[order[2]])))
    # 8 mejores terceros
    thirds.sort(key=lambda x: x[2], reverse=True)
    qualn_thirds = thirds[:8]
    third_by_group = {g: tm for g, tm, _ in qualn_thirds}

    # resolver slots de terceros (matching contra grupos permitidos)
    slots3 = [s for s in skeleton if s["away"].startswith("3:")]
    avail = dict(third_by_group)  # grupo -> equipo
    assign = {}
    def backtrack(i):
        if i == len(slots3):
            return True
        allowed = slots3[i]["away"].split(":")[1].split(",")
        for g in allowed:
            if g in avail:
                assign[slots3[i]["slot"]] = avail.pop(g)
                if backtrack(i + 1):
                    return True
                avail[g] = assign.pop(slots3[i]["slot"])
        return False
    if not backtrack(0):
        # fallback: asignar en orden
        rem = list(third_by_group.values())
        for s in slots3:
            assign[s["slot"]] = rem.pop() if rem else next(iter(third_by_group.values()))

    def resolve(code):
        if code.startswith("3:"):
            return None  # se llena via assign
        pos, g = code[0], code[1]
        return winners[g] if pos == "1" else runners[g]

    # armar R32
    bracket = []
    for s in skeleton:
        home = resolve(s["home"])
        away = assign[s["slot"]] if s["away"].startswith("3:") else resolve(s["away"])
        bracket.append((home, away))

    # rondas eliminatorias (cruce secuencial; la final SE JUEGA)
    # r32 (32) -> octavos (16) -> cuartos (8) -> semis (4) -> final (2) -> campeon (1)
    reached = {"r32": [t for pair in bracket for t in pair]}
    winners_r = [ko_winner(a, elo[a], b, elo[b]) for a, b in bracket]  # 16
    reached["octavos"] = list(winners_r)
    cur = winners_r
    for st in ["cuartos", "semis", "final", "campeon"]:   # 16->8->4->2->1
        nxt = [ko_winner(cur[i], elo[cur[i]], cur[i + 1], elo[cur[i + 1]])
               for i in range(0, len(cur), 2)]
        reached[st] = list(nxt)
        cur = nxt
    return winners, runners, third_by_group, reached

# ---------- agregacion Monte Carlo ----------
def run_mc(grupos, elo, base, played, fixtures, skeleton, n):
    teams = list(base.keys())
    cnt = {t: {"grupo1": 0, "g2": 0, "top2": 0, "r32": 0, "octavos": 0, "cuartos": 0,
               "semis": 0, "final": 0, "campeon": 0, "sub": 0, "tercero": 0} for t in teams}
    for _ in range(n):
        winners, runners, thirds, reached = simulate_once(
            grupos, elo, base, played, fixtures, skeleton)
        for g, t in winners.items():
            cnt[t]["grupo1"] += 1; cnt[t]["top2"] += 1; cnt[t]["r32"] += 1
        for g, t in runners.items():
            cnt[t]["g2"] += 1; cnt[t]["top2"] += 1; cnt[t]["r32"] += 1
        for g, t in thirds.items():
            cnt[t]["r32"] += 1
        for t in reached["octavos"]:
            cnt[t]["octavos"] += 1
        for t in reached["cuartos"]:
            cnt[t]["cuartos"] += 1
        for t in reached["semis"]:
            cnt[t]["semis"] += 1
        for t in reached["final"]:
            cnt[t]["final"] += 1
        champ = reached["campeon"][0]
        finalistas = reached["final"]
        cnt[champ]["campeon"] += 1
        ru = finalistas[0] if finalistas[1] == champ else finalistas[1]
        cnt[ru]["sub"] += 1
        perdedores_semi = [t for t in reached["semis"] if t not in finalistas]
        if len(perdedores_semi) == 2:
            a, b = perdedores_semi
            tercero = ko_winner(a, elo[a], b, elo[b])
        elif perdedores_semi:
            tercero = perdedores_semi[0]
        else:
            tercero = None
        if tercero:
            cnt[tercero]["tercero"] += 1
    probs = {}
    for t in teams:
        probs[t] = {k: round(100.0 * v / n, 1) for k, v in cnt[t].items()}
    return probs

# ---------- snapshot de evolucion ----------
def upsert_evolution(fecha, probs, topn=8):
    path = os.path.join(DATA, "evolution.json")
    ev = []
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            ev = json.load(f)
    top = sorted(probs.items(), key=lambda x: x[1]["campeon"], reverse=True)[:topn]
    snap = {"fecha": fecha, "campeon": {t: p["campeon"] for t, p in top}}
    ev = [e for e in ev if e["fecha"] != fecha]
    ev.append(snap)
    ev.sort(key=lambda x: x["fecha"])
    save("evolution.json", ev)
    return ev

# ---------- orquestacion ----------
def compute(results_subset, teams, n):
    grupos = teams["grupos"]; seed = teams["elo_seed"]; skeleton = teams["r32_skeleton"]
    elo = elo_after(results_subset, seed)
    base = base_table(grupos)
    played = apply_group_results(base, results_subset)
    fixtures = all_group_fixtures(grupos)
    probs = run_mc(grupos, elo, base, played, fixtures, skeleton, n)
    return elo, base, probs, len(played), len(fixtures)

def main():
    n = 12000
    rebuild = "--rebuild-evolution" in sys.argv
    if "--sims" in sys.argv:
        n = int(sys.argv[sys.argv.index("--sims") + 1])

    teams = load("teams.json")
    res = load("results.json")
    results = res["partidos"]
    ultima = res["_meta"].get("ultima_fecha_cargada") or (
        max((m["fecha"] for m in results), default="—"))

    if rebuild:
        # reconstruye curva: corre el motor con cortes por cada fecha
        if os.path.exists(os.path.join(DATA, "evolution.json")):
            os.remove(os.path.join(DATA, "evolution.json"))
        fechas = sorted(set(m["fecha"] for m in results))
        for f in fechas:
            subset = [m for m in results if m["fecha"] <= f]
            _, _, probs, _, _ = compute(subset, teams, max(4000, n // 3))
            upsert_evolution(f, probs)
        print(f"Evolucion reconstruida para {len(fechas)} fechas.")

    elo, base, probs, n_played, n_total = compute(results, teams, n)
    ev = upsert_evolution(ultima, probs)

    fixtures = []
    fx_meta = {}
    fx_path = os.path.join(DATA, "fixtures.json")
    if os.path.exists(fx_path):
        fxjson = load("fixtures.json"); fixtures = fxjson.get("fixtures", []); fx_meta = fxjson.get("_meta", {})
    por_fecha, fecha_activa = build_por_fecha(teams, results, elo, fixtures, ultima)

    players = {}
    pl_path = os.path.join(DATA, "players.json")
    if os.path.exists(pl_path):
        players = load("players.json")

    tmeta = teams.get("_meta", {}); pmeta = players.get("_meta", {}) if players else {}
    metodologia = {
        "sims": n, "equipos": 48, "grupos": 12, "n_resultados": len(results),
        "fuentes": [
            {"que": "Grupos y equipos (sorteo oficial)", "fuente": tmeta.get("grupos_fuente", "")},
            {"que": "Elo semilla — fuerza inicial de cada seleccion", "fuente": tmeta.get("elo_fuente", "")},
            {"que": "Calendario de la fase de grupos", "fuente": fx_meta.get("fuente", "")},
            {"que": "Resultados reales", "fuente": "Cada partido cargado trae su fuente citada (ver tab Resultados). Regla de oro: nunca se inventa un marcador; si no esta confirmado, queda pendiente."},
            {"que": "Arbol de eliminatorias", "fuente": "Wikipedia '2026 FIFA World Cup knockout stage' + ESPN — validado sin discrepancias."},
            {"que": "Candidatos a premios (cuotas/consenso)", "fuente": " · ".join(pmeta.get("fuentes", [])) if pmeta else ""},
        ],
    }
    em = expected_matches(probs)
    premios = estimate_awards(players, probs, em, elo)
    proyeccion = projected_bracket(teams, probs, elo)
    podio = sorted(
        [{"equipo": t, "p1": probs[t]["campeon"], "p2": probs[t]["sub"],
          "p3": probs[t]["tercero"], "top3": round(probs[t]["campeon"] + probs[t]["sub"] + probs[t]["tercero"], 1)}
         for t in probs], key=lambda x: x["top3"], reverse=True)[:10]

    # estado para el panel
    state = {
        "generado": ultima,
        "ultima_fecha_cargada": ultima,
        "sims": n,
        "grupos_jugados": n_played,
        "grupos_total": n_total,
        "grupos": teams["grupos"],
        "elo_actual": {t: round(r) for t, r in sorted(elo.items(), key=lambda x: -x[1])},
        "tabla": tabla_view(base, teams["grupos"]),
        "probs": probs,
        "ranking_campeon": sorted(
            [{"equipo": t, **p} for t, p in probs.items()],
            key=lambda x: x["campeon"], reverse=True),
        "evolucion": ev,
        "por_fecha": por_fecha,
        "fecha_activa": fecha_activa,
        "podio": podio,
        "premios": premios,
        "proyeccion": proyeccion,
        "metodologia": metodologia,
        "resultados": sorted(results, key=lambda m: m["fecha"]),
        "nota_bracket": teams.get("_nota_bracket", ""),
    }
    save("state.json", state)
    render_panel(state)
    top = state["ranking_campeon"][:5]
    print(f"OK · {n_played}/{n_total} partidos de grupo jugados · {n} sims")
    print("Top 5 campeon:", ", ".join(f"{x['equipo']} {x['campeon']}%" for x in top))
    print("Panel:", os.path.join(HERE, "panel.html"))

def tabla_view(base, grupos):
    out = {}
    for g, teams in grupos.items():
        order = sorted(teams, key=lambda t: rank_key(base[t]), reverse=True)
        out[g] = [{"equipo": t, "pj": base[t]["pj"], "pts": base[t]["pts"],
                   "gf": base[t]["gf"], "gc": base[t]["gc"],
                   "dg": base[t]["gf"] - base[t]["gc"]} for t in order]
    return out

# ---------- panel HTML ----------
def render_panel(state):
    html = PANEL_TEMPLATE.replace("__STATE__", json.dumps(state, ensure_ascii=False))
    # panel.html (vista local) + index.html (lo que sirve GitHub Pages)
    for fn in ("panel.html", "index.html"):
        with open(os.path.join(HERE, fn), "w", encoding="utf-8") as f:
            f.write(html)

PANEL_TEMPLATE = r"""<!DOCTYPE html>
<html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Mundial 2026 · Predictor</title>
<style>
:root{--bg:#0d1117;--card:#161b22;--bd:#272e3a;--tx:#e6edf3;--mut:#8b949e;--ac:#3fb950;--ac2:#58a6ff;--warn:#d29922}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--tx);font:14px/1.5 -apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;padding:24px;max-width:1100px;margin:0 auto}
h1{font-size:22px;font-weight:700;letter-spacing:-.3px}
.sub{color:var(--mut);font-size:13px;margin-top:2px}
.tabs{display:flex;gap:4px;margin:20px 0 16px;flex-wrap:wrap}
.tab{padding:8px 14px;border:1px solid var(--bd);border-radius:8px;background:var(--card);color:var(--mut);cursor:pointer;font-weight:600;font-size:13px}
.tab.on{color:var(--tx);border-color:var(--ac2);background:#1b2433}
.pane{display:none}.pane.on{display:block}
.card{background:var(--card);border:1px solid var(--bd);border-radius:12px;padding:16px;margin-bottom:14px}
table{width:100%;border-collapse:collapse;font-size:13px}
th,td{text-align:left;padding:7px 8px;border-bottom:1px solid var(--bd)}
th{color:var(--mut);font-weight:600;font-size:11px;text-transform:uppercase;letter-spacing:.4px}
td.n,th.n{text-align:right;font-variant-numeric:tabular-nums}
.bar{height:8px;border-radius:4px;background:#21262d;overflow:hidden;min-width:60px}
.bar>i{display:block;height:100%;background:linear-gradient(90deg,var(--ac2),var(--ac))}
.q{color:var(--ac);font-weight:700}
.muted{color:var(--mut)}
.grp{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:12px}
.gtitle{font-weight:700;font-size:13px;margin-bottom:6px;color:var(--ac2)}
.chip{display:inline-block;padding:2px 7px;border-radius:6px;background:#1b2433;border:1px solid var(--bd);font-size:11px;color:var(--mut);margin-left:6px}
.warn{color:var(--warn);font-size:12px;border-left:3px solid var(--warn);padding-left:10px;margin:10px 0}
.pos1{color:var(--ac)}.pos2{color:var(--ac2)}
svg{width:100%;height:auto}
.lg{font-size:12px;color:var(--mut);display:flex;gap:14px;flex-wrap:wrap;margin-top:8px}
.lg span{display:flex;align-items:center;gap:5px}.dot{width:10px;height:10px;border-radius:50%}
a{color:var(--ac2);text-decoration:none}
.foot{color:var(--mut);font-size:11px;margin-top:20px;border-top:1px solid var(--bd);padding-top:12px}
.acc{margin-bottom:8px;border:1px solid var(--bd);border-radius:10px;overflow:hidden}
.acc-h{display:flex;align-items:center;gap:10px;padding:11px 14px;cursor:pointer;background:#13192199;font-weight:600;user-select:none}
.acc-h:hover{background:#1b2433}
.acc-h .cnt{margin-left:auto;font-size:12px;color:var(--mut);font-weight:500}
.acc-h .car{transition:transform .15s;color:var(--mut);font-size:11px}
.acc.open .acc-h .car{transform:rotate(90deg)}
.acc-b{display:none;padding:2px 12px 8px}
.acc.open .acc-b{display:block}
.mrow{display:flex;align-items:center;gap:12px;padding:9px 4px;border-bottom:1px solid var(--bd);font-size:13px;flex-wrap:wrap}
.mrow:last-child{border-bottom:none}
.mrow .gc{font-size:10px;color:var(--mut);width:30px;flex:none}
.mrow .tm{flex:1;display:flex;justify-content:space-between;gap:8px;min-width:200px;max-width:330px}
.sc{font-variant-numeric:tabular-nums;font-weight:700;min-width:42px;text-align:center}
.seg{display:flex;height:20px;border-radius:5px;overflow:hidden;flex:1;min-width:150px;max-width:300px}
.seg>div{display:flex;align-items:center;justify-content:center;color:#0d1117;white-space:nowrap;font-size:10px;font-weight:700}
.pron{font-size:11px;color:var(--mut);min-width:62px;text-align:right}
.done{color:var(--ac);font-size:11px}
.rname{font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.5px;color:var(--ac2);margin:14px 0 4px}
.bk{display:flex;overflow-x:auto;padding:6px 2px 14px;gap:0}
.bkcol{display:flex;flex-direction:column;justify-content:space-around;min-width:150px;flex:0 0 auto}
.bkcol.fin{justify-content:center;min-width:160px}
.bkhd{font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.4px;color:var(--mut);text-align:center;padding:0 14px 8px}
.pair{display:flex;flex-direction:column;justify-content:space-around;flex:1;position:relative}
.bm{position:relative;margin:5px 16px;background:#0f1520;border:1px solid var(--bd);border-radius:7px;overflow:hidden;flex:0 0 auto}
.br{display:flex;justify-content:space-between;gap:8px;padding:5px 9px;font-size:12px}
.br+.br{border-top:1px solid var(--bd)}
.br .tn{white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:96px}
.br .pp{color:var(--mut);font-variant-numeric:tabular-nums;font-size:11px;flex:none}
.br.w{background:#11301c}.br.w .tn{color:var(--ac);font-weight:700}.br.w .pp{color:var(--ac)}
.bm::after{content:'';position:absolute;right:-16px;top:50%;width:16px;height:2px;background:var(--bd)}
.bkcol.fin .bm::after,.champ::after{display:none}
.pair::after{content:'';position:absolute;right:-16px;top:25%;bottom:25%;width:2px;background:var(--bd)}
.bkcol:last-of-type .bm::after,.bkcol.fin .pair::after{display:none}
.champ{margin:5px 8px;padding:10px 14px;border:1px solid var(--ac);border-radius:9px;background:#11301c;text-align:center}
.champ .lab{font-size:10px;color:var(--mut);text-transform:uppercase;letter-spacing:.5px}
.champ .nm{font-size:15px;font-weight:800;color:var(--ac);margin-top:2px}
</style></head><body>
<h1>⚽ Mundial 2026 · Predictor</h1>
<div class="sub" id="sub"></div>
<div class="tabs" id="tabs"></div>
<div id="panes"></div>
<div class="foot">
  Motor Elo evolutivo + Monte Carlo · <span id="simn"></span> simulaciones · semilla Elo eloratings.net.
  Predicciones probabilisticas, no certezas. Resultados reales con fuente citada en la pestana Resultados.
</div>
<script>
const S = __STATE__;
const COLORS=['#58a6ff','#3fb950','#d29922','#f85149','#bc8cff','#39c5cf','#ff7b72','#7ee787'];
const $=(t,a={},...c)=>{const e=document.createElement(t);for(const k in a)k==='html'?e.innerHTML=a[k]:e.setAttribute(k,a[k]);c.forEach(x=>e.append(x));return e};
document.getElementById('sub').textContent =
  `Ultima fecha cargada: ${S.ultima_fecha_cargada} · ${S.grupos_jugados}/${S.grupos_total} partidos de grupo jugados`;
document.getElementById('simn').textContent = S.sims.toLocaleString();

const PANES = [
  ['porfecha','📅 Por fecha', paneFecha],
  ['campeon','🏆 Campeon', paneCampeon],
  ['premios','🏅 Premios', panePremios],
  ['bracket','🔀 Avance', paneBracket],
  ['grupos','📊 Grupos', paneGrupos],
  ['evol','📈 Evolucion', paneEvol],
  ['result','📋 Resultados', paneResult],
  ['metodo','ℹ️ Metodologia', paneMetodo],
];
const tabs=document.getElementById('tabs'), panes=document.getElementById('panes');
PANES.forEach(([id,label,fn],i)=>{
  const t=$('div',{class:'tab'+(i===0?' on':'')},label); t.onclick=()=>sel(id); tabs.append(t);
  const p=$('div',{class:'pane'+(i===0?' on':''),id:'pane-'+id}); fn(p); panes.append(p);
});
function sel(id){PANES.forEach(([x])=>{document.getElementById('pane-'+x).classList.toggle('on',x===id)});
  [...tabs.children].forEach((t,i)=>t.classList.toggle('on',PANES[i][0]===id))}
if(location.hash && PANES.some(x=>x[0]===location.hash.slice(1)))sel(location.hash.slice(1));

function pct(v){return v.toFixed(1)+'%'}
function barCell(v,max=100){const c=$('td',{class:'n'});const b=$('div',{class:'bar'});const i=$('i');
  i.style.width=Math.min(100,v/max*100)+'%';b.append(i);
  const wrap=$('div',{},$('span',{class:v>0?'q':'muted'},document.createTextNode(pct(v))));
  wrap.style.cssText='display:flex;align-items:center;gap:8px';wrap.prepend(b);c.append(wrap);return c}

function fmtDate(d){const p=d.split('-');const ms=['ene','feb','mar','abr','may','jun','jul','ago','sep','oct','nov','dic'];return p[2]+' '+ms[+p[1]-1]}
function matchRow(m){
  const r=$('div',{class:'mrow'});
  r.append($('span',{class:'gc'}, m.grupo?('Gr '+m.grupo):(m.fase||'')));
  r.append($('span',{class:'tm'},$('b',{},m.home),$('span',{class:'muted'},'vs'),$('b',{},m.away)));
  if(m.jugado){
    r.append($('span',{class:'sc'}, m.gl+'–'+m.gv));
    r.append($('span',{class:'done'},'✓ final'));
    if(m.fuente)r.append($('a',{href:m.fuente,target:'_blank'},'fuente'));
  } else if(m.pred){
    const seg=$('div',{class:'seg'});
    [['pH','#58a6ff','L'],['pD','#6e7681','E'],['pA','#bc8cff','V']].forEach(([k,c,lab])=>{
      const v=m.pred[k];const d=$('div',{}, v>=12?(lab+' '+Math.round(v)+'%'):'');
      d.style.background=c;d.style.width=v+'%';seg.append(d)});
    r.append(seg);
    r.append($('span',{class:'pron'},'pron '+m.pred.score[0]+'–'+m.pred.score[1]));
  } else { r.append($('span',{class:'muted'},'—')) }
  return r;
}
function paneFecha(p){
  const intro=$('div',{class:'muted',html:'<small>Dia en curso abierto por defecto · toca cualquier dia para expandir. Jugados con resultado real (fuente); por jugar con prediccion del modelo: <b style="color:#58a6ff">L</b> gana local · <b style="color:#8b949e">E</b> empate · <b style="color:#bc8cff">V</b> gana visita · “pron” = marcador mas probable.</small>'});
  intro.style.marginBottom='12px';p.append(intro);
  S.por_fecha.forEach(day=>{
    const open=day.fecha===S.fecha_activa;
    const acc=$('div',{class:'acc'+(open?' open':'')});
    const h=$('div',{class:'acc-h'});
    h.append($('span',{class:'car'},'▶'),$('span',{},'📅 '+fmtDate(day.fecha)),
      $('span',{class:'cnt'}, day.jugados+'/'+day.total+' jugados'));
    h.onclick=()=>acc.classList.toggle('open');
    const b=$('div',{class:'acc-b'});
    day.partidos.forEach(m=>b.append(matchRow(m)));
    acc.append(h,b);p.append(acc);
  });
}
function paneCampeon(p){
  const card=$('div',{class:'card'});
  const tb=$('table');tb.append($('tr',{},$('th',{},'#'),$('th',{},'Equipo'),
    $('th',{class:'n'},'Campeon'),$('th',{class:'n'},'Final'),$('th',{class:'n'},'Semis'),
    $('th',{class:'n'},'Cuartos'),$('th',{class:'n'},'Pasa de grupo')));
  S.ranking_campeon.slice(0,24).forEach((r,i)=>{
    const tr=$('tr',{});tr.append($('td',{class:'muted'},String(i+1)),$('td',{html:'<b>'+r.equipo+'</b>'}));
    tr.append(barCell(r.campeon));
    [r.final,r.semis,r.cuartos,r.top2].forEach(v=>tr.append($('td',{class:'n muted'},pct(v))));
    tb.append(tr)});
  card.append($('div',{class:'gtitle'},'Probabilidad de ganar el Mundial'),tb);
  p.append(card);
  if(S.nota_bracket)p.append($('div',{class:'warn'},S.nota_bracket));
}

function paneGrupos(p){
  const wrap=$('div',{class:'grp'});
  for(const g of Object.keys(S.tabla)){
    const c=$('div',{class:'card'});c.append($('div',{class:'gtitle'},'Grupo '+g));
    const tb=$('table');tb.append($('tr',{},$('th',{},'Equipo'),$('th',{class:'n'},'PJ'),
      $('th',{class:'n'},'Pts'),$('th',{class:'n'},'DG'),$('th',{class:'n'},'Pasa%')));
    S.tabla[g].forEach((row,i)=>{
      const tr=$('tr',{});const cls=i===0?'pos1':i===1?'pos2':'';
      tr.append($('td',{html:'<span class="'+cls+'">'+row.equipo+'</span>'}),
        $('td',{class:'n'},String(row.pj)),$('td',{class:'n'},String(row.pts)),
        $('td',{class:'n'},(row.dg>0?'+':'')+row.dg),
        $('td',{class:'n q'},pct(S.probs[row.equipo].top2)));
      tb.append(tr)});
    c.append(tb);wrap.append(c)}
  p.append(wrap);
}

function paneBracket(p){
  const card=$('div',{class:'card'});
  card.append($('div',{class:'gtitle'},'Probabilidad de alcanzar cada ronda'));
  const tb=$('table');tb.append($('tr',{},$('th',{},'Equipo'),$('th',{class:'n'},'R32'),
    $('th',{class:'n'},'Octavos'),$('th',{class:'n'},'Cuartos'),$('th',{class:'n'},'Semis'),
    $('th',{class:'n'},'Final'),$('th',{class:'n'},'Campeon')));
  S.ranking_campeon.slice(0,24).forEach(r=>{
    const tr=$('tr',{});tr.append($('td',{html:'<b>'+r.equipo+'</b>'}));
    [r.r32,r.octavos,r.cuartos,r.semis,r.final,r.campeon].forEach((v,i)=>
      tr.append($('td',{class:'n'+(i===5?' q':' muted')},pct(v))));
    tb.append(tr)});
  card.append(tb);p.append(card);
  // Proyeccion del cuadro (arbol de eliminatorias)
  const pr=S.proyeccion;
  if(pr && pr.rondas){
    const pc=$('div',{class:'card'});
    pc.append($('div',{class:'gtitle'},'🔮 Proyeccion del cuadro — arbol de eliminatorias'));
    pc.append($('div',{class:'muted',html:'<small>Cruces segun el <b>arbol oficial</b> (Wikipedia knockout stage), con los clasificados mas probables por grupo y el ganador estimado de cada llave (prob. via Elo). Proyeccion puntual: cambia con cada resultado.</small>'}));
    pc.append(bracketTree(pr));
    p.append(pc);
  }
  if(S.nota_bracket)p.append($('div',{class:'warn'},S.nota_bracket));
}

function bmBox(m){
  const box=$('div',{class:'bm'});
  [['home','pHome'],['away','pAway']].forEach(([t,pk])=>{
    const win=m.winner===m[t];
    const r=$('div',{class:'br'+(win?' w':'')});
    r.append($('span',{class:'tn'}, m[t]||'—'));
    r.append($('span',{class:'pp'}, m[pk]!=null?(m[pk]+'%'):''));
    box.append(r);
  });
  return box;
}
function bracketTree(pr){
  const bk=$('div',{class:'bk'});
  const labels={'Dieciseisavos':'16avos','Octavos':'Octavos','Cuartos':'Cuartos','Semifinal':'Semis','Final':'Final'};
  pr.rondas.forEach((rd,ci)=>{
    const col=$('div',{class:'bkcol'+(rd.ronda==='Final'?' fin':'')});
    col.append($('div',{class:'bkhd'}, labels[rd.ronda]||rd.ronda));
    // agrupar de a pares para dibujar el conector vertical (salvo la final)
    if(rd.ronda!=='Final'){
      for(let i=0;i<rd.partidos.length;i+=2){
        const pair=$('div',{class:'pair'});
        pair.append(bmBox(rd.partidos[i]));
        if(rd.partidos[i+1])pair.append(bmBox(rd.partidos[i+1]));
        col.append(pair);
      }
    } else {
      col.append(bmBox(rd.partidos[0]));
    }
    bk.append(col);
  });
  // columna campeon
  const cc=$('div',{class:'bkcol fin'});
  cc.append($('div',{class:'bkhd'},'🏆'));
  cc.append($('div',{class:'champ'},$('div',{class:'lab'},'Campeon proyectado'),
    $('div',{class:'nm'}, pr.campeon_proyectado||'—')));
  bk.append(cc);
  return bk;
}

function awardTable(title, rows, note){
  const c=$('div',{class:'card'});
  c.append($('div',{class:'gtitle'},title));
  if(note)c.append($('div',{class:'muted',html:'<small>'+note+'</small>'}));
  const tb=$('table');tb.append($('tr',{},$('th',{},'#'),$('th',{},'Jugador'),$('th',{},'Equipo'),
    $('th',{class:'n'},'Prob.'),$('th',{class:'n'},'Cuota')));
  rows.forEach((r,i)=>{
    const tr=$('tr',{});
    tr.append($('td',{class:'muted'},String(i+1)),$('td',{html:'<b>'+r.jugador+'</b>'}),
      $('td',{class:'muted'},r.equipo));
    tr.append(barCell(r.prob));
    tr.append($('td',{class:'n muted'}, r.odds||'—'));
    tb.append(tr)});
  c.append(tb);return c;
}
function panePremios(p){
  // Podio
  const pc=$('div',{class:'card'});
  pc.append($('div',{class:'gtitle'},'🏆 Podio — probabilidad de terminar 1°, 2° o 3°'));
  const tb=$('table');tb.append($('tr',{},$('th',{},'#'),$('th',{},'Equipo'),
    $('th',{class:'n'},'1° 🥇'),$('th',{class:'n'},'2° 🥈'),$('th',{class:'n'},'3° 🥉'),$('th',{class:'n'},'Podio')));
  S.podio.forEach((r,i)=>{
    const tr=$('tr',{});
    tr.append($('td',{class:'muted'},String(i+1)),$('td',{html:'<b>'+r.equipo+'</b>'}),
      $('td',{class:'n q'},pct(r.p1)),$('td',{class:'n'},pct(r.p2)),
      $('td',{class:'n'},pct(r.p3)),$('td',{class:'n muted'},pct(r.top3)));
    tb.append(tr)});
  pc.append(tb);p.append(pc);
  // Premios individuales
  const pr=S.premios||{};
  const nota='Estimacion = consenso de mercado (cuota/rating) × recorrido simulado del equipo. NO es certeza.';
  if(pr.goleador)p.append(awardTable('⚽ Bota de Oro (goleador)', pr.goleador, nota));
  if(pr.arquero)p.append(awardTable('🧤 Guante de Oro (mejor arquero)', pr.arquero, nota));
  if(pr.joven)p.append(awardTable('🌟 Mejor jugador joven (sub-21)', pr.joven, nota));
}

function paneEvol(p){
  const card=$('div',{class:'card'});
  card.append($('div',{class:'gtitle'},'Como se movio la probabilidad de campeon, fecha a fecha'));
  const ev=S.evolucion;
  if(ev.length<1){card.append($('div',{class:'muted'},'Sin datos aun.'));p.append(card);return}
  // equipos a graficar = union de tops de cada snapshot (max 8)
  const teams=[...new Set(ev.flatMap(e=>Object.keys(e.campeon)))].slice(0,8);
  const W=900,H=320,pad=44;
  const xs=ev.map((_,i)=>ev.length===1?pad:pad+i*(W-2*pad)/(ev.length-1));
  const maxY=Math.max(5,...ev.flatMap(e=>Object.values(e.campeon)));
  const y=v=>H-pad-(v/maxY)*(H-2*pad);
  const svg=$svg('svg',{viewBox:`0 0 ${W} ${H}`});
  // ejes
  for(let g=0;g<=4;g++){const yy=pad+g*(H-2*pad)/4;const val=(maxY*(4-g)/4).toFixed(0);
    svg.append($svg('line',{x1:pad,y1:yy,x2:W-pad,y2:yy,stroke:'#272e3a'}));
    svg.append($svg('text',{x:6,y:yy+4,fill:'#8b949e','font-size':11},val+'%'))}
  ev.forEach((e,i)=>svg.append($svg('text',{x:xs[i],y:H-pad+18,fill:'#8b949e','font-size':11,'text-anchor':'middle'},e.fecha.slice(5))));
  teams.forEach((t,ti)=>{
    const pts=ev.map((e,i)=>[xs[i],y(e.campeon[t]||0)]);
    const d=pts.map((q,i)=>(i?'L':'M')+q[0]+' '+q[1]).join(' ');
    svg.append($svg('path',{d,fill:'none',stroke:COLORS[ti%8],'stroke-width':2.5}));
    pts.forEach(q=>svg.append($svg('circle',{cx:q[0],cy:q[1],r:3,fill:COLORS[ti%8]})))});
  card.append(svg);
  const lg=$('div',{class:'lg'});
  teams.forEach((t,ti)=>{const s=$('span');const d=$('span',{class:'dot'});d.style.background=COLORS[ti%8];
    s.append(d,document.createTextNode(t));lg.append(s)});
  card.append(lg);
  p.append(card);
  p.append($('div',{class:'muted',html:'<small>La curva crece a medida que cargas fechas. Con una sola fecha veras un punto; con varias, la tendencia.</small>'}));
}
function $svg(t,a={},...c){const e=document.createElementNS('http://www.w3.org/2000/svg',t);
  for(const k in a)e.setAttribute(k,a[k]);c.forEach(x=>e.append(x));return e}

function paneMetodo(p){
  const M=S.metodologia||{fuentes:[]};
  // Que es
  const c0=$('div',{class:'card'});
  c0.append($('div',{class:'gtitle'},'¿Que es esto?'));
  c0.append($('div',{html:'Un predictor del Mundial 2026 que combina un <b>motor estadistico</b> (calcula las probabilidades) con <b>resultados reales</b> que se cargan fecha a fecha. Cada vez que entra un resultado, todo el pronostico se recalcula. <b>Son probabilidades, no certezas.</b>'}));
  p.append(c0);
  // Algoritmo
  const c1=$('div',{class:'card'});
  c1.append($('div',{class:'gtitle'},'⚙️ El algoritmo en 5 pasos'));
  const steps=[
    ['1. Fuerza de cada seleccion (Elo)','Cada equipo arranca con un rating Elo (mide su fuerza). Tras cada partido real, el Elo sube o baja segun el resultado y por cuanto (un 3-0 pesa mas que un 1-0). Asi la "forma" del torneo entra al modelo: quien rinde mas de lo esperado, sube.'],
    ['2. Modelo de un partido (Poisson)','Para cualquier cruce, la diferencia de Elo define los goles esperados de cada lado; con eso se sortean marcadores con una distribucion de Poisson. De ahi sale P(gana local / empate / gana visita) y el marcador mas probable.'],
    ['3. Simulacion del torneo (Monte Carlo)','Se simula el torneo completo '+(M.sims||0).toLocaleString()+' veces: los partidos jugados se respetan tal cual, y los que faltan se sortean con el modelo. Contando cuantas veces cada equipo gana su grupo, avanza o sale campeon, salen las probabilidades.'],
    ['4. Cuadro de eliminatorias (arbol oficial)','Las llaves siguen el arbol OFICIAL de FIFA (validado): los cruces de octavos a la final son los reales, y dos equipos del mismo grupo no pueden cruzarse antes de la final.'],
    ['5. Premios individuales','Goleador, arquero y joven se estiman combinando el consenso de las casas de apuestas (quien es favorito) con el recorrido simulado de su equipo (mas partidos y mas profundo = mas chance). Es la capa mas heuristica.'],
  ];
  steps.forEach(([t,d])=>{
    c1.append($('div',{class:'rname'},t));
    c1.append($('div',{class:'muted',html:'<small>'+d+'</small>'}));
  });
  p.append(c1);
  // Parametros y datos
  const c2=$('div',{class:'card'});
  c2.append($('div',{class:'gtitle'},'🔢 Datos y parametros'));
  const tb=$('table');
  [['Equipos / grupos',(M.equipos||48)+' equipos · '+(M.grupos||12)+' grupos de 4'],
   ['Simulaciones Monte Carlo',(M.sims||0).toLocaleString()+' por corrida'],
   ['Resultados reales cargados',(M.n_resultados||0)+' partidos (con fuente)'],
   ['Factor K del Elo','60 (estandar para mundiales)'],
   ['Ventaja de localia','Ninguna (sedes tratadas como neutrales)'],
   ['Desempate de grupos','Puntos → dif. de gol → goles a favor (simplificado)']].forEach(([k,v])=>{
    tb.append($('tr',{},$('td',{class:'muted'},k),$('td',{html:'<b>'+v+'</b>'})));
  });
  c2.append(tb);p.append(c2);
  // Fuentes
  const c3=$('div',{class:'card'});
  c3.append($('div',{class:'gtitle'},'📚 Fuentes de los datos'));
  const ft=$('table');ft.append($('tr',{},$('th',{},'Dato'),$('th',{},'Fuente')));
  (M.fuentes||[]).forEach(f=>{
    let val=f.fuente||'—';
    val=val.replace(/(https?:\/\/[^\s|·]+)/g,'<a href="$1" target="_blank">$1</a>');
    ft.append($('tr',{},$('td',{html:'<b>'+f.que+'</b>'}),$('td',{class:'muted',html:'<small>'+val+'</small>'})));
  });
  c3.append(ft);p.append(c3);
  // Limitaciones
  const c4=$('div',{class:'card'});
  c4.append($('div',{class:'gtitle'},'⚠️ Limitaciones (honestas)'));
  const lis=['Es un modelo probabilistico: dice que es MAS probable, no que va a pasar. Un torneo tiene mucha varianza.',
    'El Elo concentra la probabilidad en los favoritos; puede sobreestimar al mejor rankeado.',
    'Los premios individuales son una heuristica (consenso de mercado × recorrido del equipo), no una prediccion fina por jugador.',
    'La asignacion exacta de los 8 mejores terceros a cada llave se resuelve recien al cerrar la fase de grupos; antes es una aproximacion.',
    'Sin ventaja de localia ni lesiones/suspensiones individuales en el modelo.'];
  const ul=$('div',{});
  lis.forEach(t=>{const d=$('div',{class:'muted',html:'<small>• '+t+'</small>'});d.style.padding='3px 0';ul.append(d)});
  c4.append(ul);p.append(c4);
}
function paneResult(p){
  const card=$('div',{class:'card'});
  card.append($('div',{class:'gtitle'},'Resultados reales cargados (con fuente)'));
  const tb=$('table');tb.append($('tr',{},$('th',{},'Fecha'),$('th',{},'Fase'),$('th',{},'Partido'),
    $('th',{class:'n'},'Marcador'),$('th',{},'Fuente')));
  S.resultados.forEach(m=>{
    const tr=$('tr',{});
    tr.append($('td',{class:'muted'},m.fecha),$('td',{class:'muted'},(m.grupo?('Gr '+m.grupo):m.fase)),
      $('td',{},m.local+' vs '+m.visita),
      $('td',{class:'n'},'<b>'+m.gl+'–'+m.gv+'</b>'),
      $('td',{html:'<a href="'+m.fuente+'" target="_blank">link</a>'}));
    tr.children[3].innerHTML='<b>'+m.gl+'–'+m.gv+'</b>';
    tb.append(tr)});
  card.append(tb);p.append(card);
}
</script></body></html>"""

if __name__ == "__main__":
    main()
