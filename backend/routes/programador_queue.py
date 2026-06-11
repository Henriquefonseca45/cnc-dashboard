from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import List, Optional
from sqlalchemy import text
from sqlalchemy.orm import Session

# >>>> TROQUE PELO SEU get_db REAL <<<<
def get_db():
    raise NotImplementedError

router = APIRouter()

class AddBody(BaseModel):
    arquivo_id: int

class ReorderBody(BaseModel):
    ordem: List[int]  # seu frontend manda "ordem"

def has_em_execucao(db: Session, maquina_id: str) -> bool:
    r = db.execute(
        text("""
            SELECT 1
            FROM fila
            WHERE maquina_id = :m AND status = 'EM_EXECUCAO'
            LIMIT 1
        """),
        {"m": maquina_id},
    ).first()
    return r is not None

def reindex_aguardando(db: Session, maquina_id: str):
    """
    Mantém posições consistentes:
    - Se existe EM_EXECUCAO => ele fica posicao=0 e AGUARDANDO começa em 1
    - Se NÃO existe EM_EXECUCAO => AGUARDANDO começa em 0
    """
    start = 1 if has_em_execucao(db, maquina_id) else 0

    rows = db.execute(
        text("""
            SELECT id
            FROM fila
            WHERE maquina_id = :m AND status = 'AGUARDANDO'
            ORDER BY posicao ASC, id ASC
        """),
        {"m": maquina_id},
    ).mappings().all()

    for i, r in enumerate(rows):
        db.execute(
            text("""
                UPDATE fila
                SET posicao = :p
                WHERE id = :id AND maquina_id = :m AND status = 'AGUARDANDO'
            """),
            {"p": start + i, "id": r["id"], "m": maquina_id},
        )

def get_locked_and_editable(db: Session, maquina_id: str):
    """
    Regra: trava os 2 primeiros itens AGUARDANDO (fila viva).
    """
    rows = db.execute(
        text("""
            SELECT id
            FROM fila
            WHERE maquina_id = :m AND status = 'AGUARDANDO'
            ORDER BY posicao ASC, id ASC
        """),
        {"m": maquina_id},
    ).mappings().all()

    ids = [r["id"] for r in rows]
    locked = ids[:2]    # 1º e 2º da fila viva
    editable = ids[2:]  # azuis
    return locked, editable

def get_arquivo_nome(db: Session, arquivo_id: int) -> Optional[str]:
    """
    Se você tem tabela arquivos com campo nome, use isso.
    Ajuste se seu schema for diferente.
    """
    r = db.execute(
        text("SELECT nome FROM arquivos WHERE id = :id"),
        {"id": arquivo_id},
    ).first()
    return r[0] if r else None


# ---------------------------------------------------------
# 1) ADD - compatível com seu frontend
# POST /fila/{maquina_id}/add   {arquivo_id}
# ---------------------------------------------------------
@router.post("/fila/{maquina_id}/add")
def add_to_queue(maquina_id: str, body: AddBody, db: Session = Depends(get_db)):
    with db.begin():
        max_pos = db.execute(
            text("""
                SELECT COALESCE(MAX(posicao), -1)
                FROM fila
                WHERE maquina_id = :m AND status IN ('AGUARDANDO','EM_EXECUCAO')
            """),
            {"m": maquina_id},
        ).scalar_one()

        new_pos = int(max_pos) + 1
        nome = get_arquivo_nome(db, body.arquivo_id)

        # Insere como AGUARDANDO no final
        row = db.execute(
            text("""
                INSERT INTO fila (maquina_id, arquivo_id, arquivo_nome, posicao, status, criado_em)
                VALUES (:m, :aid, :anome, :p, 'AGUARDANDO', NOW())
                RETURNING id
            """),
            {"m": maquina_id, "aid": body.arquivo_id, "anome": nome, "p": new_pos},
        ).first()

        item_id = int(row[0]) if row else None

        # Reindex para ficar consistente com EM_EXECUCAO
        reindex_aguardando(db, maquina_id)

    return {
        "ok": True,
        "item_id": item_id,
        "maquina_id": maquina_id,
        "arquivo_id": body.arquivo_id,
        "arquivo_nome": nome,
        "posicao": new_pos,
    }


# ---------------------------------------------------------
# 2) REORDER - compatível com seu frontend
# POST /fila/{maquina_id}/reorder   {ordem: [ids]}
# regra: só itens azuis podem mudar
# ---------------------------------------------------------
@router.post("/fila/{maquina_id}/reorder")
def reorder_queue(maquina_id: str, body: ReorderBody, db: Session = Depends(get_db)):
    with db.begin():
        locked, editable = get_locked_and_editable(db, maquina_id)

        ordem = body.ordem or []

        # Aceita 2 formatos:
        # A) frontend manda só os azuis: ordem == editable
        # B) frontend manda a fila toda (AGUARDANDO): locked + editable
        # Em ambos os casos, locked NÃO pode mudar.
        if sorted(ordem) == sorted(editable):
            new_order = locked + ordem
        elif sorted(ordem) == sorted(locked + editable):
            # valida se os 2 primeiros ficaram iguais
            if ordem[:len(locked)] != locked:
                raise HTTPException(400, "Posição 1 e 2 são travadas. Não pode reordenar os travados.")
            new_order = ordem
        else:
            raise HTTPException(
                400,
                "ordem inválida. Envie somente os IDs azuis (posição 3+) ou toda a fila AGUARDANDO preservando os 2 primeiros.",
            )

        start = 1 if has_em_execucao(db, maquina_id) else 0

        for idx, fila_id in enumerate(new_order):
            db.execute(
                text("""
                    UPDATE fila
                    SET posicao = :p
                    WHERE id = :id AND maquina_id = :m AND status = 'AGUARDANDO'
                """),
                {"p": start + idx, "id": fila_id, "m": maquina_id},
            )

    return {"ok": True}


# ---------------------------------------------------------
# 3) DELETE - compatível com seu frontend
# DELETE /fila/item/{item_id}
# regra: não remove travado (1º/2º AGUARDANDO)
# ---------------------------------------------------------
@router.delete("/fila/item/{item_id}")
def delete_item(item_id: int, db: Session = Depends(get_db)):
    with db.begin():
        # Descobre maquina_id e arquivo_id do item
        row = db.execute(
            text("""
                SELECT maquina_id, arquivo_id
                FROM fila
                WHERE id = :id AND status = 'AGUARDANDO'
            """),
            {"id": item_id},
        ).first()

        if not row:
            raise HTTPException(404, "Item não encontrado (ou não está AGUARDANDO).")

        maquina_id, arquivo_id = row[0], row[1]

        locked, editable = get_locked_and_editable(db, maquina_id)
        if item_id in locked:
            raise HTTPException(400, "Não pode remover: posição 1 e 2 são travadas.")

        res = db.execute(
            text("""
                DELETE FROM fila
                WHERE id = :id AND status = 'AGUARDANDO'
            """),
            {"id": item_id},
        )

        if res.rowcount == 0:
            raise HTTPException(400, "Não foi possível remover.")

        reindex_aguardando(db, maquina_id)

    return {"ok": True, "maquina_id": maquina_id, "arquivo_id": arquivo_id}