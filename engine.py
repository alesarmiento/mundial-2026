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
def ad_factors(a, b, ad, w):
    """Factor multiplicativo ataque/defensa, centrado en 1.0.
    w<=0 o sin ratings -> (1.0, 1.0): comportamiento Elo puro (identidad)."""
    if not ad or w <= 0:
        return 1.0, 1.0
    atk, dfn = ad.get("atk", {}), ad.get("dfn", {})
    fa = (1 - w) + w * atk.get(a, 1.0) * dfn.get(b, 1.0)
    fb = (1 - w) + w * atk.get(b, 1.0) * dfn.get(a, 1.0)
    return fa, fb

def sample_goals(ra, rb, fa=1.0, fb=1.0):
    """Marcador via Poisson; goles esperados derivados de la dif de Elo y (opcional) del factor ataque/defensa."""
    la, lb = _lambdas(ra, rb, fa, fb)
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

def _lambdas(ra, rb, fa=1.0, fb=1.0):
    sup = (ra - rb) / 150.0
    base = 1.35
    return max(0.18, (base + sup / 2.0) * fa), max(0.18, (base - sup / 2.0) * fb)

def match_pred(home, away, elo, ad=None, w=0.0, host_adv=0.0, hosts=()):
    """Prediccion analitica de un partido: P(gana local/empate/gana visita) + marcador mas probable.
    Capa ataque/defensa (ad,w) y localia de anfitriones (host_adv,hosts) son opcionales:
    con w=0 y host_adv=0 el resultado es identico al modelo Elo+Poisson puro."""
    if home not in elo or away not in elo:
        return None
    ra = elo[home] + (host_adv if home in hosts else 0.0)
    rb = elo[away] + (host_adv if away in hosts else 0.0)
    fa, fb = ad_factors(home, away, ad, w)
    la, lb = _lambdas(ra, rb, fa, fb)
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
    # marcador para mostrar Y puntuar: REDONDEO del xG (goles esperados) de cada equipo, ajustado para
    # NO contradecir el 1X2 mas probable. Sigue al xG (ej. 2.67 -> 3) y respeta quien gana. Lo que se
    # muestra es lo que se puntua (campo "score_med"). "score" (moda) queda informativo, no se usa.
    disp = [int(la + 0.5), int(lb + 0.5)]
    if pH >= pD and pH >= pA:           # gana local
        if disp[0] <= disp[1]: disp[0] = disp[1] + 1
    elif pA >= pD and pA >= pH:         # gana visita
        if disp[1] <= disp[0]: disp[1] = disp[0] + 1
    elif disp[0] != disp[1]:            # empate mas probable -> mostrar empate
        mm = max(disp); disp = [mm, mm]
    return {"pH": round(100 * pH / s, 1), "pD": round(100 * pD / s, 1),
            "pA": round(100 * pA / s, 1), "score": [best[0], best[1]],
            "score_med": disp,
            "xgH": round(la, 2), "xgA": round(lb, 2)}

def build_por_fecha(teams, results, elo, fixtures, anchor, cfg=None):
    """Vista por dia: cada partido con resultado real (si jugado) o prediccion (si por jugar)."""
    cfg = cfg or {}
    ad = compute_ad(results, cfg.get("ghist"), teams["grupos"]) if cfg.get("w", 0) > 0 else None
    played = {frozenset((m["local"], m["visita"])): m for m in results}
    by_date = defaultdict(list)
    seen = set()
    for fx in fixtures:
        h, a = fx["home"], fx["away"]
        key = frozenset((h, a)); seen.add(key)
        e = {"home": h, "away": a, "grupo": fx.get("grupo"), "fase": fx.get("fase", "grupos"), "utc": fx.get("utc")}
        r = played.get(key)
        if r:
            e["jugado"] = True
            if r["local"] == h: e["gl"], e["gv"] = r["gl"], r["gv"]
            else: e["gl"], e["gv"] = r["gv"], r["gl"]
            e["fuente"] = r.get("fuente")
        else:
            e["jugado"] = False
            e["pred"] = match_pred(h, a, elo, ad, cfg.get("w", 0.0),
                                   cfg.get("host_adv", 0.0), cfg.get("hosts", set()))
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

def estimate_awards(players, probs, em, elo, defstats=None, scorers=None):
    if not players:
        return {}
    defstats = defstats or {}
    def fin(rows):
        s = sum(w for _, w in rows) or 1.0
        out = [{"jugador": c["jugador"], "equipo": c["equipo"], "odds": c.get("odds", ""),
                "prob": round(100 * w / s, 1)} for c, w in rows]
        return sorted(out, key=lambda x: x["prob"], reverse=True)
    # Goleador (Bota de Oro): goles REALES acumulados (tabla de goleadores) + proyeccion de lo que
    # le queda por marcar (rating x partidos esperados restantes). Mezcla "quien va metiendo" con
    # "quien tiene mas recorrido por delante". Incluye goleadores que no estaban en el consenso.
    cands = {}
    for c in players.get("goleador", []):
        if c["equipo"] not in em:
            continue
        cands[c["jugador"]] = {"jugador": c["jugador"], "equipo": c["equipo"],
                               "odds": c.get("odds", ""), "rating": c["rating"], "goles": 0}
    for s in (scorers or []):
        t = s.get("equipo")
        if t not in em:
            continue
        if s["jugador"] in cands:
            cands[s["jugador"]]["goles"] = s.get("goles", 0)
        else:  # goleador fuera del consenso: aparece por sus goles reales, con rating modesto
            cands[s["jugador"]] = {"jugador": s["jugador"], "equipo": t, "odds": "",
                                   "rating": 6.5, "goles": s.get("goles", 0)}
    gole = []
    for c in cands.values():
        pj = defstats.get(c["equipo"], {}).get("pj", 0)
        rem = max(0.5, em[c["equipo"]] - pj)        # partidos esperados que le quedan
        proj = (c["rating"] / 10.0) * rem * 0.75    # goles proyectados en lo que resta
        gole.append((c, c["goles"] + proj))         # goles totales estimados al final
    def fin_gol(rows):
        s = sum(w for _, w in rows) or 1.0
        out = [{"jugador": c["jugador"], "equipo": c["equipo"], "odds": c.get("odds", ""),
                "goles": c["goles"], "prob": round(100 * w / s, 1)} for c, w in rows]
        return sorted(out, key=lambda x: (x["prob"], x["goles"]), reverse=True)
    # Arquero (Guante de Oro): rating x recorrido profundo x rendimiento defensivo REAL.
    # El rendimiento mezcla la solidez del Elo con los datos acumulados: arcos en cero (suben) y
    # goles recibidos por partido (bajan), ponderados por cuantos partidos lleva jugados el equipo.
    arq = []
    for c in players.get("arquero", []):
        t = c["equipo"]
        if t not in probs: continue
        deep = probs[t]["cuartos"] / 100.0 + 0.05
        defn = max(0.2, (elo[t] - 1500) / 700.0)
        ds = defstats.get(t)
        if ds and ds["pj"] > 0:
            perf = (1.0 + ds["cs"] / ds["pj"]) / (1.0 + ds["gc"] / ds["pj"])  # >1 con arcos en cero, <1 si recibe mucho
            w = min(1.0, ds["pj"] / 3.0)                                       # peso del dato real crece con los partidos
            defn = defn * ((1.0 - w) + w * perf)
        arq.append((c, c["rating"] * deep * defn))
    # Joven: rating x exposicion (partidos esperados)
    jov = [(c, c["rating"] * em[c["equipo"]]) for c in players.get("joven", []) if c["equipo"] in em]
    return {"goleador": fin_gol(gole), "arquero": fin(arq), "joven": fin(jov)}

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
    # cada cruce se resuelve con la PROBABILIDAD del Monte Carlo de alcanzar la ronda siguiente
    # (las mismas del tab Campeon/Avance) -> el campeon del arbol coincide SIEMPRE con el #1 del ranking.
    NEXT = {"Dieciseisavos": "octavos", "Octavos": "cuartos", "Cuartos": "semis",
            "Semifinal": "final", "Final": "campeon"}
    for nm in ["Dieciseisavos", "Octavos", "Cuartos", "Semifinal", "Final"]:
        key = NEXT[nm]
        matches, winners = [], []
        for h, a in pairs:
            if h and a:
                ph, pa = probs[h][key], probs[a][key]
                w = h if ph >= pa else a
                matches.append({"home": h, "away": a, "pHome": round(ph, 1), "pAway": round(pa, 1), "winner": w})
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
def simulate_once(grupos, elo, base, played, fixtures, skeleton, rcfg):
    # copia mutable de la tabla
    tab = {tm: dict(v) for tm, v in base.items()}
    ad, w = rcfg["ad"], rcfg["w"]
    hadv, hosts = rcfg["host_adv"], rcfg["hosts"]
    for g, a, b in fixtures:
        if frozenset((a, b)) in played:
            continue
        ra = elo[a] + (hadv if a in hosts else 0.0)
        rb = elo[b] + (hadv if b in hosts else 0.0)
        fa, fb = ad_factors(a, b, ad, w)
        gl, gv = sample_goals(ra, rb, fa, fb)
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
def run_mc(grupos, elo, base, played, fixtures, skeleton, n, rcfg=None):
    if rcfg is None:
        rcfg = {"ad": None, "w": 0.0, "host_adv": 0.0, "hosts": set()}
    teams = list(base.keys())
    cnt = {t: {"grupo1": 0, "g2": 0, "top2": 0, "r32": 0, "octavos": 0, "cuartos": 0,
               "semis": 0, "final": 0, "campeon": 0, "sub": 0, "tercero": 0} for t in teams}
    for _ in range(n):
        winners, runners, thirds, reached = simulate_once(
            grupos, elo, base, played, fixtures, skeleton, rcfg)
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

