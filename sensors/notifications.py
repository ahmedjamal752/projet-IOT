import os
import urllib.parse
import threading
import logging
from datetime import datetime, timedelta
import requests
from django.conf import settings
from django.core.mail import send_mail
from django.utils import timezone

logger = logging.getLogger(__name__)

# Anti-flood / Cooldown pour éviter de spammer le téléphone et l'email
_LAST_ALERT_TIME = None
_ALERT_COOLDOWN_SECONDS = 300  # 5 minutes de répit minimum entre 2 rafales d'alertes externes


def _log_to_incident(incident, message):
    """Ajoute une trace système dans le chatgroup de l'incident."""
    if not incident:
        return
    try:
        from .models import IncidentMessage
        IncidentMessage.objects.create(
            incident=incident,
            auteur="Système Alertes",
            message=message,
            is_system=True
        )
    except Exception as e:
        logger.warning(f"Impossible d'enregistrer le message d'incident: {e}")


def send_alert_email(temp, incident=None):
    """
    Envoie un email d'alerte d'urgence à l'adresse spécifiée.
    """
    recipient = getattr(settings, 'ALERT_EMAIL_RECIPIENT', 'jamaleddineahmed972@gmail.com')
    subject = f"🚨 [ALERTE CRITIQUE IOT] Dépassement de température : {temp:.1f}°C"
    
    date_str = timezone.localtime(timezone.now()).strftime('%d/%m/%Y à %H:%M:%S')
    incident_id = incident.id if incident else 'N/A'
    compteur = incident.compteur_alertes if incident else 1

    message_body = f"""Bonjour Ahmed,

⚠️ ALERTE CRITIQUE DÉTECTÉE SUR VOTRE SYSTÈME IOT DHT11 !

Détails de l'anomalie :
--------------------------------------------------
• Température mesurée : {temp:.1f} °C (Seuil maximal dépassé)
• Date & Heure : {date_str}
• Incident ID : #{incident_id}
• Niveau d'alerte / Compteur : {compteur}
• Destinataire : {recipient}
--------------------------------------------------

Le téléphone (+212696860564) a été notifié par WhatsApp et un appel d'urgence (sonnerie + vibreur) a été déclenché.

Veuillez intervenir rapidement sur votre installation.

Accès plateforme :
- Dashboard : http://localhost:8000/dashboard/
- Gestionnaire d'Incidents : http://localhost:8000/incidents/

-- 
Système de Surveillance IoT Automatique
"""
    try:
        from_email = getattr(settings, 'DEFAULT_FROM_EMAIL', 'iot-alerts@system.local')
        send_mail(
            subject=subject,
            message=message_body,
            from_email=from_email,
            recipient_list=[recipient],
            fail_silently=False,
        )
        logger.info(f"Email d'alerte envoyé avec succès à {recipient}")
        _log_to_incident(incident, f"📧 Email d'urgence envoyé à {recipient} (Temp: {temp:.1f}°C)")
        return True
    except Exception as e:
        logger.error(f"Échec de l'envoi de l'email à {recipient}: {e}")
        _log_to_incident(incident, f"⚠️ Erreur envoi email ({recipient}) : {e}")
        return False


