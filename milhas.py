"""Milhas (Smiles / LATAM Pass) dos trechos avulsos, coletadas pelo Chrome do usuário.

Os sites de milhas bloqueiam scripts, então a coleta é feita pela rotina `milhas/rotina-milhas.ps1`, que roda
o Claude (`claude -p --chrome`) no Chrome do usuário (mesmo esquema do Valor no Market Picks). O Claude lê as
páginas e grava `milhas/coleta/<AAAA-MM-DD_HHMM>.json`. A coleta de preços (monitor.py → trechos.py) lê o arquivo
mais recente, guarda no histórico, alerta e mostra no painel.

    python milhas.py urls      # lista JSON das buscas a fazer (usada pela rotina)
    python milhas.py ativo     # exit 0 se há trecho ativo com datas futuras, senão 1
"""

import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent
PASTA = BASE / "milhas" / "coleta"
BRT = timezone(timedelta(hours=-3))
VALIDADE_HORAS = 14  # coleta de milhas mais velha que isso é ignorada


def _dias(t, hoje):
    ini, fim = date.fromisoformat(t["data_inicio"]), date.fromisoformat(t["data_fim"])
    d = max(ini, hoje)
    while d <= fim:
        yield d
        d += timedelta(days=1)


def _cidade(aeroportos):
    return "SAO" if set(aeroportos) <= {"CGH", "GRU", "VCP"} else aeroportos[0]


def buscas(cfg, hoje=None):
    hoje = hoje or date.today()
    out = []
    for t in cfg.get("trechos", []):
        if not t.get("ativo", True) or not t.get("milhas"):
            continue
        o, dst = _cidade(t["origens"]), t["destinos"][0]
        for d in _dias(t, hoje):
            ms = int(datetime(d.year, d.month, d.day, 12, tzinfo=BRT).timestamp() * 1000)
            if "smiles" in t["milhas"]:
                out.append({"trecho": t["nome"], "programa": "smiles", "data": d.isoformat(), "url": (
                    "https://www.smiles.com.br/mfe/emissao-passagem/?adults=1&cabin=ALL&children=0"
                    f"&departureDate={ms}&infants=0&isElegible=false&isFlexibleDateChecked=false&returnDate="
                    f"&searchType=g3&segments=1&tripType=2&originAirport={o}&originCity=&originCountry="
                    f"&originAirportIsAny={'true' if o == 'SAO' else 'false'}&destinationAirport={dst}"
                    "&destinCity=&destinCountry=&destinAirportIsAny=false&novo-resultado-voos=true")})
            if "latam" in t["milhas"]:
                out.append({"trecho": t["nome"], "programa": "latam", "data": d.isoformat(), "url": (
                    f"https://www.latamairlines.com/br/pt/oferta-voos?origin={o}"
                    f"&outbound={d.isoformat()}T15%3A00%3A00.000Z&destination={dst}&inbound=null"
                    "&adt=1&chd=0&inf=0&trip=OW&cabin=Economy&redemption=true&sort=RECOMMENDED")})
    return out


def ultima_coleta(agora=None):
    """Conteúdo do JSON de milhas mais recente, se tiver menos de VALIDADE_HORAS."""
    agora = agora or datetime.now()
    arqs = sorted(PASTA.glob("*.json"))
    if not arqs:
        return None
    try:
        dados = json.loads(arqs[-1].read_text(encoding="utf-8-sig"))
        ts = datetime.fromisoformat(dados["coletado_em"][:19])
    except Exception:
        return None
    if agora - ts > timedelta(hours=VALIDADE_HORAS):
        return None
    return dados


def _hora(s: str) -> int:
    return int(s.replace("h", ":").split(":")[0])


def melhor(voos, partida_apos=None):
    """Voo com menos milhas, respeitando a hora mínima de partida."""
    ok = [v for v in voos or [] if v.get("milhas") and (partida_apos is None or _hora(v["sai"]) >= partida_apos)]
    return min(ok, key=lambda v: v["milhas"]) if ok else None


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    cfg = json.loads((BASE / "config.json").read_text(encoding="utf-8"))
    if sys.argv[1:] == ["urls"]:
        print(json.dumps(buscas(cfg), ensure_ascii=False, indent=1))
    elif sys.argv[1:] == ["ativo"]:
        sys.exit(0 if buscas(cfg) else 1)
    else:
        print(__doc__)
