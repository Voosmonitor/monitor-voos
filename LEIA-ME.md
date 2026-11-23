# Monitor de voos (SP ↔ Rio / Salvador)

Busca no Google Flights todos os fins de semana, feriados e emendas dos próximos 12 meses,
guarda o histórico (`historico.db`), atualiza o `painel.html` e manda e-mail quando algo muda.

## Regras de datas
- Ida: véspera da folga (dia útil) **a partir das 18h**, ou qualquer horário no 1º dia de folga.
- Volta: qualquer horário no último dia (ou penúltimo, em folgas de 3+ dias), ou na **manhã do
  dia útil seguinte** chegando até 08:00 em CGH, 07:00 em GRU, 06:30 em VCP.
- Ida: CGH/GRU. Volta: CGH/GRU/VCP. Só voos diretos (o skiplag é tratado à parte).

## Quando chega e-mail
- O ida+volta de uma janela **caiu** 5% ou mais (e pelo menos R$ 30) desde a última coleta;
- **Menor preço já visto** para aquela janela (depois de 3 coletas);
- Fim de semana curto ficou **abaixo do teto** (R$ 600);
- **Skiplag** que economiza R$ 60 ou mais vs. o melhor voo direto do dia.
Não repete aviso do mesmo preço.

## Agenda
Duas vezes por dia (07:00 e 19:00, tarefa "Monitor de Voos"). A primeira execução do dia
cobre o ano inteiro (~50 min); a segunda só os próximos 120 dias (~20 min).
O PC precisa estar ligado; se estiver desligado no horário, roda quando ligar.

## Comandos
```
rodar.bat --teste --sem-email   # rápido: 2 próximas janelas
rodar.bat --completo            # força o ano inteiro
powershell -ExecutionPolicy Bypass -File agendar.ps1 -Horarios "07:00","19:00"
Unregister-ScheduledTask -TaskName "Monitor de Voos" -Confirm:$false   # desligar
```

## E-mail
Crie `credenciais.json` a partir de `credenciais.exemplo.json` (Gmail + senha de app).
Sem esse arquivo, tudo funciona, mas o e-mail fica só em `ultimo_email.html`.

## Observações
- Se o Google bloquear ou mudar o site, aparece no `monitor.log`. Atualize com
  `.venv\Scripts\python.exe -m pip install -U fast-flights`.
- Skiplag: só trecho de ida, sem bagagem despachada, sem número de fidelidade. Viola as regras
  da companhia.
