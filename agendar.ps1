# Cria (ou atualiza) a tarefa no Agendador de Tarefas do Windows: 2x por dia.
# A 1a execução do dia faz a coleta completa (1 ano); a 2a só os próximos 120 dias.
# Uso: powershell -ExecutionPolicy Bypass -File agendar.ps1 [-Horarios "09:30","16:00"]
param([string[]]$Horarios = @("09:30", "16:00"))

$pasta = Split-Path -Parent $MyInvocation.MyCommand.Path
$acao = New-ScheduledTaskAction -Execute "$pasta\rodar.bat" -WorkingDirectory $pasta
$gatilhos = $Horarios | ForEach-Object { New-ScheduledTaskTrigger -Daily -At $_ }
$opcoes = New-ScheduledTaskSettingsSet -StartWhenAvailable -DontStopIfGoingOnBatteries `
    -AllowStartIfOnBatteries -ExecutionTimeLimit (New-TimeSpan -Hours 3) -MultipleInstances IgnoreNew

Register-ScheduledTask -TaskName "Monitor de Voos" -Action $acao -Trigger $gatilhos `
    -Settings $opcoes -Description "Monitora passagens SP <-> Rio/Salvador" -Force | Out-Null

Write-Host "Tarefa 'Monitor de Voos' agendada: $($Horarios -join ', ') todos os dias."

# Milhas (Smiles/LATAM Pass) pelo Chrome: 20 min antes de cada coleta, para o monitor já ler o JSON novo.
# A rotina sai sozinha quando não há trecho com milhas e datas futuras.
$acaoM = New-ScheduledTaskAction -Execute "powershell.exe" -WorkingDirectory $pasta `
    -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$pasta\milhas\rotina-milhas.ps1`""
$gatM = $Horarios | ForEach-Object { New-ScheduledTaskTrigger -Daily -At ([datetime]$_).AddMinutes(-20).ToString("HH:mm") }
$opcM = New-ScheduledTaskSettingsSet -StartWhenAvailable -DontStopIfGoingOnBatteries `
    -AllowStartIfOnBatteries -ExecutionTimeLimit (New-TimeSpan -Minutes 40) -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName "Monitor de Voos - milhas" -Action $acaoM -Trigger $gatM `
    -Settings $opcM -Description "Coleta milhas Smiles/LATAM Pass pelo Chrome (Claude)" -Force | Out-Null
Write-Host "Tarefa 'Monitor de Voos - milhas' agendada 20 min antes de cada coleta."
Write-Host "Para remover: Unregister-ScheduledTask -TaskName 'Monitor de Voos' -Confirm:`$false"