# ---------- puntaje del modelo (scoring tipo polla) ----------
def actual_qualifiers(grupos, base):
    """Los 32 reales: 2 primeros de cada grupo + 8 mejores terceros. Solo valido si la fase de grupos termino."""
    quals = set(); thirds = []
    for g, teams in grupos.items():
        order = sorted(teams, key=lambda t: rank_key(base[t]), reverse=True)
        quals.add(order[0]); quals.add(order[1]); thirds.append((order[2], rank_key(base[order[2]])))
    thirds.sort(key=lambda x: x[1], reverse=True)
    for t, _ in thirds[:8]:
        quals.add(t)
    return quals

def compute_scoring(teams, results, fixtures, base, picks, cfg=None):
    """Puntaje acumulativo. Partidos: pronostico PREVIO a cada partido vs real. Torneo: picks congelados."""
    cfg = cfg or {}
    seed = teams["elo_seed"]; grupos = teams["grupos"]
    fx_by_pair = {frozenset((f["home"], f["away"])): f for f in fixtures}
    by_date = defaultdict(list)
    for m in results:
        by_date[m["fecha"]].append(m)
    sw = cfg.get("scoring_w", 0.0); sdesde = cfg.get("scoring_desde")
    rows = []; total_match = 0
    for d in sorted(by_date):
        prev = [r for r in results if r["fecha"] < d]
        elo_prev = elo_after(prev, seed)
        usar_new = bool(sw > 0 and sdesde and d >= sdesde)
        w_use = sw if usar_new else 0.0
        ad_prev = compute_ad(prev, cfg.get("ghist"), grupos) if w_use > 0 else None
        for m in by_date[d]:
            fx = fx_by_pair.get(frozenset((m["local"], m["visita"])))
            home, away = (fx["home"], fx["away"]) if fx else (m["local"], m["visita"])
            pred = match_pred(home, away, elo_prev, ad_prev, w_use,
                              cfg.get("host_adv", 0.0), cfg.get("hosts", set()))
            if not pred:
                continue
            ph, pa = pred["score_med"]  # se puntua con el MISMO marcador que se muestra (redondeo del xG)
            ah, aa = (m["gl"], m["gv"]) if m["local"] == home else (m["gv"], m["gl"])
            parts = {}; pts = 0
            if ((ph > pa) - (ph < pa)) == ((ah > aa) - (ah < aa)):
                pts += 3; parts["ganador"] = 3
            if ph == ah:
                pts += 2; parts["gol_local"] = 2
            if pa == aa:
                pts += 2; parts["gol_visita"] = 2
            if ph == ah and pa == aa:
                pts += 4; parts["exacto"] = 4
            total_match += pts
            rows.append({"fecha": d, "grupo": m.get("grupo"), "home": home, "away": away,
                         "pred": [ph, pa], "real": [ah, aa], "pts": pts, "parts": parts,
                         "modelo": "NEW" if usar_new else "OLD"})
    # resolucion de predicciones de torneo (solo cuando ocurren)
    group_done = sum(1 for r in results if r.get("fase", "grupos") == "grupos") >= 72
    quals = actual_qualifiers(grupos, base) if group_done else None
    def ko_w(r):
        if r["gl"] > r["gv"]: return r["local"]
        if r["gv"] > r["gl"]: return r["visita"]
        return r.get("ganador")
    fin = [r for r in results if r.get("fase") == "final"]
    tp = [r for r in results if r.get("fase") == "tercer_puesto"]
    champ = ko_w(fin[-1]) if fin else None
    sub = (fin[-1]["visita"] if champ == fin[-1]["local"] else fin[-1]["local"]) if (fin and champ) else None
    ter = ko_w(tp[-1]) if tp else None
    aw_path = os.path.join(DATA, "awards_actual.json")
    aw = load("awards_actual.json") if os.path.exists(aw_path) else {}

    def item(label, pts, pick, actual, resolved):
        ok = bool(resolved and pick is not None and actual is not None and pick == actual)
        return {"label": label, "pts": pts, "pick": pick, "actual": actual,
                "estado": "pendiente" if not resolved else ("acertado" if ok else "fallado"),
                "ganado": pts if ok else 0}
    tour = [
        item("Campeon", 18, picks.get("campeon"), champ, champ is not None),
        item("Subcampeon", 15, picks.get("subcampeon"), sub, sub is not None),
        item("Tercer puesto", 12, picks.get("tercero"), ter, ter is not None),
        item("Goleador", 10, picks.get("goleador"), aw.get("goleador"), bool(aw.get("goleador"))),
        item("Mejor arquero", 10, picks.get("arquero"), aw.get("arquero"), bool(aw.get("arquero"))),
        item("Mejor joven", 5, picks.get("joven"), aw.get("joven"), bool(aw.get("joven"))),
    ]
    pick_q = picks.get("clasificados", [])
    if group_done and quals is not None:
        ac = len([t for t in pick_q if t in quals])
        clas = {"label": "Clasificados 2da ronda", "pick_n": len(pick_q), "aciertos": ac,
                "estado": "resuelto", "ganado": 7 * ac, "potencial": 7 * len(pick_q)}
    else:
        clas = {"label": "Clasificados 2da ronda", "pick_n": len(pick_q), "aciertos": None,
                "estado": "pendiente", "ganado": 0, "potencial": 7 * len(pick_q)}
    ganado = total_match + sum(t["ganado"] for t in tour) + clas["ganado"]
    en_juego = sum(t["pts"] for t in tour if t["estado"] == "pendiente") + (clas["potencial"] if clas["estado"] == "pendiente" else 0)
    uso_old = any(r.get("modelo") == "OLD" for r in rows)
    if sw > 0 and not uso_old:
        modelo_nota = "El juego de puntos usa el modelo mejorado (Elo + ataque/defensa) en TODOS los partidos, hacia atras y en adelante."
    elif sw > 0 and sdesde:
        modelo_nota = f"Elo puro hasta {sdesde}; modelo mejorado (ataque/defensa) desde {sdesde}."
    else:
        modelo_nota = ""
    return {"corte": picks.get("corte"), "por_partido": rows, "total_partidos": total_match,
            "torneo": tour, "clasificados": clas, "ganado": ganado, "en_juego": en_juego,
            "n_partidos": len(rows), "modelo_nota": modelo_nota, "scoring_desde": sdesde}

