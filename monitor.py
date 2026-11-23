"""
Monitor de voos SP <-> destinos favoritos (fins de semana, feriados e emendas, 1 ano à frente).

Fonte: Google Flights (consulta direta, várias combinações de aeroportos por busca).
Uso:
    python monitor.py               # decide sozinho: coleta completa (1 ano) 1x/dia, senão só próximos 120 dias
    python monitor.py --completo    # força coleta do ano inteiro
    python monitor.py --sem-email   # não envia e-mail (gera painel normalmente)
    python monitor.py --teste       # só as 2 próximas janelas
"""

import argparse
import base64
import json
import logging
import os
import random
import smtplib
import sqlite3
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from email.mime.text import MIMEText
from html import escape
from pathlib import Path
from urllib.parse import quote

from fast_flights.exceptions import FlightsNotFound
from fast_flights.parser import parse, parse_js
from selectolax.lexbor import LexborHTMLParser
from fast_flights.pb.flights_pb2 import Airport, FlightData, Info, Passenger, Seat, Trip
from primp import Client

import painel

BASE = Path(__file__).resolve().parent
DB_PATH = BASE / "historico.db"
GF_URL = "https://www.google.com/travel/flights"
DIAS_SEMANA = ["seg", "ter", "qua", "qui", "sex", "sáb", "dom"]
MESES = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]

log = logging.getLogger("monitor")


def fmt_data(d: date) -> str:
    return f"{DIAS_SEMANA[d.weekday()]} {d.day:02d}/{MESES[d.month - 1]}"


# ======================================================================= feriados / janelas

def pascoa(ano: int) -> date:
    a, b, c = ano % 19, ano // 100, ano % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    return date(ano, (h + l - 7 * m + 114) // 31, (h + l - 7 * m + 114) % 31 + 1)


def feriados(ano: int) -> dict[date, str]:
    p = pascoa(ano)
    return {
        date(ano, 1, 1): "Ano Novo",
        date(ano, 1, 25): "Aniversário de SP",
        p - timedelta(days=48): "Carnaval",
        p - timedelta(days=47): "Carnaval",
        p - timedelta(days=2): "Sexta-feira Santa",
        date(ano, 4, 21): "Tiradentes",
        date(ano, 5, 1): "Dia do Trabalho",
        p + timedelta(days=60): "Corpus Christi",
        date(ano, 7, 9): "Revolução Constitucionalista",
        date(ano, 9, 7): "Independência",
        date(ano, 10, 12): "N. Sra. Aparecida",
        date(ano, 11, 2): "Finados",
        date(ano, 11, 15): "Proclamação da República",
        date(ano, 11, 20): "Consciência Negra",
        date(ano, 12, 25): "Natal",
    }


@dataclass
class Ida:
    data: date
    partida_apos: int | None  # hora mínima de partida (dia útil)


@dataclass
class Volta:
    data: date
    chegada_ate: dict | None  # {"CGH": "08:00", ...} quando é manhã de dia útil


@dataclass
class Janela:
    inicio: date
    fim: date
    nome: str
    idas: list[Ida] = field(default_factory=list)
    voltas: list[Volta] = field(default_factory=list)

    @property
    def id(self) -> str:
        return f"{self.inicio.isoformat()}_{self.fim.isoformat()}"

    @property
    def curto(self) -> bool:
        return (self.fim - self.inicio).days <= 1  # só sáb+dom (inclui feriado que cai no fds)

    @property
    def rotulo(self) -> str:
        return f"{self.nome} ({fmt_data(self.inicio)} a {fmt_data(self.fim)})"


