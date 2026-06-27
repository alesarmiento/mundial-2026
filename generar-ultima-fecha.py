import json, os
BASE=os.path.dirname(os.path.abspath(__file__))  # carpeta del skill, portable (Mac o nube)
d=json.load(open(os.path.join(BASE,'data/state.json')))
probs=d['probs']; g_of={t:g for g,ts in d['grupos'].items() for t in ts}
robust=set(sorted(probs,key=lambda t:-probs[t]['r32'])[:32])
clinched=set(t for t in probs if probs[t]['r32']>=99.95)  # ya 100% clasificados (real)
eliminated=set(t for t in probs if probs[t]['r32']<=0.05)  # ya 100% eliminados (no pueden clasificar)
jug=[('Mexico','South Africa',2,1),('South Korea','Czechia',1,1),('Czechia','South Africa',2,1),('Mexico','South Korea',2,1),('Canada','Bosnia and Herzegovina',1,0),('Qatar','Switzerland',0,2),('Switzerland','Bosnia and Herzegovina',3,1),('Canada','Qatar',3,0),('Brazil','Morocco',3,0),('Haiti','Scotland',0,2),('Scotland','Morocco',1,2),('Brazil','Haiti',4,0),('United States','Paraguay',1,0),('Australia','Turkiye',1,2),('United States','Australia',1,1),('Turkiye','Paraguay',2,1),('Germany','Curacao',4,0),('Ivory Coast','Ecuador',0,1),('Germany','Ivory Coast',2,1),('Ecuador','Curacao',3,0),('Netherlands','Japan',2,1),('Sweden','Tunisia',2,0),('Netherlands','Sweden',3,1),('Tunisia','Japan',0,3),('Belgium','Egypt',3,1),('Iran','New Zealand',2,0),('Belgium','Iran',2,1),('New Zealand','Egypt',1,2),('Spain','Cape Verde',5,0),('Saudi Arabia','Uruguay',0,2),('Spain','Saudi Arabia',4,0),('Uruguay','Cape Verde',2,0),('France','Senegal',2,1),('Iraq','Norway',0,3),('France','Iraq',3,0),('Norway','Senegal',2,1),('Argentina','Algeria',2,0),('Austria','Jordan',2,1),('Argentina','Austria',2,0),('Jordan','Algeria',1,2),('Portugal','DR Congo',2,0),('Uzbekistan','Colombia',0,2),('Portugal','Uzbekistan',2,0),('Colombia','DR Congo',2,0),('England','Croatia',2,1),('Ghana','Panama',1,2),('England','Ghana',4,0),('Panama','Croatia',1,3)]
# Ranking FIFA oficial (jun-2026) usado como criterio de desempate REAL de FIFA tras pts/DG/GF.
# Nota: el criterio 4 oficial es "juego limpio" (tarjetas), que el modelo NO trackea; usamos el
# criterio 5 (Ranking FIFA) como desempate determinista. Fuente: Yahoo/ESPN ranking jun-2026.
fifa_rank={'Argentina':1,'France':2,'Spain':3,'England':4,'Brazil':5,'Morocco':6,'Netherlands':7,'Germany':8,'Portugal':9,'Belgium':10,'Mexico':11,'Colombia':12,'United States':13,'Croatia':15,'Japan':16,'Senegal':17,'Switzerland':18,'Uruguay':19,'Austria':21,'Iran':22,'South Korea':23,'Australia':25,'Egypt':26,'Norway':27,'Canada':28,'Algeria':29,'Ecuador':30,'Ivory Coast':31,'Turkiye':32,'Sweden':36,'Paraguay':37,'Panama':40,'Scotland':41,'DR Congo':43,'Czechia':44,'Uzbekistan':54,'Qatar':57,'Tunisia':58,'Saudi Arabia':59,'Iraq':60,'South Africa':61,'Cape Verde':63,'Bosnia and Herzegovina':64,'Ghana':65,'Jordan':68,'Curacao':81,'New Zealand':84,'Haiti':87}
# Mi pronostico de ultima fecha (EV-optimo + overlay rotacion)
mine_last={('Czechia','Mexico'):(1,2),('South Africa','South Korea'):(0,2),('Switzerland','Canada'):(1,1),('Bosnia and Herzegovina','Qatar'):(2,0),('Scotland','Brazil'):(0,2),('Morocco','Haiti'):(2,0),('Turkiye','United States'):(1,2),('Paraguay','Australia'):(0,1),('Curacao','Ivory Coast'):(0,3),('Ecuador','Germany'):(1,2),('Japan','Sweden'):(3,1),('Tunisia','Netherlands'):(0,3),('Egypt','Iran'):(5,1),('New Zealand','Belgium'):(0,2),('Cape Verde','Saudi Arabia'):(1,0),('Uruguay','Spain'):(1,2),('Norway','France'):(1,2),('Senegal','Iraq'):(2,0),('Algeria','Austria'):(0,1),('Jordan','Argentina'):(1,2),('Colombia','Portugal'):(1,2),('DR Congo','Uzbekistan'):(1,1),('Panama','England'):(0,3),('Croatia','Ghana'):(1,0)}

def resolve(last, base_jug):
    st={t:{'pts':0,'gf':0,'gc':0} for t in g_of}
    for h,a,gh,ga in base_jug:
        st[h]['pts']+=3 if gh>ga else (1 if gh==ga else 0); st[h]['gf']+=gh; st[h]['gc']+=ga
        st[a]['pts']+=3 if ga>gh else (1 if ga==gh else 0); st[a]['gf']+=ga; st[a]['gc']+=gh
    for (h,a),(gh,ga) in last.items():
        st[h]['pts']+=3 if gh>ga else (1 if gh==ga else 0); st[h]['gf']+=gh; st[h]['gc']+=ga
        st[a]['pts']+=3 if ga>gh else (1 if ga==gh else 0); st[a]['gf']+=ga; st[a]['gc']+=gh
    # FIFA: pts -> DG -> GF -> (juego limpio, no trackeado) -> Ranking FIFA (menor n = mejor)
    key=lambda t:(st[t]['pts'],st[t]['gf']-st[t]['gc'],st[t]['gf'],-fifa_rank.get(t,99))
    groups={}; thirds=[]
    for g,ts in d['grupos'].items():
        o=sorted(ts,key=key,reverse=True); groups[g]=o; thirds.append(o[2])
    b8=set(sorted(thirds,key=key,reverse=True)[:8])
    q=set()
    for g,o in groups.items():
        q.add(o[0]); q.add(o[1])
        if o[2] in b8: q.add(o[2])
    return q, groups, b8, st

# TU cuadro: tus predicciones de jugados (fijas) + mi ultima fecha
mine32, groups, b8, st = resolve(mine_last, jug)
# REAL+PROY: resultados reales jugados + mi ultima fecha SOLO para lo que aun no se jugo (evita doble conteo)
_res=json.load(open(os.path.join(BASE,'data/results.json')))['partidos']
real_jug=[(m['local'],m['visita'],m['gl'],m['gv']) for m in _res]
played_pairs={(m['local'],m['visita']) for m in _res}
pending_last={k:v for k,v in mine_last.items() if k not in played_pairs}
realproy32, rgroups, rb8, rst = resolve(pending_last, real_jug)
# "REAL + PROYECTADO" = proyeccion determinista: resultados REALES + tus marcadores proyectados para lo que falta.
# (Antes se comparaba contra `robust` = top-32 del modelo Monte Carlo; eso metia equipos dudosos como Iran 65%
#  que NO estan en tu proyeccion. Ahora la comparacion calza con la tabla de terceros, que tambien usa realproy32.)
sistema32 = realproy32

