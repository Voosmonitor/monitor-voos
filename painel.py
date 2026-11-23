"""Gera painel.html (autocontido) a partir do historico.db."""

import json
from collections import defaultdict
from datetime import date, datetime
from html import escape

MESES = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]
DIAS = ["seg", "ter", "qua", "qui", "sex", "sáb", "dom"]


def _fd(s: str) -> str:
    d = date.fromisoformat(s)
    return f"{DIAS[d.weekday()]} {d.day:02d}/{MESES[d.month - 1]}"


def _brl(v) -> str:
    return "—" if v is None else f"R$ {v:,.0f}".replace(",", ".")


def _carregar(con):
    hoje = date.today().isoformat()
    rows = con.execute(
        "SELECT coletado_em, janela, inicio, fim, rotulo, curto, cidade, modo, total, detalhe "
        "FROM totais WHERE fim >= ? ORDER BY coletado_em", (hoje,)).fetchall()
    serie = defaultdict(list)
    ultimo = {}
    for ts, jid, ini, fim, rot, curto, cid, modo, tot, det in rows:
        k = (jid, cid, modo)
        serie[k].append((ts, tot))
        ultimo[k] = {"ts": ts, "janela": jid, "inicio": ini, "fim": fim, "rotulo": rot,
                     "curto": bool(curto), "cidade": cid, "total": tot, "det": json.loads(det) if det else None}
    return serie, ultimo


def _sparkline(pts, w=90, h=22) -> str:
    vals = [v for _, v in pts][-40:]
    if len(vals) < 2:
        return ""
    lo, hi = min(vals), max(vals)
    rng = (hi - lo) or 1
    step = w / (len(vals) - 1)
    coords = " ".join(f"{i * step:.1f},{h - 3 - (v - lo) / rng * (h - 6):.1f}" for i, v in enumerate(vals))
    lx, ly = coords.split(" ")[-1].split(",")
    return (f'<svg class="spark" viewBox="0 0 {w} {h}" width="{w}" height="{h}" aria-hidden="true">'
            f'<polyline points="{coords}" fill="none" stroke="var(--series-1)" stroke-width="1.5"/>'
            f'<circle cx="{lx}" cy="{ly}" r="2.5" fill="var(--series-1)"/></svg>')