def gerar_janelas(hoje: date, horizonte: int, cfg: dict) -> list[Janela]:
    fim = hoje + timedelta(days=horizonte)
    fer: dict[date, str] = {}
    for ano in range(hoje.year, fim.year + 2):
        fer.update(feriados(ano))
    for s in cfg.get("feriados_extras", []):
        fer[date.fromisoformat(s)] = "Folga extra"
    for s in cfg.get("feriados_ignorar", []):
        fer.pop(date.fromisoformat(s), None)

    livres: dict[date, str] = {}
    d = hoje - timedelta(days=3)
    while d <= fim + timedelta(days=7):
        if d.weekday() >= 5:
            livres[d] = ""
        if d in fer:
            livres[d] = fer[d]
        d += timedelta(days=1)
    if cfg.get("incluir_emendas", True):
        for d, nome in fer.items():
            if d.weekday() == 1:
                livres.setdefault(d - timedelta(days=1), f"emenda {nome}")
            elif d.weekday() == 3:
                livres.setdefault(d + timedelta(days=1), f"emenda {nome}")

    grupos: list[list[date]] = []
    for d in sorted(livres):
        if grupos and d - grupos[-1][-1] == timedelta(days=1):
            grupos[-1].append(d)
        else:
            grupos.append([d])

    hora_ida = cfg.get("ida_em_dia_util_partida_apos")
    limites_volta = cfg.get("volta_dia_util_chegada_ate") or None
    janelas = []
    for g in grupos:
        if len(g) < 2 or g[0] > fim:
            continue
        nomes = []
        for d in g:
            n = livres[d]
            if n and not n.startswith("emenda") and n not in nomes:
                nomes.append(n)
        j = Janela(g[0], g[-1], " + ".join(nomes) if nomes else "Fim de semana")
        idas = [Ida(g[0] - timedelta(days=1), hora_ida), Ida(g[0], None)]
        voltas = [Volta(g[-1], None)]
        if len(g) >= 3:
            voltas.append(Volta(g[-2], None))
        if limites_volta:
            voltas.append(Volta(g[-1] + timedelta(days=1), limites_volta))
        j.idas = [x for x in idas if x.data >= hoje]
        j.voltas = [x for x in voltas if x.data >= hoje]
        if j.idas and j.voltas and g[-1] >= hoje:
            janelas.append(j)
    return janelas


# ======================================================================= busca

def _varint(n: int) -> bytes:
    out = b""
    while True:
        b, n = n & 0x7F, n >> 7
        if n:
            out += bytes([b | 0x80])
        else:
            return out + bytes([b])


def montar_tfs(data: date, origens, destinos, max_paradas, partida_apos) -> str:
    """Monta o parâmetro tfs do Google Flights aceitando vários aeroportos de cada lado."""
    fb = FlightData(date=data.isoformat(), max_stops=max_paradas,
                    earliest_departure_hour=partida_apos).SerializeToString()
    for a in origens:
        fb += FlightData(from_airport=Airport(airport=a)).SerializeToString()
    for a in destinos:
        fb += FlightData(to_airport=Airport(airport=a)).SerializeToString()
    info = Info(seat=Seat.ECONOMY, trip=Trip.ONE_WAY, passengers=[Passenger.ADULT]).SerializeToString()
    num = Info.DESCRIPTOR.fields_by_name["data"].number
    info += _varint((num << 3) | 2) + _varint(len(fb)) + fb
    return base64.b64encode(info).decode()


def parse_tudo(html: str):
    """O parser do fast-flights só lê o bloco "outros voos" (payload[3]); os "melhores voos"
    (payload[2]) ficavam de fora e costumam ser justamente os mais baratos. Aqui juntamos os dois."""
    js = LexborHTMLParser(html).css_first(r"script.ds\:1").text()
    data = js.split("data:", 1)[1].rsplit(",", 1)[0]
    if data.endswith("errorHasStatus: true"):
        raise FlightsNotFound("no flights found; received error")
    p = json.loads(data)
    melhores = (p[2][0] if p[2] else None) or []
    if melhores:
        outros = (p[3][0] if p[3] else None) or []
        p[3] = [melhores + outros, *(p[3][1:] if p[3] else [])]
    return parse_js("data:" + json.dumps(p) + ",x")