CHK=chr(9989); SKULL=chr(128128); X=chr(10060)
live=sorted([t for t in mine32 if t in realproy32])
dead=sorted([t for t in mine32 if t not in realproy32])
miss=sorted([t for t in realproy32 if t not in mine32])

# ===== MI PARTICIPACION: pronostico por partido vs real, con puntaje (regla del sistema) =====
ESp={'Algeria':'Argelia','Argentina':'Argentina','Australia':'Australia','Austria':'Austria','Belgium':'Belgica','Bosnia and Herzegovina':'Bosnia','Brazil':'Brasil','Canada':'Canada','Cape Verde':'Cabo Verde','Colombia':'Colombia','Croatia':'Croacia','Curacao':'Curazao','Czechia':'Chequia','DR Congo':'R.D. Congo','Ecuador':'Ecuador','Egypt':'Egipto','England':'Inglaterra','France':'Francia','Germany':'Alemania','Ghana':'Ghana','Haiti':'Haiti','Iran':'Iran','Iraq':'Irak','Ivory Coast':'C. Marfil','Japan':'Japon','Jordan':'Jordania','Mexico':'Mexico','Morocco':'Marruecos','Netherlands':'P. Bajos','New Zealand':'N. Zelanda','Norway':'Noruega','Panama':'Panama','Paraguay':'Paraguay','Portugal':'Portugal','Qatar':'Catar','Saudi Arabia':'Arabia S.','Scotland':'Escocia','Senegal':'Senegal','South Africa':'Sudafrica','South Korea':'Corea Sur','Spain':'Espana','Sweden':'Suecia','Switzerland':'Suiza','Tunisia':'Tunez','Turkiye':'Turquia','United States':'USA','Uruguay':'Uruguay','Uzbekistan':'Uzbekistan'}
_fx=json.load(open(os.path.join(BASE,'data/fixtures.json')))['fixtures']
fxdate={(f['home'],f['away']):f['date'][:10] for f in _fx}
realres={(m['local'],m['visita']):(m['gl'],m['gv']) for m in _res}
# probabilidades del MODELO (Elo + ataque/defensa) por partido: P(resultado 1X2) y P(marcador exacto, Poisson)
import math as _math
predix={}
for _blk in d.get('por_fecha',[]):
    for _p in _blk.get('partidos',[]):
        if _p.get('pred'): predix[(_p['home'],_p['away'])]=_p['pred']
def _pois(k,l): return (_math.exp(-l)*l**k/_math.factorial(k)) if l and l>0 else (1.0 if k==0 else 0.0)
def model_prob(h,a,gh,ga):
    pr=predix.get((h,a))
    if not pr: return None
    pout=pr['pH'] if gh>ga else (pr['pD'] if gh==ga else pr['pA'])
    pex=_pois(gh,pr.get('xgH',0))*_pois(ga,pr.get('xgA',0))*100
    return (pout,pex)
def score_pred(pred,real):
    ph,pa=pred; rh,ra=real
    o=lambda x,y:(x>y)-(x<y); p=0
    if o(ph,pa)==o(rh,ra): p+=3
    if ph==rh: p+=2
    if pa==ra: p+=2
    if ph==rh and pa==ra: p+=4
    return p
DAYLBL={'2026-06-24':'Mie 24-jun','2026-06-25':'Jue 25-jun','2026-06-26':'Vie 26-jun','2026-06-27':'Sab 27-jun'}
part_items=sorted(mine_last.items(), key=lambda kv: (fxdate.get(kv[0],'9'),))
mi_ganado=0; mi_jugados=0; mi_pend=0
prow=''; curday=None
for (h,a),pred in part_items:
    day=fxdate.get((h,a),'?');
    if day!=curday:
        prow+='<tr><td colspan="6" style="padding:8px 6px 3px;color:#58a6ff;font-weight:700;font-size:12px">'+DAYLBL.get(day,day)+'</td></tr>'; curday=day
    real=realres.get((h,a))
    pk='%d-%d'%pred
    mp=model_prob(h,a,pred[0],pred[1])
    if mp:
        pout,pex=mp; pcol = '#56d364' if pout>=65 else ('#e3b341' if pout>=45 else '#f0883e')
        probcell='<td style="text-align:center;font-size:10.5px"><b style="color:%s">%.0f%%</b> <span style="color:#6e7681">res</span> &middot; <span style="color:#8b949e">%.0f%% ex</span></td>'%(pcol,pout,pex)
    else:
        probcell='<td style="text-align:center;color:#6e7681;font-size:10.5px">&mdash;</td>'
    if real:
        p=score_pred(pred,real); mi_ganado+=p; mi_jugados+=1
        rl='%d-%d'%real
        pc = '#56d364' if p>=4 else ('#d29922' if p>0 else '#f85149')
        prow+='<tr style="border-bottom:1px solid #21262d"><td style="padding:4px 6px">%s vs %s</td><td style="text-align:center;color:#8b949e">%s</td>%s<td style="text-align:center;font-weight:700">%s</td><td style="text-align:center;color:%s;font-weight:700">+%d</td><td style="color:#7d8590;font-size:10.5px">jugado</td></tr>'%(ESp[h],ESp[a],pk,probcell,rl,pc,p)
    else:
        mi_pend+=1
        prow+='<tr style="border-bottom:1px solid #21262d"><td style="padding:4px 6px">%s vs %s</td><td style="text-align:center;color:#e3b341;font-weight:700">%s</td>%s<td style="text-align:center;color:#6e7681">&mdash;</td><td style="text-align:center;color:#6e7681">&middot;</td><td style="color:#7d8590;font-size:10.5px">por jugar</td></tr>'%(ESp[h],ESp[a],pk,probcell)
