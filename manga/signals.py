import os
from django.conf import settings
from django.db.models.signals import post_delete, pre_save
from django.dispatch import receiver
from .models import Page  


def _remove_lite_cache(page_id):
    """Удаляет сжатые копии страницы из кэша читалки."""
    cache_dir = os.path.join(settings.MEDIA_ROOT, 'cache', 'lite')
    if not os.path.isdir(cache_dir):
        return
    prefix = f'{page_id}_'
    for name in os.listdir(cache_dir):
        if name.startswith(prefix):
            try:
                os.remove(os.path.join(cache_dir, name))
            except OSError:
                pass


@receiver(post_delete, sender=Page)
def auto_delete_page_image_on_delete(sender, instance, **kwargs):
    if instance.image:
        if os.path.isfile(instance.image.path):
            os.remove(instance.image.path)
    _remove_lite_cache(instance.pk)


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
        _remove_lite_cache(instance.pk)