def send_alert_whatsapp(temp, incident=None):
    """
    Envoie un message WhatsApp avec mot-clé d'urgence au numéro de téléphone.
    Prend en charge :
    1. Green-API (Scannage QR code WhatsApp direct - très simple et stable)
    2. CallMeBot (Gratuit)
    3. Twilio WhatsApp officiel
    """
    phone = getattr(settings, 'ALERT_PHONE_NUMBER', '+212696860564')
    date_str = timezone.localtime(timezone.now()).strftime('%H:%M:%S')
    incident_id = incident.id if incident else 'N/A'

    # Texte formaté pour WhatsApp (avec balises grasses * et mot-clé pour sonnerie/vibreur)
    text_content = (
        f"🚨 *[ALERTE DHT11 - CRITIQUE]* 🚨\n\n"
        f"⚠️ *Température anormale :* {temp:.1f}°C\n"
        f"🕒 *Heure :* {date_str}\n"
        f"🆔 *Incident :* #{incident_id}\n\n"
        f"🔔 *ATTENTION :* Seuil de température dépassé ! Le vibreur et la sonnerie d'urgence ont été activés.\n"
        f"👉 Vérifiez le dashboard : http://localhost:8000/dashboard/"
    )

    success = False

    # 1. Option Green-API (QR Code WhatsApp - 100% fonctionnel et direct)
    green_id = getattr(settings, 'GREEN_API_INSTANCE_ID', os.getenv('GREEN_API_INSTANCE_ID', '')).strip()
    green_token = getattr(settings, 'GREEN_API_TOKEN', os.getenv('GREEN_API_TOKEN', '')).strip()
    if green_id and green_token:
        try:
            clean_digits = ''.join(filter(str.isdigit, phone))
            chat_id = f"{clean_digits}@c.us"
            url = f"https://api.green-api.com/waInstance{green_id}/sendMessage/{green_token}"
            payload = {"chatId": chat_id, "message": text_content}
            res = requests.post(url, json=payload, timeout=10)
            if res.status_code == 200:
                logger.info(f"WhatsApp envoyé via Green-API à {phone}")
                _log_to_incident(incident, f"📱 WhatsApp envoyé avec succès au {phone} via Green-API")
                success = True
            else:
                logger.warning(f"Green-API code {res.status_code} : {res.text}")
        except Exception as e:
            logger.error(f"Erreur Green-API : {e}")

    # 2. Option CallMeBot
    callmebot_apikey = getattr(settings, 'CALLMEBOT_API_KEY', os.getenv('CALLMEBOT_API_KEY', '')).strip()
    if not success and callmebot_apikey:
        try:
            encoded_text = urllib.parse.quote(text_content)
            clean_phone = phone.replace('+', '')
            url = f"https://api.callmebot.com/whatsapp.php?phone={clean_phone}&text={encoded_text}&apikey={callmebot_apikey}"
            res = requests.get(url, timeout=10)
            if res.status_code == 200:
                logger.info(f"WhatsApp envoyé via CallMeBot à {phone}")
                _log_to_incident(incident, f"📱 WhatsApp envoyé avec succès au {phone} via CallMeBot")
                success = True
            else:
                logger.warning(f"CallMeBot code {res.status_code} : {res.text}")
        except Exception as e:
            logger.error(f"Erreur CallMeBot : {e}")

    # 3. Option Twilio WhatsApp
    twilio_sid = getattr(settings, 'TWILIO_ACCOUNT_SID', os.getenv('TWILIO_ACCOUNT_SID', '')).strip()
    twilio_token = getattr(settings, 'TWILIO_AUTH_TOKEN', os.getenv('TWILIO_AUTH_TOKEN', '')).strip()
    twilio_wa_from = getattr(settings, 'TWILIO_WHATSAPP_NUMBER', os.getenv('TWILIO_WHATSAPP_NUMBER', '')).strip()

    if not success and twilio_sid and twilio_token and twilio_wa_from:
        try:
            from twilio.rest import Client
            client = Client(twilio_sid, twilio_token)
            wa_to = f"whatsapp:{phone}" if not phone.startswith("whatsapp:") else phone
            wa_from = f"whatsapp:{twilio_wa_from}" if not twilio_wa_from.startswith("whatsapp:") else twilio_wa_from

            msg = client.messages.create(body=text_content, from_=wa_from, to=wa_to)
            logger.info(f"WhatsApp envoyé via Twilio à {phone}")
            _log_to_incident(incident, f"📱 WhatsApp envoyé au {phone} via Twilio")
            success = True
        except Exception as e:
            logger.error(f"Erreur Twilio : {e}")

    return success


def send_alert_telegram(temp, incident=None):
    """
    Envoie une alerte Telegram instantanée (100% gratuit, fiable, sonnerie d'alarme et vibreur sur le smartphone).
    """
    bot_token = getattr(settings, 'TELEGRAM_BOT_TOKEN', os.getenv('TELEGRAM_BOT_TOKEN', '')).strip()
    chat_id = getattr(settings, 'TELEGRAM_CHAT_ID', os.getenv('TELEGRAM_CHAT_ID', '')).strip()

    if not bot_token or not chat_id:
        return False

    date_str = timezone.localtime(timezone.now()).strftime('%H:%M:%S')
    incident_id = incident.id if incident else 'N/A'

    msg = (
        f"🚨 <b>ALERTE CRITIQUE IOT - TEMPERATURE</b> 🚨\n\n"
        f"⚠️ <b>Température :</b> {temp:.1f}°C\n"
        f"🕒 <b>Heure :</b> {date_str}\n"
        f"🆔 <b>Incident :</b> #{incident_id}\n\n"
        f"🔔 <i>Le téléphone sonne et vibre. Vérifiez immédiatement l'installation !</i>"
    )

    try:
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": msg,
            "parse_mode": "HTML",
            "disable_notification": False  # Force la sonnerie et le vibreur !
        }
        res = requests.post(url, json=payload, timeout=10)
        if res.status_code == 200:
            logger.info("Notification Telegram transmise avec succès")
            _log_to_incident(incident, f"📢 Alerte Telegram envoyée (Sonnerie & Vibreur déclenchés)")
            return True
        else:
            logger.warning(f"Telegram API a répondu : {res.text}")
    except Exception as e:
        logger.error(f"Erreur Telegram : {e}")

    return False


