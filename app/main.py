"""TrustNum — plateforme de vérification de numéros pour éviter les arnaques
téléphoniques / Mobile Money au Bénin.

Point de départ MVP défini avec l'utilisateur : recherche d'un numéro,
signalement avec mécanismes anti-abus (corroboration, tentative de recontact,
droit de réponse), modération humaine avant publication, pages légales
corrigeant les failles identifiées chez le concurrent (DénonceTonScammeur).
"""
import os
import time
import datetime
from typing import Optional

from fastapi import FastAPI, Request, Depends, Form, UploadFile, File, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse, PlainTextResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import func

from .database import engine, SessionLocal, get_db
from .models import (
    PhoneNumber, Alias, Report, Evidence, Contestation, AdminUser,
    ReportStatus, NotificationStatus,
)
from . import scoring, utils
from .security import verify_password

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

app = FastAPI(title="TrustNum")
# Le schéma est géré par Alembic (dossier migrations/), pas par create_all :
# exécuter `alembic upgrade head` avant le premier lancement et à chaque mise à jour.

SECRET_KEY = os.environ.get("TRUSTNUM_SECRET_KEY")
if not SECRET_KEY:
    # Avertissement explicite plutôt qu'un échec silencieux : à fixer avant toute
    # mise en production réelle (checklist sécurité, point 8.3).
    import secrets as _secrets
    SECRET_KEY = _secrets.token_hex(32)
    print("ATTENTION : TRUSTNUM_SECRET_KEY non définie, une clé temporaire a été générée. "
          "Les sessions ne survivront pas à un redémarrage. Définissez cette variable "
          "d'environnement avant la mise en production.")

app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY, same_site="lax")
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")

templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))
templates.env.globals["now_ts"] = lambda: time.time()
templates.env.globals["current_year"] = lambda: datetime.datetime.utcnow().year

SITE_NAME = "TrustNum"
CONTACT_EMAIL = os.environ.get("TRUSTNUM_CONTACT_EMAIL", "contact@trustnum.example")

SCAM_TYPES = [
    ("depot_sans_livraison", "Dépôt / paiement sans livraison du produit ou service"),
    ("faux_support_technique", "Faux support technique / faux agent opérateur"),
    ("fausse_promotion", "Fausse promotion / concours frauduleux"),
    ("usurpation_identite", "Usurpation d'identité (entreprise ou particulier)"),
    ("arnaque_sentimentale", "Arnaque sentimentale"),
    ("faux_investissement", "Faux investissement / pyramide financière"),
    ("phishing", "Hameçonnage (demande de code, de PIN Mobile Money...)"),
    ("fausse_livraison", "Faux livreur / rançon à la livraison"),
    ("autre", "Autre"),
]
CONTACT_CHANNELS = [
    ("tiktok", "Vidéo / compte TikTok"),
    ("facebook", "Facebook (page, groupe, marketplace)"),
    ("instagram", "Instagram"),
    ("whatsapp", "WhatsApp direct"),
    ("site_web", "Site web"),
    ("bouche_a_oreille", "Recommandation / bouche-à-oreille"),
    ("autre", "Autre"),
]
RECONTACT_OUTCOMES = [
    ("silence_total", "Silence total, plus aucune réponse"),
    ("blocage", "Le contact m'a bloqué"),
    ("promesses_sans_suite", "Promesses répétées jamais tenues"),
    ("reponse_partielle", "Réponse obtenue, litige en cours de discussion"),
]


# --------------------------------------------------------------------------
# Aide : authentification admin par session
# --------------------------------------------------------------------------

def require_admin(request: Request, db: Session = Depends(get_db)) -> AdminUser:
    admin_id = request.session.get("admin_id")
    if not admin_id:
        raise HTTPException(status_code=status.HTTP_303_SEE_OTHER, headers={"Location": "/admin/connexion"})
    admin = db.query(AdminUser).filter(AdminUser.id == admin_id).first()
    if not admin:
        raise HTTPException(status_code=status.HTTP_303_SEE_OTHER, headers={"Location": "/admin/connexion"})
    return admin


