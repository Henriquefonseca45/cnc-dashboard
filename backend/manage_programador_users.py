from __future__ import annotations

import argparse
from getpass import getpass

from backend.db import get_conn
from backend.programador_auth import create_or_update_user, ensure_programador_auth_schema, hash_password, normalize_role, utc_iso


def main() -> None:
    parser = argparse.ArgumentParser(description="Gerencia usuários do módulo Programador.")
    sub = parser.add_subparsers(dest="command", required=True)

    create = sub.add_parser("create", help="Cria ou atualiza um Programador/Líder/DEV.")
    create.add_argument("--name", required=True)
    create.add_argument("--login", required=True)
    create.add_argument("--role", choices=("programador", "lider", "dev"), required=True)

    state = sub.add_parser("set-active", help="Ativa ou desativa um usuário.")
    state.add_argument("--login", required=True)
    state.add_argument("--active", choices=("yes", "no"), required=True)

    reset = sub.add_parser("reset-password", help="Redefine a senha de um usuário.")
    reset.add_argument("--login", required=True)

    role = sub.add_parser("set-role", help="Altera o perfil de um usuário.")
    role.add_argument("--login", required=True)
    role.add_argument("--role", choices=("programador", "lider"), required=True)

    args = parser.parse_args()
    conn = get_conn()
    try:
        ensure_programador_auth_schema(conn)
        login = args.login.strip().lower()
        if args.command == "create":
            password = getpass("Senha (mínimo 8 caracteres): ")
            confirmation = getpass("Confirme a senha: ")
            if password != confirmation:
                raise SystemExit("As senhas não coincidem.")
            user = create_or_update_user(conn, nome=args.name, login=login, password=password, role=args.role)
            print(f"Usuário salvo: {user['nome']} ({user['login']}) — {user['role']}")
        elif args.command == "set-active":
            cursor = conn.execute(
                "UPDATE usuarios SET ativo = ?, updated_at = ? WHERE LOWER(login) = ? AND role IN ('programador','lider','dev')",
                (1 if args.active == "yes" else 0, utc_iso(), login),
            )
            if cursor.rowcount != 1:
                raise SystemExit("Usuário do módulo Programador não encontrado.")
            if args.active == "no":
                conn.execute(
                    "UPDATE programador_sessions SET revoked_at = ? WHERE usuario_id = (SELECT id FROM usuarios WHERE LOWER(login) = ?) AND revoked_at IS NULL",
                    (utc_iso(), login),
                )
            print("Situação atualizada.")
        elif args.command == "reset-password":
            password = getpass("Nova senha (mínimo 8 caracteres): ")
            confirmation = getpass("Confirme a senha: ")
            if password != confirmation:
                raise SystemExit("As senhas não coincidem.")
            cursor = conn.execute(
                "UPDATE usuarios SET senha = '', senha_hash = ?, updated_at = ? WHERE LOWER(login) = ? AND role IN ('programador','lider','dev')",
                (hash_password(password), utc_iso(), login),
            )
            if cursor.rowcount != 1:
                raise SystemExit("Usuário do módulo Programador não encontrado.")
            conn.execute(
                "UPDATE programador_sessions SET revoked_at = ? WHERE usuario_id = (SELECT id FROM usuarios WHERE LOWER(login) = ?) AND revoked_at IS NULL",
                (utc_iso(), login),
            )
            print("Senha redefinida e sessões existentes encerradas.")
        else:
            cursor = conn.execute(
                "UPDATE usuarios SET nivel = ?, role = ?, updated_at = ? WHERE LOWER(login) = ? AND role IN ('programador','lider')",
                (args.role.upper(), normalize_role(args.role), utc_iso(), login),
            )
            if cursor.rowcount != 1:
                raise SystemExit("Usuário do módulo Programador não encontrado.")
            print("Perfil atualizado.")
        conn.commit()
    finally:
        conn.close()


if __name__ == "__main__":
    main()