class Buscador:
    def __init__(self, pausa):
        self.pausa = pausa
        self.cache: dict = {}
        self.n_buscas = 0
        self.n_falhas = 0
        self.client = Client(impersonate="chrome_145", impersonate_os="macos",
                             referer=True, cookie_store=True)

    def buscar(self, data, origens, destinos, max_paradas, partida_apos=None):
        chave = (data, tuple(origens), tuple(destinos), max_paradas, partida_apos)
        if chave in self.cache:
            return self.cache[chave]
        tfs = montar_tfs(data, origens, destinos, max_paradas, partida_apos)
        link = f"{GF_URL}/search?tfs={quote(tfs)}&hl=pt-BR&curr=BRL"
        voos = []
        for tentativa in range(3):
            try:
                self.n_buscas += 1
                html = self.client.get(GF_URL, params={"tfs": tfs, "hl": "pt-BR", "curr": "BRL"}).text
                voos = list(parse_tudo(html))
                break
            except FlightsNotFound:
                break
            except Exception as e:
                log.warning("falha %s %s->%s (tentativa %d): %s", data, origens, destinos, tentativa + 1, e)
                time.sleep(10 * (tentativa + 1))
        else:
            self.n_falhas += 1
        time.sleep(random.uniform(*self.pausa))
        self.cache[chave] = (voos, link)
        return voos, link


@dataclass
class Opcao:
    data: str
    de: str
    para: str
    preco: int
    cia: str
    partida: str
    chegada: str
    paradas: int
    link: str
    skiplag_ate: str | None = None

    def descr(self) -> str:
        d = date.fromisoformat(self.data)
        s = f"{fmt_data(d)} {self.de}→{self.para} {self.partida}-{self.chegada} {self.cia}"
        if self.paradas:
            s += f" ({self.paradas} parada)"
        if self.skiplag_ate:
            s += f" [SKIPLAG: bilhete até {self.skiplag_ate}, desça em {self.para}]"
        return s


def _hhmm(t) -> str:
    return f"{t[0]:02d}:{t[1]:02d}"


def _min(s: str) -> int:
    h, m = s.split(":")
    return int(h) * 60 + int(m)


def _partida_ok(f, apos) -> bool:
    return apos is None or f.flights[0].departure.time[0] >= apos


def _chegada_ok(f, idx, data: date, limites) -> bool:
    if not limites:
        return True
    seg = f.flights[idx]
    lim = limites.get(seg.to_airport.code)
    if lim is None:
        return False
    if date(*seg.arrival.date) != data:
        return False
    return seg.arrival.time[0] * 60 + seg.arrival.time[1] <= _min(lim)


def _opcao(f, data: date, link, idx=None) -> Opcao:
    segs = f.flights
    ult = segs[idx] if idx is not None else segs[-1]
    return Opcao(data=data.isoformat(), de=segs[0].from_airport.code, para=ult.to_airport.code,
                 preco=int(f.price), cia=", ".join(f.airlines), partida=_hhmm(segs[0].departure.time),
                 chegada=_hhmm(ult.arrival.time),
                 paradas=idx if idx is not None else len(segs) - 1, link=link,
                 skiplag_ate=segs[-1].to_airport.code if idx is not None else None)


def opcoes_normais(b, data, origens, destinos, max_paradas, partida_apos, limites):
    voos, link = b.buscar(data, origens, destinos, max_paradas, partida_apos)
    return [_opcao(f, data, link) for f in voos
            if f.price and _partida_ok(f, partida_apos)
            and _chegada_ok(f, len(f.flights) - 1, data, limites)]


def opcoes_skiplag(b, data, origens, alem, desembarques, partida_apos, limites):
    voos, link = b.buscar(data, origens, alem, 1, partida_apos)
    out = []
    for f in voos:
        if not f.price or f.type == "multi" or len(f.flights) < 2 or not _partida_ok(f, partida_apos):
            continue
        for i, s in enumerate(f.flights[:-1]):
            if s.to_airport.code in desembarques:
                if _chegada_ok(f, i, data, limites):
                    out.append(_opcao(f, data, link, i))
                break
    return out


