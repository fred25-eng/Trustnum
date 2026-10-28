"""Logique de score — cœur de la différenciation produit définie dans le cadrage.

Principes non négociables (décidés avant le code, à respecter dans toute évolution) :
1. Le score ne doit jamais affirmer un fait non prouvable. Il agrège du signal,
   il ne rend pas un jugement ("ce numéro a arnaqué X personnes" est interdit ;
   "N signalements indépendants corroborés" est autorisé).
2. Un signalement isolé ne peut jamais produire un score élevé, même avec preuves.
3. Le silence après une tentative de recontact documentée par le déclarant pèse
   plus qu'une simple déclaration de non-livraison.
4. Le silence du numéro signalé après notification (droit de réponse) renforce
   le signal — il ne le crée pas à lui seul.
5. Le score est plafonné à 98/100 : jamais de certitude absolue affichée.
"""
import datetime
from .models import Report, ReportStatus, NotificationStatus

RECONTACT_WEIGHTS = {
    "silence_total": 1.0,
    "blocage": 1.0,
    "promesses_sans_suite": 0.75,
    "reponse_partielle": 0.35,
}
DEFAULT_WEIGHT_NO_RECONTACT = 0.45
DEFAULT_WEIGHT_UNKNOWN_OUTCOME = 0.5
NOTIFICATION_SILENCE_MULTIPLIER = 1.25
MAX_REPORT_WEIGHT = 1.25
ISOLATED_SCORE_CAP = 25
CORROBORATED_SCORE_FLOOR = 30
CORROBORATED_SCORE_CAP = 98

RESPONSE_DELAY_DAYS = 5  # délai de droit de réponse avant qu'un signalement pèse pleinement


def effective_notification_status(report: Report) -> NotificationStatus:
    """Calcule le statut de notification réel, y compris quand le délai est dépassé
    sans mise à jour manuelle (pas de tâche planifiée dans ce MVP)."""
    if report.notification_status == NotificationStatus.ENVOYEE and report.response_deadline:
        if datetime.datetime.utcnow() > report.response_deadline:
            return NotificationStatus.SANS_REPONSE
    return report.notification_status


def _report_weight(report: Report) -> float:
    if not report.recontact_attempted:
        weight = DEFAULT_WEIGHT_NO_RECONTACT
    else:
        key = (report.recontact_outcome or "").strip().lower()
        weight = RECONTACT_WEIGHTS.get(key, DEFAULT_WEIGHT_UNKNOWN_OUTCOME)

    if effective_notification_status(report) == NotificationStatus.SANS_REPONSE:
        weight *= NOTIFICATION_SILENCE_MULTIPLIER

    return min(weight, MAX_REPORT_WEIGHT)


def compute_score(reports: list[Report]) -> dict:
    published = [r for r in reports if r.status == ReportStatus.PUBLIE]
    n = len(published)

    if n == 0:
        return {
            "score": 0,
            "tier": "aucun_signalement",
            "label": "Aucun signalement publié pour ce numéro à ce jour.",
            "published_count": 0,
        }

    total_weight = sum(_report_weight(r) for r in published)

    if n == 1:
        score = min(ISOLATED_SCORE_CAP, round(total_weight * 20))
        return {
            "score": score,
            "tier": "isole",
            "label": "1 signalement non corroboré — à vérifier, ne constitue pas une preuve.",
            "published_count": n,
        }

    raw = CORROBORATED_SCORE_CAP * (1 - pow(0.5, total_weight))
    score = max(CORROBORATED_SCORE_FLOOR, min(CORROBORATED_SCORE_CAP, round(raw)))

    if score < 55:
        tier, mot = "modere", "risque modéré"
    elif score < 80:
        tier, mot = "eleve", "risque élevé"
    else:
        tier, mot = "tres_eleve", "risque très élevé"

    return {
        "score": score,
        "tier": tier,
        "label": f"{n} signalements indépendants corroborés — {mot}.",
        "published_count": n,
    }


def schedule_notification(report: Report) -> None:
    """À appeler quand un modérateur approuve un signalement : ouvre le délai
    de droit de réponse avant que le signalement pèse pleinement dans le score.
    L'envoi réel (SMS/WhatsApp) n'est pas implémenté dans ce MVP : brancher un
    fournisseur local (ex. passerelle SMS béninoise) sur ce point d'extension."""
    report.notification_status = NotificationStatus.A_ENVOYER
    report.response_deadline = datetime.datetime.utcnow() + datetime.timedelta(days=RESPONSE_DELAY_DAYS)