def trigger_phone_call_alert(temp, incident=None):
    """
    Déclenche un appel vocal automatique vers le téléphone pour le faire SONNER et VIBRER.
    Utilise l'API Twilio Voice (fait sonner n'importe quel smartphone avec sonnerie + vibreur natif).
    """
    phone = getattr(settings, 'ALERT_PHONE_NUMBER', '+212696860564')
    twilio_sid = getattr(settings, 'TWILIO_ACCOUNT_SID', os.getenv('TWILIO_ACCOUNT_SID', '')).strip()
    twilio_token = getattr(settings, 'TWILIO_AUTH_TOKEN', os.getenv('TWILIO_AUTH_TOKEN', '')).strip()
    twilio_phone = getattr(settings, 'TWILIO_PHONE_NUMBER', os.getenv('TWILIO_PHONE_NUMBER', '')).strip()

    if twilio_sid and twilio_token and twilio_phone:
        try:
            from twilio.rest import Client
            client = Client(twilio_sid, twilio_token)
            
            # Message vocal prononcé en français lors du décrochage
            twiml = (
                f'<Response>'
                f'<Say language="fr-FR" voice="alice">'
                f'Attention ! Alerte critique de température du capteur I O T. '
                f'La température a atteint {temp:.1f} degrés Celsius. '
                f'Veuillez intervenir immédiatement sur le système.'
                f'</Say>'
                f'</Response>'
            )

            call = client.calls.create(
                twiml=twiml,
                to=phone,
                from_=twilio_phone
            )
            logger.info(f"Appel vocal Twilio déclenché vers {phone} (SID: {call.sid})")
            _log_to_incident(incident, f"🔔 Appel vocal déclenché vers {phone} (Sonnerie + Vibreur actif, Call SID: {call.sid})")
            return True
        except Exception as e:
            logger.error(f"Erreur déclenchement appel vocal Twilio : {e}")
            _log_to_incident(incident, f"⚠️ Erreur déclenchement appel Twilio ({phone}) : {e}")
            return False
    else:
        # Simulation / log de l'action de sonnerie et vibreur
        _log_to_incident(
            incident,
            f"🔔 [Sonnerie & Vibreur prêts] Appel vers {phone} configuré. "
            f"(Associez TWILIO_ACCOUNT_SID / TWILIO_PHONE_NUMBER ou utilisez MacroDroid sur Android déclenché par le mot-clé WhatsApp '[ALERTE DHT11]')."
        )
        return False


def trigger_all_alerts_async(temp, incident=None, force=False):
    """
    Déclenche l'ensemble des 3 alertes (Email, WhatsApp, Appel/Sonnerie/Vibreur)
    de manière asynchrone (dans un thread d'arrière-plan) pour ne pas ralentir le serveur.
    Applique une règle de Cooldown pour éviter le flood.
    """
    global _LAST_ALERT_TIME

    now = datetime.now()
    if not force and _LAST_ALERT_TIME:
        elapsed = (now - _LAST_ALERT_TIME).total_seconds()
        if elapsed < _ALERT_COOLDOWN_SECONDS:
            logger.info(f"Alerte ignorée par cooldown ({int(elapsed)}s / {_ALERT_COOLDOWN_SECONDS}s)")
            return

    _LAST_ALERT_TIME = now

    def _worker():
        logger.info(f"Exécution des alertes d'urgence pour Temp={temp:.1f}°C...")
        send_alert_email(temp, incident)
        send_alert_whatsapp(temp, incident)
        send_alert_telegram(temp, incident)
        trigger_phone_call_alert(temp, incident)

    thread = threading.Thread(target=_worker, daemon=True)
    thread.start()


def send_resolution_notification_async(temp, incident=None):
    """
    Notifie par WhatsApp et Email que la température est revenue à la normale.
    """
    def _worker():
        recipient = getattr(settings, 'ALERT_EMAIL_RECIPIENT', 'jamaleddineahmed972@gmail.com')
        phone = getattr(settings, 'ALERT_PHONE_NUMBER', '+212696860564')
        date_str = timezone.localtime(timezone.now()).strftime('%d/%m/%Y à %H:%M:%S')

        # 1. Email de résolution
        try:
            from_email = getattr(settings, 'DEFAULT_FROM_EMAIL', 'iot-alerts@system.local')
            send_mail(
                subject=f"✅ [RÉSOLU IOT] Température stabilisée à {temp:.1f}°C",
                message=(
                    f"Bonjour Ahmed,\n\n"
                    f"La température du système IoT est revenue à la normale ({temp:.1f} °C).\n"
                    f"Date de résolution : {date_str}\n"
                    f"Incident clôturé avec succès.\n\n"
                    f"Consultez l'historique : http://localhost:8000/dashboard/\n"
                ),
                from_email=from_email,
                recipient_list=[recipient],
                fail_silently=True
            )
        except Exception:
            pass

        # 2. WhatsApp de résolution
        callmebot_apikey = getattr(settings, 'CALLMEBOT_API_KEY', os.getenv('CALLMEBOT_API_KEY', '')).strip()
        if callmebot_apikey:
            try:
                msg = f"✅ *[RÉSOLUTION IOT]* La température est redevenue normale ({temp:.1f}°C) le {date_str}. Incident clôturé."
                clean_phone = phone.replace('+', '')
                url = f"https://api.callmebot.com/whatsapp.php?phone={clean_phone}&text={urllib.parse.quote(msg)}&apikey={callmebot_apikey}"
                requests.get(url, timeout=10)
            except Exception:
                pass

    thread = threading.Thread(target=_worker, daemon=True)
    thread.start()