PERIODOS = (("manhã", 5, 12), ("tarde", 12, 18), ("noite", 18, 29))  # noite inclui madrugada (até 04:59)


def por_periodo(ops, data: str) -> list[dict]:
    """Voo mais barato de cada período (manhã/tarde/noite) num dia: no máximo 3 opções."""
    def hora(o):
        h = int(o.partida[:2])
        return h + 24 if h < 5 else h
    out = []
    for nome, ini, fim in PERIODOS:
        cand = [o for o in ops if o.data == data and ini <= hora(o) < fim]
        if cand:
            out.append({"periodo": nome, **asdict(min(cand, key=lambda o: o.preco))})
    return out


def datas_viagem(ida, volta) -> str:
    """Datas reais dos voos escolhidos, ex.: 'sex 22/01 → dom 24/01 (2 noites)'."""
    di, dv = date.fromisoformat(ida.data), date.fromisoformat(volta.data)
    n = (dv - di).days
    return f"{fmt_data(di)} → {fmt_data(dv)} ({n} noite{'s' if n != 1 else ''})"


def melhor_par(idas, voltas, min_noites):
    """Par ida+volta mais barato com pelo menos min_noites entre as datas (evita bate-volta e ida num dia/volta no seguinte)."""
    melhor = None
    for i in idas:
        for v in voltas:
            if (date.fromisoformat(v.data) - date.fromisoformat(i.data)).days < min_noites:
                continue
            if melhor is None or i.preco + v.preco < melhor[0].preco + melhor[1].preco:
                melhor = (i, v)
    return melhor


# ======================================================================= banco

def abrir_db() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH)
    con.executescript("""
    CREATE TABLE IF NOT EXISTS totais(
        coletado_em TEXT, janela TEXT, inicio TEXT, fim TEXT, rotulo TEXT, curto INTEGER,
        cidade TEXT, modo TEXT, total INTEGER, detalhe TEXT);
    CREATE INDEX IF NOT EXISTS ix_totais ON totais(janela, cidade, modo, coletado_em);
    CREATE TABLE IF NOT EXISTS alertas(chave TEXT PRIMARY KEY, preco INTEGER, enviado_em TEXT);
    CREATE TABLE IF NOT EXISTS meta(chave TEXT PRIMARY KEY, valor TEXT);
    """)
    return con


def meta_get(con, k):
    r = con.execute("SELECT valor FROM meta WHERE chave=?", (k,)).fetchone()
    return r[0] if r else None


def meta_set(con, k, v):
    con.execute("INSERT OR REPLACE INTO meta VALUES(?,?)", (k, v))


def historico(con, ts, janela, cidade, modo) -> list[int]:
    return [r[0] for r in con.execute(
        "SELECT total FROM totais WHERE janela=? AND cidade=? AND modo=? AND coletado_em<? "
        "ORDER BY coletado_em", (janela, cidade, modo, ts))]


# ======================================================================= coleta