mi_max=mi_jugados*11
miparticipacion=('<div class="box" style="border-color:#d29922"><h2 style="color:#e3b341">%s Mi participacion &mdash; pronostico y puntaje (24-27 jun)</h2>'
 '<div style="color:#8b949e;font-size:12px;margin-bottom:10px">Mis marcadores de la ultima fecha jugando de verdad en la polla. Regla del sistema: <b>ganador +3, gol local +2, gol visita +2, exacto +4</b> (max 11/partido). La columna <b>Prob. modelo</b> = chance segun el motor (Elo + ataque/defensa) de que ACIERTES: <b style="color:#56d364">res</b> = el resultado 1X2 (los +3), <b style="color:#8b949e">ex</b> = el marcador exacto (los 11). En <b style="color:#f0883e">naranja</b>, picks de baja probabilidad (apuestas/ajustes). Se recalcula solo con cada resultado real.</div>'
 '<div style="display:flex;gap:18px;flex-wrap:wrap;margin-bottom:12px">'
 '<div style="background:#0d1117;border:1px solid #d29922;border-radius:9px;padding:10px 16px"><div style="font-size:11px;color:#8b949e">GANADO (jugados)</div><div style="font-size:26px;font-weight:800;color:#e3b341">%d<span style="font-size:13px;color:#7d8590"> / %d</span></div><div style="font-size:10.5px;color:#7d8590">%d partidos jugados</div></div>'
 '<div style="background:#0d1117;border:1px solid #30363d;border-radius:9px;padding:10px 16px"><div style="font-size:11px;color:#8b949e">EN JUEGO</div><div style="font-size:26px;font-weight:800;color:#58a6ff">%d</div><div style="font-size:10.5px;color:#7d8590">partidos por jugar</div></div>'
 '</div>'
 '<table style="width:100%%;border-collapse:collapse;font-size:12.5px"><tr style="color:#7d8590;font-size:10.5px"><td style="padding:2px 6px">Partido</td><td style="text-align:center">Mi pick</td><td style="text-align:center">Prob. modelo</td><td style="text-align:center">Real</td><td style="text-align:center">Pts</td><td></td></tr>')%(CHK,mi_ganado,mi_max,mi_jugados,mi_pend)+prow+'</table></div>'

ana={'A':'CERRADO (real): Mexico 1o, Sudafrica 2o. Corea 3a con 3 pts -> ENTRA como mejor tercero. Chequia afuera.','B':'CERRADO (real): Suiza 1o (gano 2-1), Canada 2o. Bosnia 3o con 4 pts (goleo 3-1 a Catar) -> VIVO.','C':'CERRADO (real): Brasil 1o (3-0), Marruecos 2o (4-2). Escocia 3a pero perdio 0-3 -> SE CAE del corte.','D':'USA 1ro. Australia el 2do mas seguro (DG 0). Con tu Australia 0-1, Australia queda en tus 32 y Paraguay 3o (pelea el ultimo cupo de terceros; ver tabla). Se juega HOY.','E':'Alemania 1ro, C.Marfil 2do (vivo). Ecuador (1pt) sigue en TUS 32: +7 si DA LA SORPRESA y le gana a Alemania rotada, pero pronosticamos Alemania 2-1 (lo mas real). Se juega HOY.','F':'PaisesBajos y Japon adentro. Suecia 3a: con tu Japon 3-1 cae a 3a pero sostiene mejor-tercero. Se juega HOY.','G':'Con tu Egipto 5-1 (goleada): Iran cae a 3o y, por el margen 4+, queda DEBAJO de Argelia en tu cuadro -> sale Iran, entra ARGELIA. Apuesta a que Egipto gana (Iran afuera en la realidad).','H':'Espana 1a. Con tu Cabo Verde 1-0, CV sube a 2do y clasifica directo; Uruguay 3o afuera.','I':'Francia, Noruega, Senegal: los 3 VIVOS.','J':'Argentina, Austria, Argelia: los 3 VIVOS.','K':'Colombia y Portugal; sin tercero clasificado.','L':'Inglaterra y Croacia. Te falta Ghana.'}

def cellcolor(t,i):
    q=(i<2) or (t in b8)
    if q and t in robust: return '#13301f','#56d364'
    if q and t not in robust: return '#3d1418','#f85149'
    return '#161b22','#7d8590'

realpts={r['equipo']:(r['pts'],r['pj']) for gg in d['tabla'] for r in d['tabla'][gg]}
# REAL+PROY = puntos reales actuales + lo recomendado en la ultima fecha
realfin={t:realpts[t][0] for t in realpts}
for (h,a),(gh,ga) in pending_last.items():
    realfin[h]+=3 if gh>ga else (1 if gh==ga else 0)
    realfin[a]+=3 if ga>gh else (1 if ga==gh else 0)
# clasificados realistas (real + recomendado), deterministico
keyr=lambda t:realfin[t]
rthirds=[]; rfirst=set(); rsec=set()
for g,ts in d['grupos'].items():
    o=sorted(ts,key=lambda t:(realfin[t],),reverse=True); rfirst.add(o[0]); rsec.add(o[1]); rthirds.append(o[2])
# usamos robust como el set realista (el plan reproduce los 32 robustos)
cards=''
for g in sorted(groups):
    head='<tr style="color:#7d8590;font-size:10px"><td></td><td></td><td style="text-align:right;padding:0 6px">HOY</td><td style="text-align:right;padding:0 6px">TU</td><td style="text-align:right;padding:0 8px">REAL+PROY</td></tr>'
    rows=''
    for i,t in enumerate(groups[g]):
        bg,fg=cellcolor(t,i)
        q=(i<2) or (t in b8)
        badge=['1','2','3' if t in b8 else '-','-'][i] if i<4 else '-'
        mk = CHK if (q and t in robust) else (SKULL if q else '')
        rp,pj=realpts.get(t,(0,0))
        rfc = '#56d364' if t in realproy32 else '#7d8590'
        rfmk = ' '+CHK if t in realproy32 else ''
        rows+='<tr style="background:%s"><td style="color:%s;padding:3px 5px;font-weight:700">%s</td><td style="color:%s;padding:3px 5px">%s %s</td><td style="color:#8b949e;text-align:right;padding:3px 6px;font-size:11px">%d</td><td style="color:%s;text-align:right;padding:3px 6px;font-weight:600">%d</td><td style="color:%s;text-align:right;padding:3px 8px;font-weight:700">%d%s</td></tr>'%(bg,fg,badge,fg,t,mk,rp,fg,st[t]['pts'],rfc,realfin[t],rfmk)
    cards+='<div class="card"><div class="gt">Grupo %s</div><table>%s%s</table><div class="an">%s</div></div>'%(g,head,rows,ana[g])

ES={'Algeria':'Argelia','Argentina':'Argentina','Australia':'Australia','Austria':'Austria','Belgium':'Belgica','Bosnia and Herzegovina':'Bosnia','Brazil':'Brasil','Canada':'Canada','Cape Verde':'Cabo Verde','Colombia':'Colombia','Croatia':'Croacia','Curacao':'Curazao','Czechia':'Chequia','DR Congo':'R.D. Congo','Ecuador':'Ecuador','Egypt':'Egipto','England':'Inglaterra','France':'Francia','Germany':'Alemania','Ghana':'Ghana','Haiti':'Haiti','Iran':'Iran','Iraq':'Irak','Ivory Coast':'Costa Marfil','Japan':'Japon','Jordan':'Jordania','Mexico':'Mexico','Morocco':'Marruecos','Netherlands':'P. Bajos','New Zealand':'N. Zelanda','Norway':'Noruega','Panama':'Panama','Paraguay':'Paraguay','Portugal':'Portugal','Qatar':'Catar','Saudi Arabia':'Arabia Saudi','Scotland':'Escocia','Senegal':'Senegal','South Africa':'Sudafrica','South Korea':'Corea Sur','Spain':'Espana','Sweden':'Suecia','Switzerland':'Suiza','Tunisia':'Tunez','Turkiye':'Turquia','United States':'USA','Uruguay':'Uruguay','Uzbekistan':'Uzbekistan'}

