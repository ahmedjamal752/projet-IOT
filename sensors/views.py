import csv
import json
from datetime import datetime
from django.shortcuts import render, redirect, get_object_or_404
from django.http import HttpResponse, JsonResponse
from django.utils import timezone
from django.db.models import Avg, Min, Max, Count
from django.contrib import messages
from rest_framework.decorators import api_view
from rest_framework.response import Response

from .models import Dht11, Incident, IncidentMessage
from .incident_manager import process_sensor_reading, TEMP_MIN, TEMP_MAX


def dashboard_view(request):
    """
    Vue principale du Dashboard IoT :
    - Traçabilité et fraîcheur des données (Alerte si > 20 mins)
    - Température & Humidité en temps réel
    - Statut du système & état d'incident
    - Historique journalier analytique (Matrice horaire / Heatmap 24h)
    - Module de test
    """
    # 1. Dernière mesure
    latest_reading = Dht11.objects.order_by('-id').first()
    
    # 2. Traçabilité (délai depuis la dernière mesure, max 20 mins)
    now = timezone.now()
    minutes_since_last = None
    is_delayed = False
    freshness_status = "Aucune donnée"
    
    if latest_reading and latest_reading.dt:
        diff = now - latest_reading.dt
        total_seconds = max(0, int(diff.total_seconds()))
        minutes_since_last = total_seconds // 60
        seconds_remainder = total_seconds % 60
        
        if minutes_since_last > 20:
            is_delayed = True
            freshness_status = f"Retard critique : dernière donnée reçue il y a {minutes_since_last} min (> 20 min max)"
        else:
            freshness_status = f"Donnée conforme reçue il y a {minutes_since_last} min {seconds_remainder} s"

    # 3. Incident actif et statut global
    active_incident = Incident.objects.filter(etat='ACTIF').order_by('-date_debut').first()
    recent_incidents = Incident.objects.all().order_by('-date_debut')[:5]

    # 4. Historique journalier (date sélectionnée ou aujourd'hui)
    selected_date_str = request.GET.get('date', now.strftime('%Y-%m-%d'))
    try:
        selected_date = datetime.strptime(selected_date_str, '%Y-%m-%d').date()
    except ValueError:
        selected_date = now.date()
        selected_date_str = selected_date.strftime('%Y-%m-%d')

    # Filtrage des enregistrements de la journée sélectionnée
    day_readings = Dht11.objects.filter(
        dt__year=selected_date.year,
        dt__month=selected_date.month,
        dt__day=selected_date.day
    ).order_by('-dt')

    # Statistiques de la journée
    stats = day_readings.aggregate(
        min_temp=Min('temp'),
        max_temp=Max('temp'),
        avg_temp=Avg('temp'),
        min_hum=Min('hum'),
        max_hum=Max('hum'),
        avg_hum=Avg('hum'),
        total_count=Count('id')
    )

    # Calcul du taux de conformité (mesures entre 2°C et 8°C)
    total_day = stats['total_count'] or 0
    conform_count = 0
    if total_day > 0:
        conform_count = day_readings.filter(temp__gte=TEMP_MIN, temp__lte=TEMP_MAX).count()
        conformity_rate = round((conform_count / total_day) * 100, 1)
    else:
        conformity_rate = 100.0

    # 5. Solution meilleure que les graphs : Matrice horaire (Heatmap 24h)
    # Découpage par tranche de 1 heure de 00h à 23h
    hourly_matrix = []
    for hour in range(24):
        slot_readings = day_readings.filter(dt__hour=hour)
        count = slot_readings.count()
        if count > 0:
            avg_t = slot_readings.aggregate(Avg('temp'))['temp__avg']
            avg_h = slot_readings.aggregate(Avg('hum'))['hum__avg']
            if avg_t is not None:
                is_conform = (TEMP_MIN <= avg_t <= TEMP_MAX)
                status_code = 'conforme' if is_conform else 'alerte'
            else:
                status_code = 'vide'
        else:
            avg_t = None
            avg_h = None
            status_code = 'vide'

        hourly_matrix.append({
            'hour': f"{hour:02d}h-{hour+1:02d}h",
            'count': count,
            'avg_temp': round(avg_t, 1) if avg_t is not None else None,
            'avg_hum': round(avg_h, 1) if avg_h is not None else None,
            'status': status_code
        })

    # Données chronologiques pour le graphique Température & Humidité
    valid_readings = day_readings.filter(dt__isnull=False)
    if valid_readings.count() > 100:
        chart_points = list(reversed(valid_readings.order_by('-dt')[:100]))
    else:
        chart_points = list(valid_readings.order_by('dt'))

    chart_labels = [p.dt.strftime('%H:%M:%S') for p in chart_points]
    chart_temps = [round(p.temp, 1) if p.temp is not None else None for p in chart_points]
    chart_hums = [round(p.hum, 1) if p.hum is not None else None for p in chart_points]

    context = {
        'latest_reading': latest_reading,
        'minutes_since_last': minutes_since_last,
        'is_delayed': is_delayed,
        'freshness_status': freshness_status,
        'active_incident': active_incident,
        'recent_incidents': recent_incidents,
        'selected_date': selected_date_str,
        'day_readings': day_readings[:50],  # Limite d'affichage à 50 derniers pour fluidité
        'day_readings_count': total_day,
        'stats': stats,
        'conformity_rate': conformity_rate,
        'hourly_matrix': hourly_matrix,
        'chart_labels_json': json.dumps(chart_labels),
        'chart_temps_json': json.dumps(chart_temps),
        'chart_hums_json': json.dumps(chart_hums),
        'temp_min': TEMP_MIN,
        'temp_max': TEMP_MAX,
    }
    return render(request, 'sensors/dashboard.html', context)


