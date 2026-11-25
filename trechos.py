"""Trechos avulsos só de ida (ex.: SP → Salvador no Natal), configurados em config.json → "trechos".

Diferente da coleta principal (ida+volta em fins de semana/feriados), aqui cada trecho tem datas fixas e é
buscado em toda execução. Usa o RPC GetShoppingResults do Google Flights com "mostrar tudo" (até ~300
itinerários, com conexões), que a página HTML esconde. Para cada dia guarda:
  normal  = mais barato para o destino (com ou sem conexão)
  direto  = mais barato sem escala
  skiplag = bilhete para outra cidade que faz parada no destino (desce na parada; só bagagem de mão)
"""

import json
import logging
import random
import time
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from html import escape

from primp import Client

import milhas

log = logging.getLogger("monitor")

RPC_URL = ("https://www.google.com/_/FlightsFrontendUi/data/"
           "travel.frontend.flights.FlightsFrontendService/GetShoppingResults")
DIAS = ["seg", "ter", "qua", "qui", "sex", "sáb", "dom"]
MESES = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]
PERIODOS = (("manhã", 5, 12), ("tarde", 12, 18), ("noite", 18, 29))


def _fd(s: str) -> str:
    d = date.fromisoformat(s)
    return f"{DIAS[d.weekday()]} {d.day:02d}/{MESES[d.month - 1]}"


def _brl(v) -> str:
    return "—" if v is None else f"R$ {v:,.0f}".replace(",", ".")


PROGRAMAS = {"smiles": "Smiles", "latam": "LATAM Pass"}
MODOS = ("normal", "direto", "skiplag", "smiles", "latam")


def _val(modo, v) -> str:
    if modo in PROGRAMAS:
        return "—" if v is None else f"{v:,.0f} milhas".replace(",", ".")
    return _brl(v)


def _op_milhas(v, data, url, milheiro=None) -> "OpTrecho":
    """milheiro = quanto custa (para você) cada 1.000 milhas, em R$ — config "valor_milheiro"."""
    partes = []
    if milheiro:
        partes.append(f"≈ {_brl(v['milhas'] / 1000 * milheiro + (v.get('taxas') or 0))} "
                      f"(milheiro R$ {milheiro:g}{' + taxas' if v.get('taxas') else ''})")
    if v.get("reais"):
        partes.append(f"no site: ou {_brl(v['reais'])} em dinheiro")
    elif v.get("taxas") and not milheiro:
        partes.append(f"+ taxas {_brl(v['taxas'])}")
    extra = " · ".join(partes)
    par = v.get("paradas")
    return OpTrecho(data=data, preco=int(v["milhas"]), cia=v.get("cia", ""), de=v.get("de", ""),
                    para=v.get("para", ""), partida=v.get("sai", ""), chegada=v.get("chega", ""),
                    chegada_data=data, paradas=par or 0, voos=extra,
                    rota=f"{v.get('de', '')} → {v.get('para', '')}" +
                    ("" if par is None else " (direto)" if par == 0 else f" ({par} parada{'s' if par > 1 else ''})"),
                    link=url)


def _hm(v) -> str:
    p = [*(v or []), None, None]
    return f"{p[0] or 0:02d}:{p[1] or 0:02d}"


# ======================================================================= busca

class BuscadorRPC:
    def __init__(self, pausa):
        self.pausa = pausa
        self.n_buscas = self.n_falhas = 0
        self.client = Client(impersonate="chrome_145", impersonate_os="macos", referer=True, cookie_store=True)

    def buscar(self, dia: str, origens, destinos) -> list[dict] | None:
        """Todos os itinerários (qualquer nº de paradas) de um dia. None = falhou."""
        seg = [[[[a, 0] for a in origens]], [[[a, 0] for a in destinos]], None, 0, [], None,
               dia, None, None, None, None, None, None, None, 3]
        filtros = [[], [None, None, 2, None, [], 1, [1, 0, 0, 0], None, None, None, None, None, None,
                        [seg], None, None, None, 1], 1, 1, 0, 2]  # 2º valor da cauda = 1 → "mostrar tudo"
        corpo = "f.req=" + _quote(json.dumps([None, json.dumps(filtros, separators=(",", ":"))],
                                             separators=(",", ":")))
        for tent in range(3):
            try:
                self.n_buscas += 1
                r = self.client.post(RPC_URL, params={"hl": "pt-BR", "gl": "BR", "curr": "BRL"},
                                     content=corpo.encode(),
                                     headers={"content-type": "application/x-www-form-urlencoded;charset=UTF-8"})
                bruto = json.loads(r.text.lstrip(")]}'"))[0][2]
                time.sleep(random.uniform(*self.pausa))
                return _ler(bruto) if bruto else []
            except Exception as e:
                log.warning("trecho: falha %s %s->%s (tentativa %d): %s", dia, origens, destinos, tent + 1,
                            repr(e)[:200])
                time.sleep(10 * (tent + 1))
        self.n_falhas += 1
        return None


