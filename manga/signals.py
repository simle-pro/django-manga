import os
from django.db.models.signals import post_delete, pre_save
from django.dispatch import receiver
from .models import Page  

@receiver(post_delete, sender=Page)
def auto_delete_page_image_on_delete(sender, instance, **kwargs):
    if instance.image:
        if os.path.isfile(instance.image.path):
            os.remove(instance.image.path)


@receiver(pre_save, sender=Page)
def auto_delete_old_page_image_on_change(sender, instance, **kwargs):
    if not instance.pk:
        return False

    try:
        old_file = Page.objects.get(pk=instance.pk).image
    except Page.DoesNotExist:
        return False

    new_file = instance.image
    if old_file and old_file != new_file:
        if os.path.isfile(old_file.path):
            os.remove(old_file.path)