def _grafico(itens, teto) -> str:
    """Barras: preço ida+volta atual por janela (ordem cronológica)."""
    if not itens:
        return "<p class='muted'>Sem dados ainda.</p>"
    W, H, ml, mr, mt, mb = 1000, 250, 56, 8, 12, 34
    pw, ph = W - ml - mr, H - mt - mb
    vmax = max(i["total"] for i in itens)
    passo = 250 if vmax <= 2000 else 500 if vmax <= 4000 else 1000
    topo = (int(vmax * 1.08) // passo + 1) * passo
    n = len(itens)
    slot = pw / n
    bw = max(3.0, min(22.0, slot - 2))
    y = lambda v: mt + ph - v / topo * ph
    p = [f'<svg class="chart" viewBox="0 0 {W} {H}" role="img" aria-label="Preço ida e volta por janela">']
    for t in range(0, topo + 1, passo):
        p.append(f'<line x1="{ml}" x2="{W - mr}" y1="{y(t):.1f}" y2="{y(t):.1f}" class="grid"/>'
                 f'<text x="{ml - 6}" y="{y(t) + 4:.1f}" class="tick" text-anchor="end">{_brl(t)}</text>')
    if teto:
        p.append(f'<line x1="{ml}" x2="{W - mr}" y1="{y(teto):.1f}" y2="{y(teto):.1f}" class="teto"/>'
                 f'<text x="{W - mr}" y="{y(teto) - 4:.1f}" class="tick" text-anchor="end">'
                 f'seu teto p/ fim de semana: {_brl(teto)}</text>')
    mes_ant = None
    for idx, it in enumerate(itens):
        cx = ml + slot * idx + slot / 2
        x0, yt = cx - bw / 2, y(it["total"])
        hgt = max(1.0, mt + ph - yt)
        r = min(4.0, bw / 2, hgt)
        cls = "bar hot" if it["barato"] else "bar"
        d = (f"M{x0:.1f},{mt + ph:.1f} V{yt + r:.1f} Q{x0:.1f},{yt:.1f} {x0 + r:.1f},{yt:.1f} "
             f"H{x0 + bw - r:.1f} Q{x0 + bw:.1f},{yt:.1f} {x0 + bw:.1f},{yt + r:.1f} V{mt + ph:.1f} Z")
        tip = escape(json.dumps(it["tip"], ensure_ascii=False))
        p.append(f'<g class="hit" data-tip="{tip}"><rect x="{ml + slot * idx:.1f}" y="{mt}" '
                 f'width="{slot:.1f}" height="{ph}" fill="transparent"/><path d="{d}" class="{cls}"/></g>')
        m = it["inicio"][:7]
        if m != mes_ant:
            dd = date.fromisoformat(it["inicio"])
            p.append(f'<text x="{ml + slot * idx:.1f}" y="{H - 12}" class="tick">'
                     f'{MESES[dd.month - 1]}{"/" + str(dd.year)[2:] if dd.month == 1 or mes_ant is None else ""}</text>')
            mes_ant = m
    p.append(f'<line x1="{ml}" x2="{W - mr}" y1="{mt + ph}" y2="{mt + ph}" class="axis"/></svg>')
    return "".join(p)


def _op_html(o) -> str:
    sk = f' <span class="tag">skiplag: bilhete até {o["skiplag_ate"]}</span>' if o.get("skiplag_ate") else ""
    return (f'<a href="{escape(o["link"])}" target="_blank" rel="noopener">{_fd(o["data"])} '
            f'{o["de"]}→{o["para"]} {o["partida"]}–{o["chegada"]}</a> '
            f'<span class="muted">{escape(o["cia"])} · {_brl(o["preco"])}</span>{sk}')


def gerar(con, cfg, caminho):
    serie, ultimo = _carregar(con)
    teto = cfg.get("teto_fim_de_semana_curto")
    pct = cfg.get("alertas", {}).get("faixa_barata_percentil", 20) / 100
    atualizado = max((u["ts"] for u in ultimo.values()), default=None)

    secoes = []
    for cidade in cfg["destinos"]:
        itens = sorted((u for (j, c, m), u in ultimo.items() if c == cidade and m == "normal"),
                       key=lambda u: u["inicio"])
        # faixa "barata": percentil por tipo (fim de semana curto vs feriado)
        limites = {}
        for tipo in (True, False):
            vs = sorted(i["total"] for i in itens if i["curto"] == tipo)
            if vs:
                limites[tipo] = vs[int(pct * (len(vs) - 1))]
        linhas = []
        for it in itens:
            k = (it["janela"], cidade, "normal")
            hist = [v for _, v in serie[k]]
            ant = hist[-2] if len(hist) >= 2 else None
            delta = it["total"] - ant if ant is not None else None
            it["barato"] = (it["total"] <= limites.get(it["curto"], -1)) or bool(
                teto and it["curto"] and it["total"] <= teto)
            sk = ultimo.get((it["janela"], cidade, "skiplag"))
            it["tip"] = {"t": it["rotulo"], "v": _brl(it["total"]),
                         "d": "" if delta in (None, 0) else f"{'+' if delta > 0 else '−'}{_brl(abs(delta))} vs. coleta anterior",
                         "m": f"mínimo visto {_brl(min(hist))}", "s": f"com skiplag {_brl(sk['total'])}" if sk else ""}
            dcls = "" if not delta else ("down" if delta < 0 else "up")
            dtxt = "—" if not delta else f"{'▼' if delta < 0 else '▲'} {_brl(abs(delta))}"
            linhas.append(
                f'<tr class="{"hotrow" if it["barato"] else ""}" data-tipo="{"curto" if it["curto"] else "feriado"}">'
                f'<td><b>{escape(it["rotulo"])}</b>{" <span class=tag>barato</span>" if it["barato"] else ""}</td>'
                f'<td class="num"><b>{_brl(it["total"])}</b></td><td class="num {dcls}">{dtxt}</td>'
                f'<td class="num">{_brl(min(hist))}</td><td>{_sparkline(serie[k])}</td>'
                f'<td class="num">{_brl(sk["total"]) if sk else "—"}</td>'
                f'<td>{_op_html(it["det"]["ida"])}</td><td>{_op_html(it["det"]["volta"])}</td></tr>')
        secoes.append(
            f'<section><h2>{escape(cidade)}</h2>'
            f'<p class="muted">Menor ida+volta atual por janela. Barras escuras = entre os '
            f'{int(pct * 100)}% mais baratos do ano (comparando fins de semana com fins de semana e '
            f'feriados com feriados) ou abaixo do seu teto. Passe o mouse para detalhes.</p>'
            f'{_grafico(itens, teto)}'
            f'<div class="tw"><table><thead><tr><th>Janela</th><th class="num">Ida+volta</th>'
            f'<th class="num">Variação</th><th class="num">Mín. visto</th><th>Tendência</th>'
            f'<th class="num">c/ skiplag</th><th>Ida</th><th>Volta</th></tr></thead>'
            f'<tbody>{"".join(linhas)}</tbody></table></div></section>')

    upd = datetime.fromisoformat(atualizado).strftime("%d/%m/%Y %H:%M") if atualizado else "—"
    html = f"""<!DOCTYPE html>
<html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Monitor de voos</title>
<style>
.viz-root{{color-scheme:light;--surface-0:#f4f4f2;--surface-1:#fcfcfb;--text-primary:#0b0b0b;--text-secondary:#52514e;
--muted:#7a7974;--grid:#e4e3df;--axis:#bdbcb6;--series-1:#2a78d6;--series-1-soft:#b9d2f1;--good:#008300;--bad:#c23b3a;}}
@media (prefers-color-scheme:dark){{.viz-root{{color-scheme:dark;--surface-0:#121211;--surface-1:#1a1a19;--text-primary:#f0efec;
--text-secondary:#c3c2b7;--muted:#97968e;--grid:#2c2c2a;--axis:#4a4a46;--series-1:#3987e5;--series-1-soft:#2b4566;--good:#3fb93f;--bad:#e66767;}}}}
*{{box-sizing:border-box}}body{{margin:0}}
.viz-root{{background:var(--surface-0);color:var(--text-primary);font:14px/1.45 system-ui,-apple-system,"Segoe UI",sans-serif;padding:20px;min-height:100vh}}
header{{display:flex;flex-wrap:wrap;gap:12px;align-items:baseline;justify-content:space-between;max-width:1300px;margin:0 auto 8px}}
h1{{font-size:22px;margin:0}}h2{{font-size:18px;margin:0 0 4px}}
section{{background:var(--surface-1);border-radius:12px;padding:18px;max-width:1300px;margin:14px auto}}
.muted{{color:var(--text-secondary);font-size:12.5px}}
.filtros{{display:flex;gap:6px}}.filtros button{{border:1px solid var(--axis);background:var(--surface-1);color:var(--text-primary);
border-radius:999px;padding:4px 12px;cursor:pointer;font:inherit;font-size:13px}}.filtros button.on{{background:var(--text-primary);color:var(--surface-1)}}
.chart{{width:100%;height:auto;display:block;margin:6px 0 10px}}
.grid{{stroke:var(--grid);stroke-width:1}}.axis{{stroke:var(--axis);stroke-width:1}}
.teto{{stroke:var(--text-secondary);stroke-width:1;stroke-dasharray:4 4}}
.tick{{fill:var(--muted);font-size:11px}}
.bar{{fill:var(--series-1-soft)}}.bar.hot{{fill:var(--series-1)}}
.hit:hover .bar{{opacity:.75}}
.tw{{overflow-x:auto}}table{{border-collapse:collapse;width:100%;font-size:13px}}
th{{text-align:left;color:var(--text-secondary);font-weight:600;border-bottom:1px solid var(--axis);padding:6px 8px;white-space:nowrap}}
td{{border-bottom:1px solid var(--grid);padding:6px 8px;vertical-align:top}}
.num{{text-align:right;white-space:nowrap;font-variant-numeric:tabular-nums}}
.down{{color:var(--good)}}.up{{color:var(--bad)}}
tr.hotrow td:first-child{{box-shadow:inset 3px 0 0 var(--series-1)}}
.tag{{display:inline-block;font-size:11px;border:1px solid var(--series-1);color:var(--text-primary);border-radius:999px;padding:0 6px;margin-left:4px}}
a{{color:var(--text-primary)}}
#tip{{position:fixed;pointer-events:none;background:var(--surface-1);color:var(--text-primary);border:1px solid var(--axis);
border-radius:8px;padding:8px 10px;font-size:12.5px;box-shadow:0 4px 14px rgba(0,0,0,.18);display:none;max-width:280px;z-index:9}}
#tip b{{font-size:15px}}
</style></head>
<body class="viz-root">
<header><div><h1>✈️ Monitor de voos</h1>
<div class="muted">Atualizado em {upd} · preços do Google Flights, 1 adulto, só ida por trecho, voos diretos, sem bagagem despachada</div></div>
<div class="filtros" role="group" aria-label="Filtrar janelas">
<button class="on" data-f="todos">Todas</button><button data-f="feriado">Feriados</button><button data-f="curto">Fins de semana</button></div></header>
{"".join(secoes)}
<div id="tip" role="tooltip"></div>
<script>
const tip=document.getElementById('tip');
document.querySelectorAll('.hit').forEach(g=>{{
  g.addEventListener('mousemove',e=>{{const d=JSON.parse(g.dataset.tip);
    tip.innerHTML=`<div class="muted">${{d.t}}</div><b>${{d.v}}</b> ida+volta`+(d.d?`<div>${{d.d}}</div>`:'')+`<div class="muted">${{d.m}}</div>`+(d.s?`<div class="muted">${{d.s}}</div>`:'');
    tip.style.display='block';const x=Math.min(e.clientX+14,innerWidth-tip.offsetWidth-8);tip.style.left=x+'px';tip.style.top=(e.clientY+14)+'px';}});
  g.addEventListener('mouseleave',()=>tip.style.display='none');}});
document.querySelectorAll('.filtros button').forEach(b=>b.addEventListener('click',()=>{{
  document.querySelectorAll('.filtros button').forEach(x=>x.classList.toggle('on',x===b));
  document.querySelectorAll('tbody tr').forEach(tr=>tr.style.display=(b.dataset.f==='todos'||tr.dataset.tipo===b.dataset.f)?'':'none');}}));
</script></body></html>"""
    caminho.write_text(html, encoding="utf-8")
