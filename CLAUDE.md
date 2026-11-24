# Monitor de Voos — contexto do projeto

Monitor pessoal de preços de passagens SP ↔ Salvador/Rio. Python (venv + parser fast-flights, com consulta `tfs` multi-aeroporto própria do Google Flights). Conversar com o usuário em português. Ver também `LEIA-ME.md`.

Este arquivo é a memória do projeto: tudo o que foi combinado com o usuário até 2026-11-24, migrado das notas locais do Claude do PC corporativo. Mantenha-o atualizado quando algo novo for decidido.

## Repositório e máquinas (desde 2026-11-24)
- Repositório: GitHub `vbranco6/monitor-voos` (público — necessário para o GitHub Pages gratuito; o código não tem senhas). Transferido da conta `Voosmonitor` em 2026-11-24.
- Painel: `https://vbranco6.github.io/monitor-voos/` (antes `voosmonitor.github.io/monitor-voos`).
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
- Toda execução local (exceto `--teste`) chama `publicar_github` (config `publicar_github` em config.json): force-push de painel.html como index.html na branch `painel` (Pages = "deploy from branch: painel") e de historico.db na branch `dados`. Autenticação git via credential helper do `gh` — a conta ativa do `gh` precisa ter acesso ao repositório.
- `monitor.py` remove BOM/espaços das credenciais (PowerShell 5.1 adicionava BOM ao passar segredos por pipe; usar `gh secret set --body`).

## Notas técnicas (2026-11-11)
- O parser do fast-flights lê só "other flights" (payload[3]); os mais baratos costumam estar em "best flights" (payload[2]). `parse_tudo` junta os dois. Preços gravados antes de 2026-11-11 estão superestimados.
- A página HTML esconde a maioria das conexões; o motor skiplag próprio perde várias. Lista completa vem de POST ao RPC `GetShoppingResults` com cauda `1,1,0,2` (segundo valor 1 = mostrar tudo), usando primp. Usado avulso (busca SP→SSA 21–23/12); ainda não portado para monitor.py.
- Instalar pacotes novos com pip foi bloqueado pelo classificador de permissões; openpyxl não está no venv.

## Roadmap
- Fase 1 (atual): Google Flights para tarifas normais + motor skiplag próprio. A API do skiplagged.com dá 403 para scripts.
- Fase 2 (só quando o usuário pedir): sites de milhas (Smiles, LATAM Pass, TudoAzul etc.).
- Ideias de produto futuras (não iniciadas; uso pessoal vem primeiro): grupo pago de WhatsApp com alertas (sem API oficial simples; Telegram suporta canais pagos — fallback e base futura), site comparando dinheiro vs milhas vs misto. Riscos levantados: termos de uso/bloqueio ao raspar Google Flights e sites de milhas; repositório público expõe o código. Construir o envio de alertas como notificadores plugáveis.

## Preferências gerais do usuário (valem para qualquer trabalho)
- Conversar em português, de forma simples e direta.
- Todo arquivo que produzirmos juntos (documentos, scripts, resultados) fica salvo dentro da pasta do projeto, para ir ao GitHub — nunca só em pasta temporária ou scratchpad. Arquivo descartável de teste pode ficar no temporário.
- Entregáveis em formato de planilha (listas para revisar, exportações, relatórios): sempre **.xlsx**, nunca .csv, a menos que o usuário peça CSV. (Pedido de 2026-07-31: "Da próxima vez, gere um arquivo xlsx e não csv".)
- Toda instrução ou decisão nova do usuário vai para este CLAUDE.md (e para a memória do Claude) e é enviada ao GitHub na mesma sessão, para os dois PCs ficarem com as mesmas regras.
