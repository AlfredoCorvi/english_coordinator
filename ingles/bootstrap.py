"""Alta explícita de la primera Secretaría para un entorno de desarrollo."""
import argparse
from ingles.relational_storage import RelationalStore


def bootstrap(store, subject):
    subject = subject.strip()
    if not subject:
        raise ValueError('Se requiere un sujeto ficticio.')
    store.initialize()
    with store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        if db.execute("SELECT 1 FROM user_roles WHERE role='SECRETARIA' LIMIT 1").fetchone():
            raise ValueError('Ya existe una cuenta de Secretaría; no se creó otra.')
        cur = db.execute("INSERT INTO users(identity_provider,subject) VALUES ('desarrollo',?)", (subject,))
        db.execute("INSERT INTO user_roles(user_id,role) VALUES (?,'SECRETARIA')", (cur.lastrowid,))


def main():
    parser = argparse.ArgumentParser(description='Crear la primera Secretaría ficticia; no guarda contraseñas.')
    parser.add_argument('--db', required=True)
    parser.add_argument('--subject', required=True)
    args = parser.parse_args()
    bootstrap(RelationalStore(args.db), args.subject)
    print('Cuenta local de Secretaría creada.')


if __name__ == '__main__':
    main()
