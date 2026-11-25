# Monitor de Voos — contexto do projeto

Monitor pessoal de preços de passagens SP ↔ Salvador/Rio. Python (venv + parser fast-flights, com consulta `tfs` multi-aeroporto própria do Google Flights). Conversar com o usuário em português. Ver também `LEIA-ME.md`.

Este arquivo é a memória do projeto: tudo o que foi combinado com o usuário até 2026-11-24, migrado das notas locais do Claude do PC corporativo. Mantenha-o atualizado quando algo novo for decidido.

## Repositório e máquinas (desde 2026-11-24)
- Repositório: GitHub `vbranco6/monitor-voos`, PRIVADO (o usuário não quer o código visível). Transferido da conta `Voosmonitor` em 2026-11-24.
- Painel: `https://monitor-voos.pages.dev/` no Cloudflare Pages (mesma conta Cloudflare do Market Picks), protegido por senha (Basic Auth em `cloudflare/functions/_middleware.js`, segredo `PAINEL_SENHA` = a mesma senha do editor do Market Picks, que o usuário guarda no celular). Trocar: `npx wrangler pages secret put PAINEL_SENHA --project-name monitor-voos` (rodar dentro de `cloudflare/`) + nova publicação. Endereços antigos (`voosmonitor.github.io`, `vbranco6.github.io`) não existem mais.
- PC corporativo = estação principal: roda a tarefa agendada "Monitor de Voos" (`rodar.bat`, 09:30 e 16:00, criada por `agendar.ps1`). PC pessoal = estação secundária: só trabalho interativo e execuções manuais com `--teste`. **Nunca agendar em dois PCs ao mesmo tempo** (e-mails duplicados). Migrar só quando o usuário pedir.
- Sempre `git pull` antes de começar e commit + push ao terminar. Commits com o e-mail noreply do GitHub, nunca o Gmail do usuário.
- Fora do git: `credenciais.json` (Gmail remetente, senha de app, destinatário — criar à mão em cada PC a partir de `credenciais.exemplo.json`; nunca commitar nem mostrar a senha), `historico.db` (backup na branch `dados`), `.venv`, logs, HTMLs gerados.
- A conta `Voosmonitor` do GitHub não é mais necessária. Os disparos de e-mail saem do Gmail `voosmonitor@gmail.com` (criado no iPhone do usuário; verificação em 2 etapas pelo telefone) e não dependem do GitHub.

## Restrições do usuário (2026-11-06)
- Grátis, só uso pessoal.
- Ida: CGH/GRU → SSA, GIG, SDU. Volta para CGH, GRU ou VCP.
- Datas: fins de semana, feriados e emendas.
- Trabalha sex 9–18: partida em dia útil só depois das 18h. Feriado na sexta → quinta após 18h serve.
- Pode voltar na manhã do dia útil seguinte se chegar em CGH antes das 8h. (Limites GRU/VCP 07:00/06:30 são suposição do Claude, não do usuário.)
- Sem preço-alvo fixo: alertas relativos/baseados no histórico. Único teto: R$ 600 ida e volta num fim de semana curto.
- Horizonte de 1 ano, 2 execuções/dia, alertar quando mudar.

## Decisões de 2026-11-11 e 2026-11-23
- Nunca parear ida e volta no mesmo dia ou no dia seguinte: `min_noites: 2` em config.json (`melhor_par` em monitor.py).
- Só buscar viagens a partir de 2027-01-18 (`data_inicio_busca`). Horizonte completo = início+365, prioritário = início+120. O painel esconde janelas anteriores.
- Por dia de viagem, no máximo 3 voos: o mais barato de manhã (05–12), tarde (12–18) e noite (18–05). `por_periodo` / PERIODOS. Mostrado no e-mail e no painel.
- E-mail, log e painel mostram as datas reais dos voos e o número de noites (o rótulo da janela, ex. "sáb a dom", não é o voo).
- Roda no PC local (escolha efetiva). O workflow do GitHub Actions fica DESATIVADO: a partir de IPs do Actions o Google Flights devolve `errorHasStatus: true` intermitente (bloqueio leve), enquanto local funciona.
- Toda execução local (exceto `--teste`) chama `publicar_github` (config `publicar_github` em config.json): publica painel.html no Cloudflare Pages via `npx wrangler pages deploy` (cwd `cloudflare/`, para levar o middleware de senha; precisa de Node e `npx wrangler login` no PC) e faz force-push de historico.db na branch `dados` do GitHub (autenticação via credential helper do `gh` — a conta ativa precisa ser vbranco6). A branch `painel` e o GitHub Pages foram abandonados em 2026-11-24.
- `monitor.py` remove BOM/espaços das credenciais (PowerShell 5.1 adicionava BOM ao passar segredos por pipe; usar `gh secret set --body`).

