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

## Confirmações automáticas de status

O backend precisa permanecer em execução, com o fuso `America/Sao_Paulo`
(já configurado em `docker-compose.yml`). O navegador não precisa estar aberto
para as mudanças automáticas; precisa estar aberto para o operador ver e responder ao aviso.

- Todos os dias, às 23:19: pergunta se deve continuar no status atual. Sem
  confirmação até 23:24, muda para `DESLIGADA`.
- Segunda a sexta, às 05:05: cada CNC de produção, inclusive desligada, recebe
  uma pergunta de início de turno. O operador identifica seu nome e escolhe o
  status. Sem resposta até 05:15, muda para `FALTA DE OPERADOR` e limpa o operador.
- A seleção da manhã mantém as validações de usinagem e manutenção. Lubrificação
  não exige OS. Escolher o mesmo status confirma sem reiniciar seu tempo.
- Se a CNC estava em manutenção no aviso das 23:19, às 05:05 o operador pode
  retomar a manutenção com o mesmo tipo e a mesma OS, preenchidos pelo servidor.
- Uma troca manual de status durante um aviso pendente também conta como resposta.
  A máquina de teste não participa dessas rotinas.
- Os avisos e as respostas ficam persistidos no SQLite. Um aviso da manhã já
  criado é retomado após reinício no mesmo dia, desde que o status não tenha mudado.
  Avisos de dias anteriores expiram. Se o servidor ficar indisponível durante
  toda a janela de 05:05–05:15, não é criado um aviso retroativo fora do horário.

O frontend consulta os avisos a cada 15 segundos. No servidor, a verificação é
feita a cada segundo próximo aos horários de confirmação. As tabelas são criadas
automaticamente, sem apagar dados existentes. Após atualizar o código, recompile
e reinicie o container para ativar a melhoria.
