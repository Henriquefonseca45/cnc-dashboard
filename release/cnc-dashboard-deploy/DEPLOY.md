# Deploy no Dockhand

Este projeto sobe como um unico container:

- FastAPI em `:8000`
- frontend React/Vite compilado e servido pelo proprio backend
- SQLite persistido em `./deploy-data/cnc.db`
- arquivos DXF persistidos em `./storage`

## Preparar os dados

No servidor, antes de subir o stack, deixe o banco atual em:

```powershell
deploy-data/cnc.db
```

Se estiver enviando a pasta atual para o servidor, crie a pasta `deploy-data` e copie o banco principal:

```powershell
New-Item -ItemType Directory -Force deploy-data
Copy-Item cnc.db deploy-data\cnc.db
```

## Subir pelo Dockhand

1. Abra `Stacks`.
2. Clique em `Create`.
3. Use o conteudo de `docker-compose.yml`, ou a opcao equivalente para criar a partir da pasta/projeto.
4. Confirme que o stack tem acesso aos arquivos `Dockerfile`, `requirements.txt`, `backend/`, `frontend/`, `deploy-data/` e `storage/`.
5. Inicie o stack.

## Acessos

- Programador: `http://IP_DO_SERVIDOR:8000/programador`
- Operador: `http://IP_DO_SERVIDOR:8000/operador/CNC01`
- Visual: `http://IP_DO_SERVIDOR:8000/visual`
- API health: `http://IP_DO_SERVIDOR:8000/health`

## Comandos equivalentes via terminal

```bash
docker compose up -d --build
docker compose logs -f cnc-dashboard
```

Para atualizar:

```bash
docker compose up -d --build
```