def seedmap(teamset, statef):
    k=lambda t:(statef[t]['pts'],statef[t]['gf']-statef[t]['gc'],statef[t]['gf'])
    return {t:i+1 for i,t in enumerate(sorted(teamset,key=k,reverse=True))}
mine_seed=seedmap(mine32, st)
real_seed=seedmap(realproy32, rst)
# Diferencia tu cuadro vs tu proyeccion (real+proy), separando los casos donde el MODELO disiente:
#  - 💀 muerto real  = lo tenes, tu proy lo deja afuera Y el modelo tambien (coincide con la lista de abajo)
#  - 🎲 sorpresa      = lo tenes, tu proy lo deja afuera PERO el modelo lo da probable (Iran): +7 si clasifica
#  - ➕ te falta       = tu proy lo mete y no lo tenes, y el modelo lo confirma
#  - 🎲 dudoso (der)  = tu proy lo mete pero el modelo lo da improbable (DR Congo)
_mine_only=mine32-realproy32
_real_only=realproy32-mine32
g_dead    =sorted([t for t in _mine_only if t not in robust], key=lambda t:-mine_seed.get(t,99))
g_surprise=sorted([t for t in _mine_only if t in robust],      key=lambda t:-mine_seed.get(t,99))
g_add     =sorted([t for t in _real_only if t in robust],      key=lambda t:real_seed.get(t,99))
g_weak    =sorted([t for t in _real_only if t not in robust],  key=lambda t:real_seed.get(t,99))
mine_only=g_dead; real_only=g_add  # para el cartel (los casos "claros")
PLUS='&#10133;'; DICE='&#127922;'

def gblock(g, gr, st2, b8s, deadset=None, seed=None, addset=None, surpriseset=None, weakset=None):
    rws=''
    for i,t in enumerate(gr[g]):
        pts=st2[t]['pts']; dg=st2[t]['gf']-st2[t]['gc']
        isq=(i<2) or (i==2 and t in b8s)
        if i<2: cfg='#7ee787'; cbg='#0f2417'; tag=str(i+1)
        elif i==2 and t in b8s: cfg='#f0883e'; cbg='#2b1d10'; tag='3'+CHK
        elif i==2: cfg='#8b949e'; cbg='#161b22'; tag='3'
        else: cfg='#6e7681'; cbg='#161b22'; tag='4'
        nm=ES[t]
        if deadset and isq and t in deadset:
            cfg='#f85149'; cbg='#2d1418'; nm=ES[t]+' '+SKULL+' <span style="font-size:9px;color:#f85149;font-weight:700">&minus;7</span>'
        elif surpriseset and isq and t in surpriseset:
            cfg='#e3b341'; cbg='#2b2410'; nm=ES[t]+' '+DICE
        elif weakset and isq and t in weakset:
            cfg='#e3b341'; cbg='#2b2410'; nm=ES[t]+' '+DICE
        elif addset and isq and t in addset:
            cfg='#58a6ff'; cbg='#0d2233'; nm=ES[t]+' '+PLUS
        sd=' <span style="color:#8b949e;font-size:9px;font-weight:600">#%d</span>'%seed[t] if (seed and isq and t in seed) else ''
        cut='border-bottom:2px dashed #3d444d;' if i==1 else ''
        rws+='<tr style="background:%s;%s"><td style="color:%s;font-weight:700;width:30px;padding:3px 6px">%s</td><td style="color:%s;padding:3px 6px;white-space:nowrap">%s%s</td><td style="text-align:center;font-weight:700;color:%s;width:26px">%d</td><td style="text-align:center;color:#7d8590;width:36px;font-size:10.5px">%+d</td></tr>'%(cbg,cut,cfg,tag,cfg,nm,sd,cfg,pts,dg)
    return '<div class="gb"><div class="gbh">Grupo '+g+'</div><table>'+rws+'</table></div>'

compare48=('<div class="box"><h2>Los 48 equipos: tu cuadro vs la realidad &mdash; con cortes de clasificacion</h2>'
 '<div style="color:#8b949e;font-size:12px;margin-bottom:12px">Cada grupo ordenado por puntos (incluye tu ultima fecha proyectada). '
 '<b style="color:#7ee787">1&ordm;-2&ordm; (verde)</b> = clasifican directo &mdash; la <b>linea punteada</b> es ese corte. '
 '<b style="color:#f0883e">3&ordm; con '+CHK+' (naranja)</b> = mejor tercero que clasifica; '
 '<b style="color:#8b949e">3&ordm; gris</b> o <b style="color:#6e7681">4&ordm;</b> = afuera. '
 'El <b style="color:#8b949e">#n</b> = puesto en el ranking de los 32 (por puntos).</div>'
 # CARTEL: la diferencia explicita entre TU cuadro y REAL+PROYECTADO
 '<div style="background:#0d1117;border:1px solid #30363d;border-radius:9px;padding:11px 14px;margin-bottom:14px;font-size:13px;line-height:1.7">'
 '<div style="font-weight:700;margin-bottom:5px">Tu cuadro vs lo que va a pasar &mdash; donde difieren:</div>'
 '<div><span style="color:#f85149;font-weight:700">'+SKULL+' Muertos</span> (los tenes y NO clasifican &mdash; tu proyeccion y el modelo coinciden; <b style="color:#f85149">'+str(len(g_dead)*7)+' pts</b> perdidos): '+(', '.join(ES[t] for t in g_dead) or '&mdash;')+'</div>'
 +('<div><span style="color:#e3b341;font-weight:700">'+DICE+' Sorpresa posible</span> (los tenes; tu pronostico los deja afuera, pero el modelo los da PROBABLES &mdash; si clasifican cobras +7 igual): '+', '.join(ES[t] for t in g_surprise)+'</div>' if g_surprise else '')
 +'<div><span style="color:#58a6ff;font-weight:700">'+PLUS+' Te faltan</span> (clasifican y no los tenes): '+(', '.join(ES[t] for t in g_add) or '&mdash;')+'</div>'
 +('<div><span style="color:#e3b341;font-weight:700">'+DICE+' Dudoso</span> (tu pronostico los mete pero el modelo los da improbables): '+', '.join(ES[t] for t in g_weak)+'</div>' if g_weak else '')
 +'<div style="color:#8b949e;font-size:11.5px;margin-top:5px">En el cuadro: '+SKULL+' rojo = muerto, '+DICE+' amarillo = incierto (tu proy y el modelo no coinciden), '+PLUS+' azul = te falta. <b>Clave:</b> un equipo tuyo te suma +7 si clasifica EN LA REALIDAD, sin importar tu marcador.</div>'
 '</div>'
 # Cabecera de las dos columnas
 '<div class="cmp" style="margin-bottom:4px">'
 '<div class="cpanel"><h3 style="color:#d29922">TUS PRONOSTICOS</h3><div style="color:#8b949e;font-size:11px">tu cuadro (congelado + ultima fecha) &middot; '+SKULL+' muerto &middot; '+DICE+' incierto</div></div>'
 '<div class="cpanel"><h3 style="color:#58a6ff">REAL + PROYECTADO</h3><div style="color:#8b949e;font-size:11px">real + tus picks &middot; '+PLUS+' clasifica y te falta &middot; '+DICE+' dudoso</div></div>'
 '</div>'
 # Grupo por grupo: cada grupo en su propia fila de 2 columnas -> izquierda y derecha SIEMPRE alineadas
 +''.join('<div class="cmp" style="align-items:start;margin-bottom:2px">'
   +gblock(g, groups, st, b8, deadset=g_dead, seed=mine_seed, surpriseset=g_surprise)
   +gblock(g, rgroups, rst, rb8, seed=real_seed, addset=g_add, weakset=g_weak)
   +'</div>' for g in sorted(groups))
 +'</div>')