def incidents_view(request):
    """
    Page dédiée aux Incidents et au Chatgroup collaboratif.
    Chaque incident liste : début, fin, durée, compteur alertes, temp max, état, chatgroup.
    """
    incidents = Incident.objects.prefetch_related('messages').all().order_by('-date_debut')
    active_incident = Incident.objects.filter(etat='ACTIF').order_by('-date_debut').first()

    context = {
        'incidents': incidents,
        'active_incident': active_incident,
        'temp_min': TEMP_MIN,
        'temp_max': TEMP_MAX,
    }
    return render(request, 'sensors/incidents.html', context)


def add_incident_comment(request, incident_id):
    """
    Ajout d'un commentaire dans le chatgroup de l'incident.
    Gère les autorisations d'opérateurs selon le compteur d'alertes :
    - Opérateur 1 : toujours autorisé lors d'une alerte
    - Opérateur 2 : autorisé dès compteur >= 4
    - Opérateur 3 : autorisé dès compteur >= 7
    """
    incident = get_object_or_404(Incident, id=incident_id)

    if request.method == 'POST':
        auteur = request.POST.get('auteur', '').strip()
        message_text = request.POST.get('message', '').strip()

        if not auteur or not message_text:
            messages.error(request, "Veuillez renseigner votre nom et votre message.")
            return redirect(request.META.get('HTTP_REFERER', '/incidents/'))

        # Contrôle des habilitations
        if auteur == 'Opérateur 2' and incident.compteur_alertes < 4:
            messages.error(request, "L'Opérateur 2 n'est invité qu'à partir de 4 alertes consécutives.")
            return redirect(request.META.get('HTTP_REFERER', '/incidents/'))

        if auteur == 'Opérateur 3' and incident.compteur_alertes < 7:
            messages.error(request, "L'Opérateur 3 n'est invité qu'à partir de 7 alertes consécutives.")
            return redirect(request.META.get('HTTP_REFERER', '/incidents/'))

        # Enregistrement du message
        IncidentMessage.objects.create(
            incident=incident,
            auteur=auteur,
            message=message_text,
            is_system=False
        )
        messages.success(request, f"Commentaire ajouté au chatgroup par {auteur}.")

    return redirect(request.META.get('HTTP_REFERER', '/incidents/'))


