import secrets
from datetime import date

from django.db import models
from django.contrib.auth.models import AbstractUser
from django.db.models import Q, UniqueConstraint
from pytils.translit import slugify


def _generate_public_id():
    """Генерирует уникальный 8-значный публичный ID пользователя."""
    while True:
        pid = str(secrets.randbelow(90000000) + 10000000)
        if not User.objects.filter(public_id=pid).exists():
            return pid


class User(AbstractUser):
    class Role(models.TextChoices):
        READER = 'reader', 'Читатель'
        AUTHOR = 'author', 'Автор / Переводчик'
        ADMIN = 'admin', 'Администратор'

    class BookmarksVisibility(models.TextChoices):
        EVERYONE = 'everyone', 'Все'
        FRIENDS = 'friends', 'Только друзья'
        NOBODY = 'nobody', 'Никто (только исключения)'

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
    public_id = models.CharField(
        max_length=20,
        unique=True,
        null=True,
        blank=True,
        editable=False,
        verbose_name='Публичный ID'
    )
    birth_date = models.DateField(
        null=True,
        blank=True,
        verbose_name='Дата рождения'
    )
    is_closed = models.BooleanField(
        default=False,
        verbose_name='Закрытый аккаунт'
    )
    bookmarks_visibility = models.CharField(
        max_length=10,
        choices=BookmarksVisibility.choices,
        default=BookmarksVisibility.EVERYONE,
        verbose_name='Кто смотрит закладки'
    )
    hide_nsfw = models.BooleanField(
        default=False,
        verbose_name='Скрывать NSFW-тайтлы'
    )

    @property
    def age(self):
        """Возраст пользователя или None, если дата рождения не указана."""
        if not self.birth_date:
            return None
        today = date.today()
        return today.year - self.birth_date.year - (
            (today.month, today.day) < (self.birth_date.month, self.birth_date.day)
        )

    @property
    def is_adult(self):
        age = self.age
        return age is not None and age >= 18

    @property
    def can_view_nsfw(self):
        """Видит ли пользователь NSFW-тайтлы (18+ и не включено скрытие)."""
        return self.is_adult and not self.hide_nsfw

    @property
    def xp(self):
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

    @property
    def friends(self):
        """Список друзей пользователя (принятые заявки в обе стороны)."""
        accepted = FriendRequest.objects.filter(status='accepted').filter(
            Q(from_user=self) | Q(to_user=self)
        )
        friend_ids = set()
        for fr in accepted:
            friend_ids.add(fr.to_user_id if fr.from_user_id == self.id else fr.from_user_id)
        friend_ids.discard(self.id)
        return User.objects.filter(id__in=friend_ids)

    @property
    def friends_count(self):
        return self.friends.count()

    def is_friends_with(self, other):
        if not other or other.pk == self.pk:
            return False
        return FriendRequest.objects.filter(status='accepted').filter(
            Q(from_user=self, to_user=other) | Q(from_user=other, to_user=self)
        ).exists()

    def friendship_with(self, other):
        """Принятая заявка-дружба между self и other (или None)."""
        if not other or other.pk == self.pk:
            return None
        return FriendRequest.objects.filter(status='accepted').filter(
            Q(from_user=self, to_user=other) | Q(from_user=other, to_user=self)
        ).first()

    @property
    def pending_friend_requests_count(self):
        return FriendRequest.objects.filter(to_user=self, status='pending').count()

    @property
    def is_site_admin(self):
        """Админ сайта: роль admin или флаги Django-персонала."""
        return bool(
            self.is_staff or self.is_superuser
            or getattr(self, 'role', '') == self.Role.ADMIN
        )

    def save(self, *args, **kwargs):
        if not self.public_id:
            self.public_id = _generate_public_id()
        super().save(*args, **kwargs)

    def has_blocked(self, other):
        """Заблокировал ли self пользователя other."""
        if not other or other.pk == self.pk:
            return False
        return UserBlock.objects.filter(blocker=self, blocked=other).exists()

    def is_blocked_by(self, other):
        """Заблокировал ли other пользователя self."""
        if not other or other.pk == self.pk:
            return False
        return UserBlock.objects.filter(blocker=other, blocked=self).exists()

    def can_view_profile(self, viewer):
        """Может ли viewer смотреть полный профиль (тайтлы, закладки, историю)."""
        viewer_is_auth = viewer is not None and getattr(viewer, 'is_authenticated', False)

        if viewer_is_auth and viewer == self:
            return True
        if viewer_is_auth and (viewer.is_staff or viewer.is_superuser):
            return True

        # Чёрный список скрывает профиль в обе стороны
        if viewer_is_auth and (self.has_blocked(viewer) or self.is_blocked_by(viewer)):
            return False

        if self.is_closed:
            if not viewer_is_auth:
                return False
            return self.is_friends_with(viewer)

        return True

    def can_view_bookmarks(self, viewer):
        """Может ли viewer смотреть закладки пользователя."""
        if not self.can_view_profile(viewer):
            return False

        viewer_is_auth = viewer is not None and getattr(viewer, 'is_authenticated', False)
        if viewer_is_auth and viewer == self:
            return True

        if self.bookmarks_visibility == self.BookmarksVisibility.EVERYONE:
            return True
        if self.bookmarks_visibility == self.BookmarksVisibility.FRIENDS:
            if not viewer_is_auth:
                return False
            return self.is_friends_with(viewer)

        # nobody — только пользователи из исключений
        if not viewer_is_auth:
            return False
        return BookmarkAccess.objects.filter(owner=self, viewer=viewer).exists()


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
    is_nsfw = models.BooleanField(
        default=False,
        verbose_name='NSFW (18+)'
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

    @property
    def collaborator_ids(self):
        """ID пользователей, которым разрешено совместно добавлять главы."""
        return set(CollaborationRequest.objects.filter(
            title=self, status='accepted'
        ).values_list('from_user_id', flat=True))


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
    note = models.TextField(blank=True, default='', max_length=1000, verbose_name='Заметка')
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
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notifications', verbose_name="Пользователь")
    title = models.CharField(max_length=255, verbose_name="Заголовок")
    message = models.TextField(verbose_name="Сообщение")
    link = models.CharField(max_length=255, blank=True, null=True, verbose_name="Ссылка")
    is_read = models.BooleanField(default=False, verbose_name="Прочитано")
    friend_request = models.ForeignKey(
        'FriendRequest',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='notifications',
        verbose_name="Заявка в друзья"
    )
    is_announcement = models.BooleanField(default=False, verbose_name="Объявление администрации")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Дата создания")

    class Meta:
        verbose_name = 'Уведомление'
        verbose_name_plural = 'Уведомления'
        ordering = ['-created_at']

    def __str__(self):
        return f"Уведомление для {self.user.username}: {self.title}"


class FriendRequest(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Ожидает'),
        ('accepted', 'Принята'),
        ('declined', 'Отклонена'),
    ]

    from_user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='sent_friend_requests', verbose_name='Отправитель'
    )
    to_user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='received_friend_requests', verbose_name='Получатель'
    )
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='pending', verbose_name='Статус')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Дата отправки')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='Дата обновления')

    class Meta:
        verbose_name = 'Заявка в друзья'
        verbose_name_plural = 'Заявки в друзья'
        constraints = [
            UniqueConstraint(fields=['from_user', 'to_user'], name='unique_friend_request_pair')
        ]

    def __str__(self):
        return f"{self.from_user.username} -> {self.to_user.username} ({self.get_status_display()})"