# ---------- ratings ataque/defensa (Maher/Dixon-Coles, opponent-adjusted) ----------
def compute_ad(results, ghist, grupos, k0=6, iters=12):
    """Estima ataque (goles que marca) y defensa (goles que recibe) por equipo, ajustado por rival,
    SOLO desde marcadores reales (historial citado + ledger del torneo). Centrados en 1.0 y
    encogidos hacia 1.0 segun tamano de muestra. Sin datos -> dicts vacios (factor 1.0 = identidad).
    Convencion: dfn>1 = recibe mas de lo esperado (peor defensa).
    Universo abierto: cuenta partidos contra CUALQUIER rival (no solo los 48), para poder usar
    el historial pre-Mundial vs selecciones no clasificadas; los rivales externos se ratean igual
    (shrunk) y simplemente no se consultan al predecir (ad_factors usa default 1.0)."""
    qualified = set()
    for ts in grupos.values():
        qualified.update(ts)
    matches = []
    for m in list((ghist or {}).get("partidos", [])) + list(results):
        a, b, gl, gv = m.get("local"), m.get("visita"), m.get("gl"), m.get("gv")
        if a and b and gl is not None and gv is not None:
            matches.append((a, b, gl, gv))
    if not matches:
        return {"atk": {}, "dfn": {}, "n": {}, "mu": 0.0}
    teams = set(qualified)
    for a, b, _, _ in matches:
        teams.add(a); teams.add(b)
    mu = sum(gl + gv for _, _, gl, gv in matches) / (2 * len(matches)) or 1.0
    gf, ga, n = defaultdict(float), defaultdict(float), defaultdict(int)
    for a, b, gl, gv in matches:
        gf[a] += gl; ga[a] += gv; n[a] += 1
        gf[b] += gv; ga[b] += gl; n[b] += 1
    atk = {t: 1.0 for t in teams}; dfn = {t: 1.0 for t in teams}
    # Actualizacion REGULARIZADA hacia 1.0 (prior fuerza k0). S[t]/T[t] = goles esperados de t si
    # su rating fuera neutro (1.0); atk = (marcados + k0) / (esperado + k0). Estable, sin division por cero.
    for _ in range(iters):
        S, T = defaultdict(float), defaultdict(float)
        for a, b, gl, gv in matches:
            S[a] += mu * dfn[b]; T[a] += mu * atk[b]
            S[b] += mu * dfn[a]; T[b] += mu * atk[a]
        for t in teams:
            atk[t] = (gf[t] + k0) / (S[t] + k0)
            dfn[t] = (ga[t] + k0) / (T[t] + k0)
    # normalizar la media a 1.0 sobre los 48 clasificados (interpretabilidad; el producto atk*dfn ~ 1)
    qa = [atk[t] for t in qualified] or [1.0]; qd = [dfn[t] for t in qualified] or [1.0]
    ma = (sum(qa) / len(qa)) or 1.0; md = (sum(qd) / len(qd)) or 1.0
    atk = {t: round(atk[t] / ma, 4) for t in teams}; dfn = {t: round(dfn[t] / md, 4) for t in teams}
    return {"atk": atk, "dfn": dfn, "n": dict(n), "mu": round(mu, 3)}

# ---------- harness de auto-evaluacion (backtest honesto + calibracion) ----------
def compute_evaluation(teams, results, fixtures, cfg):
    """Para cada partido jugado reconstruye la prediccion PREVIA del modelo (solo fechas anteriores)
    y la compara con el real. Devuelve Brier vs baseline, log-loss, acierto 1X2, exacto y calibracion.
    Anti-trampa: el marcador real nunca entra en la prediccion, solo en la evaluacion."""
    seed = teams["elo_seed"]; grupos = teams["grupos"]
    fx_by_pair = {frozenset((f["home"], f["away"])): f for f in fixtures}
    by_date = defaultdict(list)
    for m in results:
        by_date[m["fecha"]].append(m)
    prior = {"H": 0.40, "D": 0.27, "A": 0.33}
    rows = []
    for d in sorted(by_date):
        prev = [r for r in results if r["fecha"] < d]
        elo_prev = elo_after(prev, seed)
        ad_prev = compute_ad(prev, cfg.get("ghist"), grupos) if cfg.get("w", 0) > 0 else None
        for m in by_date[d]:
            fx = fx_by_pair.get(frozenset((m["local"], m["visita"])))
            home, away = (fx["home"], fx["away"]) if fx else (m["local"], m["visita"])
            pred = match_pred(home, away, elo_prev, ad_prev, cfg.get("w", 0.0),
                              cfg.get("host_adv", 0.0), cfg.get("hosts", set()))
            if not pred:
                continue
            ah, aa = (m["gl"], m["gv"]) if m["local"] == home else (m["gv"], m["gl"])
            out = "H" if ah > aa else ("D" if ah == aa else "A")
            pH, pD, pA = pred["pH"] / 100, pred["pD"] / 100, pred["pA"] / 100
            pick = max([("H", pH), ("D", pD), ("A", pA)], key=lambda x: x[1])[0]
            y = {"H": 0, "D": 0, "A": 0}; y[out] = 1
            brier = sum((p - y[k]) ** 2 for k, p in (("H", pH), ("D", pD), ("A", pA)))
            brier_base = sum((prior[k] - y[k]) ** 2 for k in y)
            pout = {"H": pH, "D": pD, "A": pA}[out]
            sh, sa = pred["score_med"]
            rows.append({"fecha": d, "home": home, "away": away, "real": [ah, aa],
                         "pred_score": [sh, sa], "out": out, "pick": pick, "hit": pick == out,
                         "pH": round(pH, 3), "pD": round(pD, 3), "pA": round(pA, 3),
                         "brier": round(brier, 3), "brier_base": brier_base,
                         "ll": -math.log(max(pout, 1e-9)), "exact": sh == ah and sa == aa})
    n = len(rows)
    if not n:
        return {"n": 0}
    agg = lambda k: sum(r[k] for r in rows)
    buckets = [{"lo": lo, "hi": lo + 0.2, "n": 0, "hit": 0, "psum": 0.0} for lo in (0.0, 0.2, 0.4, 0.6, 0.8)]
    for r in rows:
        pmax = max(r["pH"], r["pD"], r["pA"])
        for bk in buckets:
            if (bk["lo"] <= pmax < bk["hi"]) or (bk["hi"] >= 1.0 and pmax >= 1.0):
                bk["n"] += 1; bk["hit"] += 1 if r["hit"] else 0; bk["psum"] += pmax; break
    calib = [{"rango": f"{int(b['lo']*100)}-{int(b['hi']*100)}%", "n": b["n"],
              "conf": round(100 * b["psum"] / b["n"], 1) if b["n"] else None,
              "obs": round(100 * b["hit"] / b["n"], 1) if b["n"] else None} for b in buckets]
    brier = agg("brier") / n; brier_base = agg("brier_base") / n
    draws_real = sum(1 for r in rows if r["out"] == "D")
    return {"n": n, "hit": agg("hit"), "hit_pct": round(100 * agg("hit") / n, 1),
            "exact": agg("exact"), "exact_pct": round(100 * agg("exact") / n, 1),
            "brier": round(brier, 3), "brier_base": round(brier_base, 3),
            "mejor_que_baseline": brier < brier_base, "logloss": round(agg("ll") / n, 3),
            "draws_real": draws_real, "draws_real_pct": round(100 * draws_real / n),
            "draws_pick": sum(1 for r in rows if r["pick"] == "D"),
            "calib": calib, "rows": rows, "w": cfg.get("w", 0.0), "host_adv": cfg.get("host_adv", 0.0)}

# ---------- comparacion OLD (Elo puro) vs NEW (Elo + ataque/defensa) ----------
def compute_comparison(teams, results, fixtures, ghist, w_new):
    """Para cada partido: prediccion del modelo OLD (Elo puro) vs NEW (Elo + capa ataque/defensa w_new).
    Jugados: prediccion previa vs real, con acierto de signo de cada modelo. Por jugar: ambos pronosticos."""
    seed = teams["elo_seed"]; grupos = teams["grupos"]
    fx_by_pair = {frozenset((f["home"], f["away"])): f for f in fixtures}
    def signo(p): return "L" if p["pH"] >= max(p["pD"], p["pA"]) else ("E" if p["pD"] >= p["pA"] else "V")
    by_date = defaultdict(list)
    for m in results:
        by_date[m["fecha"]].append(m)
    jug = []; oh = nh = 0; ob = nb = 0.0
    for d in sorted(by_date):
        prev = [r for r in results if r["fecha"] < d]
        elo = elo_after(prev, seed); ad = compute_ad(prev, ghist, grupos)
        for m in by_date[d]:
            fx = fx_by_pair.get(frozenset((m["local"], m["visita"])))
            home, away = (fx["home"], fx["away"]) if fx else (m["local"], m["visita"])
            po = match_pred(home, away, elo); pn = match_pred(home, away, elo, ad, w_new)
            if not po or not pn:
                continue
            ah, aa = (m["gl"], m["gv"]) if m["local"] == home else (m["gv"], m["gl"])
            out = "L" if ah > aa else ("E" if ah == aa else "V")
            so, sn = signo(po), signo(pn)
            y = {"L": 0, "E": 0, "V": 0}; y[out] = 1
            ob += sum((po[k] / 100 - y[s]) ** 2 for k, s in (("pH", "L"), ("pD", "E"), ("pA", "V")))
            nb += sum((pn[k] / 100 - y[s]) ** 2 for k, s in (("pH", "L"), ("pD", "E"), ("pA", "V")))
            oh += so == out; nh += sn == out
            som, snm = po.get("score_med", po["score"]), pn.get("score_med", pn["score"])
            jug.append({"fecha": d, "home": home, "away": away, "real": [ah, aa],
                        "old": {"score": som, "signo": so, "hit": so == out},
                        "new": {"score": snm, "signo": sn, "hit": sn == out},
                        "diff": som != snm or so != sn})
    njug = len(jug) or 1
    elo = elo_after(results, seed); ad = compute_ad(results, ghist, grupos)
    played = {frozenset((m["local"], m["visita"])) for m in results}
    fut = []
    for f in sorted(fixtures, key=lambda x: x.get("date", "")):
        if frozenset((f["home"], f["away"])) in played:
            continue
        po = match_pred(f["home"], f["away"], elo); pn = match_pred(f["home"], f["away"], elo, ad, w_new)
        if not po or not pn:
            continue
        so, sn = signo(po), signo(pn)
        som, snm = po.get("score_med", po["score"]), pn.get("score_med", pn["score"])
        fut.append({"fecha": f.get("date"), "home": f["home"], "away": f["away"],
                    "old": {"score": som, "signo": so, "fav": max(po["pH"], po["pD"], po["pA"])},
                    "new": {"score": snm, "signo": sn, "fav": max(pn["pH"], pn["pD"], pn["pA"])},
                    "diff": som != snm or so != sn})
    return {"w_new": w_new, "jugados": jug, "porjugar": fut,
            "agg": {"n": len(jug), "old_hit": oh, "new_hit": nh,
                    "old_brier": round(ob / njug, 3), "new_brier": round(nb / njug, 3)}}