# (fecha, local, visita, xG, EVmax, FINAL, flag_rotacion, razon)
matches=[
 ('Vie 24-jun','Chequia','Mexico','0.2-2.6','0-2','1-2',1,'JUGADO. REAL: Mexico 0-3 (Chavez, Quinones, Fidalgo). Mexico 1o de A, Chequia eliminada.'),
 ('Vie 24-jun','Sudafrica','Corea Sur','0.4-2.3','0-2','0-2',0,'JUGADO. REAL: Sudafrica 1-0 (SORPRESA). Sudafrica 2a y a octavos por 1a vez; Corea 3a pero ENTRA como mejor tercero.'),
 ('Vie 24-jun','Suiza','Canada','1.27-1.26','1-0','1-1',1,'JUGADO. REAL: Suiza 2-1 (Vargas, Manzambi; David descuenta). Suiza 1a de B, Canada 2a. Ambos ya clasificados.'),
 ('Vie 24-jun','Bosnia','Catar','2.2-0.9','2-0','2-0',0,'JUGADO. REAL: Bosnia 3-1. Bosnia 3a de B con 4 pts -> mejor tercero VIVO.'),
 ('Vie 24-jun','Escocia','Brasil','0.6-2.4','0-2','0-2',0,'JUGADO. REAL: Brasil 0-3 (Vinicius x2, Cunha). Escocia 3a pero DG-3 -> SE CAE del corte de terceros.'),
 ('Vie 24-jun','Marruecos','Haiti','3.0-0.2','2-0','2-0',0,'JUGADO. REAL: Marruecos 4-2 (remontada: Hakimi, Saibari, Rahimi, Yassine). Marruecos 2o de C.'),
 ('Jue 25-jun','Turquia','USA','0.7-2.6','0-2','1-2',0,'AJUSTE: aca el marcador es LIBRE (cambie de 1-1 a USA 1-2). Turquia y USA quedan igual en tus 32 (Turquia pasa de 1o a 2o de tu cuadro, sigue dentro) -> no se pierde ningun clasificado. Asi que vamos al marcador mas real: Turquia obligada ataca y marca, pero USA (mejor plantel) gana 2-1. Si Turquia diera la sorpresa y clasificara, igual te suma sus 7 (sigue en tus 32).'),
 ('Jue 25-jun','Paraguay','Australia','0.9-1.5','0-1','0-1',1,'CLAVE para tus 7 pts: Australia tiene DG 0 vs -2 de Paraguay -> es el clasificado MAS SEGURO (con empate o triunfo es 2o directo). Pronosticamos que gana Australia (0-1) para MANTENER a Australia en tus 32. El mercado ve a Paraguay favorito (43/29/28) en el marcador, pero el +7 por el clasificado seguro pesa mas que acertar el marcador.'),
 ('Sab 25-jun','Curazao','Costa Marfil','0.2-2.7','0-2','0-2',0,'EV-max directo'),
 ('Jue 25-jun','Ecuador','Alemania','0.6-1.9','0-1','1-2',0,'AJUSTE (mismo criterio que Turquia): Ecuador ya esta en tus 32, asi que si DA LA SORPRESA y gana igual te suma +7 sin importar este marcador. Como lo mas probable es que Alemania (aunque rota) gane, vamos al marcador real: Alemania 2-1. Si Ecuador realmente gana, cobras sus 7 igual.'),
 ('Sab 25-jun','Japon','Suecia','3.1-0.7','3-0','3-1',0,'TU PICK: Japon 3-1. Japon no rota (pelea 1o), goleador; Suecia peligrosa marca uno pero pierde -> Suecia sigue 3a y clasifica como mejor tercero (sube su GF a 7).'),
 ('Sab 25-jun','Tunez','Paises Bajos','0.2-3.4','0-3','0-3',0,'NL quiere goles para el 1o; EV-max directo'),
 ('Vie 26-jun','Egipto','Iran','1.2-1.3','0-1','5-1',1,'TU PICK: Egipto 5-1 (goleada). MOVIMIENTO ESTRATEGICO: si crees que Egipto gana, Iran (2 pts) queda AFUERA en la realidad y entra Argelia. El 5-1 (margen 4+) es lo que hace falta para que en TU cuadro Iran caiga debajo de Argelia -> ahora tu apuesta es ARGELIA, no Iran. Cuesta puntos de marcador (5-1 es raro), pero alinea tu clasificado con quien realmente pasa si Egipto gana.'),
 ('Vie 26-jun','N.Zelanda','Belgica','0.3-2.8','0-2','0-2',0,'Belgica debe ganar; EV-max 0-2'),
 ('Vie 26-jun','Cabo Verde','Saudi','1.3-1.0','1-0','1-0',0,'TU PICK: Cabo Verde 1-0 (coincide con el EV-max). Gana y SUBE a 2o de H -> clasifica directo y deja a Uruguay (3o) afuera.'),
 ('Vie 26-jun','Uruguay','Espana','0.3-2.5','0-2','1-2',0,'TU PICK (ajuste ultima hora): gana Espana 2-1 (Uruguay 1-2). Espana ya 1a administra; Uruguay marca uno pero pierde -> sigue 3o de H, afuera.'),
 ('Vie 26-jun','Noruega','Francia','0.9-2.0','0-1','1-2',0,'TU PICK: Francia 2-1 (Noruega 1-2). Ambos YA clasificados; define el 1o del grupo. Francia favorita gana ajustado.'),
 ('Vie 26-jun','Senegal','Irak','2.5-0.5','2-0','2-0',0,'Senegal asegura el 3o; EV-max'),
 ('Sab 27-jun','Argelia','Austria','1.1-1.7','0-1','0-1',0,'Argelia debe ganar, pero EV-max da Austria por 1 (toss-up)'),
 ('Sab 27-jun','Jordania','Argentina','0.2-4.0','0-4','1-2',1,'Argentina ya 1a ROTA fuerte (Messi descansa) -> 1-2, no la goleada del xG'),
 ('Sab 27-jun','Colombia','Portugal','1.6-1.4','2-1','1-2',1,'TU PICK: gana Portugal 2-1. Ambos YA clasificados (define solo el 1o de K) -> LIBRE para tu cuadro: Colombia y Portugal quedan los dos en tus 32. El modelo ve a Colombia leve favorita (43/24/33), pero no afecta nada.'),
 ('Sab 27-jun','Congo','Uzbekistan','1.1-1.1','1-0','1-0',0,'EV-max: Congo por la minima'),
 ('Sab 27-jun','Panama','Inglaterra','0.2-3.2','0-3','0-3',0,'Inglaterra rota parcial pero cuida GD; Panama improbable que marque -> EV-max'),
 ('Sab 27-jun','Croacia','Ghana','2.7-0.3','2-0','1-0',1,'50-50 real: Ghana comoda con empate (mejor GD), Croacia debe ganar -> 1-0'),
]
stakes={
 'Chequia':'Mexico: YA 1o, sin riesgo. Chequia (1pt): solo ganar le sirve y depende de otros (casi out).',
 'Sudafrica':'Corea (3pts): con empate casi sella el 2o. Sudafrica (1pt): debe ganar + ayuda.',
 'Suiza':'NO aplica: ambos YA clasificados. Juegan el 1o del grupo (posicion de cuadro).',
 'Bosnia':'Bosnia (1pt): debe ganar para pelear el mejor-tercero. Catar (-6): eliminado salvo milagro.',
 'Escocia':'Brasil: pelea el 1o con Marruecos (ya clasificado). Escocia (3pts): sumando asegura mejor-tercero.',
 'Marruecos':'Marruecos: pelea el 1o, quiere goles para la diferencia. Haiti: ELIMINADO.',
 'Turquia':'USA: YA 1o. Turquia (0pts): ELIMINADA salvo goleada + ayuda.',
 'Paraguay':'CLAVE: el GANADOR clasifica 2o. Empate -> Australia 2a (mejor DG) y Paraguay a mejor-tercero. El que pierde, depende.',
 'Curazao':'C.Marfil (3pts): con empate asegura el 2o. Curazao (1pt): casi out.',
 'Ecuador':'Alemania: YA 1o. Ecuador (1pt): debe ganarle al lider + ayuda.',
 'Japon':'Japon: pelea el 1o con P.Bajos (ya clasificado). Suecia (3pts): ganar la mete 2a; un punto puede bastarle como mejor-tercero.',
 'Tunez':'P.Bajos: pelea el 1o por diferencia de gol. Tunez: ELIMINADA.',
 'Egipto':'Egipto (4pts): con tu 1-0 gana, llega a 7 pts y sella el 1o de G. Iran (2pts): cae al 3o y queda AFUERA del repechaje de terceros.',
 'N.Zelanda':'Belgica (2pts): DEBE GANAR para clasificar seguro. NZ (1pt): casi out.',
 'Cabo Verde':'Cabo Verde (2pts): con tu 1-0 gana, sube a 5 pts y se mete 2a de H -> clasifica DIRECTO. Saudi (1pt): ELIMINADO.',
 'Uruguay':'Espana: YA 1a (empate sella). Uruguay (2pts): debe ganar para el 2o o depender del mejor-tercero.',
 'Noruega':'NO aplica: ambos YA clasificados (6pts). Juegan el 1o del grupo.',
 'Senegal':'Senegal (0pts): DEBE GANAR para entrar como mejor-tercero. Irak: casi out.',
 'Argelia':'Austria (3pts): con EMPATE clasifica (mejor DG). Argelia (3pts): DEBE GANAR o queda colgada del mejor-tercero.',
 'Jordania':'Argentina: YA 1a. Jordania: ELIMINADA.',
 'Colombia':'NO aplica: ambos YA clasificados. Juegan el 1o del grupo.',
 'Congo':'Congo (1pt): ganar deja un hilo de mejor-tercero. Uzbekistan (-7): ELIMINADO virtual.',
 'Panama':'Inglaterra (4pts): ganar sella el 1o. Panama: ELIMINADA.',
 'Croacia':'CLAVE: el GANADOR es 2o. Empate -> Ghana 2a (mejor DG) y Croacia 3a. Ambos probablemente avanzan (uno como mejor-tercero).',
}
elowarn=set()  # ya no hay picks que contradigan al favorito del Elo (Turquia y Ecuador ahora van con el favorito)
mh='<div class="mrow" style="background:#21262d;font-weight:700;color:#c9d1d9"><div>Partido</div><div>xG &rarr; EV-max &rarr; FINAL</div><div>Por que (marcador)</div></div>'
last=None
for fe,h,a,xg,ev,fin,flag,rz in matches:
    if fe!=last: mh+='<div class="md">'+fe+'</div>'; last=fe
    adj = (ev!=fin)
    finstyle = 'color:#d29922' if adj else 'color:#56d364'
    elow = h in elowarn
    bord = ' style="border-left:3px solid #f85149"' if elow else (' style="border-left:3px solid #d29922"' if flag else '')
    wbadge = ' <span style="background:#3d1418;color:#f85149;font-size:9px;padding:1px 5px;border-radius:4px;white-space:nowrap">&#9888; CONTRADICE EL ELO</span>' if elow else ''
    chain = '<span style="color:#7d8590">xG '+xg+'</span> &rarr; <span style="color:#7d8590">EV '+ev+'</span> &rarr; <b style="'+finstyle+';font-size:15px">'+fin+'</b>'
    stk=stakes.get(h,'')
    stkc = '#7d8590' if stk.startswith('NO aplica') else '#58a6ff'
    mh+='<div class="mwrap"><div class="mrow"'+bord+'><div class="mt">'+h+' vs '+a+wbadge+'</div><div>'+chain+'</div><div class="mr">'+rz+'</div></div><div class="stk" style="color:'+stkc+'">CLASIFICACION: '+stk+'</div></div>'