def recompute_and_cache(db: Session, phone_number: PhoneNumber) -> dict:
    result = scoring.compute_score(phone_number.reports)
    phone_number.score = result["score"]
    phone_number.score_tier = result["tier"]
    db.add(phone_number)
    db.commit()
    return result


# --------------------------------------------------------------------------
# Pages publiques
# --------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
def accueil(request: Request, db: Session = Depends(get_db)):
    total_numeros = db.query(func.count(PhoneNumber.id)).scalar() or 0
    total_signalements = db.query(func.count(Report.id)).filter(Report.status == ReportStatus.PUBLIE).scalar() or 0
    return templates.TemplateResponse(request, "index.html", {
        "total_numeros": total_numeros,
        "total_signalements": total_signalements,
    })


@app.get("/rechercher", response_class=HTMLResponse)
def rechercher_formulaire(request: Request, numero: Optional[str] = None):
    if numero:
        normalized = utils.normalize_phone_number(numero)
        if normalized:
            return RedirectResponse(url=f"/numero/{normalized.lstrip('+')}", status_code=303)
    return templates.TemplateResponse(request, "rechercher.html", {"erreur": bool(numero)})


@app.get("/numero/{number}", response_class=HTMLResponse)
def fiche_numero(request: Request, number: str, db: Session = Depends(get_db)):
    normalized = utils.normalize_phone_number(number)
    if not normalized:
        raise HTTPException(status_code=404)

    phone = db.query(PhoneNumber).filter(PhoneNumber.number == normalized).first()
    if not phone:
        return templates.TemplateResponse(request, "numero_inconnu.html", {"numero": normalized})

    result = recompute_and_cache(db, phone)
    published_reports = [r for r in phone.reports if r.status == ReportStatus.PUBLIE]
    published_reports.sort(key=lambda r: r.created_at, reverse=True)

    return templates.TemplateResponse(request, "numero_detail.html", {
        "numero": normalized,
        "phone": phone,
        "score": result,
        "reports": published_reports,
        "aliases": phone.aliases,
        "scam_type_labels": dict(SCAM_TYPES),
        "channel_labels": dict(CONTACT_CHANNELS),
        "recontact_labels": dict(RECONTACT_OUTCOMES),
    })


@app.get("/signaler", response_class=HTMLResponse)
def signaler_formulaire(request: Request):
    return templates.TemplateResponse(request, "signaler.html", {
        "scam_types": SCAM_TYPES,
        "contact_channels": CONTACT_CHANNELS,
        "recontact_outcomes": RECONTACT_OUTCOMES,
        "erreurs": [],
        "valeurs": {},
    })


