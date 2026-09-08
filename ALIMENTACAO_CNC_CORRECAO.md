# Correção das regras da Alimentação CNC

## Causa

A aba lê a fila persistida inteira, inclusive registros anteriores à alimentação
semiautomática. As proteções antigas do SQLite só eram aplicadas quando o plano
ou algum plano da CNC tinha `alimentacao_cnc=1`. Filas inteiramente legadas não
tinham essa garantia no banco. A interface também aplicava o rótulo Próximo a
todos os itens pendentes sem a marca de deslocamento.

Isso explica a exposição de filas acima de 3 como posições normais. Não foi
atribuída a criação dos registros a um endpoint específico sem evidência histórica.

Consulta somente leitura ao servidor durante esta correção: CNC05 com 14 planos
ativos (11 excedentes); CNC04 com 2. Total: 1 CNC acima do limite, 14 itens nela,
11 excedentes. São valores de uma consulta pontual, não um estado permanente.

## Correção

- A migração substitui os guards antigos por `feeding_guard_v2_insert/update`.
- Limites de entrada valem para todas as filas, gerenciadas ou legadas, em
  inserções, transferências, substituições e reativações de registros.
- Atualizar/consumir itens já presentes continua permitido, para normalizar filas
  antigas sem excluir ou mover registros automaticamente.
- Uma terceira entrada exige deslocamento de prioridade; quarta entrada é bloqueada.
- Prioridade/FIFO, compatibilidade, proteção Programado e indisponibilidade da CNC
  continuam sendo respeitados pela distribuição.
- A conclusão de três itens retorna a dois: o primeiro aguarda o início pelo operador,
  o deslocado vira Próximo. Não há preenchimento normal da terceira posição.
- O resumo da API informa CNCs acima do limite, total de itens nessas filas e excesso.
- A interface identifica filas legadas/inconsistentes, bloqueio e lotação; itens
  excedentes não recebem falsamente o rótulo Próximo nem são ocultados.

## Fresa

Não foi localizada identificação de fresa nos esquemas/importação/agente inspecionados.
O status Aguardando fresa não identifica uma ferramenta. A fonte dos dados e o
critério (exigir igualdade ou preferir a mesma fresa) precisam ser definidos.
O usuário adiou expressamente essa parte; nenhum campo ou extrator foi criado.

## Verificação e publicação

Testes usam bancos temporários e cobrem filas vazias, normal, deslocamento,
lotação, prioridades, proteção Programado, concorrência, conclusão, estados
indisponíveis, legado, entrada direta no SQLite, reativação e transferência.
Nenhum deploy ou alteração de dados de produção foi executado.
