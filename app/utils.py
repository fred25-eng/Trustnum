"""Fonctions utilitaires : normalisation de numéro, validation de fichiers, anti-spam."""
import re
import time
import uuid
import os

ALLOWED_EVIDENCE_TYPES = {
    "image/png", "image/jpeg", "image/webp", "application/pdf",
}
MAX_EVIDENCE_SIZE_BYTES = 4 * 1024 * 1024  # 4 Mo, aligné sur la pratique du concurrent
MAX_EVIDENCE_FILES = 10


def normalize_phone_number(raw: str, default_country_prefix: str = "+229") -> str | None:
    """Normalise un numéro béninois (ou international) vers un format E.164 simplifié.
    Retourne None si le numéro est manifestement invalide (trop court/trop long)."""
    if not raw:
        return None
    cleaned = re.sub(r"[\s().-]", "", raw.strip())
    if cleaned.startswith("00"):
        cleaned = "+" + cleaned[2:]
    if not cleaned.startswith("+"):
        # Numéro local béninois sans indicatif (8 chiffres typiquement)
        digits = re.sub(r"\D", "", cleaned)
        if len(digits) <= 9:
            cleaned = default_country_prefix + digits
        else:
            cleaned = "+" + digits
    digits_only = re.sub(r"\D", "", cleaned)
    if len(digits_only) < 8 or len(digits_only) > 15:
        return None
    return "+" + digits_only


def is_honeypot_filled(honeypot_value: str | None) -> bool:
    """Champ caché aux humains (CSS) mais visible aux robots de spam."""
    return bool(honeypot_value and honeypot_value.strip())


def is_submitted_too_fast(form_rendered_at: float | None, min_seconds: float = 3.0) -> bool:
    """Anti-spam léger : un formulaire rempli en moins de quelques secondes est suspect."""
    if form_rendered_at is None:
        return False
    try:
        return (time.time() - float(form_rendered_at)) < min_seconds
    except (TypeError, ValueError):
        return False


def safe_storage_filename(original_filename: str) -> str:
    ext = os.path.splitext(original_filename)[1].lower()
    ext = ext if len(ext) <= 5 else ""
    return f"{uuid.uuid4().hex}{ext}"
