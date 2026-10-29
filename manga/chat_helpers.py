from django.db.models import Q, F, OuterRef, Subquery
from django.urls import reverse

from .models import User, Notification, ChatRoom, ChatRoomMessage, ChatRoomRead


def admin_users_qs():
    """Все админы сайта: роль admin или Django-персонал."""
    return User.objects.filter(
        Q(role=User.Role.ADMIN) | Q(is_staff=True) | Q(is_superuser=True)
    ).distinct()


def get_admin_room():
    """Общий чат админов (создаётся при первом обращении)."""
    room, _ = ChatRoom.objects.get_or_create(
        room_type=ChatRoom.RoomType.ADMIN, owner=None
    )
    return room


def get_feedback_room(user):
    """Приватный тред пользователя «баги/идеи» с разработчиками."""
    room, _ = ChatRoom.objects.get_or_create(
        room_type=ChatRoom.RoomType.FEEDBACK, owner=user
    )
    return room


def can_access_room(user, room):
    """Кто может читать/писать в комнате."""
    if not user or not user.is_authenticated:
        return False
    if user.is_site_admin:
        return True
    return room.room_type == ChatRoom.RoomType.FEEDBACK and room.owner_id == user.id


def mark_room_read(room, user):
    """Отмечает все текущие сообщения комнаты как прочитанные для user."""
    last_id = (
        room.messages.order_by('-id').values_list('id', flat=True).first() or 0
    )
    ChatRoomRead.objects.update_or_create(
        room=room, user=user, defaults={'last_read_id': last_id}
    )


def _last_read_subquery(user):
    return Subquery(
        ChatRoomRead.objects.filter(
            room=OuterRef('room_id'), user=user
        ).values('last_read_id')[:1]
    )


def room_unread_count(room, user):
    """Непрочитанные в конкретной комнате (не от author)."""
    last_read = ChatRoomRead.objects.filter(
        room=room, user=user
    ).values_list('last_read_id', flat=True).first() or 0
    return room.messages.filter(id__gt=last_read).exclude(author=user).count()


def rooms_unread_count(user, rooms_q):
    """Непрочитанные по набору комнат одним запросом."""
    return (
        ChatRoomMessage.objects.filter(rooms_q)
        .exclude(author=user)
        .annotate(last_read=_last_read_subquery(user))
        .filter(Q(last_read__isnull=True) | Q(id__gt=F('last_read')))
        .count()
    )


def feedback_unread_count(user):
    """Сколько непрочитанных обращений ждёт пользователя."""
    q = Q(room__room_type=ChatRoom.RoomType.FEEDBACK)
    if not user.is_site_admin:
        q &= Q(room__owner=user)
    return rooms_unread_count(user, q)


def admin_chat_unread_count(user):
    """Непрочитанные в чате админов (0 для не-админов)."""
    if not user.is_site_admin:
        return 0
    return rooms_unread_count(user, Q(room__room_type=ChatRoom.RoomType.ADMIN))


def notify_room_message(room, message):
    """Уведомления о новом сообщении: о первом непрочитанном, чтобы не затапливать."""
    text = message.text[:80]
    author = message.author

    if room.room_type == ChatRoom.RoomType.FEEDBACK:
        if author == room.owner:
            # Пользователь написал в поддержку — оповещаем всех админов
            link = reverse('support_thread', kwargs={'room_id': room.id})
            title = 'Обращение в поддержку'
            targets = admin_users_qs().exclude(pk=author.pk)
        else:
            # Админ ответил владельцу треда
            if not room.owner_id or room.owner_id == author.id:
                return
            link = reverse('support')
            title = 'Ответ из поддержки'
            targets = User.objects.filter(pk=room.owner_id)
    else:
        # Чат админов: оповещаем остальных админов
        link = reverse('admin_chat')
        title = 'Сообщение в чате админов'
        targets = admin_users_qs().exclude(pk=author.pk)

    to_notify = [
        u for u in targets
        if room_unread_count(room, u) <= 1  # только первое непрочитанное
    ]
    if to_notify:
        Notification.objects.bulk_create([
            Notification(
                user=u,
                title=title,
                message=f'{author.username}: {text}',
                link=link,
            )
            for u in to_notify
        ])


def feedback_room_rows(current_user, viewer):
    """Список тредов обращений для сайдбара админа."""
    rooms = list(
        ChatRoom.objects.filter(room_type=ChatRoom.RoomType.FEEDBACK)
        .exclude(owner=None)
        .select_related('owner')
        .order_by('-id')
    )
    rows = []
    for room in rooms:
        last = room.messages.select_related('author').order_by('-id').first()
        rows.append({
            'room': room,
            'owner': room.owner,
            'last': last,
            'unread': room_unread_count(room, viewer),
            'is_own': room.owner_id == current_user.id,
        })
    rows.sort(
        key=lambda r: r['last'].created_at.timestamp() if r['last'] else r['room'].created_at.timestamp(),
        reverse=True,
    )
    return rows