# ---------- detalle por equipo (para el popup explicativo) ----------
def build_equipo_detalle(teams, results, ghist, elo, ad, topn=12):
    """Por seleccion: Elo actual, ratings ataque/defensa, y sus ultimos partidos reales
    (con rival y marcador). Alimenta el popup que explica cada pronostico."""
    qual = set(tm for ts in teams["grupos"].values() for tm in ts)
    allm = list((ghist or {}).get("partidos", [])) + list(results)
    by_team = defaultdict(list)
    for m in allm:
        a, b, gl, gv = m.get("local"), m.get("visita"), m.get("gl"), m.get("gv")
        if gl is None or gv is None:
            continue
        if a in qual: by_team[a].append((m["fecha"], b, gl, gv))
        if b in qual: by_team[b].append((m["fecha"], a, gv, gl))
    atk = (ad or {}).get("atk", {}); dfn = (ad or {}).get("dfn", {}); nmap = (ad or {}).get("n", {})
    det = {}
    for t in qual:
        ms = sorted(by_team[t], reverse=True)[:topn]
        ult = [{"fecha": f, "rival": opp, "gf": gf, "gc": gc,
                "res": "G" if gf > gc else ("E" if gf == gc else "P")} for f, opp, gf, gc in ms]
        gf_tot = sum(x[2] for x in by_team[t]); n_tot = len(by_team[t]) or 1
        det[t] = {"elo": round(elo[t]), "atk": round(atk.get(t, 1.0), 2), "dfn": round(dfn.get(t, 1.0), 2),
                  "n": nmap.get(t, 0), "gf_prom": round(gf_tot / n_tot, 2),
                  "gc_prom": round(sum(x[3] for x in by_team[t]) / n_tot, 2), "ult": ult}
    return det