# ranking3 AUTO-CALCULADO desde la proyeccion REAL+PROY (rgroups/rb8/rst) -> nunca queda stale
notes3={
 'DR Congo':'Con tu empate 1-1 a Uzbekistan queda en 3 pts (en tu cuadro), GF bajo: afuera del corte.',
 'Ghana':'Ya tiene 4 pts reales (empato Inglaterra + gano Panama).',
 'Bosnia and Herzegovina':'REAL 24-jun goleo 3-1 a Catar -> 4 pts.',
 'Senegal':'Le gana a Irak -> 3 pts, buen DG.',
 'South Korea':'Perdio 0-1 con Sudafrica (REAL) pero ya tenia 3 pts -> 3a de A y entra como mejor tercero.',
 'Sweden':'Pierde 3-1 con Japon (tu pick) pero con GF alto (7) se sostiene.',
 'Paraguay':'REAL: 4 pts (3o de D, grupo ya cerrado). De los 8 grupos cerrados es top-4 de terceros -> CLASIFICADO 100% como mejor tercero (entra pase lo que pase).',
 'Algeria':'En tu proyeccion (Argelia 0-1 Austria) queda 3o de J con 3 pts y toma el ultimo cupo de terceros (8o), por encima de Escocia (9a, peor DG). NO es 100%: el grupo J sigue abierto.',
 'Scotland':'REAL 24-jun perdio 0-3 con Brasil -> 3 pts pero DG bajo: se cae del corte.',
 'Ecuador':'Ya CLASIFICO (le gano 2-1 a Alemania, REAL): 4 pts, 3o de E -> entra.',
 'Iran':'Con tu Egipto 5-1, Iran cae 3o de G y por debajo de Argelia (margen 4+): SALE de tu apuesta. (Apuesta a que Egipto gana.)',
 'Uruguay':'Con tu Cabo Verde 1-0, Uruguay 3o de H con 2 pts: afuera.',
}
_k3=lambda t:(rst[t]['pts'],rst[t]['gf']-rst[t]['gc'],rst[t]['gf'],-fifa_rank.get(t,99))
_thirds_rank=sorted([(g,rgroups[g][2]) for g in rgroups],key=lambda gt:_k3(gt[1]),reverse=True)
ranking3=[]
for _pos,(_g,_t) in enumerate(_thirds_rank,1):
    _s=rst[_t];_dg=_s['gf']-_s['gc']
    _inb8=_t in rb8
    if _inb8: _est,_col='IN','#56d364'
    else: _est,_col='OUT','#f85149'
    # marca 100% (real), mismo criterio que la columna izquierda: clinched -> ya dentro, eliminated -> ya afuera
    if _t in clinched:
        _nm=ES[_t]+' <span title="ya clasificado 100%" style="color:#56d364;font-size:10px">'+CHK+'</span>'
    elif _t in eliminated:
        _nm='<span style="color:#f85149">'+ES[_t]+'</span> <span title="ya eliminado 100%" style="color:#f85149;font-size:10px">'+X+'</span>'
    else:
        _nm=ES[_t]
    _dgs='0' if _dg==0 else '%+d'%_dg
    ranking3.append((_pos,_g,_nm,_s['pts'],_dgs,_s['gf'],_est,_col,notes3.get(_t,'3o de '+_g+'.')))
