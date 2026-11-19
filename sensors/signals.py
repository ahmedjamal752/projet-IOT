from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import Dht11
from .incident_manager import process_sensor_reading


@receiver(post_save, sender=Dht11)
def handle_new_dht11_reading(sender, instance, created, **kwargs):
    if created:
        process_sensor_reading(instance)
