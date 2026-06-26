$ErrorActionPreference = "Stop"

$TaskName = "CNC VCarve Agent"
$AgentDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$StartScript = Join-Path $AgentDir "start_vcarve_agent.ps1"
$PowerShell = "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"

if (-not (Test-Path -LiteralPath $StartScript)) {
  throw "Arquivo nao encontrado: $StartScript"
}

$Action = New-ScheduledTaskAction `
  -Execute $PowerShell `
  -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$StartScript`""

$Trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$Settings = New-ScheduledTaskSettingsSet `
  -AllowStartIfOnBatteries `
  -DontStopIfGoingOnBatteries `
  -MultipleInstances IgnoreNew `
  -ExecutionTimeLimit (New-TimeSpan -Hours 0)

Register-ScheduledTask `
  -TaskName $TaskName `
  -Action $Action `
  -Trigger $Trigger `
  -Settings $Settings `
  -Description "Inicia o agente local do VCarve para o CNC Dashboard." `
  -Force | Out-Null

Start-ScheduledTask -TaskName $TaskName

Write-Host "Agente VCarve instalado na inicializacao do Windows."
Write-Host "Tarefa: $TaskName"
Write-Host "Teste no navegador: http://127.0.0.1:8765/status"