n_in=sum(1 for r in ranking3 if r[6].startswith('IN'))

# Terceros segun TU ESTIMACION PURA (tu cuadro: groups/b8/st)
_k3m=lambda t:(st[t]['pts'],st[t]['gf']-st[t]['gc'],st[t]['gf'],-fifa_rank.get(t,99))
_mine_thirds=sorted([(g,groups[g][2]) for g in groups],key=lambda gt:_k3m(gt[1]),reverse=True)
mine_rows=[]
for _pos,(_g,_t) in enumerate(_mine_thirds,1):
    _s=st[_t]; _dg=_s['gf']-_s['gc']; _dgs='0' if _dg==0 else '%+d'%_dg
    _est,_col=('IN','#56d364') if _t in b8 else ('OUT','#f85149')
    if _t in clinched:
        _nm=ES[_t]+' <span title="ya clasificado 100%" style="color:#56d364;font-size:10px">'+CHK+'</span>'
    elif _t in eliminated:
        _nm='<span style="color:#f85149">'+ES[_t]+'</span> <span title="ya eliminado 100%" style="color:#f85149;font-size:10px">'+X+'</span>'
    else:
        _nm=ES[_t]
    mine_rows.append((_pos,_nm,_g,_s['pts'],_dgs,_s['gf'],_est,_col))

# Tabla COMBINADA: una sola tabla, cada fila empareja el puesto i de ambos lados -> misma altura
_SEP='border-left:2px solid #30363d;'
_thr='text-align:center'
combo_super=('<tr><td colspan="6" style="color:#d29922;font-weight:700;font-size:13px;padding:2px 6px 6px">TU estimacion (terceros) &mdash; <span style="color:#56d364;font-weight:400;font-size:11px">'+CHK+' ya dentro 100%</span> <span style="color:#f85149;font-weight:400;font-size:11px">&middot; '+X+' ya eliminado 100%</span></td>'
 '<td colspan="7" style="color:#58a6ff;font-weight:700;font-size:13px;padding:2px 6px 6px;'+_SEP+'">REAL + PROYECTADO</td></tr>')
combo_hdr=('<tr style="color:#7d8590;font-size:10px">'
 '<td style="padding:2px 6px">#</td><td>Equipo</td><td style="'+_thr+'">Pts</td><td style="'+_thr+'">DG</td><td style="'+_thr+'">GF</td><td style="'+_thr+'">Estado</td>'
 '<td style="padding:2px 6px;'+_SEP+'">#</td><td>Equipo</td><td style="'+_thr+'">Pts</td><td style="'+_thr+'">DG</td><td style="'+_thr+'">GF</td><td style="'+_thr+'">Estado</td><td>Por que</td></tr>')
combo_rows=''
for i in range(12):
    lp,lt,lg,lpts,ldg,lgf,lest,lcol=mine_rows[i]
    rp,rg,rt,rpts,rdg,rgf,rest,rcol,rz=ranking3[i]
    cut=' style="border-top:2px solid #d29922"' if i==8 else ''
    combo_rows+=('<tr'+cut+'>'
     '<td style="padding:3px 6px;color:#7d8590">%d</td><td style="font-weight:600">%s <span style="color:#7d8590;font-size:10px">G%s</span></td><td style="'+_thr+'">%s</td><td style="'+_thr+'">%s</td><td style="'+_thr+'">%s</td><td style="'+_thr+';color:%s;font-weight:600;font-size:11px">%s</td>'
     '<td style="padding:3px 6px;color:#7d8590;'+_SEP+'">%d</td><td style="font-weight:600">%s <span style="color:#7d8590;font-size:10px">G%s</span></td><td style="'+_thr+'">%s</td><td style="'+_thr+'">%s</td><td style="'+_thr+'">%s</td><td style="'+_thr+';color:%s;font-weight:600;font-size:11px">%s</td><td style="color:#8b949e;font-size:11px;line-height:1.35">%s</td>'
     '</tr>')%(lp,lt,lg,str(lpts),ldg,str(lgf),lcol,lest, rp,rt,rg,str(rpts),rdg,str(rgf),rcol,rest,rz)
combined3_html='<table style="width:100%;border-collapse:collapse;font-size:12px;vertical-align:top">'+combo_super+combo_hdr+combo_rows+'</table>'

def chips(lst,c):
    return ''.join('<span style="background:%s22;border:1px solid %s;color:%s;padding:3px 9px;border-radius:7px;margin:3px;display:inline-block;font-size:13px">%s</span>'%(c,c,c,t) for t in lst)