@app.post("/signaler", response_class=HTMLResponse)
async def signaler_soumission(
    request: Request,
    db: Session = Depends(get_db),
    numero_signale: str = Form(...),
    alias_plateforme: Optional[str] = Form(None),
    alias_identifiant: Optional[str] = Form(None),
    scam_type: str = Form(...),
    first_contact_channel: str = Form(...),
    story: str = Form(...),
    amount_lost: Optional[str] = Form(None),
    recontact_attempted: Optional[str] = Form(None),
    recontact_outcome: Optional[str] = Form(None),
    declarant_name: Optional[str] = Form(None),
    declarant_email: Optional[str] = Form(None),
    declarant_phone: Optional[str] = Form(None),
    site_internet: Optional[str] = Form(None),   # honeypot
    rendered_at: Optional[str] = Form(None),
    evidences: list[UploadFile] = File(default=[]),
):
    erreurs = []

    # Anti-spam : honeypot + délai minimum de remplissage, rejet silencieux côté UX
    if utils.is_honeypot_filled(site_internet) or utils.is_submitted_too_fast(
        float(rendered_at) if rendered_at else None
    ):
        return templates.TemplateResponse(request, "signaler_merci.html", {"filtre": True})

    normalized = utils.normalize_phone_number(numero_signale)
    if not normalized:
        erreurs.append("Le numéro signalé semble invalide. Vérifiez le format (ex. +229XXXXXXXX).")

    if len(story.strip()) < 30:
        erreurs.append("Le récit est trop court pour être examiné sérieusement par la modération (30 caractères minimum).")

    recontact_bool = recontact_attempted == "oui"
    if recontact_bool and not recontact_outcome:
        erreurs.append("Précisez ce qui s'est passé lors de votre tentative de recontact.")

    if evidences and len(evidences) > utils.MAX_EVIDENCE_FILES:
        erreurs.append(f"Maximum {utils.MAX_EVIDENCE_FILES} fichiers joints.")

    if erreurs:
        return templates.TemplateResponse(request, "signaler.html", {
            "scam_types": SCAM_TYPES,
            "contact_channels": CONTACT_CHANNELS,
            "recontact_outcomes": RECONTACT_OUTCOMES,
            "erreurs": erreurs,
            "valeurs": {
                "numero_signale": numero_signale, "scam_type": scam_type,
                "first_contact_channel": first_contact_channel, "story": story,
                "amount_lost": amount_lost, "recontact_attempted": recontact_attempted,
                "recontact_outcome": recontact_outcome, "alias_plateforme": alias_plateforme,
                "alias_identifiant": alias_identifiant,
            },
        }, status_code=422)

    phone = db.query(PhoneNumber).filter(PhoneNumber.number == normalized).first()
    if not phone:
        phone = PhoneNumber(number=normalized)
        db.add(phone)
        db.flush()

    if alias_plateforme and alias_identifiant:
        exists = db.query(Alias).filter(
            Alias.phone_number_id == phone.id, Alias.handle == alias_identifiant.strip()
        ).first()
        if not exists:
            db.add(Alias(phone_number_id=phone.id, platform=alias_plateforme, handle=alias_identifiant.strip()))

    amount_int = None
    if amount_lost:
        try:
            amount_int = int(float(amount_lost.replace(" ", "").replace(",", ".")))
        except ValueError:
            amount_int = None

    report = Report(
        phone_number_id=phone.id,
        scam_type=scam_type,
        first_contact_channel=first_contact_channel,
        story=story.strip(),
        amount_lost=amount_int,
        recontact_attempted=recontact_bool,
        recontact_outcome=recontact_outcome if recontact_bool else None,
        declarant_name=(declarant_name or "").strip() or None,
        declarant_email=(declarant_email or "").strip() or None,
        declarant_phone=(declarant_phone or "").strip() or None,
        status=ReportStatus.EN_ATTENTE,
    )
    db.add(report)
    db.flush()

    saved = 0
    for ev in evidences or []:
        if not ev.filename:
            continue
        if saved >= utils.MAX_EVIDENCE_FILES:
            break
        content = await ev.read()
        if len(content) > utils.MAX_EVIDENCE_SIZE_BYTES:
            continue
        if ev.content_type not in utils.ALLOWED_EVIDENCE_TYPES:
            continue
        stored_name = utils.safe_storage_filename(ev.filename)
        with open(os.path.join(UPLOAD_DIR, stored_name), "wb") as f:
            f.write(content)
        db.add(Evidence(
            report_id=report.id, original_filename=ev.filename,
            stored_path=stored_name, content_type=ev.content_type,
        ))
        saved += 1

    db.commit()
    return templates.TemplateResponse(request, "signaler_merci.html", {"filtre": False, "numero": normalized})


@app.get("/contester", response_class=HTMLResponse)
def contester_formulaire(request: Request, numero: Optional[str] = None):
    return templates.TemplateResponse(request, "contester.html", {"numero": numero or "", "erreurs": []})


@app.post("/contester", response_class=HTMLResponse)
def contester_soumission(
    request: Request,
    db: Session = Depends(get_db),
    numero: str = Form(...),
    message: str = Form(...),
    contact_email: str = Form(...),
    site_internet: Optional[str] = Form(None),
):
    if utils.is_honeypot_filled(site_internet):
        return templates.TemplateResponse(request, "contester_merci.html", {})

    erreurs = []
    normalized = utils.normalize_phone_number(numero)
    if not normalized:
        erreurs.append("Numéro invalide.")
    if "@" not in (contact_email or ""):
        erreurs.append("Adresse email invalide — nécessaire pour vous recontacter.")
    if len(message.strip()) < 20:
        erreurs.append("Expliquez votre contestation plus en détail (20 caractères minimum).")

    if erreurs:
        return templates.TemplateResponse(request, "contester.html", {
            "numero": numero, "erreurs": erreurs,
        }, status_code=422)

    phone = db.query(PhoneNumber).filter(PhoneNumber.number == normalized).first()
    if phone:
        for r in phone.reports:
            if r.status == ReportStatus.PUBLIE:
                r.notification_status = NotificationStatus.CONTESTEE
        db.add(Contestation(
            phone_number_id=phone.id, message=message.strip(), contact_email=contact_email.strip(),
        ))
        db.commit()

    return templates.TemplateResponse(request, "contester_merci.html", {})