def coletar(cfg, janelas, con, ts) -> dict:
    b = Buscador(tuple(cfg.get("pausa_entre_buscas_seg", [2, 4])))
    destinos = cfg["destinos"]
    cidade_de = {a: c for c, dc in destinos.items() for a in dc["aeroportos"]}
    todos_dest = list(cidade_de)
    origens, retornos = cfg["origens_sp"], cfg["retornos_sp"]
    maxp = cfg.get("max_paradas_voo_normal", 0)
    sk = cfg.get("skiplag", {})
    sk_on = sk.get("ativo", False)
    eco_min = sk.get("economia_minima_reais", 60)
    min_noites = cfg.get("min_noites", 2)

    resultados, skiplags = [], []
    for n, j in enumerate(janelas, 1):
        idas = {c: [] for c in destinos}
        voltas = {c: [] for c in destinos}
        for ida in j.idas:
            for c, dc in destinos.items():
                idas[c] += opcoes_normais(b, ida.data, origens, dc["aeroportos"], maxp, ida.partida_apos, None)
            if sk_on:
                for grupo in sk.get("grupos_alem_do_destino", []):
                    for op in opcoes_skiplag(b, ida.data, origens, grupo, set(todos_dest), ida.partida_apos, None):
                        idas[cidade_de[op.para]].append(op)
        for volta in j.voltas:
            for c, dc in destinos.items():
                voltas[c] += opcoes_normais(b, volta.data, dc["aeroportos"], retornos, maxp, None, volta.chegada_ate)
            if sk_on:
                for grupo in sk.get("grupos_alem_de_sp", []):
                    for op in opcoes_skiplag(b, volta.data, todos_dest, grupo, set(retornos), None, volta.chegada_ate):
                        voltas[cidade_de[op.de]].append(op)

        for c in destinos:
            ni = [o for o in idas[c] if not o.skiplag_ate]
            nv = [o for o in voltas[c] if not o.skiplag_ate]
            if not ni or not nv:
                log.info("[%d/%d] %s / %s: sem voos", n, len(janelas), j.rotulo, c)
                continue
            par_n = melhor_par(ni, nv, min_noites)
            if not par_n:
                log.info("[%d/%d] %s / %s: sem par ida+volta com %d+ noites", n, len(janelas), j.rotulo, c, min_noites)
                continue
            bi, bv = par_n
            res = {"janela": j, "cidade": c, "normal": {"ida": bi, "volta": bv, "total": bi.preco + bv.preco},
                   "periodos": {"ida": por_periodo(ni, bi.data), "volta": por_periodo(nv, bv.data)}}
            si, sv = melhor_par(idas[c], voltas[c], min_noites)
            if si.preco + sv.preco <= res["normal"]["total"] - eco_min:
                res["skiplag"] = {"ida": si, "volta": sv, "total": si.preco + sv.preco}
            for lista, normais in ((idas[c], ni), (voltas[c], nv)):
                for o in lista:
                    if o.skiplag_ate:
                        ref = min((x.preco for x in normais if x.data == o.data), default=None)
                        if ref and ref - o.preco >= eco_min:
                            skiplags.append({"op": o, "ref": ref, "cidade": c, "janela": j})
            for modo in ("normal", "skiplag"):
                if modo in res:
                    r = res[modo]
                    d = {"ida": asdict(r["ida"]), "volta": asdict(r["volta"])}
                    if modo == "normal":
                        d["periodos"] = res["periodos"]
                    det = json.dumps(d, ensure_ascii=False)
                    con.execute("INSERT INTO totais VALUES(?,?,?,?,?,?,?,?,?,?)",
                                (ts, j.id, j.inicio.isoformat(), j.fim.isoformat(), j.rotulo,
                                 int(j.curto), c, modo, r["total"], det))
            resultados.append(res)
            log.info("[%d/%d] %s / %s: R$ %d — voo %s%s", n, len(janelas), j.rotulo, c, res["normal"]["total"],
                     datas_viagem(bi, bv),
                     f" (skiplag R$ {res['skiplag']['total']}: {datas_viagem(si, sv)})" if "skiplag" in res else "")
        con.commit()
    log.info("buscas: %d, falhas: %d", b.n_buscas, b.n_falhas)
    return {"resultados": resultados, "skiplags": skiplags, "buscas": b.n_buscas, "falhas": b.n_falhas}


# ======================================================================= alertas

