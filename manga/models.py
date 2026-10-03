from django.db import models
from django.contrib.auth.models import AbstractUser
from pytils.translit import slugify


class User(AbstractUser):
    class Role(models.TextChoices):
        READER = 'reader', 'Читатель'
        AUTHOR = 'author', 'Автор / Переводчик'
        ADMIN = 'admin', 'Администратор'

    role = models.CharField(
        max_length=10,
        choices=Role.choices,
        default=Role.READER,
        verbose_name='Роль'
    )
    avatar = models.ImageField(
        upload_to='avatars/',
        blank=True,
        null=True,
        verbose_name='Аватар'
    )

    @property
    def xp(self):
        """Автоматический расчет XP пользователя"""
        # Исправлено: обращаемся к reading_history вместо read_chapters
        read_chapters_count = self.reading_history.count() if hasattr(self, 'reading_history') else 0
        ratings_count = self.ratings.count() if hasattr(self, 'ratings') else 0
        comments_count = self.comment_set.count() if hasattr(self, 'comment_set') else 0
        completed_bookmarks = self.bookmarks.filter(status='completed').count() if hasattr(self, 'bookmarks') else 0

        return (read_chapters_count * 1) + (ratings_count * 2) + (comments_count * 3) + (completed_bookmarks * 10)

    @property
    def level(self):
        return (self.xp // 50) + 1

    @property
    def rank_name(self):
        lvl = self.level
        if lvl < 3:
            return "Новичок"
        elif lvl < 7:
            return "Любитель манги"
        elif lvl < 15:
            return "Опытный читатель"
        elif lvl < 30:
            return "Манга-гуру"
        return "Легенда"


class Genre(models.Model):
    name = models.CharField(max_length=100, unique=True, verbose_name='Название')
    slug = models.SlugField(max_length=100, unique=True, verbose_name='URL-слаг')

    class Meta:
        verbose_name = 'Жанр'
        verbose_name_plural = 'Жанры'

    def __str__(self):
        return self.name


class Title(models.Model):
    class TypeChoices(models.TextChoices):
        MANGA = 'manga', 'Манга'
        MANHWA = 'manhwa', 'Манхва'
        MANHUA = 'manhua', 'Маньхуа'

    class StatusChoices(models.TextChoices):
        ONGOING = 'ongoing', 'Онгоинг'
        COMPLETED = 'completed', 'Завершён'
        ANNOUNCEMENT = 'announcement', 'Анонс'

    name = models.CharField(max_length=255, verbose_name='Название на русском')
    original_name = models.CharField(max_length=255, blank=True, verbose_name='Оригинальное название')
    slug = models.SlugField(max_length=255, unique=True, blank=True, verbose_name='URL-слаг')
    cover = models.ImageField(upload_to='covers/', verbose_name='Обложка')
    description = models.TextField(verbose_name='Описание')

    type = models.CharField(
        max_length=20,
        choices=TypeChoices.choices,
        default=TypeChoices.MANGA,
        verbose_name='Тип'
    )
    status = models.CharField(
        max_length=20,
        choices=StatusChoices.choices,
        default=StatusChoices.ONGOING,
        verbose_name='Статус'
    )

    genres = models.ManyToManyField(Genre, related_name='titles', verbose_name='Жанры')
    author = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='titles',
        verbose_name='Автор / Переводчик'
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Дата добавления')

    class Meta:
        verbose_name = 'Тайтл'
        verbose_name_plural = 'Тайтлы'

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug or self.slug.strip() == '':
            base_slug = slugify(self.name)
            if not base_slug:
                base_slug = 'title'

            slug = base_slug
            count = 1
            while Title.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug = f"{base_slug}-{count}"
                count += 1
            self.slug = slug

        super().save(*args, **kwargs)

    def average_rating(self):
        ratings = self.ratings.all()
        if ratings.exists():
            return round(sum(r.score for r in ratings) / ratings.count(), 1)
        return 0.0


class Chapter(models.Model):
    title = models.ForeignKey(Title, on_delete=models.CASCADE, related_name='chapters', verbose_name='Тайтл')
    volume = models.PositiveIntegerField(default=1, verbose_name='Том')
    number = models.CharField(max_length=10, verbose_name='Номер главы')
    name = models.CharField(max_length=255, blank=True, verbose_name='Название главы')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Дата добавления')

    class Meta:
        verbose_name = 'Глава'
        verbose_name_plural = 'Главы'
        ordering = ['volume', 'number']

    def __str__(self):
        return f"{self.title.name} — Том {self.volume} Глава {self.number}"


class Page(models.Model):
    chapter = models.ForeignKey(Chapter, on_delete=models.CASCADE, related_name='pages', verbose_name='Глава')
    image = models.ImageField(upload_to='chapters/', verbose_name='Изображение')
    page_number = models.PositiveIntegerField(verbose_name='Номер страницы')

    class Meta:
        verbose_name = 'Страница'
        verbose_name_plural = 'Страницы'
        ordering = ['page_number']

    def __str__(self):
        return f"{self.chapter} — Стр. {self.page_number}"


class Bookmark(models.Model):
    STATUS_CHOICES = [
        ('reading', 'Читаю'),
        ('planned', 'В планах'),
        ('completed', 'Прочитано'),
        ('dropped', 'Брошено'),
        ('favorite', 'Любимое'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='bookmarks', verbose_name='Пользователь')
    title = models.ForeignKey(Title, on_delete=models.CASCADE, related_name='bookmarks', verbose_name='Тайтл')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, verbose_name='Статус')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Дата создания')

    class Meta:
        verbose_name = 'Закладка'
        verbose_name_plural = 'Закладки'
        unique_together = ('user', 'title')

    def __str__(self):
        return f"{self.user.username} - {self.title.name} ({self.get_status_display()})"


class Rating(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='ratings', verbose_name='Пользователь')
    title = models.ForeignKey(Title, on_delete=models.CASCADE, related_name='ratings', verbose_name='Тайтл')
    score = models.PositiveSmallIntegerField(verbose_name='Оценка')

    class Meta:
        verbose_name = 'Рейтинг'
        verbose_name_plural = 'Рейтинги'
        unique_together = ('user', 'title')

    def __str__(self):
        return f"{self.title.name}: {self.score} от {self.user.username}"


class Comment(models.Model):
    title = models.ForeignKey(Title, on_delete=models.CASCADE, related_name='comments', verbose_name='Тайтл')
    user = models.ForeignKey(User, on_delete=models.CASCADE, verbose_name='Пользователь')
    text = models.TextField(verbose_name='Текст комментария')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Дата создания')
    parent = models.ForeignKey('self', on_delete=models.CASCADE, null=True, blank=True, related_name='replies', verbose_name='Родительский комментарий')

    class Meta:
        verbose_name = 'Комментарий'
        verbose_name_plural = 'Комментарии'

    def __str__(self):
        return f"{self.user.username} - {self.title.name}"


class ReadingHistory(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='reading_history', verbose_name='Пользователь')
    chapter = models.ForeignKey(Chapter, on_delete=models.CASCADE, verbose_name='Глава')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='Дата обновления')

    class Meta:
        verbose_name = 'История чтения'
        verbose_name_plural = 'История чтения'
        ordering = ['-updated_at']
        unique_together = ('user', 'chapter')

    def __str__(self):
        return f"{self.user.username} read {self.chapter}"


class Notification(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notifications', verbose_name='Пользователь')
    title = models.CharField(max_length=255, verbose_name="Заголовок")
    message = models.TextField(verbose_name="Сообщение")
    link = models.CharField(max_length=255, blank=True, null=True, verbose_name="Ссылка")
    is_read = models.BooleanField(default=False, verbose_name="Прочитано")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Дата создания")

    class Meta:
        verbose_name = 'Уведомление'
        verbose_name_plural = 'Уведомления'
        ordering = ['-created_at']

    def __str__(self):
        return f"Уведомление для {self.user.username}: {self.title}"