# Agente Local VCarve

Este agente roda no PC Windows do facilitador e abre os arquivos DXF no VCarve a partir do CNC Dashboard.

## Configurar

1. Copie a pasta `agent` para o PC do facilitador.
2. Confira o arquivo `vcarve_agent_config.json`.
3. Ajuste o caminho do VCarve se necessario:

```json
"vcarve_exe": "C:\\ProgramData\\Microsoft\\Windows\\Start Menu\\Programs\\VCarve Pro 7.5"
```

## Testar manualmente

Dê dois cliques em:

```text
iniciar_vcarve_agent.bat
```

Depois acesse no navegador:

```text
http://127.0.0.1:8765/status
```

## Instalar para iniciar com o Windows

Abra o PowerShell no PC do facilitador e execute:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
cd C:\caminho\da\pasta\agent
.\install_vcarve_agent_startup.ps1
```

O agente sera iniciado automaticamente quando o usuario fizer login no Windows.

## Remover da inicializacao

```powershell
cd C:\caminho\da\pasta\agent
.\uninstall_vcarve_agent_startup.ps1
```

## Logs

Os logs ficam em:

```text
agent\logs\vcarve_agent.out.log
agent\logs\vcarve_agent.err.log
```