def _quote(s):
    from urllib.parse import quote
    return quote(s)


def _ler(bruto: str) -> list[dict]:
    p = json.loads(bruto)
    out = []
    for idx in (2, 3):
        bloco = p[idx][0] if len(p) > idx and p[idx] else None
        for k in bloco or []:
            f = k[0]
            try:
                preco = int(k[1][0][-1])
            except Exception:
                continue
            segs = []
            for s in f[2]:
                try:
                    num = f"{s[22][0]} {s[22][1]}"
                except Exception:
                    num = ""
                segs.append({"de": s[3], "para": s[6], "sai": _hm(s[8]), "chega": _hm(s[10]),
                             "dsai": date(*s[20]).isoformat(), "dche": date(*s[21]).isoformat(), "voo": num})
            if segs:
                out.append({"preco": preco, "cias": list(f[1] or []), "segs": segs})
    return out


@dataclass
class OpTrecho:
    data: str          # dia da partida
    preco: int
    cia: str
    de: str
    para: str          # onde você desce (o destino do trecho)
    partida: str
    chegada: str
    chegada_data: str
    paradas: int       # paradas até onde você desce
    voos: str          # números dos voos até onde você desce
    rota: str          # ex.: "GRU → GIG → SSA"
    link: str
    skiplag_ate: str | None = None
    rota_bilhete: str | None = None  # itinerário completo do bilhete (skiplag)


def _op(it, data, n_ate, link, skiplag=False) -> OpTrecho:
    segs = it["segs"]
    usados = segs[:n_ate + 1]
    rota = " → ".join([usados[0]["de"]] + [s["para"] for s in usados])
    return OpTrecho(data=data, preco=it["preco"], cia=", ".join(it["cias"]), de=segs[0]["de"],
                    para=usados[-1]["para"], partida=segs[0]["sai"], chegada=usados[-1]["chega"],
                    chegada_data=usados[-1]["dche"], paradas=len(usados) - 1,
                    voos=", ".join(s["voo"] for s in usados if s["voo"]), rota=rota, link=link,
                    skiplag_ate=segs[-1]["para"] if skiplag else None,
                    rota_bilhete=" → ".join([segs[0]["de"]] + [s["para"] for s in segs]) if skiplag else None)


def _hora(o: OpTrecho) -> int:
    h = int(o.partida[:2])
    return h + 24 if h < 5 else h


def _por_periodo(ops):
    out = []
    for nome, ini, fim in PERIODOS:
        cand = [o for o in ops if ini <= _hora(o) < fim]
        if cand:
            out.append({"periodo": nome, **asdict(min(cand, key=lambda o: o.preco))})
    return out


def dias_do_trecho(t, hoje: date) -> list[tuple[str, int | None]]:
    ini, fim = date.fromisoformat(t["data_inicio"]), date.fromisoformat(t["data_fim"])
    apos = t.get("partida_apos") or {}
    out, d = [], max(ini, hoje)
    while d <= fim:
        out.append((d.isoformat(), apos.get(d.isoformat())))
        d += timedelta(days=1)
    return out