def decidir_alertas(cfg, con, ts, saida):
    a = cfg.get("alertas", {})
    q_pct = a.get("queda_min_percentual", 5) / 100
    q_rs = a.get("queda_min_reais", 30)
    obs_min = a.get("observacoes_min_para_recorde", 3)
    teto = cfg.get("teto_fim_de_semana_curto")
    alertas, chaves = [], []

    for r in saida["resultados"]:
        j = r["janela"]
        for modo in ("normal", "skiplag"):
            if modo not in r:
                continue
            tot = r[modo]["total"]
            hist = historico(con, ts, j.id, r["cidade"], modo)
            ant = hist[-1] if hist else None
            motivos = []
            if ant and ant - tot >= max(q_rs, ant * q_pct):
                motivos.append(f"caiu de R$ {ant} para R$ {tot} (-{(ant - tot) / ant:.0%})")
            if len(hist) >= obs_min and tot < min(hist):
                motivos.append(f"menor preço já visto (antes R$ {min(hist)})")
            if teto and j.curto and tot <= teto and (ant is None or ant > teto):
                motivos.append(f"abaixo do seu teto de R$ {teto}")
            if not motivos:
                continue
            chave = f"{j.id}|{r['cidade']}|{modo}"
            ult = con.execute("SELECT preco FROM alertas WHERE chave=?", (chave,)).fetchone()
            if ult and tot > ult[0] - q_rs and not (ant and ant > ult[0]):
                continue  # já avisado por preço igual/menor e não houve alta no meio
            alertas.append({"r": r, "modo": modo, "tot": tot, "motivos": motivos})
            chaves.append((chave, tot))

    sk_novos = []
    for s in saida["skiplags"]:
        o = s["op"]
        chave = f"skip|{o.data}|{o.de}|{o.para}|{o.skiplag_ate}|{o.partida}"
        ult = con.execute("SELECT preco FROM alertas WHERE chave=?", (chave,)).fetchone()
        if (ult and o.preco > ult[0] - q_rs) or any(c == chave for c, _ in chaves):
            continue
        sk_novos.append(s)
        chaves.append((chave, o.preco))
    return alertas, sk_novos, chaves


# ======================================================================= e-mail

def _linha(o: Opcao) -> str:
    return f'<a href="{escape(o.link)}">{escape(o.descr())}</a> — <b>R$ {o.preco}</b>'


def _periodos_html(r) -> str:
    """Linha compacta com o mais barato de manhã/tarde/noite no dia da ida e no da volta."""
    p = r.get("periodos") or {}
    out = []
    for lado, nome in (("ida", "Opções na ida"), ("volta", "Opções na volta")):
        ops = p.get(lado) or []
        if ops:
            itens = " · ".join(f'<a href="{escape(o["link"])}">{o["periodo"]} {o["partida"]} {escape(o["cia"])} '
                               f'R$ {o["preco"]}</a>' for o in ops)
            out.append(f"<br><span style='color:#555;font-size:13px'>{nome}: {itens}</span>")
    return "".join(out)


def montar_email(cfg, saida, alertas, sk_novos, ts) -> str:
    h = ['<div style="font-family:Arial,sans-serif;font-size:14px;color:#222;max-width:760px">']
    link = cfg.get("link_painel")
    if link:
        h.append(f'<p><a href="{escape(link)}">📊 Abrir painel completo</a></p>')
    if alertas:
        h.append("<h2>🔔 Mudanças de preço</h2>")
        for a in sorted(alertas, key=lambda a: a["r"]["janela"].inicio):
            r, par = a["r"], a["r"][a["modo"]]
            tag = " · usando skiplag" if a["modo"] == "skiplag" else ""
            h.append(f"<p><b>{escape(r['cidade'])} — {escape(datas_viagem(par['ida'], par['volta']))}{tag}: "
                     f"R$ {a['tot']} ida+volta</b><br><span style='color:#666'>{escape(r['janela'].rotulo)}</span>"
                     f"<br><i>{escape('; '.join(a['motivos']))}</i>"
                     f"<br>Ida: {_linha(par['ida'])}<br>Volta: {_linha(par['volta'])}"
                     f"{_periodos_html(r)}</p>")
    if sk_novos:
        h.append("<h2>🧳 Oportunidades de skiplag (só bagagem de mão!)</h2>")
        for s in sorted(sk_novos, key=lambda s: s["ref"] - s["op"].preco, reverse=True)[:15]:
            h.append(f"<p>{_linha(s['op'])} — economiza R$ {s['ref'] - s['op'].preco} "
                     f"vs. melhor voo normal do dia (R$ {s['ref']})</p>")
    h.append(f"<p style='color:#888;font-size:11px'>Coleta {ts} · {saida['buscas']} buscas, "
             f"{saida['falhas']} falhas · Google Flights, 1 adulto, trechos só de ida, sem bagagem "
             "despachada. Confira o preço no site antes de comprar.</p></div>")
    return "".join(h)


