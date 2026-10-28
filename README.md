# TrustNum — MVP

Plateforme de vérification de numéros de téléphone / Mobile Money pour éviter les
arnaques au dépôt, Bénin d'abord. Voir `cadrage-projet.md` (dans le projet Claude
attaché) pour l'historique des décisions produit et juridiques.

## Portée de ce premier jet

Construit : recherche d'un numéro, signalement avec mécanismes anti-abus
(corroboration, tentative de recontact, droit de réponse), modération humaine,
pages légales (mentions légales, confidentialité, CGU) corrigeant les failles
identifiées chez le concurrent, statistiques, pages techniques de base
(robots.txt, sitemap.xml, 404, favicon).

Volontairement pas construit à ce stade, car ça n'a de sens qu'avec du volume
réel : Elasticsearch, file de messages (Kafka/RabbitMQ), scoring par
machine learning, phase 2 réseaux sociaux complète, envoi réel de SMS/WhatsApp
pour le droit de réponse (le code prévoit le point d'extension, voir
`app/scoring.py::schedule_notification`).

## Lancer en local

Base de données : PostgreSQL (pas de mode SQLite dans ce projet — le code est
écrit pour tourner comme en production dès le dev local).

```bash
cd trustnum
docker compose up -d          # lance PostgreSQL dans un conteneur
pip install -r requirements.txt

alembic upgrade head          # crée les tables (ne jamais utiliser create_all)
TRUSTNUM_ADMIN_PASSWORD='change-moi' python3 -m app.seed

TRUSTNUM_SECRET_KEY='une-longue-valeur-aleatoire' uvicorn app.main:app --reload
```

`docker-compose.yml` démarre Postgres avec les identifiants par défaut déjà
attendus par `app/database.py` (`trustnum`/`trustnum`, base `trustnum`,
port 5432). Change ces identifiants avant toute mise en ligne réelle via
`DATABASE_URL`.

### Modifier le schéma (ajouter un champ, une table...)

```bash
# après avoir modifié app/models.py
alembic revision --autogenerate -m "description du changement"
alembic upgrade head
```

Le site est alors sur http://127.0.0.1:8000, l'espace de modération sur
`/admin/connexion` (identifiant `admin`, mot de passe celui défini ci-dessus).

## Variables d'environnement

| Variable | Rôle | Défaut |
|---|---|---|
| `DATABASE_URL` | Connexion PostgreSQL | `postgresql+psycopg://trustnum:trustnum@localhost:5432/trustnum` |
| `TRUSTNUM_SECRET_KEY` | Signature des sessions admin | générée au hasard si absente (sessions perdues au redémarrage — à fixer avant la mise en ligne) |
| `TRUSTNUM_ADMIN_USER` / `TRUSTNUM_ADMIN_PASSWORD` | Compte de modération initial | `admin` / généré aléatoirement si absent |
| `TRUSTNUM_CONTACT_EMAIL` | Email affiché sur les pages contact/légales | `contact@trustnum.example` |

## Avant une mise en ligne réelle (reprise de la checklist de base)

Ce qui est déjà géré dans le code : HTML sémantique, responsive mobile-first,
formulaires validés côté serveur, protection anti-spam (honeypot + délai
minimum), ORM paramétré (protection injection SQL) et échappement Jinja2
automatique (protection XSS), fichiers de téléversement limités en taille/type
et jamais servis publiquement, 404 personnalisée, favicon, robots.txt,
sitemap.xml, balises Open Graph.

Restent à faire avant une ouverture publique, et volontairement laissés de
côté pour ce premier jet :

1. **Compléter les mentions légales** (`app/templates/legal/mentions-legales.html`)
   avec la véritable identité de l'exploitant — idéalement une entité déclarée,
   pas une personne anonyme (voir le cadrage pour pourquoi).
2. **HTTPS** via un reverse proxy (Caddy/Nginx + Let's Encrypt) ou l'hébergeur choisi.
3. **PostgreSQL managé en production** (Railway, Render, Supabase...) plutôt que le conteneur Docker local — changer `DATABASE_URL`, rien d'autre.
4. **Authentification à deux facteurs** pour l'espace de modération, avant d'ouvrir
   des comptes à plusieurs modérateurs.
5. **Brancher un vrai envoi SMS/WhatsApp** pour le droit de réponse (actuellement
   simulé : le délai est calculé mais aucun message n'est réellement envoyé).
6. **Tâche planifiée de purge** des coordonnées de déclarants et pièces jointes
   selon les durées annoncées dans `/confidentialite`.
7. **Sauvegardes régulières** de la base de données et des pièces jointes.
8. Déclarer le site dans Google Search Console et, si souhaité, un outil de
   statistiques respectueux de la vie privée (ex. Plausible) — volontairement
   non intégré pour ne pas ajouter de traqueur avant que la politique de
   confidentialité réelle ne le prévoie explicitement.

## Structure

```
app/
  main.py          routes FastAPI
  models.py        modèles SQLAlchemy (PhoneNumber = identifiant central)
  scoring.py        logique de score par corroboration (cœur du produit)
  security.py       hachage de mot de passe (admin)
  utils.py           normalisation de numéro, anti-spam, validation fichiers
  seed.py             crée le compte admin (après alembic upgrade head)
  templates/          pages Jinja2
  static/             CSS/JS/favicon
migrations/           schéma de base de données (Alembic) — jamais create_all()
docker-compose.yml    PostgreSQL local pour le dev
```