# ---------- orquestacion ----------
def compute(results_subset, teams, n, cfg):
    grupos = teams["grupos"]; seed = teams["elo_seed"]; skeleton = teams["r32_skeleton"]
    elo = elo_after(results_subset, seed)
    ad = compute_ad(results_subset, cfg.get("ghist"), grupos) if cfg.get("w", 0) > 0 else None
    base = base_table(grupos)
    played = apply_group_results(base, results_subset)
    fixtures = all_group_fixtures(grupos)
    rcfg = {"ad": ad, "w": cfg.get("w", 0.0), "host_adv": cfg.get("host_adv", 0.0), "hosts": cfg.get("hosts", set())}
    probs = run_mc(grupos, elo, base, played, fixtures, skeleton, n, rcfg)
    return elo, base, probs, len(played), len(fixtures), ad

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

    # config del motor (knobs dormidos por defecto: w=0 y host=0 -> identico al modelo original)
    mcfg = load("model_config.json") if os.path.exists(os.path.join(DATA, "model_config.json")) else {}
    ghist = load("goals_history.json") if os.path.exists(os.path.join(DATA, "goals_history.json")) else {"partidos": []}
    cfg = {"w": float(mcfg.get("ad_weight", 0.0)),
           "host_adv": float(mcfg.get("host_advantage_elo", 0)),
           "hosts": set(mcfg.get("hosts", [])),
           "ghist": ghist,
           "scoring_w": float(mcfg.get("scoring_ad_weight", 0.0)),
           "scoring_desde": mcfg.get("scoring_modelo_desde")}

    if rebuild:
        # reconstruye curva: corre el motor con cortes por cada fecha
        if os.path.exists(os.path.join(DATA, "evolution.json")):
            os.remove(os.path.join(DATA, "evolution.json"))
        fechas = sorted(set(m["fecha"] for m in results))
        for f in fechas:
            subset = [m for m in results if m["fecha"] <= f]
            _, _, probs, _, _, _ = compute(subset, teams, max(4000, n // 3), cfg)
            upsert_evolution(f, probs)
        print(f"Evolucion reconstruida para {len(fechas)} fechas.")

    elo, base, probs, n_played, n_total, ad = compute(results, teams, n, cfg)
    ev = upsert_evolution(ultima, probs)

    fixtures = []
    fx_meta = {}
    fx_path = os.path.join(DATA, "fixtures.json")
    if os.path.exists(fx_path):
        fxjson = load("fixtures.json"); fixtures = fxjson.get("fixtures", []); fx_meta = fxjson.get("_meta", {})
    por_fecha, fecha_activa = build_por_fecha(teams, results, elo, fixtures, ultima, cfg)

    players = {}
    pl_path = os.path.join(DATA, "players.json")
    if os.path.exists(pl_path):
        players = load("players.json")
    scorers = load("scorers.json").get("jugadores", []) if os.path.exists(os.path.join(DATA, "scorers.json")) else []

    tmeta = teams.get("_meta", {}); pmeta = players.get("_meta", {}) if players else {}
    metodologia = {
        "sims": n, "equipos": 48, "grupos": 12, "n_resultados": len(results),
        "fuentes": [
            {"que": "Grupos y equipos (sorteo oficial)", "fuente": tmeta.get("grupos_fuente", "")},
            {"que": "Elo semilla — fuerza inicial de cada seleccion", "fuente": tmeta.get("elo_fuente", "")},
            {"que": "Calendario de la fase de grupos", "fuente": fx_meta.get("fuente", "")},
            {"que": "Resultados reales", "fuente": "Cada partido cargado trae su fuente citada (ver tab Resultados). Regla de oro: nunca se inventa un marcador; si no esta confirmado, queda pendiente."},
            {"que": "Historial ataque/defensa (750 partidos 2024-2026)", "fuente": "Marcadores internacionales reales por seleccion, cada uno con fuente (Wikipedia/ESPN/confederaciones FIFA). Muestra verificada contra la fuente. Sin invencion."},
            {"que": "Arbol de eliminatorias", "fuente": "Wikipedia '2026 FIFA World Cup knockout stage' + ESPN — validado sin discrepancias."},
            {"que": "Candidatos a premios (cuotas/consenso)", "fuente": " · ".join(pmeta.get("fuentes", [])) if pmeta else ""},
        ],
    }
    em = expected_matches(probs)
    # stats defensivas reales por equipo (Guante de Oro): partidos, goles en contra, arcos en cero
    defstats = defaultdict(lambda: {"pj": 0, "gc": 0, "cs": 0})
    for m in results:
        for tm, against in ((m["local"], m["gv"]), (m["visita"], m["gl"])):
            defstats[tm]["pj"] += 1; defstats[tm]["gc"] += against; defstats[tm]["cs"] += (against == 0)
    premios = estimate_awards(players, probs, em, elo, defstats, scorers)
    proyeccion = projected_bracket(teams, probs, elo)
    podio = sorted(
        [{"equipo": t, "p1": probs[t]["campeon"], "p2": probs[t]["sub"],
          "p3": probs[t]["tercero"], "top3": round(probs[t]["campeon"] + probs[t]["sub"] + probs[t]["tercero"], 1)}
         for t in probs], key=lambda x: x["top3"], reverse=True)[:10]

    # picks de torneo (campeon/podio/premios/clasificados): FLOTAN (estimacion viva) mientras la fase
    # de grupos no termine, y se CONGELAN una sola vez al cerrar la fase de grupos. Asi la prediccion
    # oficial queda fijada justo cuando se conoce el cuadro, para comparar contra la realidad del KO.
    grupo_cerrado = n_played >= n_total
    pick_path = os.path.join(DATA, "picks.json")
    prev_picks = load("picks.json") if os.path.exists(pick_path) else {}
    if prev_picks.get("locked") and "--relock-picks" not in sys.argv:
        picks = prev_picks
    else:
        clasif = [t for mt in proyeccion["rondas"][0]["partidos"] for t in (mt["home"], mt["away"]) if t != "?"]
        def top(lst):
            return (lst[0]["jugador"] if lst else None)
        picks = {
            "corte": ultima if grupo_cerrado else None,
            "locked": grupo_cerrado,
            "campeon": max(probs, key=lambda t: probs[t]["campeon"]),
            "subcampeon": max(probs, key=lambda t: probs[t]["sub"]),
            "tercero": max(probs, key=lambda t: probs[t]["tercero"]),
            "goleador": top(premios.get("goleador", [])),
            "arquero": top(premios.get("arquero", [])),
            "joven": top(premios.get("joven", [])),
            "clasificados": clasif,
        }
        save("picks.json", picks)
    puntaje = compute_scoring(teams, results, fixtures, base, picks, cfg)
    evaluacion = compute_evaluation(teams, results, fixtures, cfg)
    comparativa = compute_comparison(teams, results, fixtures, ghist, cfg["scoring_w"]) if cfg["scoring_w"] > 0 else None
    ad_det = ad if ad else compute_ad(results, ghist, teams["grupos"])
    equipo_detalle = build_equipo_detalle(teams, results, ghist, elo, ad_det)
    mu_liga = ad_det.get("mu") if ad_det else None

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
        "puntaje": puntaje,
        "evaluacion": evaluacion,
        "comparativa": comparativa,
        "equipo_detalle": equipo_detalle,
        "mu_liga": mu_liga,
        "ad_ratings": ad,
        "model_cfg": {"w": cfg["w"], "host_adv": cfg["host_adv"], "hosts": sorted(cfg["hosts"])},
        "picks": picks,
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
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'%3E%3Ctext y='.9em' font-size='90'%3E%E2%9A%BD%3C/text%3E%3C/svg%3E">
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
.mrow .hora{font-size:11px;color:var(--ac2);font-variant-numeric:tabular-nums;width:52px;flex:none;font-weight:600}
.mrow .pronv{font-size:11px;color:var(--mut);font-variant-numeric:tabular-nums;flex:none}
.ptschip{font-size:11px;font-weight:700;padding:1px 7px;border-radius:5px;background:#21262d;color:var(--mut);flex:none}
.ptschip.on{background:#11301c;color:var(--ac)}
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
.mrow.clk{cursor:pointer}.mrow.clk:hover{background:#1b2433;border-radius:6px}
.info{font-size:10px;color:var(--ac2);border:1px solid var(--bd);border-radius:5px;padding:0 5px;flex:none}
.mbg{position:fixed;inset:0;background:#000b;display:none;align-items:center;justify-content:center;z-index:100;padding:14px}
.mbg.on{display:flex}
.modal{background:var(--card);border:1px solid var(--bd);border-radius:14px;max-width:700px;width:100%;max-height:92vh;overflow:auto;padding:20px}
.modal .x{float:right;cursor:pointer;color:var(--mut);font-size:22px;line-height:1;padding:0 4px}
.mh{font-size:18px;font-weight:800}
.msub{color:var(--mut);font-size:12px;margin:2px 0 12px}
.xgbar{display:flex;gap:8px;margin:10px 0 4px}
.xgbox{flex:1;text-align:center;background:#0f1520;border:1px solid var(--bd);border-radius:9px;padding:9px}
.xgbox .v{font-size:22px;font-weight:800;color:var(--ac2)}
.xgbox .l{font-size:11px;color:var(--mut)}
.tcards{display:flex;gap:10px;margin:12px 0}
.tcard{flex:1;background:#0f1520;border:1px solid var(--bd);border-radius:10px;padding:12px;min-width:0}
.tcard h4{font-size:13px;margin-bottom:7px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.stat{display:flex;justify-content:space-between;font-size:12px;padding:2px 0;color:var(--mut)}
.stat b{color:var(--tx);font-variant-numeric:tabular-nums}
.flbl{font-size:10px;color:var(--mut);text-transform:uppercase;letter-spacing:.4px;margin:8px 0 4px}
.frow{display:flex;align-items:center;gap:6px;font-size:11px;padding:2px 0;color:var(--mut)}
.fdot{font-size:10px;font-weight:700;padding:1px 5px;border-radius:4px;flex:none;width:16px;text-align:center}
.fG{background:#11301c;color:var(--ac)}.fE{background:#21262d;color:var(--mut)}.fP{background:#3d1418;color:#f85149}
.lect{background:#11203a;border-left:3px solid var(--ac2);padding:9px 12px;border-radius:6px;font-size:12.5px;margin-top:6px}
</style></head><body>
<h1>⚽ Mundial 2026 · Predictor</h1>
<div class="sub" id="sub"></div>
<div class="tabs" id="tabs"></div>
<div id="panes"></div>
<div class="mbg" id="modalbg"><div class="modal"><span class="x" id="modalx">×</span><div id="modalbody"></div></div></div>
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
  ['puntaje','🎯 Puntaje', paneScore],
  ['comp','🆚 Comparativa', paneComp],
  ['eval','📐 Evaluacion', paneEval],
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
function horaCL(utc){if(!utc)return '';try{
  return new Date(utc).toLocaleTimeString('es-CL',{timeZone:'America/Santiago',hour:'2-digit',minute:'2-digit',hour12:false});
}catch(e){return ''}}
var _scoreMap=null;
function scoreFor(h,a){if(!_scoreMap){_scoreMap={};((S.puntaje&&S.puntaje.por_partido)||[]).forEach(x=>{_scoreMap[x.home+'|'+x.away]=x})}return _scoreMap[h+'|'+a]}
function matchRow(m){
  const r=$('div',{class:'mrow clk'});
  r.onclick=()=>openModal(m);
  const h=horaCL(m.utc);
  r.append($('span',{class:'hora'}, h?(h+' hs'):''));
  r.append($('span',{class:'gc'}, m.grupo?('Gr '+m.grupo):(m.fase||'')));
  r.append($('span',{class:'tm'},$('b',{},m.home),$('span',{class:'muted'},'vs'),$('b',{},m.away)));
  if(m.jugado){
    r.append($('span',{class:'sc'}, m.gl+'–'+m.gv));
    const sc=scoreFor(m.home,m.away);
    if(sc){
      r.append($('span',{class:'pronv'},'pron '+sc.pred[0]+'–'+sc.pred[1]));
      r.append($('span',{class:'ptschip'+(sc.pts>0?' on':'')}, '+'+sc.pts+' pts'));
    }
    r.append($('span',{class:'done'},'✓'));
    if(m.fuente){const a=$('a',{href:m.fuente,target:'_blank'},'fuente');a.onclick=e=>e.stopPropagation();r.append(a);}
  } else if(m.pred){
    const seg=$('div',{class:'seg'});
    [['pH','#58a6ff','L'],['pD','#6e7681','E'],['pA','#bc8cff','V']].forEach(([k,c,lab])=>{
      const v=m.pred[k];const d=$('div',{}, v>=12?(lab+' '+Math.round(v)+'%'):'');
      d.style.background=c;d.style.width=v+'%';seg.append(d)});
    r.append(seg);
    const ps=m.pred.score_med||m.pred.score;
    r.append($('span',{class:'pron'},'pron '+ps[0]+'–'+ps[1]));
  } else { r.append($('span',{class:'muted'},'—')) }
  r.append($('span',{class:'info'},'ⓘ por qué'));
  return r;
}
function modalForm(d){
  if(!d||!d.ult||!d.ult.length)return '<div class="frow muted">sin datos</div>';
  return d.ult.map(u=>`<div class="frow"><span class="fdot f${u.res}">${u.res}</span> ${u.gf}–${u.gc} vs ${u.rival} <span class="muted">(${fmtDate(u.fecha)} ${u.fecha.slice(0,4)})</span></div>`).join('');
}
function teamCard(name,d){
  if(!d)return `<div class="tcard"><h4>${name}</h4><div class="muted">sin datos</div></div>`;
  const ap=Math.round((d.atk-1)*100), dp=Math.round((d.dfn-1)*100);
  return `<div class="tcard"><h4>${name}</h4>
    <div class="stat">Elo (fuerza) <b>${d.elo}</b></div>
    <div class="stat">Ataque <b>${d.atk}</b><span class="muted">${ap>=0?'+':''}${ap}% vs prom</span></div>
    <div class="stat">Defensa <b>${d.dfn}</b><span class="muted">recibe ${dp>=0?'+':''}${dp}%</span></div>
    <div class="stat">Reales /pj <b>${d.gf_prom}</b> a favor · <b>${d.gc_prom}</b> contra<span class="muted">${d.n} pj</span></div>
    <div class="flbl">Últimos partidos</div>${modalForm(d)}</div>`;
}
function lectura(home,away,dh,da,pred){
  if(!dh||!da)return '';
  let ps=[];
  if(da.dfn<=0.85)ps.push(`la defensa sólida de ${away} (recibe poco) frena el ataque de ${home}`);
  if(dh.atk>=1.2)ps.push(`${home} viene marcando (ataque ${dh.atk})`);
  if(dh.dfn<=0.85)ps.push(`${home} defiende bien`);
  if(da.atk>=1.2)ps.push(`${away} también genera (ataque ${da.atk})`);
  if(dh.dfn>=1.2)ps.push(`${home} viene recibiendo goles`);
  if(!ps.length)ps.push('equipos parejos en ataque y defensa para este cruce');
  const xg=(pred&&pred.xgH!=null)?`xG = goles esperados (promedio): ${home} ${pred.xgH} · ${away} ${pred.xgA}. `:'';
  return `<div class="lect">📊 ${xg}El marcador mostrado redondea ese xG (no es probabilidad): ${ps.join('; ')}.</div>`;
}
function openModal(m){
  const D=S.equipo_detalle||{}, dh=D[m.home], da=D[m.away];
  let pred=null, realTxt='', probTxt='', scoreTxt='';
  if(m.jugado){const sc=scoreFor(m.home,m.away);pred=sc?{score:sc.pred,xgH:null,xgA:null}:null;realTxt=` · Resultado real: <b>${m.gl}–${m.gv}</b>`;}
  else pred=m.pred;
  const psc=pred?(pred.score_med||pred.score):null;
  if(psc)scoreTxt=`Pronóstico: <b>${psc[0]}–${psc[1]}</b>`;
  if(!m.jugado&&m.pred)probTxt=` · L ${Math.round(m.pred.pH)}% / E ${Math.round(m.pred.pD)}% / V ${Math.round(m.pred.pA)}%`;
  const xgHtml=(pred&&pred.xgH!=null)?`<div class="xgbar"><div class="xgbox"><div class="v">${pred.xgH}</div><div class="l">goles esperados ${m.home}</div></div><div class="xgbox"><div class="v">${pred.xgA}</div><div class="l">goles esperados ${m.away}</div></div></div>`:'';
  document.getElementById('modalbody').innerHTML=
    `<div class="mh">${m.home} vs ${m.away}</div>
     <div class="msub">${m.grupo?('Grupo '+m.grupo+' · '):''}${scoreTxt}${probTxt}${realTxt}</div>
     ${xgHtml}
     <div class="tcards">${teamCard(m.home,dh)}${teamCard(m.away,da)}</div>
     ${lectura(m.home,m.away,dh,da,pred)}
     <div class="muted" style="font-size:11px;margin-top:10px">Ataque/defensa centrados en 1.0 (promedio mundial), ajustados por la fuerza de los rivales enfrentados y encogidos por tamaño de muestra. Elo de eloratings.net evolucionado con cada resultado.</div>`;
  document.getElementById('modalbg').classList.add('on');
}
document.getElementById('modalx').onclick=()=>document.getElementById('modalbg').classList.remove('on');
document.getElementById('modalbg').onclick=e=>{if(e.target.id==='modalbg')document.getElementById('modalbg').classList.remove('on')};
document.addEventListener('keydown',e=>{if(e.key==='Escape')document.getElementById('modalbg').classList.remove('on')});
function paneFecha(p){
  const intro=$('div',{class:'muted',html:'<small>Horarios en <b>hora de Chile</b> · dia en curso abierto por defecto · toca cualquier dia para expandir. <b>Toca un partido (ⓘ por qué)</b> para ver el desglose del pronostico: Elo, ataque/defensa y ultimos partidos de ambos. Por jugar: <b style="color:#58a6ff">L</b> local · <b style="color:#8b949e">E</b> empate · <b style="color:#bc8cff">V</b> visita · “pron” = marcador mas probable.</small>'});
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
    pc.append($('div',{class:'muted',html:'<small>Cruces segun el <b>arbol oficial</b> (Wikipedia knockout stage), con los clasificados mas probables por grupo. El % de cada equipo es su <b>probabilidad (Monte Carlo) de llegar a la ronda siguiente</b> — avanza el mayor, por eso el campeon del arbol coincide SIEMPRE con el #1 del tab Campeon. Proyeccion puntual: cambia con cada resultado.</small>'}));
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

function awardTable(title, rows, note, goals){
  const c=$('div',{class:'card'});
  c.append($('div',{class:'gtitle'},title));
  if(note)c.append($('div',{class:'muted',html:'<small>'+note+'</small>'}));
  const head=[$('th',{},'#'),$('th',{},'Jugador'),$('th',{},'Equipo')];
  if(goals)head.push($('th',{class:'n'},'Goles ya'));
  head.push($('th',{class:'n'},'Prob.'),$('th',{class:'n'},'Cuota'));
  const tb=$('table');tb.append($('tr',{},...head));
  rows.forEach((r,i)=>{
    const tr=$('tr',{});
    tr.append($('td',{class:'muted'},String(i+1)),$('td',{html:'<b>'+r.jugador+'</b>'}),
      $('td',{class:'muted'},r.equipo));
    if(goals)tr.append($('td',{class:'n'+(r.goles>0?' q':' muted')}, r.goles!=null?String(r.goles):'—'));
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
  if(pr.goleador)p.append(awardTable('⚽ Bota de Oro (goleador)', pr.goleador, 'Goles reales acumulados (tabla de goleadores, con fuente) + proyeccion de lo que le queda por marcar segun cuanto avanza su equipo. '+nota, true));
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

function bigStat(v,label,color){const d=$('div',{});const n=$('div',{},String(v));
  n.style.cssText='font-size:30px;font-weight:800;color:'+color;const l=$('div',{class:'muted'},label);
  l.style.fontSize='12px';d.append(n,l);return d}
function estadoChip(s){const c={pendiente:'#8b949e',acertado:'#3fb950',fallado:'#f85149',resuelto:'#3fb950'}[s]||'#8b949e';
  return '<span style="color:'+c+';font-weight:700;text-transform:uppercase;font-size:11px">'+s+'</span>'}
function paneScore(p){
  const Q=S.puntaje;
  if(!Q){p.append($('div',{class:'muted'},'Sin datos de puntaje.'));return}
  const c0=$('div',{class:'card'});
  c0.append($('div',{class:'gtitle'},'🎯 Puntaje del modelo'));
  const row=$('div',{});row.style.cssText='display:flex;gap:32px;flex-wrap:wrap;align-items:baseline;margin:6px 0';
  row.append(bigStat(Q.ganado,'puntos ganados','var(--ac)'));
  row.append(bigStat(Q.en_juego,'en juego (pendiente)','var(--ac2)'));
  c0.append(row);
  c0.append($('div',{class:'warn',html:'<b>Sin trampa:</b> el pronóstico de cada partido se reconstruye con el estado del modelo PREVIO al partido (solo resultados de fechas anteriores) y el marcador real no influye en la predicción — se usa únicamente para puntuar.'}));
  const locked=S.picks&&S.picks.locked;
  const pickTxt=locked
    ? 'Picks de torneo (campeón/podio/premios) CONGELADOS al '+(S.picks.corte||Q.corte||'—')+' (cierre de la fase de grupos).'
    : 'Picks de torneo (campeón/podio/premios) <b>todavía NO congelados</b>: son estimación VIVA y se fijan automáticamente al cerrar la fase de grupos, para comparar contra la realidad del cuadro.';
  c0.append($('div',{class:'muted',html:'<small>'+pickTxt+' Acumulativo por partido: ganador 3 · goles local 2 · goles visita 2 · marcador exacto 4 (máx 11).</small>'}));
  if(Q.modelo_nota)c0.append($('div',{class:'muted',html:'<small>🔧 '+Q.modelo_nota+'</small>'}));
  p.append(c0);
  // Torneo
  const c1=$('div',{class:'card'});
  c1.append($('div',{class:'gtitle'},'🏆 Predicciones de torneo (se resuelven al final)'));
  const tb=$('table');tb.append($('tr',{},$('th',{},'Premio'),$('th',{},'Pick del modelo'),$('th',{},'Estado'),$('th',{class:'n'},'Puntos')));
  Q.torneo.forEach(t=>{
    const tr=$('tr',{});
    tr.append($('td',{},t.label),$('td',{html:'<b>'+(t.pick||'—')+'</b>'}),
      $('td',{html:estadoChip(t.estado)}),
      $('td',{class:'n'+(t.ganado>0?' q':' muted')}, t.estado==='pendiente'?('en juego: '+t.pts):String(t.ganado)));
    tb.append(tr)});
  const cl=Q.clasificados,tr=$('tr',{});
  tr.append($('td',{},cl.label+' (7 c/u)'),
    $('td',{class:'muted'}, cl.pick_n+' equipos elegidos'),
    $('td',{html: cl.estado==='pendiente'?estadoChip('pendiente'):('<span class="q">'+cl.aciertos+'/'+cl.pick_n+' aciertos</span>')}),
    $('td',{class:'n'+(cl.ganado>0?' q':' muted')}, cl.estado==='pendiente'?('en juego: '+cl.potencial):String(cl.ganado)));
  tb.append(tr);c1.append(tb);p.append(c1);
  // Por partido
  const c2=$('div',{class:'card'});
  c2.append($('div',{class:'gtitle'},'⚽ Puntos por partido — '+Q.n_partidos+' jugados · '+Q.total_partidos+' pts'));
  c2.append($('div',{class:'muted',html:'<small>Aciertos: <b>G</b> ganador · <b>L</b> goles local · <b>V</b> goles visita · <b>E</b> marcador exacto.</small>'}));
  const mt=$('table');mt.append($('tr',{},$('th',{},'Fecha'),$('th',{},'Partido'),
    $('th',{class:'n'},'Pronóstico'),$('th',{class:'n'},'Real'),$('th',{},'Aciertos'),$('th',{class:'n'},'Pts')));
  Q.por_partido.forEach(m=>{
    const tr=$('tr',{});
    const ac=['ganador','gol_local','gol_visita','exacto'].filter(k=>m.parts[k])
      .map(k=>({ganador:'G',gol_local:'L',gol_visita:'V',exacto:'E'}[k])).join(' ');
    tr.append($('td',{class:'muted'},m.fecha.slice(5)),$('td',{},m.home+' vs '+m.away),
      $('td',{class:'n muted'},m.pred[0]+'–'+m.pred[1]),
      $('td',{class:'n'},m.real[0]+'–'+m.real[1]),
      $('td',{class:'q'},ac||'—'),
      $('td',{class:'n'+(m.pts>0?' q':' muted')},String(m.pts)));
    mt.append(tr)});
  c2.append(mt);p.append(c2);
}
function paneComp(p){
  const C=S.comparativa;
  if(!C){p.append($('div',{class:'muted'},'Comparativa no disponible (scoring_ad_weight=0).'));return}
  const c0=$('div',{class:'card'});
  c0.append($('div',{class:'gtitle'},'🆚 Modelo actual (Elo puro) vs Mejorado (ataque/defensa, w='+C.w_new+')'));
  c0.append($('div',{class:'muted',html:'<small><b>OLD</b> = modelo en producción (campeón/grupos/por fecha siguen con este). <b>NEW</b> = añade cuánto marca/recibe cada selección. El signo (L/E/V) es el 1X2 más probable; puede diferir del marcador modal. Las filas con <b style="color:#d29922">Δ</b> son donde difieren.</small>'}));
  const A=C.agg;
  const row=$('div',{});row.style.cssText='display:flex;gap:28px;flex-wrap:wrap;align-items:baseline;margin:8px 0';
  row.append(bigStat(A.old_hit+'/'+A.n,'acierto signo OLD','var(--mut)'));
  row.append(bigStat(A.new_hit+'/'+A.n,'acierto signo NEW','var(--ac2)'));
  row.append(bigStat(A.old_brier,'Brier OLD','var(--mut)'));
  row.append(bigStat(A.new_brier,'Brier NEW', A.new_brier<A.old_brier?'var(--ac)':'var(--warn)'));
  c0.append(row);
  p.append(c0);
  // Jugados
  const c1=$('div',{class:'card'});
  c1.append($('div',{class:'gtitle'},'Jugados — predicción previa vs real'));
  const t1=$('table');t1.append($('tr',{},$('th',{},'Fecha'),$('th',{},'Partido'),$('th',{class:'n'},'Real'),
    $('th',{class:'n'},'OLD'),$('th',{},''),$('th',{class:'n'},'NEW'),$('th',{},''),$('th',{},'Δ')));
  C.jugados.forEach(r=>{
    const tr=$('tr',{});
    const ok=v=>v?'<span class="q">✓</span>':'<span class="muted">·</span>';
    tr.append($('td',{class:'muted'},r.fecha.slice(5)),$('td',{},r.home+'–'+r.away),
      $('td',{class:'n'},r.real[0]+'–'+r.real[1]),
      $('td',{class:'n muted'},r.old.score[0]+'–'+r.old.score[1]+' '+r.old.signo),$('td',{html:ok(r.old.hit)}),
      $('td',{class:'n'},r.new.score[0]+'–'+r.new.score[1]+' '+r.new.signo),$('td',{html:ok(r.new.hit)}),
      $('td',{html:r.diff?'<b style="color:#d29922">Δ</b>':''}));
    t1.append(tr)});
  c1.append(t1);p.append(c1);
  // Por jugar
  const c2=$('div',{class:'card'});
  c2.append($('div',{class:'gtitle'},'Por jugar — ambos pronósticos'));
  const t2=$('table');t2.append($('tr',{},$('th',{},'Fecha'),$('th',{},'Partido'),
    $('th',{class:'n'},'OLD (fav)'),$('th',{class:'n'},'NEW (fav)'),$('th',{},'Δ')));
  C.porjugar.forEach(r=>{
    const tr=$('tr',{});
    tr.append($('td',{class:'muted'},(r.fecha||'').slice(5)),$('td',{},r.home+'–'+r.away),
      $('td',{class:'n muted'},r.old.score[0]+'–'+r.old.score[1]+' '+r.old.signo+' '+r.old.fav+'%'),
      $('td',{class:'n'},r.new.score[0]+'–'+r.new.score[1]+' '+r.new.signo+' '+r.new.fav+'%'),
      $('td',{html:r.diff?'<b style="color:#d29922">Δ</b>':''}));
    t2.append(tr)});
  c2.append(t2);p.append(c2);
}
function paneEval(p){
  const E=S.evaluacion;
  if(!E||!E.n){p.append($('div',{class:'muted'},'Aun no hay partidos jugados para evaluar.'));return}
  const c0=$('div',{class:'card'});
  c0.append($('div',{class:'gtitle'},'📐 Auto-evaluacion del modelo (backtest honesto)'));
  c0.append($('div',{class:'warn',html:'<b>Sin trampa:</b> cada partido se predice con el estado del modelo PREVIO a esa fecha (solo resultados anteriores). Mide que tan bien calibradas estan las probabilidades — distinto del Puntaje, que cuenta aciertos tipo polla.'}));
  const row=$('div',{});row.style.cssText='display:flex;gap:28px;flex-wrap:wrap;align-items:baseline;margin:8px 0';
  row.append(bigStat(E.hit_pct+'%','acierto 1X2 ('+E.hit+'/'+E.n+')','var(--ac2)'));
  row.append(bigStat(E.exact_pct+'%','marcador exacto','var(--mut)'));
  row.append(bigStat(E.brier,'Brier (baseline '+E.brier_base+')', E.mejor_que_baseline?'var(--ac)':'var(--warn)'));
  row.append(bigStat(E.logloss,'log-loss','var(--mut)'));
  c0.append(row);
  c0.append($('div',{class:'muted',html:'<small>'+(E.mejor_que_baseline
    ? '✅ El modelo SUPERA al baseline (prior fijo 40/27/33, sin informacion). Menor Brier = mejor.'
    : '⚠️ El modelo NO supera al baseline (prior fijo 40/27/33). Brier mayor = peor: senal de sobre-confianza o de una muestra atipica (pocos partidos / muchos empates).')+'</small>'}));
  c0.append($('div',{class:'muted',html:'<small>Empates reales: <b>'+E.draws_real+'/'+E.n+'</b> ('+E.draws_real_pct+'%) · empates como pick modal 1X2: <b>'+E.draws_pick+'</b>. Capa ataque/defensa <b>w='+E.w+'</b> · localia anfitriones <b>+'+E.host_adv+'</b> Elo (knobs en model_config.json).</small>'}));
  p.append(c0);
  const cc=$('div',{class:'card'});
  cc.append($('div',{class:'gtitle'},'🎚️ Calibracion — confianza declarada vs aciertos observados'));
  cc.append($('div',{class:'muted',html:'<small>De la clase mas probable de cada partido. Idealmente confianza ≈ observado. Muestra chica: leer con cautela.</small>'}));
  const tb=$('table');tb.append($('tr',{},$('th',{},'Rango de confianza'),$('th',{class:'n'},'Partidos'),$('th',{class:'n'},'Confianza media'),$('th',{class:'n'},'Acierto observado')));
  E.calib.forEach(b=>{if(!b.n)return;
    tb.append($('tr',{},$('td',{},b.rango),$('td',{class:'n'},String(b.n)),
      $('td',{class:'n muted'},b.conf+'%'),$('td',{class:'n q'},b.obs+'%')))});
  cc.append(tb);p.append(cc);
  const c2=$('div',{class:'card'});
  c2.append($('div',{class:'gtitle'},'Detalle por partido'));
  const mt=$('table');mt.append($('tr',{},$('th',{},'Fecha'),$('th',{},'Partido'),$('th',{class:'n'},'Real'),
    $('th',{class:'n'},'Pred'),$('th',{},'1X2 (L/E/V)'),$('th',{},'Signo'),$('th',{class:'n'},'Brier')));
  E.rows.forEach(r=>{
    const tr=$('tr',{});
    tr.append($('td',{class:'muted'},r.fecha.slice(5)),$('td',{},r.home+' vs '+r.away),
      $('td',{class:'n'},r.real[0]+'–'+r.real[1]),
      $('td',{class:'n muted'},r.pred_score[0]+'–'+r.pred_score[1]),
      $('td',{class:'muted'},Math.round(r.pH*100)+'/'+Math.round(r.pD*100)+'/'+Math.round(r.pA*100)),
      $('td',{html: r.hit?'<span class="q">✓</span>':'<span class="muted">·</span>'}),
      $('td',{class:'n muted'},r.brier.toFixed(2)));
    mt.append(tr)});
  c2.append(mt);p.append(c2);
}
function paneMetodo(p){
  const M=S.metodologia||{fuentes:[]};
  // Que es
  const c0=$('div',{class:'card'});
  c0.append($('div',{class:'gtitle'},'¿Que es esto?'));
  c0.append($('div',{html:'Un predictor del Mundial 2026 que combina un <b>motor estadistico</b> (calcula las probabilidades) con <b>resultados reales</b> que se cargan fecha a fecha. Cada vez que entra un resultado, todo el pronostico se recalcula. <b>Son probabilidades, no certezas.</b>'}));
  p.append(c0);
  // En que se basa el modelo
  const cm=$('div',{class:'card'});
  cm.append($('div',{class:'gtitle'},'🧠 En que se basa el modelo'));
  cm.append($('div',{class:'muted',html:'<small>No es un modelo de marca unica: combina cuatro metodos estandar y bien probados de la industria de prediccion deportiva (la misma familia que usan FiveThirtyEight y Opta). Etiqueta corta: <b>modelo Elo + ataque/defensa + Poisson con simulacion de Monte Carlo</b>.</small>'}));
  [['Sistema Elo — fuerza de cada seleccion','Creado por Arpad Elo (originalmente para el ajedrez). Uso la variante World Football Elo Ratings (eloratings.net): factor K=60 para mundiales y ajuste por diferencia de goles. El Elo evoluciona con cada resultado real.'],
   ['Ratings ataque/defensa — cuanto marca y recibe cada seleccion','Cada equipo tiene un rating de ataque (goles que mete) y de defensa (goles que recibe), <b>ajustados por la fuerza del rival</b> y centrados en 1.0 (promedio mundial). Se estiman desde 750 partidos internacionales reales 2024-2026 (con fuente) y evolucionan con cada resultado. Es la pieza que distingue, p.ej., una defensa solida (Senegal) de una floja a igual Elo. Mismo linaje Maher/Dixon-Coles.'],
   ['Modelo de Poisson — marcadores','Modela los goles de cada equipo con una distribucion de Poisson. Los goles esperados salen de la diferencia de Elo, modulados por los ratings ataque/defensa. De ahi sale P(gana local / empate / gana visita) y el marcador mas probable.'],
   ['Simulacion de Monte Carlo — proyeccion del torneo','Simular el torneo completo miles de veces (12.000) y contar frecuencias para estimar probabilidades. Se llama asi por el casino de Monaco; es el estandar cuando hay mucha incertidumbre.']].forEach(([t,d])=>{
    cm.append($('div',{class:'rname'},t));
    cm.append($('div',{class:'muted',html:'<small>'+d+'</small>'}));
  });
  cm.append($('div',{class:'muted',html:'<small style="opacity:.85">Lo propio de este sistema es la <b>implementacion</b> (el Elo que evoluciona con cada resultado, el arbol oficial de FIFA, el puntaje de la polla), no la matematica de base, que es publica y probada.</small>'}));
  p.append(cm);
  // Algoritmo
  const c1=$('div',{class:'card'});
  c1.append($('div',{class:'gtitle'},'⚙️ El algoritmo en 5 pasos'));
  const steps=[
    ['1. Fuerza de cada seleccion (Elo)','Cada equipo arranca con un rating Elo (mide su fuerza). Tras cada partido real, el Elo sube o baja segun el resultado y por cuanto (un 3-0 pesa mas que un 1-0). Asi la "forma" del torneo entra al modelo: quien rinde mas de lo esperado, sube.'],
    ['2. Modelo de un partido (Elo + ataque/defensa + Poisson)','Para cualquier cruce, la diferencia de Elo define una base de goles esperados; esa base se ajusta por cuanto marca el equipo y cuanto recibe el rival (ratings ataque/defensa). Con los goles esperados resultantes se sortean marcadores con una Poisson. De ahi sale P(gana local / empate / gana visita) y el marcador mas probable. Toca cualquier partido en "Por fecha" para ver este desglose.'],
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
  const cfg=S.model_cfg||{w:0,host_adv:0};
  const adOn=cfg.w>0;
  [['Equipos / grupos',(M.equipos||48)+' equipos · '+(M.grupos||12)+' grupos de 4'],
   ['Simulaciones Monte Carlo',(M.sims||0).toLocaleString()+' por corrida'],
   ['Resultados reales cargados',(M.n_resultados||0)+' partidos del torneo (con fuente)'],
   ['Factor K del Elo','60 (estandar para mundiales)'],
   ['Capa ataque/defensa',adOn?('ACTIVA (peso '+cfg.w+') — analista principal de las fechas'):'apagada (Elo puro)'],
   ['Historial para ataque/defensa','750 partidos internacionales 2024-2026 (con fuente, muestra verificada)'],
   ['Modelo del juego de puntos',(S.puntaje&&S.puntaje.scoring_desde)?('Elo puro hasta '+S.puntaje.scoring_desde+', mejorado desde esa fecha'):'Elo puro'],
   ['Ventaja de localia',cfg.host_adv>0?('+'+cfg.host_adv+' Elo a anfitriones'):'Ninguna (sedes neutrales)'],
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
    'El marcador mostrado redondea el xG (goles esperados) de cada equipo, ajustado para no contradecir al ganador mas probable; el puntaje de la polla usa ESE MISMO marcador (lo que se ve es lo que se puntua). El xG es un promedio, no una probabilidad: un equipo con xG 2,7 puede hacer 2, 3 o 4. La lectura completa (xG + probabilidades 1X2) esta en el popup de cada partido.',
    'Los ratings de ataque/defensa se anclan sobre todo con partidos dentro de cada confederacion; el nivel relativo entre confederaciones (ej. Africa vs Europa) esta debilmente calibrado y se corrige a medida que el Mundial cruza selecciones de distintas confederaciones.',
    'La capa ataque/defensa mejora el marcador pero, sobre los 16 partidos jugados, todavia no supera de forma concluyente al baseline (ver pestana Evaluacion). Es la mejor estimacion disponible, no una certeza.',
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