## Trechos avulsos só de ida (pedido de 2026-11-24)
- Além das janelas de ida+volta, o usuário quer monitorar **só a ida SP (CGH/GRU/VCP) → Salvador de 18/12/2026 (após 18h) a 23/12/2026**. É uma exceção ao `data_inicio_busca`.
- Fica em config.json → `trechos` (lista; dá para adicionar outros). Código em `trechos.py`. Roda em toda execução agendada (≈78 buscas, ~5 min), e também com `monitor.py --so-trechos`. `--teste` não roda trechos. Dias passados são pulados sozinhos.
- Usa o RPC `GetShoppingResults` com "mostrar tudo" (até 300 itinerários, inclui conexões). Por dia guarda em `trechos_hist`: `normal` (mais barato, com conexão), `direto`, `skiplag` (bilhete para REC/FOR/AJU/MCZ/NAT/JPA/BPS/SLZ/THE/BEL/MAO/VDC com parada em SSA; top 5 no detalhe) e o mais barato por período.
- Alertas: queda/recorde (mesmas regras) por dia e modo, mais "skiplag mais barato que o normal" (≥ R$ 60). Vão no e-mail normal (seção 🎄) e no topo do painel.
- O filtro `via` do RPC não funcionou (devolvia voos diretos), e destinos com vários aeroportos + "mostrar tudo" devolvem 0. Por isso a busca é feita destino por destino, filtrando as paradas em SSA.
- Primeira coleta (24/11, 18h): o mais barato normal ficou em R$ 927–1.416 e o direto em R$ 1.289–1.580. O skiplag Gol VCP→SSA (G3 1935, bilhete VCP→**Porto Seguro (BPS)** — não é Paulo Afonso, que é PAV; o Claude errou isso na conversa e corrigiu) saiu R$ 965, num voo direto até SSA.
- Milhas (Smiles/LATAM Pass), pedido de 2026-11-24. A consulta direta às APIs foi barrada pelo classificador (não contornar). O usuário escolheu o esquema do Valor no Market Picks: a tarefa "Monitor de Voos - milhas" (criada por agendar.ps1, 20 min antes de cada coleta) roda `milhas/rotina-milhas.ps1` → `claude -p --chrome` com `milhas/rotina-milhas.md`. Ela lê as páginas no Chrome do usuário (só leitura, nunca login nem compra) e grava `milhas/coleta/<ts>.json`. O trechos.py lê o JSON mais recente (com menos de 14h), guarda os modos `smiles`/`latam` e alerta em quedas ≥ max(2.000 milhas, 5%).
  - A Smiles abre sem login (URL com departureDate em ms, originAirport=SAO). A extração por JS foi validada: 20/12 deu 59.000 milhas ou R$ 1.123,65, o mesmo voo Gol que o Google mostra. A LATAM redireciona para auth.latamairlines.com: o usuário precisa logar no Chrome (o Claude nunca digita senha). Sem login, o JSON diz "precisa login" e o painel mostra isso.
  - Conversão em reais (pedido do usuário): `valor_milheiro` em config.json (R$ por 1.000 milhas; smiles 17, latam 25 — **suposição do Claude**, o usuário pode ajustar). O painel e o e-mail mostram "≈ R$ X (milheiro R$ Y)" e, na Smiles, também o preço "ou R$" em dinheiro que o próprio site mostra.
  - O login do Claude Code expira entre 29/11 e 02/12/2026. As rotinas com `claude -p` (milhas e Market Picks) param se não renovar (`claude auth login` ou `claude setup-token`).

## Notas técnicas (2026-11-11)
- O parser do fast-flights lê só "other flights" (payload[3]); os mais baratos costumam estar em "best flights" (payload[2]). `parse_tudo` junta os dois. Preços gravados antes de 2026-11-11 estão superestimados.
- A página HTML esconde a maioria das conexões; o motor skiplag próprio perde várias. Lista completa vem de POST ao RPC `GetShoppingResults` com cauda `1,1,0,2` (segundo valor 1 = mostrar tudo), usando primp. Usado avulso (busca SP→SSA 21–23/12); ainda não portado para monitor.py.
- Instalar pacotes novos com pip foi bloqueado pelo classificador de permissões; openpyxl não está no venv.

## Roadmap
- Fase 1 (atual): Google Flights para tarifas normais + motor skiplag próprio. A API do skiplagged.com dá 403 para scripts.
- Fase 2: sites de milhas (Smiles, LATAM Pass, TudoAzul etc.). O usuário pediu Smiles + LATAM Pass em 2026-11-24 (ver "Trechos avulsos"); o acesso automático foi bloqueado e está pendente.
- Ideias de produto futuras (não iniciadas; uso pessoal vem primeiro): grupo pago de WhatsApp com alertas (sem API oficial simples; Telegram suporta canais pagos — fallback e base futura), site comparando dinheiro vs milhas vs misto. Riscos levantados: termos de uso/bloqueio ao raspar Google Flights e sites de milhas; repositório público expõe o código. Construir o envio de alertas como notificadores plugáveis.

## Preferências gerais do usuário (valem para qualquer trabalho)
- Conversar em português, de forma simples e direta.
- Todo arquivo que produzirmos juntos (documentos, scripts, resultados) fica salvo dentro da pasta do projeto, para ir ao GitHub — nunca só em pasta temporária ou scratchpad. Arquivo descartável de teste pode ficar no temporário.
- Entregáveis em formato de planilha (listas para revisar, exportações, relatórios): sempre **.xlsx**, nunca .csv, a menos que o usuário peça CSV. (Pedido de 2026-07-31: "Da próxima vez, gere um arquivo xlsx e não csv".)
- Toda instrução ou decisão nova do usuário vai para este CLAUDE.md (e para a memória do Claude) e é enviada ao GitHub na mesma sessão, para os dois PCs ficarem com as mesmas regras.
