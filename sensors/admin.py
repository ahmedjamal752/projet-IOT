from django.contrib import admin
from .models import Dht11, Incident, IncidentMessage


@admin.register(Dht11)
class Dht11Admin(admin.ModelAdmin):
    list_display = ('id', 'temp', 'hum', 'dt')
    list_filter = ('dt',)
    ordering = ('-dt',)


class IncidentMessageInline(admin.TabularInline):
    model = IncidentMessage
    extra = 1


@admin.register(Incident)
class IncidentAdmin(admin.ModelAdmin):
    list_display = ('id', 'etat', 'compteur_alertes', 'temp_max', 'date_debut', 'date_fin', 'duree_str')
    list_filter = ('etat', 'date_debut')
    inlines = [IncidentMessageInline]


@admin.register(IncidentMessage)
class IncidentMessageAdmin(admin.ModelAdmin):
    list_display = ('id', 'incident', 'auteur', 'is_system', 'date_envoi', 'message')
    list_filter = ('is_system', 'date_envoi')
