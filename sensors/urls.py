from django.urls import path
from django.shortcuts import redirect
from . import views
from . import api

urlpatterns = [
    # Redirection accueil vers le Dashboard
    path("", lambda request: redirect("dashboard"), name="home"),

    # Vues Web Plateforme
    path("dashboard/", views.dashboard_view, name="dashboard"),
    path("incidents/", views.incidents_view, name="incidents"),
    path("incidents/<int:incident_id>/comment/", views.add_incident_comment, name="add_incident_comment"),
    path("export/csv/", views.export_csv, name="export_csv"),
    path("simulate/", views.simulate_reading, name="simulate_reading"),
    path("api/dashboard-data/", views.live_dashboard_data, name="live_dashboard_data"),

    # Endpoints existants API REST
    path("api/get", api.Dlist, name="api_get"),
    path("api/post", api.Dhtviews.as_view(), name="api_post"),
    path("test/", lambda request: redirect("dashboard")),
]