class CollaborationRequest(models.Model):
    """Запрос переводчика на совместное добавление глав к чужому тайтлу."""
    STATUS_CHOICES = [
        ('pending', 'Ожидает'),
        ('accepted', 'Принят'),
        ('declined', 'Отклонён'),
    ]

    title = models.ForeignKey(
        Title, on_delete=models.CASCADE, related_name='collab_requests', verbose_name='Тайтл'
    )
    from_user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='collab_requests_sent', verbose_name='Переводчик'
    )
    message = models.TextField(blank=True, max_length=500, verbose_name='Сообщение')
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='pending', verbose_name='Статус')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Дата отправки')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='Дата обновления')

    class Meta:
        verbose_name = 'Запрос на общий перевод'
        verbose_name_plural = 'Запросы на общий перевод'
        constraints = [
            UniqueConstraint(fields=['title', 'from_user'], name='unique_collab_request_pair')
        ]

    def __str__(self):
        return f"{self.from_user.username} -> «{self.title.name}» ({self.get_status_display()})"


class UserBlock(models.Model):
    """Чёрный список: blocker блокирует blocked."""
    blocker = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='blocking', verbose_name='Кто заблокировал'
    )
    blocked = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='blocked_by', verbose_name='Заблокированный'
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Дата блокировки')

    class Meta:
        verbose_name = 'Заблокированный пользователь'
        verbose_name_plural = 'Чёрные списки'
        ordering = ['-created_at']
        constraints = [
            UniqueConstraint(fields=['blocker', 'blocked'], name='unique_user_block')
        ]

    def __str__(self):
        return f"{self.blocker.username} → {self.blocked.username}"