def coletar(cfg, con, ts, link_fn, hoje=None) -> dict:
    """Busca todos os trechos ativos e grava em trechos_hist. link_fn(data, origens, destinos) → URL."""
    hoje = hoje or date.today()
    trechos = [t for t in cfg.get("trechos", []) if t.get("ativo", True)]
    con.execute("""CREATE TABLE IF NOT EXISTS trechos_hist(
        coletado_em TEXT, trecho TEXT, data TEXT, modo TEXT, preco INTEGER, detalhe TEXT)""")
    con.execute("CREATE INDEX IF NOT EXISTS ix_trechos ON trechos_hist(trecho, data, modo, coletado_em)")
    b = BuscadorRPC(tuple(cfg.get("pausa_entre_buscas_seg", [2, 4])))
    resultados = []
    mil = milhas.ultima_coleta()
    urls = {(x["trecho"], x["programa"], x["data"]): x["url"] for x in milhas.buscas(cfg, hoje)}
    mil_nova = bool(mil) and con.execute("SELECT valor FROM meta WHERE chave='milhas_coleta'").fetchone() != (
        mil["coletado_em"],)
    if mil:
        con.execute("INSERT OR REPLACE INTO meta VALUES('milhas_status', ?)", (json.dumps(
            {"coletado_em": mil["coletado_em"], **{k: v.get("status") for k, v in mil.get("programas", {}).items()}},
            ensure_ascii=False),))
    for t in trechos:
        origens, destinos = t["origens"], t["destinos"]
        alvo = set(destinos)
        for dia, apos in dias_do_trecho(t, hoje):
            ok = lambda it: it["segs"][0]["dsai"] == dia and (apos is None or int(it["segs"][0]["sai"][:2]) >= apos)
            itens = b.buscar(dia, origens, destinos)
            if itens is None:
                log.info("trecho %s %s: falha na busca", t["nome"], dia)
                continue
            link = link_fn(date.fromisoformat(dia), origens, destinos, apos)
            normais = [_op(it, dia, len(it["segs"]) - 1, link) for it in itens
                       if ok(it) and it["segs"][-1]["para"] in alvo]
            skip = []
            for grupo in t.get("skiplag_alem", []):
                for dest in grupo:
                    its = b.buscar(dia, origens, [dest])
                    lk = link_fn(date.fromisoformat(dia), origens, [dest], apos)
                    for it in its or []:
                        if not ok(it):
                            continue
                        for i, s in enumerate(it["segs"][:-1]):
                            if s["para"] in alvo:
                                skip.append(_op(it, dia, i, lk, skiplag=True))
                                break
            if not normais and not skip:
                log.info("trecho %s %s: sem voos", t["nome"], dia)
                continue
            res = {"trecho": t, "data": dia, "partida_apos": apos, "periodos": _por_periodo(normais)}
            if normais:
                res["normal"] = min(normais, key=lambda o: o.preco)
            diretos = [o for o in normais if o.paradas == 0]
            if diretos:
                res["direto"] = min(diretos, key=lambda o: o.preco)
            if skip:
                res["skiplag"] = min(skip, key=lambda o: (o.preco, o.paradas))
                res["skiplags_top"] = sorted(skip, key=lambda o: (o.preco, o.paradas))[:5]
            if mil_nova:
                for prog in t.get("milhas", []):
                    dia_m = ((mil["programas"].get(prog) or {}).get("dias") or {}).get(dia) or {}
                    v = milhas.melhor(dia_m.get("voos"), apos)
                    if v:
                        res[prog] = _op_milhas(v, dia, urls.get((t["nome"], prog, dia), ""),
                                               (cfg.get("valor_milheiro") or {}).get(prog))
            for modo in MODOS:
                if modo in res:
                    det = asdict(res[modo])
                    if modo == "normal":
                        det["periodos"] = res["periodos"]
                    if modo == "skiplag":
                        det["top"] = [asdict(o) for o in res["skiplags_top"]]
                    con.execute("INSERT INTO trechos_hist VALUES(?,?,?,?,?,?)",
                                (ts, t["nome"], dia, modo, res[modo].preco, json.dumps(det, ensure_ascii=False)))
            resultados.append(res)
            n, dr, sk = res.get("normal"), res.get("direto"), res.get("skiplag")
            log.info("trecho %s %s: menor %s%s | direto %s | skiplag %s%s%s", t["nome"], dia,
                     _brl(n and n.preco), f" ({n.rota})" if n else "", _brl(dr and dr.preco),
                     _brl(sk and sk.preco), f" (bilhete até {sk.skiplag_ate}, {sk.rota})" if sk else "",
                     "".join(f" | {PROGRAMAS[p]} {_val(p, res[p].preco)}" for p in PROGRAMAS if p in res))
        con.commit()
    # só o detalhe da coleta mais recente fica guardado
    con.execute("UPDATE trechos_hist SET detalhe=NULL WHERE detalhe IS NOT NULL AND rowid NOT IN "
                "(SELECT MAX(rowid) FROM trechos_hist GROUP BY trecho, data, modo)")
    con.commit()
    if mil_nova:
        con.execute("INSERT OR REPLACE INTO meta VALUES('milhas_coleta', ?)", (mil["coletado_em"],))
        con.commit()
    log.info("trechos: %d buscas, %d falhas; milhas: %s", b.n_buscas, b.n_falhas,
             (f"coleta {mil['coletado_em']}" + ("" if mil_nova else " (já registrada)")) if mil
             else "nenhuma coleta recente")
    return {"resultados": resultados, "buscas": b.n_buscas, "falhas": b.n_falhas}