def carregar_credenciais() -> dict | None:
    """GitHub Actions: variáveis de ambiente (Secrets). Local: credenciais.json."""
    limpar = lambda v: (v or "").replace("﻿", "").strip()  # BOM/espaços colados por engano
    if os.environ.get("GMAIL_SENHA_APP"):
        cred = {"gmail_remetente": os.environ["GMAIL_REMETENTE"],
                "senha_de_app": os.environ["GMAIL_SENHA_APP"],
                "destinatario": os.environ["EMAIL_DESTINO"]}
    else:
        p = BASE / "credenciais.json"
        if not p.exists():
            return None
        cred = json.loads(p.read_text(encoding="utf-8-sig"))
    cred = {k: limpar(v) if isinstance(v, str) else v for k, v in cred.items()}
    return cred if cred.get("senha_de_app") else None


def publicar_github(cfg, ts):
    """Coleta local → publica o painel (branch "painel", servida pelo GitHub Pages) e faz backup do
    histórico (branch "dados"). Falha aqui só gera aviso: não atrapalha a coleta nem o e-mail."""
    import shutil, subprocess, tempfile
    pub = cfg.get("publicar_github") or {}
    if not pub.get("ativo") or os.environ.get("GITHUB_ACTIONS"):
        return
    git = shutil.which("git") or r"C:\Program Files\Git\cmd\git.exe"
    url = f"https://github.com/{pub['repo']}.git"
    envios = {"painel": {"index.html": BASE / "painel.html", ".nojekyll": None},
              "dados": {"historico.db": DB_PATH}}
    for branch, arquivos in envios.items():
        try:
            with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
                for nome, src in arquivos.items():
                    if src:
                        shutil.copy(src, Path(d) / nome)
                    else:
                        (Path(d) / nome).write_text("")
                for args in (["init", "-q", "-b", branch], ["add", "-A"],
                             ["-c", f"user.name={pub.get('nome', 'monitor-bot')}",
                              "-c", f"user.email={pub['email']}", "commit", "-q", "-m", f"{branch} {ts}"],
                             ["push", "-q", "--force", url, branch]):
                    subprocess.run([git, *args], cwd=d, check=True, capture_output=True, text=True, timeout=300)
            log.info("GitHub: branch %s publicada", branch)
        except Exception as e:
            err = getattr(e, "stderr", "") or e
            log.warning("GitHub: falha ao publicar %s: %s", branch, str(err).strip()[:300])


def podar_db(con):
    """Mantém o detalhe (links/horários) só da coleta mais recente de cada janela; o resto fica só o preço."""
    con.execute("UPDATE totais SET detalhe=NULL WHERE detalhe IS NOT NULL AND rowid NOT IN "
                "(SELECT MAX(rowid) FROM totais GROUP BY janela, cidade, modo)")
    con.commit()
    con.execute("VACUUM")


def enviar_email(cred, assunto, html):
    msg = MIMEText(html, "html", "utf-8")
    msg["Subject"], msg["From"], msg["To"] = assunto, cred["gmail_remetente"], cred["destinatario"]
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
        s.login(cred["gmail_remetente"], cred["senha_de_app"].replace(" ", ""))
        s.send_message(msg)