class BookmarkAccess(models.Model):
    """Исключение видимости закладок: owner разрешает viewer смотреть свои закладки."""
    owner = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='bookmark_access_grants', verbose_name='Владелец закладок'
    )
    viewer = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='bookmark_access_received', verbose_name='Кому разрешён доступ'
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Дата добавления')

    class Meta:
        verbose_name = 'Исключение по закладкам'
        verbose_name_plural = 'Исключения по закладкам'
        ordering = ['viewer__username']
        constraints = [
            UniqueConstraint(fields=['owner', 'viewer'], name='unique_bookmark_access')
        ]

    def __str__(self):
        return f"{self.owner.username} → {self.viewer.username}"


class Message(models.Model):
    """Личное сообщение в мини-чате (только между друзьями)."""
    sender = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='sent_messages', verbose_name='Отправитель'
    )
    recipient = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='received_messages', verbose_name='Получатель'
    )
    text = models.TextField(max_length=2000, verbose_name='Текст сообщения')
    is_read = models.BooleanField(default=False, verbose_name='Прочитано')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Дата отправки')

    class Meta:
        verbose_name = 'Сообщение'
        verbose_name_plural = 'Сообщения'
        ordering = ['created_at']

    def __str__(self):
        return f"{self.sender.username} → {self.recipient.username}: {self.text[:30]}"

    @property
    def short_time(self):
        return self.created_at.strftime('%d.%m %H:%M')


class ChatRoom(models.Model):
    """Комната группового чата: общий чат админов или тред «баги/идеи» с разработчиками."""

    class RoomType(models.TextChoices):
        ADMIN = 'admin', 'Чат админов'
        FEEDBACK = 'feedback', 'Баги и идеи'

    room_type = models.CharField(
        max_length=10,
        choices=RoomType.choices,
        default=RoomType.FEEDBACK,
        verbose_name='Тип комнаты'
    )
    owner = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='feedback_rooms',
        verbose_name='Владелец треда'
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Создана')

    class Meta:
        verbose_name = 'Комната чата'
        verbose_name_plural = 'Комнаты чатов'
        constraints = [
            UniqueConstraint(
                fields=['room_type', 'owner'],
                name='unique_chat_room_per_owner'
            )
        ]

    def __str__(self):
        if self.room_type == self.RoomType.ADMIN:
            return 'Чат админов'
        return f'Обращение: {self.owner.username if self.owner else "—"}'


class ChatRoomMessage(models.Model):
    """Сообщение в комнате чата (чат админов / чат поддержки)."""

    room = models.ForeignKey(
        ChatRoom, on_delete=models.CASCADE, related_name='messages', verbose_name='Комната'
    )
    author = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='room_messages', verbose_name='Автор'
    )
    text = models.TextField(max_length=2000, verbose_name='Текст сообщения')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Дата отправки')

    class Meta:
        verbose_name = 'Сообщение чата'
        verbose_name_plural = 'Сообщения чатов'
        ordering = ['created_at']

    def __str__(self):
        return f'{self.author.username} в «{self.room}»: {self.text[:30]}'

    @property
    def short_time(self):
        return self.created_at.strftime('%d.%m %H:%M')


class ChatRoomRead(models.Model):
    """Отметка прочитанного: до какого сообщения комнаты пользователь дочитал."""

    room = models.ForeignKey(
        ChatRoom, on_delete=models.CASCADE, related_name='reads', verbose_name='Комната'
    )
    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='room_reads', verbose_name='Пользователь'
    )
    last_read_id = models.PositiveIntegerField(default=0, verbose_name='ID последнего прочитанного')

    class Meta:
        verbose_name = 'Прочитанное сообщение комнаты'
        verbose_name_plural = 'Прочитанные сообщения комнат'
        constraints = [
            UniqueConstraint(fields=['room', 'user'], name='unique_room_read_per_user')
        ]

    def __str__(self):
        return f'{self.user.username} ↔ {self.room} (до #{self.last_read_id})'