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

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='bookmarks')
    title = models.ForeignKey(Title, on_delete=models.CASCADE, related_name='bookmarks')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('user', 'title')

    def __str__(self):
        return f"{self.user.username} - {self.title.name} ({self.get_status_display()})"


class Rating(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='ratings')
    title = models.ForeignKey(Title, on_delete=models.CASCADE, related_name='ratings')
    score = models.PositiveSmallIntegerField()

    class Meta:
        unique_together = ('user', 'title')

    def __str__(self):
        return f"{self.title.name}: {self.score} от {self.user.username}"


class Comment(models.Model):
    title = models.ForeignKey(Title, on_delete=models.CASCADE, related_name='comments')
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    text = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    parent = models.ForeignKey('self', on_delete=models.CASCADE, null=True, blank=True, related_name='replies')

    def __str__(self):
        return f"{self.user.username} - {self.title.name}"



class ReadingHistory(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='reading_history')
    chapter = models.ForeignKey(Chapter, on_delete=models.CASCADE)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at']
        unique_together = ('user', 'chapter')

    def __str__(self):
        return f"{self.user.username} read {self.chapter}"



class Notification(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notifications')
    title = models.CharField(max_length=255, verbose_name="Заголовок")
    message = models.TextField(verbose_name="Сообщение")
    link = models.CharField(max_length=255, blank=True, null=True, verbose_name="Ссылка")
    is_read = models.BooleanField(default=False, verbose_name="Прочитано")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Уведомление для {self.user.username}: {self.title}"