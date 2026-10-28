"""Crée le premier compte de modération. Exécuter `alembic upgrade head` AVANT ce script
pour que les tables existent.

Usage : python -m app.seed
Le mot de passe est lu depuis la variable d'environnement TRUSTNUM_ADMIN_PASSWORD,
ou généré aléatoirement et affiché une seule fois si elle est absente.
"""
import os
import secrets

from .database import SessionLocal
from .models import AdminUser
from .security import hash_password


def main():
    db = SessionLocal()
    try:
        username = os.environ.get("TRUSTNUM_ADMIN_USER", "admin")
        existing = db.query(AdminUser).filter(AdminUser.username == username).first()
        if existing:
            print(f"Compte admin '{username}' déjà existant, rien à faire.")
            return

        password = os.environ.get("TRUSTNUM_ADMIN_PASSWORD")
        generated = False
        if not password:
            password = secrets.token_urlsafe(12)
            generated = True

        admin = AdminUser(username=username, password_hash=hash_password(password))
        db.add(admin)
        db.commit()
        print(f"Base de données initialisée. Compte modérateur créé : {username}")
        if generated:
            print(f"Mot de passe généré (à noter, non ré-affiché) : {password}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