@app.get("/statistiques", response_class=HTMLResponse)
def statistiques(request: Request, db: Session = Depends(get_db)):
    total_numeros = db.query(func.count(PhoneNumber.id)).scalar() or 0
    total_publies = db.query(func.count(Report.id)).filter(Report.status == ReportStatus.PUBLIE).scalar() or 0
    total_en_attente = db.query(func.count(Report.id)).filter(Report.status == ReportStatus.EN_ATTENTE).scalar() or 0
    par_type = (
        db.query(Report.scam_type, func.count(Report.id))
        .filter(Report.status == ReportStatus.PUBLIE)
        .group_by(Report.scam_type).all()
    )
    return templates.TemplateResponse(request, "statistiques.html", {
        "total_numeros": total_numeros, "total_publies": total_publies,
        "total_en_attente": total_en_attente, "par_type": par_type,
        "scam_type_labels": dict(SCAM_TYPES),
    })


@app.get("/comment-ca-marche", response_class=HTMLResponse)
def comment_ca_marche(request: Request):
    return templates.TemplateResponse(request, "comment_ca_marche.html", {})


@app.get("/a-propos", response_class=HTMLResponse)
def a_propos(request: Request):
    return templates.TemplateResponse(request, "a_propos.html", {})


@app.get("/contact", response_class=HTMLResponse)
def contact(request: Request):
    return templates.TemplateResponse(request, "contact.html", {"contact_email": CONTACT_EMAIL})


@app.get("/mentions-legales", response_class=HTMLResponse)
def mentions_legales(request: Request):
    return templates.TemplateResponse(request, "legal/mentions-legales.html", {"contact_email": CONTACT_EMAIL})


@app.get("/confidentialite", response_class=HTMLResponse)
def confidentialite(request: Request):
    return templates.TemplateResponse(request, "legal/confidentialite.html", {"contact_email": CONTACT_EMAIL})


@app.get("/cgu", response_class=HTMLResponse)
def cgu(request: Request):
    return templates.TemplateResponse(request, "legal/cgu.html", {"contact_email": CONTACT_EMAIL})


@app.get("/robots.txt", response_class=PlainTextResponse)
def robots_txt(request: Request):
    base = str(request.base_url).rstrip("/")
    return f"User-agent: *\nAllow: /\nDisallow: /admin\nSitemap: {base}/sitemap.xml\n"


@app.get("/sitemap.xml")
def sitemap_xml(request: Request, db: Session = Depends(get_db)):
    base = str(request.base_url).rstrip("/")
    static_paths = [
        "/", "/rechercher", "/signaler", "/contester", "/statistiques",
        "/comment-ca-marche", "/a-propos", "/contact",
        "/mentions-legales", "/confidentialite", "/cgu",
    ]
    urls = "".join(f"<url><loc>{base}{p}</loc></url>" for p in static_paths)
    xml = f'<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls}</urlset>'
    return HTMLResponse(content=xml, media_type="application/xml")


# --------------------------------------------------------------------------
# Espace de modération
# --------------------------------------------------------------------------

@app.get("/admin/connexion", response_class=HTMLResponse)
def admin_connexion_formulaire(request: Request):
    if request.session.get("admin_id"):
        return RedirectResponse(url="/admin", status_code=303)
    return templates.TemplateResponse(request, "admin/login.html", {"erreur": False})


@app.post("/admin/connexion", response_class=HTMLResponse)
def admin_connexion_soumission(
    request: Request, db: Session = Depends(get_db),
    username: str = Form(...), password: str = Form(...),
):
    admin = db.query(AdminUser).filter(AdminUser.username == username).first()
    if not admin or not verify_password(password, admin.password_hash):
        return templates.TemplateResponse(request, "admin/login.html", {"erreur": True}, status_code=401)
    request.session["admin_id"] = admin.id
    return RedirectResponse(url="/admin", status_code=303)


