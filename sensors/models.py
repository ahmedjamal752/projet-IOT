from django.db import models
from django.utils import timezone


class Dht11(models.Model):
    temp = models.FloatField(null=True)
    hum = models.FloatField(null=True)
    dt = models.DateTimeField(auto_now_add=True, null=True)

    def __str__(self):
        return f"[{self.dt}] Temp: {self.temp}°C, Hum: {self.hum}%"


class Incident(models.Model):
    STATUT_CHOICES = [
        ('ACTIF', 'Actif'),
        ('RESOLU', 'Résolu'),
    ]

    date_debut = models.DateTimeField(default=timezone.now)
    date_fin = models.DateTimeField(null=True, blank=True)
    compteur_alertes = models.IntegerField(default=1)
    temp_max = models.FloatField(default=0.0)
    etat = models.CharField(max_length=20, choices=STATUT_CHOICES, default='ACTIF')
    operateurs_invites = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ['-date_debut']

    @property
    def duree_str(self):
        end = self.date_fin if self.date_fin else timezone.now()
        diff = end - self.date_debut
        total_seconds = int(diff.total_seconds())
        if total_seconds < 0:
            total_seconds = 0
        minutes, seconds = divmod(total_seconds, 60)
        hours, minutes = divmod(minutes, 60)
        if hours > 0:
            return f"{hours}h {minutes:02d}m {seconds:02d}s"
        elif minutes > 0:
            return f"{minutes}m {seconds:02d}s"
        else:
            return f"{seconds}s"

    def __str__(self):
        return f"Incident #{self.id} [{self.etat}] - Max: {self.temp_max}°C - Alertes: {self.compteur_alertes}"


class IncidentMessage(models.Model):
    incident = models.ForeignKey(Incident, on_delete=models.CASCADE, related_name='messages')
    auteur = models.CharField(max_length=100)
    message = models.TextField()
    is_system = models.BooleanField(default=False)
    date_envoi = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['date_envoi']

    def __str__(self):
        return f"[{self.date_envoi:%d/%m %H:%M:%S}] {self.auteur}: {self.message[:30]}"