def export_csv(request):
    """
    Exportation de l'historique au format CSV (compatible Excel avec utf-8-sig).
    Filtrable par date via paramètre ?date=YYYY-MM-DD.
    """
    date_str = request.GET.get('date', None)
    queryset = Dht11.objects.all().order_by('-dt')

    filename = "releves_temperature_humidite_complet.csv"
    if date_str:
        try:
            d = datetime.strptime(date_str, '%Y-%m-%d').date()
            queryset = queryset.filter(dt__year=d.year, dt__month=d.month, dt__day=d.day)
            filename = f"releves_iot_{date_str}.csv"
        except ValueError:
            pass

    response = HttpResponse(content_type='text/csv; charset=utf-8-sig')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'

    writer = csv.writer(response, delimiter=';')
    writer.writerow(['ID', 'Date et Heure (UTC)', 'Temperature (°C)', 'Humidite (%)', 'Statut Conformite (2°C - 8°C)'])

    for row in queryset:
        statut = "CONFORME" if (row.temp is not None and TEMP_MIN <= row.temp <= TEMP_MAX) else "HORS NORME (ALERTE)"
        dt_str = row.dt.strftime('%Y-%m-%d %H:%M:%S') if row.dt else ""
        writer.writerow([
            row.id,
            dt_str,
            f"{row.temp:.1f}" if row.temp is not None else "",
            f"{row.hum:.1f}" if row.hum is not None else "",
            statut
        ])

    return response


def simulate_reading(request):
    """
    Partie pour les tests :
    Permet d'injecter des données de test (température, humidité) ou de simuler
    directement des montées en charge d'alertes (ex: 4 alertes pour inviter Opérateur 2,
    7 alertes pour inviter Opérateur 3, ou retour à 4°C pour résoudre).
    """
    if request.method == 'POST':
        action = request.POST.get('action', 'single')

        if action == 'single':
            try:
                temp = float(request.POST.get('temp', 24.1))
                hum = float(request.POST.get('hum', 50.0))
            except ValueError:
                messages.error(request, "Valeurs numériques invalides pour le test.")
                return redirect(request.META.get('HTTP_REFERER', '/'))

            dht = Dht11.objects.create(temp=temp, hum=hum)
            messages.success(request, f"Mesure de test injectée : Temp={temp}°C, Hum={hum}%.")

        elif action == 'batch_alerts_4':
            # Simuler 4 mesures hors seuil consécutives pour atteindre l'Opérateur 2
            for _ in range(4):
                Dht11.objects.create(temp=25.5, hum=60.0)
            messages.success(request, "Simulation réussie : 4 alertes injectées. Opérateur 2 invité !")

        elif action == 'batch_alerts_7':
            # Simuler 7 mesures hors seuil consécutives pour atteindre l'Opérateur 3
            for _ in range(7):
                Dht11.objects.create(temp=28.0, hum=65.0)
            messages.success(request, "Simulation réussie : 7 alertes injectées. Opérateurs 2 et 3 invités !")

        elif action == 'resolve':
            # Simuler une température conforme pour clore l'incident actif
            Dht11.objects.create(temp=5.0, hum=45.0)
            messages.success(request, "Simulation réussie : Température conforme (5.0°C) injectée. Incident résolu !")

    return redirect(request.META.get('HTTP_REFERER', '/'))


def live_dashboard_data(request):
    """
    Endpoint JSON retournant l'état temps réel pour actualisation automatique en AJAX.
    """
    latest = Dht11.objects.order_by('-id').first()
    active_incident = Incident.objects.filter(etat='ACTIF').order_by('-date_debut').first()

    now = timezone.now()
    minutes_since = None
    is_delayed = False
    if latest and latest.dt:
        diff = now - latest.dt
        total_sec = max(0, int(diff.total_seconds()))
        minutes_since = total_sec // 60
        is_delayed = minutes_since > 20

    data = {
        'temp': latest.temp if latest else None,
        'hum': latest.hum if latest else None,
        'dt': latest.dt.isoformat() if latest and latest.dt else None,
        'minutes_since': minutes_since,
        'is_delayed': is_delayed,
        'is_normal': (latest and latest.temp is not None and TEMP_MIN <= latest.temp <= TEMP_MAX),
        'active_incident': {
            'id': active_incident.id,
            'compteur_alertes': active_incident.compteur_alertes,
            'temp_max': active_incident.temp_max,
            'operateurs': active_incident.operateurs_invites,
            'duree': active_incident.duree_str
        } if active_incident else None
    }
    return JsonResponse(data)