# ======================================================================= main

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sem-email", action="store_true")
    ap.add_argument("--teste", action="store_true")
    ap.add_argument("--completo", action="store_true")
    ap.add_argument("--testar-email", action="store_true")
    args = ap.parse_args()

    if args.testar_email:
        cred = carregar_credenciais()
        if not cred:
            print("❌ Senha de app vazia em credenciais.json")
            return
        try:
            enviar_email(cred, "✈️ Teste do monitor de voos",
                         "<p>Se você recebeu isto, o e-mail do monitor está funcionando. 🎉</p>")
            print(f"✅ E-mail de teste enviado para {cred['destinatario']}")
        except smtplib.SMTPAuthenticationError:
            print("❌ O Gmail recusou o login: confira o e-mail remetente e a senha de app (16 letras).")
        return

    sys.stdout.reconfigure(encoding="utf-8")
    log.setLevel(logging.INFO)
    logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.StreamHandler(sys.stdout),
                                  logging.FileHandler(BASE / "monitor.log", encoding="utf-8")])

    cfg = json.loads((BASE / "config.json").read_text(encoding="utf-8"))
    con = abrir_db()
    agora = datetime.now()
    ts = agora.isoformat(timespec="seconds")

    ult = meta_get(con, "ultima_completa")
    completo = args.completo or ult is None or agora - datetime.fromisoformat(ult) > timedelta(hours=20)
    # só busca viagens a partir de data_inicio_busca; os horizontes contam a partir dessa data
    hoje = date.today()
    base = max(hoje, date.fromisoformat(cfg.get("data_inicio_busca") or hoje.isoformat()))
    horizonte = cfg["horizonte_dias"] if completo else cfg["horizonte_prioritario_dias"]  # contados a partir de base
    janelas = gerar_janelas(base, horizonte, cfg)
    if args.teste:
        janelas, completo = janelas[:2], False
    log.info("coleta %s: %d janelas até %s", "COMPLETA" if completo else "prioritária",
             len(janelas), janelas[-1].fim if janelas else "-")

    saida = coletar(cfg, janelas, con, ts)
    if completo and saida["resultados"]:
        meta_set(con, "ultima_completa", ts)
        con.commit()

    podar_db(con)
    if os.environ.get("PAINEL_URL"):
        cfg["link_painel"] = os.environ["PAINEL_URL"]
    painel.gerar(con, cfg, BASE / "painel.html")
    log.info("painel atualizado: %s", BASE / "painel.html")
    if not args.teste:
        publicar_github(cfg, ts)

    if not saida["resultados"]:
        log.error("nenhum resultado — o Google pode ter bloqueado ou mudado o site")
        return
    alertas, sk_novos, chaves = decidir_alertas(cfg, con, ts, saida)
    log.info("%d alertas de preço, %d skiplags novos", len(alertas), len(sk_novos))
    if not (alertas or sk_novos):
        return

    html = montar_email(cfg, saida, alertas, sk_novos, ts)
    if alertas:
        m = min(alertas, key=lambda a: a["tot"])
        assunto = (f"✈️ {len(alertas)} mudança(s) de preço — {m['r']['cidade']} R$ {m['tot']} "
                   f"({m['r']['janela'].nome}, {m['r']['janela'].inicio:%d/%m})")
    else:
        assunto = f"🧳 {len(sk_novos)} oportunidade(s) de skiplag"

    cred = carregar_credenciais()
    if args.sem_email or not cred:
        (BASE / "ultimo_email.html").write_text(html, encoding="utf-8")
        log.info("e-mail NÃO enviado (%s); prévia em ultimo_email.html",
                 "--sem-email" if args.sem_email else "sem credenciais configuradas")
        return
    enviar_email(cred, assunto, html)
    for chave, preco in chaves:
        con.execute("INSERT OR REPLACE INTO alertas VALUES(?,?,?)", (chave, preco, ts))
    con.commit()
    log.info("e-mail enviado para %s", cred["destinatario"])


if __name__ == "__main__":
    main()
