"""Modèles de données.

Décision de cadrage : le numéro de téléphone est l'identifiant central et unique
du système. Les comptes TikTok/Facebook/Instagram sont des alias rattachés à un
numéro (table Alias), jamais des entités indépendantes.
"""
import datetime
import enum
from sqlalchemy import (
    Column, Integer, String, Text, Boolean, DateTime, ForeignKey, Enum
)
from sqlalchemy.orm import relationship
from .database import Base


def utcnow():
    return datetime.datetime.utcnow()


class ReportStatus(str, enum.Enum):
    EN_ATTENTE = "en_attente"       # en file de modération
    PUBLIE = "publie"               # validé par la modération, visible publiquement
    REJETE = "rejete"               # rejeté par la modération (preuve insuffisante, abus...)
    RETIRE = "retire"                # publié puis retiré suite à une contestation fondée


class NotificationStatus(str, enum.Enum):
    NON_APPLICABLE = "non_applicable"
    A_ENVOYER = "a_envoyer"
    ENVOYEE = "envoyee"
    SANS_REPONSE = "sans_reponse"
    CONTESTEE = "contestee"


class PhoneNumber(Base):
    """Identifiant central. Un numéro = une fiche, quel que soit le nombre d'alias."""
    __tablename__ = "phone_numbers"

    id = Column(Integer, primary_key=True)
    number = Column(String(32), unique=True, index=True, nullable=False)  # format E.164, ex: +229XXXXXXXX
    created_at = Column(DateTime, default=utcnow)

    # Champs cache, recalculés par scoring.recompute_score() à chaque changement d'état d'un signalement
    score = Column(Integer, default=0)
    score_tier = Column(String(32), default="aucun_signalement")

    aliases = relationship("Alias", back_populates="phone_number", cascade="all, delete-orphan")
    reports = relationship("Report", back_populates="phone_number", cascade="all, delete-orphan")
    contestations = relationship("Contestation", back_populates="phone_number", cascade="all, delete-orphan")


class Alias(Base):
    """Compte réseau social rattaché à un numéro (TikTok, Facebook, Instagram, site web...)."""
    __tablename__ = "aliases"

    id = Column(Integer, primary_key=True)
    phone_number_id = Column(Integer, ForeignKey("phone_numbers.id"), nullable=False)
    platform = Column(String(32), nullable=False)   # tiktok, facebook, instagram, whatsapp, site_web, autre
    handle = Column(String(255), nullable=False)     # @pseudo ou URL
    created_at = Column(DateTime, default=utcnow)

    phone_number = relationship("PhoneNumber", back_populates="aliases")


class Report(Base):
    """Signalement. Ne constitue jamais une accusation nominative publiée :
    seul le contact (numéro/alias) est exposé publiquement, jamais l'identité
    du déclarant ni un nom affirmé comme coupable (cf. pratique retenue de
    DénonceTonScammeur, corrigée sur le reste)."""
    __tablename__ = "reports"

    id = Column(Integer, primary_key=True)
    phone_number_id = Column(Integer, ForeignKey("phone_numbers.id"), nullable=False)

    scam_type = Column(String(64), nullable=False)
    first_contact_channel = Column(String(32), nullable=False)  # tiktok, facebook, instagram, whatsapp, site_web, bouche_a_oreille, autre
    story = Column(Text, nullable=False)
    amount_lost = Column(Integer, nullable=True)
    currency = Column(String(8), default="XOF")

    # Anti-abus : distinguer une arnaque (silence après paiement) d'un simple litige commercial
    recontact_attempted = Column(Boolean, nullable=False, default=False)
    recontact_outcome = Column(Text, nullable=True)  # silence_total, blocage, promesses_sans_suite, reponse_partielle...

    # Coordonnées du déclarant : jamais publiées, utiles seulement à la modération et à la notification
    declarant_name = Column(String(128), nullable=True)
    declarant_email = Column(String(128), nullable=True)
    declarant_phone = Column(String(32), nullable=True)

    status = Column(Enum(ReportStatus), default=ReportStatus.EN_ATTENTE, nullable=False)
    moderator_note = Column(Text, nullable=True)
    moderated_at = Column(DateTime, nullable=True)

    # Droit de réponse : le numéro signalé dispose d'un délai avant que le signalement
    # pèse pleinement dans le score public.
    notification_status = Column(Enum(NotificationStatus), default=NotificationStatus.NON_APPLICABLE)
    notification_sent_at = Column(DateTime, nullable=True)
    response_deadline = Column(DateTime, nullable=True)

    created_at = Column(DateTime, default=utcnow)

    phone_number = relationship("PhoneNumber", back_populates="reports")
    evidences = relationship("Evidence", back_populates="report", cascade="all, delete-orphan")


class Evidence(Base):
    """Pièce jointe d'un signalement. Jamais exposée publiquement, réservée à la modération."""
    __tablename__ = "evidences"

    id = Column(Integer, primary_key=True)
    report_id = Column(Integer, ForeignKey("reports.id"), nullable=False)
    original_filename = Column(String(255), nullable=False)
    stored_path = Column(String(512), nullable=False)
    content_type = Column(String(128), nullable=True)
    uploaded_at = Column(DateTime, default=utcnow)

    report = relationship("Report", back_populates="evidences")


class Contestation(Base):
    """Canal de contestation : une personne qui s'estime signalée à tort."""
    __tablename__ = "contestations"

    id = Column(Integer, primary_key=True)
    phone_number_id = Column(Integer, ForeignKey("phone_numbers.id"), nullable=False)
    report_id = Column(Integer, ForeignKey("reports.id"), nullable=True)
    message = Column(Text, nullable=False)
    contact_email = Column(String(128), nullable=False)
    status = Column(String(32), default="ouvert")  # ouvert, en_cours, traite
    created_at = Column(DateTime, default=utcnow)

    phone_number = relationship("PhoneNumber", back_populates="contestations")


class AdminUser(Base):
    """Compte de modération. Authentification par session, mot de passe haché."""
    __tablename__ = "admin_users"

    id = Column(Integer, primary_key=True)
    username = Column(String(64), unique=True, nullable=False)
    password_hash = Column(String(256), nullable=False)
    created_at = Column(DateTime, default=utcnow)
