$ErrorActionPreference = "Stop"

$TaskName = "CNC VCarve Agent"

$Task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($Task) {
  Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
  Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
  Write-Host "Agente VCarve removido da inicializacao do Windows."
} else {
  Write-Host "Tarefa nao encontrada: $TaskName"
}