html='''<!doctype html><html><head><meta charset="utf-8"><title>Estrategia Polla</title><style>
body{background:#0d1117;color:#e6edf3;font:14px -apple-system,Segoe UI,Roboto,sans-serif;max-width:1120px;margin:0 auto;padding:24px}
h1{font-size:22px;margin-bottom:4px} h2{font-size:17px;margin:0 0 10px}
.sub{color:#8b949e;margin-bottom:18px;font-size:13px}
.grid{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}
.card{background:#161b22;border:1px solid #272e3a;border-radius:10px;padding:10px}
.gt{font-weight:700;margin-bottom:6px} table{width:100%%;border-collapse:collapse;font-size:12px}
.an{color:#8b949e;font-size:10.5px;margin-top:6px;line-height:1.4}
.box{background:#161b22;border:1px solid #272e3a;border-radius:10px;padding:16px;margin-top:18px}
.two{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-top:18px}
.md{font-weight:700;color:#58a6ff;margin:14px 0 6px;font-size:14px}
.mrow{display:grid;grid-template-columns:200px 200px 1fr;gap:10px;align-items:center;padding:7px 10px;background:#0d1117;border:1px solid #21262d;border-radius:7px 7px 0 0;font-size:12.5px}
.mt{font-weight:600} .mr{color:#8b949e;font-size:11.5px}
.mwrap{margin-bottom:7px} .stk{font-size:11px;padding:5px 10px 6px 12px;background:#0d1117;border:1px solid #21262d;border-top:0;border-radius:0 0 7px 7px;line-height:1.45}
.cmp{display:grid;grid-template-columns:1fr 1fr;gap:16px}
.cpanel h3{font-size:14px;margin:0 0 2px} .cmp table{width:100%%;border-collapse:collapse;font-size:11.5px}
.gb{margin-bottom:7px} .gbh{font-weight:700;font-size:11.5px;color:#c9d1d9;margin:7px 0 2px;border-bottom:1px solid #21262d;padding-bottom:2px}
.badge{background:#1f2937;border:1px solid #d29922;border-left:4px solid #d29922;border-radius:8px;padding:11px 14px;margin-bottom:14px;font-size:13px;line-height:1.5}
.nav{margin-bottom:14px;font-size:13px}
.nav a{color:#58a6ff;text-decoration:none}
</style></head><body>
<div class="nav"><a href="./index.html">&larr; Volver al panel del Mundial (modelo)</a></div>
<h1>Mi estimacion &mdash; Ultima fecha de grupos</h1>
<div class="badge"><b style="color:#e3b341">Esta pagina es MI estimacion personal</b>, no la salida del modelo. Los marcadores de la ultima fecha estan derivados de <b>mis estimaciones previas</b> (mi cuadro congelado de las dos primeras fechas) mas mi lectura de la ultima jornada. El panel del modelo (probabilistico) esta en el enlace de arriba. Los partidos ya jugados muestran su <b>resultado REAL</b>; los pendientes, mi pronostico. Es una proyeccion, no una certeza.</div>
<div class="sub">Clasificados: tu cuadro acierta <b>%d/32</b> segun el modelo. Tu <b>puntaje real</b> va abajo en &laquo;Mi participacion&raquo; (se recalcula con cada resultado).<br>Columnas por grupo: <b>HOY</b> = reales (2 fechas) &middot; <b>TU</b> = tu cuadro al cierre &middot; <b>REAL+PROY</b> = si se cumplen tus marcadores. El color del NOMBRE = segun el MODELO (mejor estimacion de quien clasifica). <b style="color:#f85149">&#128128; muertos</b> = los das pero el modelo no; <b style="color:#e3b341">&#127922; incierto</b> = tu proyeccion y el modelo no coinciden (si clasifica, +7 igual).</div>
%s
%s
<div class="grid">%s</div>

<div class="two">
<div class="box"><h2 style="color:#56d364">%s Lo que apostas TU (cuadro real)</h2>
<div style="color:#8b949e;font-size:12px;margin-bottom:8px">Tus 32, derivados de tus predicciones</div>
<div><b style="color:#56d364">%d VIVOS (clasifican):</b><br>%s</div>
<div style="margin-top:10px"><b style="color:#f85149">%s %d MUERTOS (no clasifican, %d pts perdidos):</b><br>%s</div></div>

<div class="box"><h2 style="color:#58a6ff">REAL + PROYECTADO</h2>
<div style="color:#8b949e;font-size:12px;margin-bottom:8px">Tus 32 segun los resultados REALES jugados + tus marcadores proyectados para lo que falta (proyeccion determinista, no el modelo)</div>
<div><b style="color:#56d364">Los mismos %d VIVOS</b> + estos %d que tu cuadro congelado NO tiene:<br>%s</div></div>
</div>

<div class="box"><h2>La diferencia (lo que cambia)</h2>
<div style="font-size:14px;line-height:1.8">
En %d coinciden. La diferencia son <b>%d equipos</b>:<br>
&bull; <b style="color:#f85149">Tu cuadro congelado:</b> %s &mdash; van a quedar afuera<br>
&bull; <b style="color:#58a6ff">Real + proyectado:</b> %s &mdash; estos clasifican<br>
<span style="color:#8b949e;font-size:12.5px">Tus %d estan "muertos" porque en las fechas JUGADAS los pronosticaste ganando de mas, y eso quedo congelado en tu cuadro. La columna real+proyectado parte de los resultados REALES.</span>
</div></div>

<div class="box"><h2>Ranking de los 3eros lugares &mdash; tu estimacion vs lo real</h2>
<div style="color:#8b949e;font-size:12px;margin-bottom:10px">12 terceros, solo <b>8 clasifican</b>; la <b style="color:#d29922">linea amarilla</b> marca el corte 8&ordm;/9&ordm;. <b>Izquierda:</b> como irian quedando segun <b style="color:#d29922">TU estimacion pura</b>; <b>Derecha:</b> el escenario <b style="color:#58a6ff">REAL + PROYECTADO</b>. <b style="color:#e3b341">Desempate FIFA 2026</b> (orden oficial): 1) puntos, 2) dif. de gol, 3) goles a favor, 4) <b>juego limpio</b> (tarjetas), 5) <b>Ranking FIFA</b>. <b>FIFA elimino el sorteo en 2026.</b> Como el modelo no trackea tarjetas, los empates exactos los resolvemos por <b>Ranking FIFA</b> (ej.: Argelia 29&ordm; supera a Paraguay 37&ordm; por el ultimo cupo). <span style="font-size:11px">Fuente: reglamento FIFA 2026 (FOX Sports / Yahoo / FIFA.com).</span></div>
%s</div>

<div class="box"><h2>Partidos a pronosticar &mdash; uno por uno (estrategia EV-optimo)</h2>
<div style="color:#8b949e;font-size:12px;margin-bottom:10px">Clasificados ya clavados en %d/32, asi que cada partido se optimiza por <b>marcador</b>. Cadena: <b>xG</b> (modelo) &rarr; <b>EV-max</b> (lo que mas puntua) &rarr; <b>FINAL</b> (con ajuste por rotacion). <span style="color:#56d364">Verde</span> = EV-max directo. <span style="color:#d29922">Amarillo</span> = ajustado porque un equipo ya 1o descansa (Mexico, USA, Alemania, Argentina) o 50-50 (Croacia).</div>
%s</div>
</body></html>'''%(len(live), miparticipacion, compare48, cards, CHK, len(live), chips(live,'#56d364'), SKULL, len(dead), len(dead)*7, chips(dead,'#f85149'), len(live), len(miss), chips(miss,'#58a6ff'), len(live), len(dead), ', '.join(dead), ', '.join(miss), len(dead), combined3_html, len(live), mh)

open(os.path.join(BASE,'ultima-fecha.html'),'w').write(html)  # vista publicada (repo / GitHub Pages)
_dl=os.path.expanduser('~/Downloads')                          # copia local solo si existe la carpeta (Mac)
if os.path.isdir(_dl): open(os.path.join(_dl,'estrategia-polla.html'),'w').write(html)
print('TU apuesta (32) = 28 vivos +', dead)
print('SISTEMA (32)    = 28 vivos +', miss)
print('Coinciden:', len(live), '| Difieren:', len(dead), 'vs', len(miss))
print('HTML guardado en ~/Downloads/estrategia-polla.html')