# ======================================================================= alertas

def _hist(con, ts, trecho, dia, modo):
    return [r[0] for r in con.execute(
        "SELECT preco FROM trechos_hist WHERE trecho=? AND data=? AND modo=? AND coletado_em<? ORDER BY coletado_em",
        (trecho, dia, modo, ts))]


def decidir_alertas(cfg, con, ts, saida):
    a = cfg.get("alertas", {})
    q_pct, q_rs = a.get("queda_min_percentual", 5) / 100, a.get("queda_min_reais", 30)
    obs_min = a.get("observacoes_min_para_recorde", 3)
    alertas, chaves = [], []
    for r in saida["resultados"]:
        t = r["trecho"]
        eco_min = t.get("skiplag_economia_minima_reais", cfg.get("skiplag", {}).get("economia_minima_reais", 60))
        for modo in MODOS:
            if modo not in r:
                continue
            p = r[modo].preco
            hist = _hist(con, ts, t["nome"], r["data"], modo)
            ant = hist[-1] if hist else None
            q_abs = a.get("queda_min_milhas", 2000) if modo in PROGRAMAS else q_rs
            motivos = []
            if ant and ant - p >= max(q_abs, ant * q_pct):
                motivos.append(f"caiu de {_val(modo, ant)} para {_val(modo, p)} (-{(ant - p) / ant:.0%})")
            if len(hist) >= obs_min and p < min(hist):
                motivos.append(f"menor preço já visto (antes {_val(modo, min(hist))})")
            if modo == "skiplag" and "normal" in r and r["normal"].preco - p >= eco_min:
                motivos.append(f"skiplag {_brl(r['normal'].preco - p)} mais barato que o melhor voo normal")
            if not motivos:
                continue
            chave = f"trecho|{t['nome']}|{r['data']}|{modo}"
            ult = con.execute("SELECT preco FROM alertas WHERE chave=?", (chave,)).fetchone()
            if ult and p > ult[0] - q_abs and not (ant and ant > ult[0]):
                continue
            alertas.append({"r": r, "modo": modo, "preco": p, "motivos": motivos})
            chaves.append((chave, p))
    return alertas, chaves


# ======================================================================= e-mail / painel

NOME_MODO = {"normal": "mais barato", "direto": "direto", "skiplag": "skiplag", **PROGRAMAS}


def _op_txt(o) -> str:
    chega = o["chegada"] + (f" ({_fd(o['chegada_data'])})" if o["chegada_data"] != o["data"] else "")
    s = f'{o["rota"]} · sai {o["partida"]}, chega {chega} · {o["cia"]}'
    if o.get("voos"):
        s += f' · {o["voos"]}'
    if o.get("skiplag_ate"):
        s += f' · bilhete até {o["skiplag_ate"]} ({o["rota_bilhete"]}), desça em {o["para"]}'
    return s


def email_html(alertas) -> str:
    if not alertas:
        return ""
    h = ["<h2>🎄 Trechos só de ida</h2>"]
    for a in sorted(alertas, key=lambda a: (a["r"]["trecho"]["nome"], a["r"]["data"], a["modo"])):
        r, o = a["r"], asdict(a["r"][a["modo"]])
        aviso = " (só bagagem de mão!)" if a["modo"] == "skiplag" else ""
        h.append(f"<p><b>{escape(r['trecho']['nome'])} — {_fd(r['data'])} — {NOME_MODO[a['modo']]}{aviso}: "
                 f"{_val(a['modo'], a['preco'])}</b><br><i>{escape('; '.join(a['motivos']))}</i><br>"
                 f'<a href="{escape(o["link"])}">{escape(_op_txt(o))}</a></p>')
    return "".join(h)