@app.get("/admin/deconnexion")
def admin_deconnexion(request: Request):
    request.session.clear()
    return RedirectResponse(url="/admin/connexion", status_code=303)


@app.get("/admin", response_class=HTMLResponse)
def admin_file_attente(request: Request, db: Session = Depends(get_db), admin: AdminUser = Depends(require_admin)):
    en_attente = (
        db.query(Report).filter(Report.status == ReportStatus.EN_ATTENTE)
        .order_by(Report.created_at.asc()).all()
    )
    contestations_ouvertes = (
        db.query(Contestation).filter(Contestation.status == "ouvert")
        .order_by(Contestation.created_at.asc()).all()
    )
    return templates.TemplateResponse(request, "admin/queue.html", {
        "admin": admin, "reports": en_attente, "contestations": contestations_ouvertes,
    })


@app.get("/admin/signalement/{report_id}", response_class=HTMLResponse)
def admin_detail_signalement(
    report_id: int, request: Request, db: Session = Depends(get_db),
    admin: AdminUser = Depends(require_admin),
):
    report = db.query(Report).filter(Report.id == report_id).first()
    if not report:
        raise HTTPException(status_code=404)
    return templates.TemplateResponse(request, "admin/report_detail.html", {
        "admin": admin, "report": report, "scam_type_labels": dict(SCAM_TYPES),
        "channel_labels": dict(CONTACT_CHANNELS),
    })


@app.post("/admin/signalement/{report_id}/approuver")
def admin_approuver(
    report_id: int, request: Request, db: Session = Depends(get_db),
    admin: AdminUser = Depends(require_admin), note: Optional[str] = Form(None),
):
    report = db.query(Report).filter(Report.id == report_id).first()
    if not report:
        raise HTTPException(status_code=404)
    report.status = ReportStatus.PUBLIE
    report.moderator_note = note
    report.moderated_at = datetime.datetime.utcnow()
    scoring.schedule_notification(report)
    db.commit()
    recompute_and_cache(db, report.phone_number)
    return RedirectResponse(url="/admin", status_code=303)


@app.post("/admin/signalement/{report_id}/rejeter")
def admin_rejeter(
    report_id: int, request: Request, db: Session = Depends(get_db),
    admin: AdminUser = Depends(require_admin), note: Optional[str] = Form(None),
):
    report = db.query(Report).filter(Report.id == report_id).first()
    if not report:
        raise HTTPException(status_code=404)
    report.status = ReportStatus.REJETE
    report.moderator_note = note
    report.moderated_at = datetime.datetime.utcnow()
    db.commit()
    recompute_and_cache(db, report.phone_number)
    return RedirectResponse(url="/admin", status_code=303)


@app.post("/admin/contestation/{contestation_id}/traiter")
def admin_traiter_contestation(
    contestation_id: int, request: Request, db: Session = Depends(get_db),
    admin: AdminUser = Depends(require_admin),
):
    cont = db.query(Contestation).filter(Contestation.id == contestation_id).first()
    if not cont:
        raise HTTPException(status_code=404)
    cont.status = "traite"
    db.commit()
    return RedirectResponse(url="/admin", status_code=303)


@app.get("/admin/preuve/{evidence_id}")
def admin_telecharger_preuve(
    evidence_id: int, db: Session = Depends(get_db), admin: AdminUser = Depends(require_admin),
):
    ev = db.query(Evidence).filter(Evidence.id == evidence_id).first()
    if not ev:
        raise HTTPException(status_code=404)
    path = os.path.join(UPLOAD_DIR, ev.stored_path)
    if not os.path.exists(path):
        raise HTTPException(status_code=404)
    return FileResponse(path, media_type=ev.content_type, filename=ev.original_filename)


# --------------------------------------------------------------------------
# Gestion d'erreurs
# --------------------------------------------------------------------------

@app.exception_handler(404)
async def not_found(request: Request, exc):
    return templates.TemplateResponse(request, "404.html", {}, status_code=404)
