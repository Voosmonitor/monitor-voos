# Cria (ou atualiza) a tarefa no Agendador de Tarefas do Windows: 2x por dia.
# A 1a execução do dia faz a coleta completa (1 ano); a 2a só os próximos 120 dias.
# Uso: powershell -ExecutionPolicy Bypass -File agendar.ps1 [-Horarios "07:00","19:00"]
param([string[]]$Horarios = @("07:00", "19:00"))

$pasta = Split-Path -Parent $MyInvocation.MyCommand.Path
$acao = New-ScheduledTaskAction -Execute "$pasta\rodar.bat" -WorkingDirectory $pasta
$gatilhos = $Horarios | ForEach-Object { New-ScheduledTaskTrigger -Daily -At $_ }
$opcoes = New-ScheduledTaskSettingsSet -StartWhenAvailable -DontStopIfGoingOnBatteries `
    -AllowStartIfOnBatteries -ExecutionTimeLimit (New-TimeSpan -Hours 3) -MultipleInstances IgnoreNew

Register-ScheduledTask -TaskName "Monitor de Voos" -Action $acao -Trigger $gatilhos `
    -Settings $opcoes -Description "Monitora passagens SP <-> Rio/Salvador" -Force | Out-Null

Write-Host "Tarefa 'Monitor de Voos' agendada: $($Horarios -join ', ') todos os dias."
Write-Host "Para remover: Unregister-ScheduledTask -TaskName 'Monitor de Voos' -Confirm:`$false"