def painel_html(con, cfg) -> str:
    hoje = date.today().isoformat()
    try:
        rows = con.execute("SELECT trecho, data, modo, preco, detalhe, coletado_em FROM trechos_hist "
                           "WHERE data >= ? ORDER BY coletado_em", (hoje,)).fetchall()
    except Exception:
        return ""
    if not rows:
        return ""
    serie, ultimo = {}, {}
    for tr, d, m, p, det, ts in rows:
        serie.setdefault((tr, d, m), []).append(p)
        if det:
            ultimo[(tr, d, m)] = json.loads(det)
    secoes = []
    for t in cfg.get("trechos", []):
        dias = sorted({d for (tr, d, m) in serie if tr == t["nome"]})
        if not dias:
            continue
        linhas = []
        for d in dias:
            cel = []
            for m in ("normal", "direto", "skiplag", *t.get("milhas", [])):
                hist = serie.get((t["nome"], d, m)) or []
                o = ultimo.get((t["nome"], d, m))
                if not hist or not o:
                    cel.append('<td class="num">—</td>')
                    continue
                ant = hist[-2] if len(hist) >= 2 else None
                dl = "" if ant in (None, hist[-1]) else (
                    f' <span class="{"down" if hist[-1] < ant else "up"}">{"▼" if hist[-1] < ant else "▲"}'
                    f'{_val(m, abs(hist[-1] - ant))}</span>')
                cel.append(f'<td class="num"><a href="{escape(o["link"])}" target="_blank" rel="noopener">'
                           f'<b>{_val(m, hist[-1])}</b></a>{dl}<div class="muted">mín. {_val(m, min(hist))}'
                           f'{"<br>" + escape(o["partida"]) + " " + escape(o["rota"]) + " " + escape(o["voos"]) if m in PROGRAMAS else ""}'
                           f'</div></td>')
            n = ultimo.get((t["nome"], d, "normal"))
            sk = ultimo.get((t["nome"], d, "skiplag"))
            per = "".join(f'<li><a href="{escape(p["link"])}" target="_blank" rel="noopener">{p["periodo"]} '
                          f'{p["partida"]}</a> <span class="muted">{escape(p["rota"])} · {escape(p["cia"])} · '
                          f'{_brl(p["preco"])}</span></li>' for p in (n or {}).get("periodos", []))
            sk_txt = ""
            if sk:
                tops = "".join(f'<li>{_brl(x["preco"])} <span class="muted">{escape(_op_txt(x))}</span></li>'
                               for x in sk.get("top", [sk]))
                sk_txt = f'<ul class="periodos">{tops}</ul>'
            apos = (t.get("partida_apos") or {}).get(d)
            linhas.append(f'<tr><td><b>{_fd(d)}</b>{f"<div class=muted>após {apos}h</div>" if apos else ""}</td>'
                          f'{"".join(cel)}<td><ul class="periodos">{per}</ul></td><td>{sk_txt}</td></tr>')
        secoes.append(
            f'<section><h2>🎄 {escape(t["nome"])} <span class="muted">(só ida)</span></h2>'
            f'<p class="muted">{" / ".join(t["origens"])} → {" / ".join(t["destinos"])}. "Mais barato" inclui '
            f'conexões. "Skiplag" = bilhete para outra cidade com parada em {"/".join(t["destinos"])}: você '
            f'desce na parada (só bagagem de mão, e não dá para comprar ida+volta assim). Clique no preço para '
            f'abrir no Google Flights.{_status_milhas(con, t)}</p>'
            f'<div class="tw"><table><thead><tr><th>Dia</th><th class="num">Mais barato</th>'
            f'<th class="num">Direto</th><th class="num">Skiplag</th>'
            f'{"".join(f"<th class=num>{PROGRAMAS[p]}</th>" for p in t.get("milhas", []))}<th>Por período</th>'
            f'<th>Melhores skiplags</th></tr></thead><tbody>{"".join(linhas)}</tbody></table></div></section>')
    return "".join(secoes)


def _status_milhas(con, t) -> str:
    if not t.get("milhas"):
        return ""
    r = con.execute("SELECT valor FROM meta WHERE chave='milhas_status'").fetchone()
    if not r:
        return " Milhas: ainda sem coleta."
    st = json.loads(r[0])
    c = st["coletado_em"]
    partes = [f"{PROGRAMAS[p]}: {st.get(p) or 'sem dados'}" for p in t["milhas"]]
    return f" Milhas (coleta pelo Chrome em {c[8:10]}/{c[5:7]} {c[11:16]}): {'; '.join(partes)}."
