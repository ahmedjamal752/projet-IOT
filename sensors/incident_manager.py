from django.utils import timezone
from .models import Incident, IncidentMessage
from .notifications import trigger_all_alerts_async, send_resolution_notification_async

TEMP_MIN = 20.0
TEMP_MAX = 30.0


def process_sensor_reading(dht_entry):
    """
    Vérifie la température par rapport au seuil [2.0°C - 8.0°C].
    Gère la création, l'incrémentation, l'escalade d'opérateurs
    et la résolution des incidents.
    """
    temp = dht_entry.temp
    if temp is None:
        return None

    active_incident = Incident.objects.filter(etat='ACTIF').order_by('-date_debut').first()
    is_anomaly = (temp < TEMP_MIN or temp > TEMP_MAX)

    if is_anomaly:
        if not active_incident:
            # 1er déclenchement : Création d'un nouvel incident et invitation Opérateur 1
            incident = Incident.objects.create(
                date_debut=dht_entry.dt or timezone.now(),
                compteur_alertes=1,
                temp_max=temp,
                etat='ACTIF',
                operateurs_invites=['Opérateur 1']
            )
            IncidentMessage.objects.create(
                incident=incident,
                auteur='Système',
                is_system=True,
                message=f"🚨 ALERTE DÉCLENCHÉE : Température hors plage ({temp:.1f}°C). Plage requise : {TEMP_MIN}°C à {TEMP_MAX}°C. Opérateur 1 invité dans le chatgroup."
            )
            # Déclenchement automatique des alertes externes (Email + WhatsApp + Sonnerie/Vibreur)
            trigger_all_alerts_async(temp, incident, force=True)
            return incident
        else:
            # Le problème persiste : incrémentation du compteur
            active_incident.compteur_alertes += 1
            if temp > active_incident.temp_max:
                active_incident.temp_max = temp

            invites = list(active_incident.operateurs_invites or [])
            if 'Opérateur 1' not in invites:
                invites.append('Opérateur 1')

            # Escalade si compteur >= 4 : inviter Opérateur 2
            if active_incident.compteur_alertes >= 4 and 'Opérateur 2' not in invites:
                invites.append('Opérateur 2')
                IncidentMessage.objects.create(
                    incident=active_incident,
                    auteur='Système',
                    is_system=True,
                    message=f"⚠️ ESCALADE NIVEAU 2 : Alerte persistante (Compteur: {active_incident.compteur_alertes}, Temp: {temp:.1f}°C). Opérateur 2 (Superviseur) invité avec droit de commenter."
                )
                trigger_all_alerts_async(temp, active_incident, force=True)

            # Escalade si compteur >= 7 : inviter Opérateur 3
            if active_incident.compteur_alertes >= 7 and 'Opérateur 3' not in invites:
                invites.append('Opérateur 3')
                IncidentMessage.objects.create(
                    incident=active_incident,
                    auteur='Système',
                    is_system=True,
                    message=f"🚨 ESCALADE CRITIQUE NIVEAU 3 : Compteur alertes = {active_incident.compteur_alertes} (Temp: {temp:.1f}°C). Opérateur 3 (Responsable Technique) invité d'urgence !"
                )
                trigger_all_alerts_async(temp, active_incident, force=True)
            else:
                # Alerte périodique respectant le cooldown (5 minutes) si la température dépasse toujours le seuil
                trigger_all_alerts_async(temp, active_incident, force=False)

            active_incident.operateurs_invites = invites
            active_incident.save()
            return active_incident
    else:
        # Température redevenue normale [2°C - 8°C]
        if active_incident:
            active_incident.etat = 'RESOLU'
            active_incident.date_fin = dht_entry.dt or timezone.now()
            active_incident.save()
            IncidentMessage.objects.create(
                incident=active_incident,
                auteur='Système',
                is_system=True,
                message=f"✅ RÉSOLUTION : Température stabilisée à {temp:.1f}°C (conforme entre {TEMP_MIN}°C et {TEMP_MAX}°C). Incident résolu."
            )
            # Notification de fin d'incident
            send_resolution_notification_async(temp, active_incident)
            return active_incident

    return None
