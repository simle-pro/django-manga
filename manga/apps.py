from django.apps import AppConfig


class MangaConfig(AppConfig):
    name = 'manga'


from django.apps import AppConfig

class MangaConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'manga'

    def ready(self):
        import manga.signals  # Регистрируем сигналы при запуске приложения