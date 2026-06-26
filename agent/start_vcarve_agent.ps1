$ErrorActionPreference = "Stop"

$AgentDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$AgentScript = Join-Path $AgentDir "vcarve_agent.py"
$LogDir = Join-Path $AgentDir "logs"
$OutLog = Join-Path $LogDir "vcarve_agent.out.log"
$ErrLog = Join-Path $LogDir "vcarve_agent.err.log"

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

$Python = $null
$PyLauncher = Get-Command py -ErrorAction SilentlyContinue
if ($PyLauncher) {
  $Python = $PyLauncher.Source
  $Arguments = @("-3", $AgentScript)
} else {
  $PythonCmd = Get-Command python -ErrorAction SilentlyContinue
  if (-not $PythonCmd) {
    throw "Python nao encontrado. Instale o Python ou deixe o comando 'py' disponivel no Windows."
  }
  $Python = $PythonCmd.Source
  $Arguments = @($AgentScript)
}

Start-Process `
  -FilePath $Python `
  -ArgumentList $Arguments `
  -WorkingDirectory $AgentDir `
  -WindowStyle Hidden `
  -RedirectStandardOutput $OutLog `
  -RedirectStandardError $ErrLog
