from django.shortcuts import render, redirect, get_object_or_404, reverse
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden, Http404, JsonResponse, FileResponse
from django.contrib.auth import login, logout, get_user_model
from django.contrib import messages
from django.db.models import Q
from django.core.files.base import ContentFile
from django.conf import settings as django_settings
from .models import *
from .forms import *
from .chat_helpers import (
    get_admin_room, get_feedback_room, can_access_room, mark_room_read,
    room_unread_count, feedback_room_rows, notify_room_message,
)

import re
import zipfile
import os
import hashlib
from PIL import Image as PILImage

User = get_user_model()

# Расширения, которые считаем картинками внутри ZIP
ZIP_IMAGE_EXTS = {'.jpg', '.jpeg', '.png', '.webp', '.gif', '.bmp'}

# Максимальная ширина «лёгких» страниц читалки
LITE_MAX_WIDTH = 800


# Может ли пользователь добавлять/редактировать главы тайтла
def _can_manage_chapters(user, title):
    if not user.is_authenticated:
        return False
    if user == title.author or user.is_superuser or user.is_staff or getattr(user, 'role', '') == 'admin':
        return True
    return user.id in title.collaborator_ids


# Может ли пользователь видеть NSFW-тайтлы (только 18+ и без настройки «скрывать»)
def _nsfw_allowed(user):
    if not user or not user.is_authenticated:
        return False
    return user.can_view_nsfw


# Убирает NSFW-тайтлы из выдачи, если пользователь не может их видеть
def filter_nsfw(titles, user):
    if _nsfw_allowed(user):
        return titles
    return titles.filter(is_nsfw=False)


# Тайтл с учётом возрастного ограничения (иначе 404)
def _get_visible_title(request, slug):
    title = get_object_or_404(Title, slug=slug)
    if title.is_nsfw and not _nsfw_allowed(request.user):
        viewer = request.user
        privileged = viewer.is_authenticated and (
            viewer == title.author or viewer.is_staff or viewer.is_superuser
        )
        if not privileged:
            raise Http404
    return title


# Натуральная сортировка: page_2.png перед page_10.png
def _natural_key(filename):
    name = os.path.basename(filename)
    return [int(part) if part.isdigit() else part.lower()
            for part in re.split(r'(\d+)', name)]


# Извлекает картинки из ZIP, сортирует по имени и создаёт страницы
def _pages_from_zip(zip_file, chapter, start_number):
    pages_to_create = []
    with zipfile.ZipFile(zip_file) as zf:
        infos = [
            info for info in zf.infolist()
            if not info.is_dir()
            and os.path.splitext(info.filename)[1].lower() in ZIP_IMAGE_EXTS
        ]
        infos.sort(key=lambda i: _natural_key(i.filename))

        for index, info in enumerate(infos, start=start_number):
            data = zf.read(info)
            ext = os.path.splitext(info.filename)[1].lower()
            page = Page(chapter=chapter, page_number=index)
            page.image.save(f'page_{index}{ext}', ContentFile(data), save=False)
            pages_to_create.append(page)

    Page.objects.bulk_create(pages_to_create)
    return len(pages_to_create)


def home_view(request):
    query = request.GET.get('q', '').strip()
    if query:
        titles = Title.objects.filter(
            Q(name__icontains=query) | Q(original_name__icontains=query)
        ).order_by('-created_at')
    else:
        titles = Title.objects.all().order_by('-created_at')

    titles = filter_nsfw(titles, request.user)

    return render(request, 'manga/home.html', {
        'titles': titles,
        'query': query
    })


def catalog_view(request):
    query = request.GET.get('q', '').strip()
    genre_filter = request.GET.get('genre', '')
    status_filter = request.GET.get('status', '')

    titles = filter_nsfw(Title.objects.all(), request.user).order_by('-created_at')

    if query:
        titles = titles.filter(
            Q(name__icontains=query) | Q(description__icontains=query)
        )
    if genre_filter:
        titles = titles.filter(genres__id=genre_filter)
    if status_filter:
        titles = titles.filter(status=status_filter)

    return render(request, 'manga/catalog.html', {
        'titles': titles,
        'query': query,
        'genres': Genre.objects.all(),
    })



def title_detail_view(request, slug):
    title = _get_visible_title(request, slug)
    chapters = title.chapters.all().order_by('volume', 'number')

    # Дерево комментариев: корни (новые сверху) + вложенные ответы любой глубины
    all_comments = list(
        title.comments.select_related('user', 'parent').order_by('created_at')
    )
    children = {c.id: [] for c in all_comments}
    comment_tree = []
    for comment in all_comments:
        if comment.parent_id and comment.parent_id in children:
            children[comment.parent_id].append(comment)
        elif comment.parent_id is None:
            comment_tree.append(comment)

    comment_tree.reverse()  # новые корневые комментарии сверху
    # ответы внутри треда остаются в хронологическом порядке (старые сверху)

    def attach_replies(comment):
        comment.replies_list = children.get(comment.id, [])
        for reply in comment.replies_list:
            attach_replies(reply)

    for root in comment_tree:
        attach_replies(root)

    user_bookmark = None
    user_rating = None
    read_chapter_ids = []
    last_read_chapter = None
    collab_request = None
    is_collaborator = False

    if request.user.is_authenticated:
        user_bookmark = Bookmark.objects.filter(user=request.user, title=title).first()
        user_rating = Rating.objects.filter(user=request.user, title=title).first()
        collab_request = CollaborationRequest.objects.filter(title=title, from_user=request.user).first()
        is_collaborator = request.user.id in title.collaborator_ids

        read_chapter_ids = set(ReadingHistory.objects.filter(
            user=request.user, 
            chapter__title=title
        ).values_list('chapter_id', flat=True))

        last_history = ReadingHistory.objects.filter(
            user=request.user, 
            chapter__title=title
        ).select_related('chapter').first()

        if last_history:
            last_read_chapter = last_history.chapter

    comment_form = CommentForm()

    is_title_author = request.user.is_authenticated and (
        request.user == title.author or request.user.is_superuser
        or request.user.is_staff or request.user.role == 'admin'
    )

    can_request_collab = request.user.is_authenticated and (
        request.user.role in ('author', 'admin')
        or request.user.is_staff or request.user.is_superuser
    )

    return render(request, 'manga/title_detail.html', {
        'title': title,
        'chapters': chapters,
        'comment_tree': comment_tree,
        'user_bookmark': user_bookmark,
        'user_rating': user_rating,
        'comment_form': comment_form,
        'read_chapter_ids': read_chapter_ids,
        'last_read_chapter': last_read_chapter,
        'collab_request': collab_request,
        'is_collaborator': is_collaborator,
        'is_title_author': is_title_author,
        'can_request_collab': can_request_collab,
        'collab_pending': CollaborationRequest.objects.filter(title=title, status='pending').select_related('from_user') if is_title_author else None,
        'collab_accepted': CollaborationRequest.objects.filter(title=title, status='accepted').select_related('from_user') if is_title_author else None,
    })


# Читалка: показывает страницы главы и сохраняет историю чтения
def reader_view(request, slug, volume, number):
    title = _get_visible_title(request, slug)
    chapter = get_object_or_404(Chapter, title=title, volume=volume, number=number)

    pages = chapter.pages.all().order_by('page_number')

    if request.user.is_authenticated:
        ReadingHistory.objects.update_or_create(
            user=request.user,
            chapter=chapter
        )

    return render(request, 'manga/reader.html', {
        'title': title,
        'chapter': chapter,
        'pages': pages,
    })


@login_required
def create_title_view(request):
    if request.user.role not in ['author', 'admin'] and not request.user.is_superuser:
        return HttpResponseForbidden("У вас нет прав для добавления тайтлов.")

    if request.method == 'POST':
        form = TitleForm(request.POST, request.FILES)
        if form.is_valid():
            title = form.save(commit=False)
            title.author = request.user
            title.save()
            form.save_m2m()

            # Свои жанры/теги: создаём новые и приклеиваем к тайтлу
            for genre in form.create_new_genres():
                title.genres.add(genre)

            return redirect('title_detail', slug=title.slug)
    else:
        form = TitleForm()

    return render(request, 'manga/create_title.html', {'form': form})




@login_required
def add_chapter_view(request, slug):
    title = get_object_or_404(Title, slug=slug)

    if not _can_manage_chapters(request.user, title):
        return HttpResponseForbidden("У вас нет прав для добавления глав к этому тайтлу.")

    if request.method == 'POST':
        chapter_form = ChapterForm(request.POST)
        page_form = PageForm(request.POST, request.FILES)

        if chapter_form.is_valid() and page_form.is_valid():
            volume = chapter_form.cleaned_data['volume']
            number = chapter_form.cleaned_data['number']
            name = chapter_form.cleaned_data.get('name', '')

            chapter, created = Chapter.objects.get_or_create(
                title=title,
                volume=volume,
                number=number,
                defaults={'name': name}
            )

            if not created and name and chapter.name != name:
                chapter.name = name
                chapter.save()

            last_page = chapter.pages.order_by('-page_number').first()
            start_number = (last_page.page_number + 1) if last_page else 1

            images = request.FILES.getlist('images')
            zip_file = request.FILES.get('zip_file')

            if images:
                # Картинки из формы: сортируем по имени (натурально)
                images = sorted(images, key=lambda f: _natural_key(f.name))
                pages_to_create = [
                    Page(
                        chapter=chapter,
                        image=image,
                        page_number=index
                    )
                    for index, image in enumerate(images, start=start_number)
                ]
                Page.objects.bulk_create(pages_to_create)
            elif zip_file:
                # ZIP-архив: распаковываем картинки и нумеруем их автоматически
                try:
                    _pages_from_zip(zip_file, chapter, start_number)
                except zipfile.BadZipFile:
                    messages.error(request, "Не удалось распаковать ZIP-архив: файл повреждён.")
                    return redirect('add_chapter', slug=title.slug)

            if created:
                bookmarks = Bookmark.objects.filter(
                    title=title,
                    status__in=['reading', 'favorite']
                ).select_related('user')

                chapter_url = reverse('reader', kwargs={
                    'slug': title.slug,
                    'volume': chapter.volume,
                    'number': chapter.number,
                })

                notifications_to_create = [
                    Notification(
                        user=b.user,
                        title=f"Новая глава в «{title.name}»!",
                        message=f"Вышла Том {chapter.volume} Глава {chapter.number}",
                        link=chapter_url
                    )
                    for b in bookmarks if b.user != request.user
                ]

                if notifications_to_create:
                    Notification.objects.bulk_create(notifications_to_create)

            # Если главы добавил переводчик — сообщить автору тайтла
            if request.user != title.author:
                Notification.objects.create(
                    user=title.author,
                    title=f"Обновление «{title.name}»!",
                    message=f"{request.user.username} добавил(а) страницы: Том {chapter.volume} Глава {chapter.number}",
                    link=reverse('title_detail', kwargs={'slug': title.slug})
                )

            return redirect('reader', slug=title.slug, volume=chapter.volume, number=chapter.number)
    else:
        chapter_form = ChapterForm()
        page_form = PageForm()

    return render(request, 'manga/add_chapter.html', {
        'title': title,
        'chapter_form': chapter_form,
        'page_form': page_form
    })

def register_view(request):
    if request.method == 'POST':
        form = RegisterForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)  
            return redirect('home')
    else:
        form = RegisterForm()
    return render(request, 'manga/register.html', {'form': form})


def login_view(request):
    if request.method == 'POST':
        form = LoginForm(data=request.POST)
        if form.is_valid():
            user = form.get_user()
            login(request, user)
            return redirect('home')
    else:
        form = LoginForm()
    return render(request, 'manga/login.html', {'form': form})


def logout_view(request):
    logout(request)
    return redirect('home')


@login_required
def add_comment_view(request, slug):
    title = _get_visible_title(request, slug)
    if request.method == 'POST':
        text = request.POST.get('text')
        parent_id = request.POST.get('parent_id')

        if text:
            parent_comment = None
            if parent_id:
                parent_comment = Comment.objects.filter(id=parent_id, title=title).first()

            comment = Comment.objects.create(
                title=title,
                user=request.user,
                text=text,
                parent=parent_comment
            )
            return redirect(f"{reverse('title_detail', kwargs={'slug': title.slug})}#comment-{comment.id}")
    return redirect('title_detail', slug=title.slug)


@login_required
def set_bookmark_view(request, slug):
    title = _get_visible_title(request, slug)
    status = request.POST.get('status')
    note = request.POST.get('note', '').strip()[:1000]

    if status in dict(Bookmark.STATUS_CHOICES):
        Bookmark.objects.update_or_create(
            user=request.user,
            title=title,
            defaults={'status': status, 'note': note}
        )
    elif status == 'remove':
        Bookmark.objects.filter(user=request.user, title=title).delete()
    elif status == 'save_note':
        # Сохранить только заметку, не меняя статус
        Bookmark.objects.filter(user=request.user, title=title).update(note=note)

    return redirect('title_detail', slug=title.slug)


@login_required
def set_rating_view(request, slug):
    title = _get_visible_title(request, slug)
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
    score = 0

    try:
        score = int(request.POST.get('score', 0))
    except ValueError:
        score = 0

    if score == 0:
        Rating.objects.filter(user=request.user, title=title).delete()
    elif 1 <= score <= 10:
        Rating.objects.update_or_create(
            user=request.user,
            title=title,
            defaults={'score': score}
        )
    else:
        score = 0

    if is_ajax:
        return JsonResponse({'status': 'ok', 'score': score, 'average': title.average_rating()})

    return redirect('title_detail', slug=title.slug)


@login_required
def my_titles_view(request):
    titles = Title.objects.filter(author=request.user).order_by('-created_at')
    return render(request, 'manga/my_titles.html', {'titles': titles})


@login_required
def my_bookmarks_view(request):
    status_filter = request.GET.get('status', 'reading')
    bookmarks = Bookmark.objects.filter(user=request.user, status=status_filter).select_related('title')
    if not _nsfw_allowed(request.user):
        bookmarks = bookmarks.filter(title__is_nsfw=False)
    
    return render(request, 'manga/my_bookmarks.html', {
        'bookmarks': bookmarks,
        'current_status': status_filter,
        'status_choices': Bookmark.STATUS_CHOICES,
    })




# AJAX-эндпоинт: уведомления исчезают после просмотра — удаляем все уведомления
@login_required
def mark_notifications_read(request):
    Notification.objects.filter(user=request.user).delete()
    return JsonResponse({'status': 'ok'})


# AJAX-эндпоинт: удаляет одно просмотренное уведомление
@login_required
def delete_notification_view(request, notif_id):
    Notification.objects.filter(pk=notif_id, user=request.user).delete()
    return JsonResponse({'status': 'ok'})


@login_required
def delete_chapter_view(request, chapter_id):
    chapter = get_object_or_404(Chapter, pk=chapter_id)
    title = chapter.title

    if not _can_manage_chapters(request.user, title):
        messages.error(request, "У вас нет прав на удаление этой главы.")
        return redirect('title_detail', slug=title.slug)

    if request.method == 'POST':
        volume, number = chapter.volume, chapter.number
        chapter.delete()
        messages.success(request, f"Глава Том {volume} №{number} и её файлы успешно удалены!")

    return redirect('title_detail', slug=title.slug)


# Профиль: загрузка аватара и переключение роли (читатель <-> автор)
@login_required
def profile_view(request):
    user = request.user

    if request.method == 'POST':
        if 'avatar' in request.FILES:
            user.avatar = request.FILES['avatar']
            user.save(update_fields=['avatar'])
            return redirect('profile')

        if 'role' in request.POST:
            new_role = request.POST.get('role')

            if new_role == User.Role.AUTHOR and user.role == User.Role.READER:
                user.role = User.Role.AUTHOR
                user.save(update_fields=['role'])
                messages.success(request, "Поздравляем! Теперь вы автор — можете добавлять тайтлы.")
            elif new_role == User.Role.READER and user.role == User.Role.AUTHOR:
                if user.titles.exists():
                    messages.error(request, "Нельзя вернуться в читатели: у вас уже есть выложенные тайтлы.")
                else:
                    user.role = User.Role.READER
                    user.save(update_fields=['role'])
                    messages.success(request, "Вы больше не автор — снова читатель.")
            return redirect('profile')

    bookmarks = Bookmark.objects.filter(user=user).select_related('title')
    history = ReadingHistory.objects.filter(user=user).select_related('chapter__title')[:10]

    context = {
        'user_profile': user,
        'bookmarks': bookmarks,
        'history': history,
        'has_titles': user.titles.exists(),
        'friends': user.friends.order_by('username')[:12],
        'friends_count': user.friends_count,
        'pending_incoming': FriendRequest.objects.filter(to_user=user, status='pending').select_related('from_user'),
    }
    return render(request, 'manga/profile.html', context)


# Ищет пользователя по нику или публичному ID (для чёрного списка/исключений)
def _find_user_by_query(query, exclude_user):
    return User.objects.filter(
        Q(username__iexact=query) | Q(public_id=query)
    ).exclude(pk=exclude_user.pk).filter(is_active=True).first()


# Полная очистка связей при блокировке: дружба, заявки, исключения закладок
def _purge_relations(user, target):
    friendship = user.friendship_with(target)
    if friendship:
        friendship.delete()
    FriendRequest.objects.filter(
        Q(from_user=user, to_user=target) | Q(from_user=target, to_user=user)
    ).delete()
    BookmarkAccess.objects.filter(owner=user, viewer=target).delete()
    BookmarkAccess.objects.filter(owner=target, viewer=user).delete()


# Отдельная страница настроек: оформление (тема/акцент/анимации) и аккаунт
def settings_view(request):
    user = request.user

    if request.method == 'POST':
        if not user.is_authenticated:
            return redirect('login')

        action = request.POST.get('action', '')

        if 'role' in request.POST and not action:
            new_role = request.POST.get('role')

            if new_role == User.Role.AUTHOR and user.role == User.Role.READER:
                user.role = User.Role.AUTHOR
                user.save(update_fields=['role'])
                messages.success(request, "Поздравляем! Теперь вы автор — можете добавлять тайтлы.")
            elif new_role == User.Role.READER and user.role == User.Role.AUTHOR:
                if user.titles.exists():
                    messages.error(request, "Нельзя вернуться в читатели: у вас уже есть выложенные тайтлы.")
                else:
                    user.role = User.Role.READER
                    user.save(update_fields=['role'])
                    messages.success(request, "Вы больше не автор — снова читатель.")
            return redirect('settings')

        if action == 'save_account':
            form = AccountForm(request.POST, instance=user)
            if form.is_valid():
                form.save()
                messages.success(request, "Настройки аккаунта сохранены.")
            else:
                messages.error(request, "Не удалось сохранить настройки: проверьте поля.")
            return redirect('settings')

        if action == 'blocklist_add':
            query = request.POST.get('username', '').strip()
            if not query:
                messages.error(request, "Введите имя пользователя или ID.")
            else:
                target = _find_user_by_query(query, user)
                if not target:
                    messages.error(request, "Пользователь не найден.")
                elif target == user:
                    messages.error(request, "Нельзя заблокировать самого себя.")
                else:
                    block, created = UserBlock.objects.get_or_create(blocker=user, blocked=target)
                    if created:
                        _purge_relations(user, target)
                        messages.success(request, f"{target.username} добавлен(а) в чёрный список.")
                    else:
                        messages.info(request, f"{target.username} уже в чёрном списке.")
            return redirect('settings')

        if action == 'blocklist_remove':
            block = get_object_or_404(UserBlock, pk=request.POST.get('block_id'), blocker=user)
            who = block.blocked.username
            block.delete()
            messages.success(request, f"{who} удалён(а) из чёрного списка.")
            return redirect('settings')

        if action == 'access_add':
            query = request.POST.get('username', '').strip()
            if not query:
                messages.error(request, "Введите имя пользователя или ID.")
            else:
                target = _find_user_by_query(query, user)
                if not target:
                    messages.error(request, "Пользователь не найден.")
                elif user.has_blocked(target) or target.has_blocked(user):
                    messages.error(request, "Нельзя добавить исключение для заблокированного пользователя.")
                else:
                    access, created = BookmarkAccess.objects.get_or_create(owner=user, viewer=target)
                    if created:
                        messages.success(request, f"{target.username} теперь видит ваши закладки.")
                    else:
                        messages.info(request, f"{target.username} уже есть в исключениях.")
            return redirect('settings')

        if action == 'access_remove':
            access = get_object_or_404(BookmarkAccess, pk=request.POST.get('access_id'), owner=user)
            who = access.viewer.username
            access.delete()
            messages.success(request, f"{who} удалён(а) из исключений.")
            return redirect('settings')

        return redirect('settings')

    context = {}
    if user.is_authenticated:
        context = {
            'user_profile': user,
            'has_titles': user.titles.exists(),
            'friends': user.friends.order_by('username')[:12],
            'friends_count': user.friends_count,
            'pending_incoming': FriendRequest.objects.filter(to_user=user, status='pending').select_related('from_user'),
            'account_form': AccountForm(instance=user),
            'blocked_list': UserBlock.objects.filter(blocker=user).select_related('blocked'),
            'bookmark_access_list': BookmarkAccess.objects.filter(owner=user).select_related('viewer'),
            'bookmarks_visibility': user.bookmarks_visibility,
        }
    return render(request, 'manga/settings.html', context)


# ---------------------------------------------------------------------------
# Публичный профиль другого пользователя
# ---------------------------------------------------------------------------
def user_profile_view(request, username):
    profile_user = get_object_or_404(User, username=username, is_active=True)
    viewer = request.user
    is_self = viewer.is_authenticated and viewer == profile_user

    # Чёрный список скрывает профиль в обе стороны
    viewer_blocked_profile = False
    profile_blocked_viewer = False
    if viewer.is_authenticated and not is_self:
        viewer_blocked_profile = viewer.has_blocked(profile_user)
        profile_blocked_viewer = profile_user.has_blocked(viewer)
    is_hidden = not is_self and (viewer_blocked_profile or profile_blocked_viewer)

    can_view_full = is_self or (not is_hidden and profile_user.can_view_profile(viewer))
    can_view_bookmarks = is_self or (not is_hidden and profile_user.can_view_bookmarks(viewer))

    titles = filter_nsfw(profile_user.titles.all(), request.user).order_by('-created_at') if can_view_full else Title.objects.none()
    profile_bookmarks = (
        Bookmark.objects.filter(user=profile_user).select_related('title')
        if can_view_bookmarks else Bookmark.objects.none()
    )
    if not _nsfw_allowed(request.user):
        profile_bookmarks = profile_bookmarks.filter(title__is_nsfw=False)

    friendship = None
    incoming_request = None
    outgoing_request = None
    my_block_id = None

    if viewer.is_authenticated and not is_self:
        if viewer_blocked_profile:
            my_block_id = UserBlock.objects.filter(
                blocker=viewer, blocked=profile_user
            ).values_list('id', flat=True).first()

        me = viewer
        friendship = FriendRequest.objects.filter(status='accepted').filter(
            Q(from_user=me, to_user=profile_user) | Q(from_user=profile_user, to_user=me)
        ).first()
        incoming_request = FriendRequest.objects.filter(
            from_user=profile_user, to_user=me, status='pending'
        ).first()
        outgoing_request = FriendRequest.objects.filter(
            from_user=me, to_user=profile_user, status='pending'
        ).first()

    context = {
        'user_profile': profile_user,
        'profile_titles': titles,
        'profile_bookmarks': profile_bookmarks,
        'is_self': is_self,
        'is_hidden': is_hidden,
        'viewer_blocked_profile': viewer_blocked_profile,
        'profile_blocked_viewer': profile_blocked_viewer,
        'my_block_id': my_block_id,
        'can_view_full': can_view_full,
        'can_view_bookmarks': can_view_bookmarks,
        'is_author': (profile_user.role in ('author', 'admin') or profile_user.is_superuser or titles.exists()) if can_view_full else False,
        'friends_count': profile_user.friends_count,
        'friendship': friendship,
        'incoming_request': incoming_request,
        'outgoing_request': outgoing_request,
    }
    return render(request, 'manga/user_profile.html', context)


# ---------------------------------------------------------------------------
# Друзья: список, заявки, принятие/отклонение/удаление
# ---------------------------------------------------------------------------
@login_required
def friends_view(request):
    me = request.user

    accepted = FriendRequest.objects.filter(status='accepted').filter(
        Q(from_user=me) | Q(to_user=me)
    ).select_related('from_user', 'to_user')

    friends_data = []
    for fr in accepted:
        other = fr.to_user if fr.from_user_id == me.id else fr.from_user
        friends_data.append({'user': other, 'friendship_id': fr.id})
    friends_data.sort(key=lambda d: d['user'].username.lower())

    incoming = FriendRequest.objects.filter(to_user=me, status='pending').select_related('from_user')
    outgoing = FriendRequest.objects.filter(from_user=me, status='pending').select_related('to_user')

    context = {
        'friends_data': friends_data,
        'friends_count': len(friends_data),
        'incoming_requests': incoming,
        'outgoing_requests': outgoing,
        'incoming_count': incoming.count(),
        'outgoing_count': outgoing.count(),
    }
    return render(request, 'manga/friends.html', context)


@login_required
def send_friend_request(request, username):
    target = get_object_or_404(User, username=username, is_active=True)
    me = request.user

    if request.method == 'POST':
        if target == me:
            messages.error(request, "Нельзя добавить в друзья самого себя.")
        elif me.has_blocked(target):
            messages.error(request, f"{target.username} в вашем чёрном списке. Разблокируйте пользователя в настройках.")
        elif target.has_blocked(me):
            messages.error(request, "Невозможно отправить заявку этому пользователю.")
        elif me.is_friends_with(target):
            messages.error(request, f"{target.username} уже у вас в друзьях.")
        else:
            fr, created = FriendRequest.objects.get_or_create(
                from_user=me, to_user=target, defaults={'status': 'pending'}
            )
            if created:
                Notification.objects.create(
                    user=target,
                    title="Новая заявка в друзья!",
                    message=f"{me.username} хочет добавить вас в друзья",
                    link=reverse('friends'),
                    friend_request=fr
                )
                messages.success(request, f"Заявка отправлена пользователю {target.username}.")
            else:
                messages.info(request, f"Заявка пользователю {target.username} уже отправлена.")

    ref = request.META.get('HTTP_REFERER')
    if ref and ref != request.build_absolute_uri():
        return redirect(ref)
    return redirect('user_profile', username=username)


# ---------------------------------------------------------------------------
# Мини-чат: личная переписка между друзьями
# ---------------------------------------------------------------------------
def _chat_can_talk(me, partner):
    """Можно ли писать этому пользователю: только друг, без блокировок."""
    if not partner or partner.pk == me.pk:
        return False
    if me.has_blocked(partner) or partner.has_blocked(me):
        return False
    return me.is_friends_with(partner)


def _chat_friends_rows(me):
    """Друзья + последнее сообщение и непрочитанные для списка диалогов."""
    friends = list(me.friends.order_by('username'))
    friend_ids = [f.id for f in friends]

    last_map = {}
    unread_map = {}

    if friend_ids:
        dialog_qs = Message.objects.filter(
            Q(sender_id=me.id, recipient_id__in=friend_ids) |
            Q(recipient_id=me.id, sender_id__in=friend_ids)
        ).order_by('created_at')
        for m in dialog_qs:
            other_id = m.recipient_id if m.sender_id == me.id else m.sender_id
            last_map[other_id] = m

        unread_ids = Message.objects.filter(
            recipient_id=me.id, is_read=False, sender_id__in=friend_ids
        ).values_list('sender_id', flat=True)
        for sid in unread_ids:
            unread_map[sid] = unread_map.get(sid, 0) + 1

    rows = [
        {'user': f, 'last': last_map.get(f.id), 'unread': unread_map.get(f.id, 0)}
        for f in friends
    ]
    rows.sort(
        key=lambda r: r['last'].created_at.timestamp() if r['last'] else 0,
        reverse=True
    )
    return rows


def _message_json(m, me):
    return {
        'id': m.id,
        'text': m.text,
        'sender': m.sender.username,
        'is_mine': m.sender_id == me.id,
        'time': m.created_at.strftime('%d.%m %H:%M'),
        'is_read': m.is_read,
    }


@login_required
def chat_list_view(request):
    rows = _chat_friends_rows(request.user)
    unread_total = Message.objects.filter(recipient=request.user, is_read=False).count()
    return render(request, 'manga/chat.html', {
        'partner': None,
        'can_chat': False,
        'chat_messages': [],
        'chat_rows': rows,
        'chat_unread_total': unread_total,
    })


@login_required
def chat_detail_view(request, username):
    me = request.user
    partner = get_object_or_404(User, username=username, is_active=True)
    can_chat = _chat_can_talk(me, partner)

    chat_messages = []
    if can_chat:
        chat_messages = list(
            Message.objects.filter(
                Q(sender=me, recipient=partner) | Q(sender=partner, recipient=me)
            ).select_related('sender', 'recipient').order_by('-created_at')[:100]
        )
        chat_messages.reverse()
        Message.objects.filter(sender=partner, recipient=me, is_read=False).update(is_read=True)
        for m in chat_messages:
            if m.recipient_id == me.id:
                m.is_read = True

    unread_total = Message.objects.filter(recipient=me, is_read=False).count()

    return render(request, 'manga/chat.html', {
        'partner': partner,
        'can_chat': can_chat,
        'chat_messages': chat_messages,
        'chat_rows': _chat_friends_rows(me),
        'chat_unread_total': unread_total,
        'last_message_id': chat_messages[-1].id if chat_messages else 0,
    })


@login_required
def chat_send_view(request, username):
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'error': 'Только POST'}, status=405)

    me = request.user
    partner = get_object_or_404(User, username=username, is_active=True)
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'

    if not _chat_can_talk(me, partner):
        if is_ajax:
            return JsonResponse({'status': 'error', 'error': 'Писать можно только друзьям.'}, status=403)
        messages.error(request, "Писать сообщения можно только друзьям.")
        return redirect('chat_detail', username=partner.username)

    text = request.POST.get('text', '').strip()[:2000]
    if not text:
        if is_ajax:
            return JsonResponse({'status': 'error', 'error': 'Сообщение пустое.'}, status=400)
        messages.error(request, "Сообщение пустое.")
        return redirect('chat_detail', username=partner.username)

    # Уведомляем только о первом непрочитанном, чтобы не затапливать колокольчик
    has_unread = Message.objects.filter(sender=me, recipient=partner, is_read=False).exists()

    msg = Message.objects.create(sender=me, recipient=partner, text=text)
    if not has_unread:
        Notification.objects.create(
            user=partner,
            title="Новое сообщение!",
            message=f"{me.username}: {text[:80]}",
            link=reverse('chat_detail', kwargs={'username': me.username})
        )

    if not is_ajax:
        return redirect('chat_detail', username=partner.username)
    return JsonResponse({'status': 'ok', 'message': _message_json(msg, me)})


@login_required
def chat_poll_view(request, username):
    me = request.user
    partner = get_object_or_404(User, username=username, is_active=True)

    if not _chat_can_talk(me, partner):
        return JsonResponse({'status': 'error', 'error': 'Нет доступа.'}, status=403)

    try:
        after = int(request.GET.get('after', 0))
    except (TypeError, ValueError):
        after = 0

    new_messages = list(
        Message.objects.filter(
            Q(sender=me, recipient=partner) | Q(sender=partner, recipient=me),
            id__gt=after
        ).select_related('sender', 'recipient').order_by('created_at')
    )

    incoming_ids = [m.id for m in new_messages if m.recipient_id == me.id]
    if incoming_ids:
        Message.objects.filter(id__in=incoming_ids).update(is_read=True)
        for m in new_messages:
            if m.id in incoming_ids:
                m.is_read = True

    # Мои сообщения, которые собеседник уже прочитал (для отметки «прочитано»)
    read_ids = list(
        Message.objects.filter(
            Q(sender=me, recipient=partner), is_read=True
        ).order_by('-created_at')[:100].values_list('id', flat=True)
    )

    return JsonResponse({
        'status': 'ok',
        'messages': [_message_json(m, me) for m in new_messages],
        'read_ids': read_ids,
        'unread': Message.objects.filter(recipient=me, is_read=False).count(),
    })


@login_required
def respond_friend_request(request, request_id):
    fr = get_object_or_404(FriendRequest, pk=request_id, to_user=request.user, status='pending')

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'accept':
            # Уведомление об этой заявке обработано — оно исчезает
            Notification.objects.filter(friend_request=fr).delete()
            fr.status = 'accepted'
            fr.save(update_fields=['status', 'updated_at'])
            Notification.objects.create(
                user=fr.from_user,
                title="Заявка принята!",
                message=f"{request.user.username} принял(а) вашу заявку в друзья",
                link=reverse('user_profile', kwargs={'username': request.user.username}),
                friend_request=fr
            )
            messages.success(request, f"{fr.from_user.username} теперь у вас в друзьях.")
        elif action == 'decline':
            # fr.delete() каскадом удаляет и уведомление об этой заявке
            fr.delete()
            messages.info(request, "Заявка в друзья отклонена.")

    ref = request.META.get('HTTP_REFERER')
    if ref and ref != request.build_absolute_uri():
        return redirect(ref)
    return redirect('friends')


@login_required
def cancel_friend_request(request, request_id):
    fr = get_object_or_404(FriendRequest, pk=request_id, from_user=request.user, status='pending')
    if request.method == 'POST':
        fr.delete()
        messages.info(request, "Заявка в друзья отозвана.")

    ref = request.META.get('HTTP_REFERER')
    if ref and ref != request.build_absolute_uri():
        return redirect(ref)
    return redirect('friends')


@login_required
def remove_friend(request, friendship_id):
    fr = get_object_or_404(
        FriendRequest, pk=friendship_id, status='accepted'
    )
    if request.method == 'POST':
        if request.user not in (fr.from_user, fr.to_user):
            return HttpResponseForbidden("Это не ваш друг.")
        other = fr.to_user if request.user == fr.from_user else fr.from_user
        fr.delete()
        messages.info(request, f"{other.username} удалён(а) из друзей.")

    ref = request.META.get('HTTP_REFERER')
    if ref and ref != request.build_absolute_uri():
        return redirect(ref)
    return redirect('friends')


# ---------------------------------------------------------------------------
# «Лёгкие» страницы читалки: сжатая копия для быстрой загрузки
# ---------------------------------------------------------------------------
def page_lite_view(request, page_id):
    page = get_object_or_404(Page, pk=page_id)

    try:
        src_path = page.image.path
    except ValueError:
        raise Http404

    if not os.path.exists(src_path):
        raise Http404

    cache_dir = os.path.join(django_settings.MEDIA_ROOT, 'cache', 'lite')
    os.makedirs(cache_dir, exist_ok=True)

    stat = os.stat(src_path)
    key = hashlib.md5(f'{page.id}-{stat.st_mtime}-{stat.st_size}'.encode()).hexdigest()[:16]
    out_path = os.path.join(cache_dir, f'{page.id}_{key}.jpg')

    if not os.path.exists(out_path):
        try:
            img = PILImage.open(src_path).convert('RGB')
        except Exception:
            raise Http404

        if img.width > LITE_MAX_WIDTH:
            ratio = LITE_MAX_WIDTH / img.width
            img = img.resize((LITE_MAX_WIDTH, max(1, int(img.height * ratio))), PILImage.LANCZOS)

        # Старый кэш той же страницы — подчищаем
        for old in os.listdir(cache_dir):
            if old.startswith(f'{page.id}_') and old != os.path.basename(out_path):
                try:
                    os.remove(os.path.join(cache_dir, old))
                except OSError:
                    pass

        img.save(out_path, 'JPEG', quality=72, optimize=True)

    return FileResponse(open(out_path, 'rb'), content_type='image/jpeg')


# ---------------------------------------------------------------------------
# Общий перевод: переводчик просит права, автор тайтла решает
# ---------------------------------------------------------------------------
@login_required
def request_collab_view(request, slug):
    title = _get_visible_title(request, slug)

    if request.method == 'POST':
        if request.user == title.author:
            messages.error(request, "Это ваш собственный тайтл.")
        elif _can_manage_chapters(request.user, title):
            messages.info(request, "У вас уже есть права на этот тайтл.")
        elif not (request.user.role in ('author', 'admin')
                  or request.user.is_staff or request.user.is_superuser):
            messages.error(request, "Запрос на совместный перевод могут отправлять только авторы и администраторы.")
        else:
            message = request.POST.get('message', '').strip()[:500]
            collab, created = CollaborationRequest.objects.get_or_create(
                title=title,
                from_user=request.user,
                defaults={'message': message, 'status': 'pending'}
            )
            if created:
                Notification.objects.create(
                    user=title.author,
                    title="Запрос на общий перевод!",
                    message=f"{request.user.username} просит права на совместное добавление глав к «{title.name}»",
                    link=reverse('title_detail', kwargs={'slug': title.slug})
                )
                messages.success(request, f"Запрос отправлен автору «{title.name}».")
            else:
                messages.info(request, "Вы уже отправляли запрос на этот тайтл.")

    ref = request.META.get('HTTP_REFERER')
    if ref and ref != request.build_absolute_uri():
        return redirect(ref)
    return redirect('title_detail', slug=title.slug)


@login_required
def respond_collab_view(request, request_id):
    collab = get_object_or_404(
        CollaborationRequest, pk=request_id, status='pending'
    )
    title = collab.title

    if request.user != title.author and request.user.role != 'admin' and not request.user.is_superuser:
        return HttpResponseForbidden("Решение принимает только автор тайтла.")

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'accept':
            collab.status = 'accepted'
            collab.save(update_fields=['status', 'updated_at'])
            Notification.objects.create(
                user=collab.from_user,
                title="Запрос на общий перевод принят!",
                message=f"Автор «{title.name}» разрешил вам добавлять главы",
                link=reverse('add_chapter', kwargs={'slug': title.slug})
            )
            messages.success(request, f"{collab.from_user.username} теперь соавтор «{title.name}».")
        elif action == 'decline':
            collab.delete()
            messages.info(request, "Запрос на общий перевод отклонён.")

    ref = request.META.get('HTTP_REFERER')
    if ref and ref != request.build_absolute_uri():
        return redirect(ref)
    return redirect('title_detail', slug=title.slug)


@login_required
def remove_collab_view(request, request_id):
    collab = get_object_or_404(
        CollaborationRequest, pk=request_id, status='accepted'
    )
    title = collab.title

    if request.user != title.author and request.user.role != 'admin' and not request.user.is_superuser:
        return HttpResponseForbidden("Убрать соавтора может только автор тайтла.")

    if request.method == 'POST':
        who = collab.from_user.username
        collab.delete()
        messages.info(request, f"{who} больше не соавтор «{title.name}».")

    ref = request.META.get('HTTP_REFERER')
    if ref and ref != request.build_absolute_uri():
        return redirect(ref)
    return redirect('title_detail', slug=title.slug)


# ---------------------------------------------------------------------------
# Редактирование главы: данные главы, новые страницы, удаление страниц
# ---------------------------------------------------------------------------
@login_required
def edit_chapter_view(request, chapter_id):
    chapter = get_object_or_404(Chapter, pk=chapter_id)
    title = chapter.title

    if not _can_manage_chapters(request.user, title):
        return HttpResponseForbidden("У вас нет прав на редактирование этой главы.")

    if request.method == 'POST':
        action = request.POST.get('action')

        # Удаление отдельной страницы
        if action == 'delete_page':
            page_id = request.POST.get('page_id')
            page = chapter.pages.filter(pk=page_id).first()
            if page:
                page.delete()  # сигнал удалит и файл, и «лёгкую» копию
                messages.success(request, f"Страница {page.page_number} удалена.")
            return redirect('edit_chapter', chapter_id=chapter.id)

        # Основная форма: данные главы + опционально новые картинки
        chapter_form = ChapterForm(request.POST, instance=chapter)
        page_form = PageForm(request.POST, request.FILES)

        if chapter_form.is_valid():
            # Нельзя сделать дубль главы (тот же том + номер у этого тайтла)
            dup = Chapter.objects.filter(
                title=title,
                volume=chapter_form.cleaned_data['volume'],
                number=chapter_form.cleaned_data['number']
            ).exclude(pk=chapter.pk).first()
            if dup:
                chapter_form.add_error(None, "Глава с таким томом и номером уже существует.")
            else:
                chapter_form.save()

                images = request.FILES.getlist('images')
                zip_file = request.FILES.get('zip_file')

                if images or zip_file:
                    last_page = chapter.pages.order_by('-page_number').first()
                    start_number = (last_page.page_number + 1) if last_page else 1

                    if images:
                        images = sorted(images, key=lambda f: _natural_key(f.name))
                        Page.objects.bulk_create([
                            Page(chapter=chapter, image=image, page_number=index)
                            for index, image in enumerate(images, start=start_number)
                        ])
                    elif zip_file:
                        try:
                            _pages_from_zip(zip_file, chapter, start_number)
                        except zipfile.BadZipFile:
                            messages.error(request, "Не удалось распаковать ZIP-архив: файл повреждён.")

                messages.success(request, "Глава обновлена.")
                return redirect('edit_chapter', chapter_id=chapter.id)
    else:
        chapter_form = ChapterForm(instance=chapter)
        page_form = PageForm()

    pages = chapter.pages.all().order_by('page_number')

    context = {
        'title': title,
        'chapter': chapter,
        'chapter_form': chapter_form,
        'page_form': page_form,
        'pages': pages,
    }
    return render(request, 'manga/edit_chapter.html', context)


# ---------------------------------------------------------------------------
# Найти друга: поиск пользователей по нику или публичному ID
# ---------------------------------------------------------------------------
@login_required
def find_friends_view(request):
    query = request.GET.get('q', '').strip()
    users = User.objects.filter(is_active=True).exclude(pk=request.user.pk).order_by('username')

    # Скрыть тех, кто заблокировал меня
    users = users.exclude(
        pk__in=UserBlock.objects.filter(blocked=request.user).values_list('blocker_id', flat=True)
    )

    if query:
        users = users.filter(
            Q(username__icontains=query) | Q(public_id__icontains=query)
        )

    users = list(users[:60])

    # Статус дружбы/заявок для каждого найденного пользователя
    user_ids = [u.id for u in users]
    accepted = FriendRequest.objects.filter(status='accepted').filter(
        Q(from_user=request.user, to_user_id__in=user_ids) |
        Q(to_user=request.user, from_user_id__in=user_ids)
    )
    friend_ids = set()
    friendship_map = {}
    for fr in accepted:
        other_id = fr.to_user_id if fr.from_user_id == request.user.id else fr.from_user_id
        friend_ids.add(other_id)
        friendship_map[other_id] = fr.id

    outgoing_map = dict(
        FriendRequest.objects.filter(
            from_user=request.user, to_user_id__in=user_ids, status='pending'
        ).values_list('to_user_id', 'id')
    )
    incoming_map = dict(
        FriendRequest.objects.filter(
            to_user=request.user, from_user_id__in=user_ids, status='pending'
        ).values_list('from_user_id', 'id')
    )
    blocked_map = dict(
        UserBlock.objects.filter(
            blocker=request.user, blocked_id__in=user_ids
        ).values_list('blocked_id', 'id')
    )

    rows = []
    for u in users:
        rows.append({
            'user': u,
            'is_friend': u.id in friend_ids,
            'friendship_id': friendship_map.get(u.id),
            'sent_request': u.id in outgoing_map,
            'incoming_request': u.id in incoming_map,
            'outgoing_id': outgoing_map.get(u.id),
            'incoming_id': incoming_map.get(u.id),
            'is_blocked_by_me': u.id in blocked_map,
            'block_id': blocked_map.get(u.id),
        })

    return render(request, 'manga/find_friends.html', {
        'query': query,
        'user_rows': rows,
        'found_count': len(rows),
    })


# ---------------------------------------------------------------------------
# Чёрный список: блокировка/разблокировка
# ---------------------------------------------------------------------------
@login_required
def block_user_view(request, username):
    target = get_object_or_404(User, username=username, is_active=True)
    me = request.user

    if request.method == 'POST':
        if target == me:
            messages.error(request, "Нельзя заблокировать самого себя.")
        else:
            block, created = UserBlock.objects.get_or_create(blocker=me, blocked=target)
            if created:
                _purge_relations(me, target)
                messages.success(request, f"{target.username} заблокирован(а). Заявки и дружба удалены.")
            else:
                messages.info(request, f"{target.username} уже в чёрном списке.")

    ref = request.META.get('HTTP_REFERER')
    if ref and ref != request.build_absolute_uri():
        return redirect(ref)
    return redirect('settings')


@login_required
def unblock_user_view(request, block_id):
    block = get_object_or_404(UserBlock, pk=block_id, blocker=request.user)

    if request.method == 'POST':
        who = block.blocked.username
        block.delete()
        messages.success(request, f"{who} разблокирован(а).")

    ref = request.META.get('HTTP_REFERER')
    if ref and ref != request.build_absolute_uri():
        return redirect(ref)
    return redirect('settings')



# ---------------------------------------------------------------------------
# Поддержка: чат «баги и идеи» с разработчиком + отдельный чат админов
# ---------------------------------------------------------------------------
def _room_message_json(m, me):
    return {
        'id': m.id,
        'text': m.text,
        'sender': m.author.username,
        'is_mine': m.author_id == me.id,
        'time': m.short_time,
    }


# Общая отрисовка страницы комнаты (сайдбар опционален)
def _render_chat_room(request, room, heading, sub, **extra):
    mark_room_read(room, request.user)
    chat_messages = list(
        room.messages.select_related('author').order_by('-created_at')[:200]
    )
    chat_messages.reverse()

    context = {
        'room': room,
        'chat_messages': chat_messages,
        'last_message_id': chat_messages[-1].id if chat_messages else 0,
        'send_url': reverse('room_send', kwargs={'room_id': room.id}),
        'poll_url': reverse('room_poll', kwargs={'room_id': room.id}),
        'chat_heading': heading,
        'chat_sub': sub,
        'room_unread': 0,
    }
    context.update(extra)
    return render(request, 'manga/support.html', context)


# Чат поддержки: обычный пользователь видит свой тред, админ — входящие обращения
@login_required
def support_view(request):
    me = request.user
    room = get_feedback_room(me)

    if request.method == 'POST':
        text = request.POST.get('text', '').strip()[:2000]
        if not text:
            messages.error(request, "Сообщение пустое.")
        else:
            msg = ChatRoomMessage.objects.create(room=room, author=me, text=text)
            notify_room_message(room, msg)
            messages.success(request, "Сообщение отправлено разработчикам.")
        return redirect('support')

    sidebar_rows = feedback_room_rows(me, me) if me.is_site_admin else []

    return _render_chat_room(
        request, room,
        heading='Баги и идеи',
        sub='Чат с разработчиком: сообщите о проблеме или предложите идею — ответят администраторы.',
        is_support=True,
        show_sidebar=True,
        sidebar_rows=sidebar_rows,
        sidebar_title='Обращения',
        sidebar_empty_msg='Обращений пока нет.',
    )


# Отдельный тред обращения (только для админов)
@login_required
def support_thread_view(request, room_id):
    me = request.user
    room = get_object_or_404(
        ChatRoom, pk=room_id, room_type=ChatRoom.RoomType.FEEDBACK
    )

    if not me.is_site_admin:
        if room.owner_id == me.id:
            return redirect('support')
        return HttpResponseForbidden("Этот тред видят только администраторы.")

    return _render_chat_room(
        request, room,
        heading=f'Обращение от {room.owner.username}' if room.owner else 'Обращение',
        sub='Ответьте пользователю — он увидит сообщение в разделе «Баги и идеи».',
        is_support=True,
        show_sidebar=True,
        sidebar_rows=feedback_room_rows(me, me),
        sidebar_title='Обращения',
        sidebar_empty_msg='Обращений пока нет.',
        active_room_id=room.id,
    )


# Отдельный чат админов: сообщения видят все админы
@login_required
def admin_chat_view(request):
    if not request.user.is_site_admin:
        return HttpResponseForbidden("Чат админов доступен только админам.")

    room = get_admin_room()

    return _render_chat_room(
        request, room,
        heading='Чат админов',
        sub='Общий чат администрации — сообщения видят все администраторы.',
        is_support=False,
        show_sidebar=False,
    )


# ---------------------------------------------------------------------------
# Объявление администрации: сообщение уходит ВСЕМ пользователям (и админам)
# ---------------------------------------------------------------------------
@login_required
def admin_announce_view(request):
    if not request.user.is_site_admin:
        return HttpResponseForbidden("Объявления может писать только администратор.")

    if request.method == 'POST':
        title = request.POST.get('title', '').strip()[:255]
        message = request.POST.get('message', '').strip()

        if not title or not message:
            messages.error(request, "Заполните заголовок и текст объявления.")
        else:
            targets = list(User.objects.filter(is_active=True))
            if targets:
                Notification.objects.bulk_create([
                    Notification(
                        user=u,
                        title=title,
                        message=message,
                        link=reverse('home'),
                        is_announcement=True,
                    )
                    for u in targets
                ])
            messages.success(
                request,
                f"Объявление «{title}» отправлено {len(targets)} пользователям."
            )
        return redirect('admin_announce')

    recent = Notification.objects.filter(
        user=request.user, is_announcement=True
    ).order_by('-created_at')[:20]

    return render(request, 'manga/admin_announce.html', {
        'recent_announcements': recent,
    })


# Отправка сообщения в любую доступную комнату (AJAX + обычная форма)
@login_required
def room_send_view(request, room_id):
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'error': 'Только POST'}, status=405)

    me = request.user
    room = get_object_or_404(ChatRoom, pk=room_id)
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'

    if not can_access_room(me, room):
        if is_ajax:
            return JsonResponse({'status': 'error', 'error': 'Нет доступа.'}, status=403)
        return HttpResponseForbidden("Нет доступа к этому чату.")

    text = request.POST.get('text', '').strip()[:2000]
    if not text:
        if is_ajax:
            return JsonResponse({'status': 'error', 'error': 'Сообщение пустое.'}, status=400)
        messages.error(request, "Сообщение пустое.")
        ref = request.META.get('HTTP_REFERER')
        if ref and ref != request.build_absolute_uri():
            return redirect(ref)
        return redirect('support')

    msg = ChatRoomMessage.objects.create(room=room, author=me, text=text)
    notify_room_message(room, msg)

    if not is_ajax:
        ref = request.META.get('HTTP_REFERER')
        if ref and ref != request.build_absolute_uri():
            return redirect(ref)
        return redirect('support')

    return JsonResponse({'status': 'ok', 'message': _room_message_json(msg, me)})


# Опрос новых сообщений комнаты (AJAX каждые 4 секунды)
@login_required
def room_poll_view(request, room_id):
    me = request.user
    room = get_object_or_404(ChatRoom, pk=room_id)

    if not can_access_room(me, room):
        return JsonResponse({'status': 'error', 'error': 'Нет доступа.'}, status=403)

    try:
        after = int(request.GET.get('after', 0))
    except (TypeError, ValueError):
        after = 0

    new_messages = list(
        room.messages.filter(id__gt=after)
        .select_related('author')
        .order_by('created_at')
    )

    if new_messages:
        mark_room_read(room, me)

    return JsonResponse({
        'status': 'ok',
        'messages': [_room_message_json(m, me) for m in new_messages],
        'unread': room_unread_count(room, me),
    })


# ---------------------------------------------------------------------------
# CRUD тайтлов: автор тайтла и админы могут редактировать и удалять
# ---------------------------------------------------------------------------
def _can_edit_title(user, title):
    if not user or not user.is_authenticated:
        return False
    return user == title.author or user.is_site_admin


@login_required
def edit_title_view(request, slug):
    title = _get_visible_title(request, slug)

    if not _can_edit_title(request.user, title):
        return HttpResponseForbidden("Редактировать тайтл может только его автор.")

    if request.method == 'POST':
        form = TitleForm(request.POST, request.FILES, instance=title)
        if form.is_valid():
            form.save()

            for genre in form.create_new_genres():
                title.genres.add(genre)

            messages.success(request, f"Тайтл «{title.name}» обновлён.")
            return redirect('title_detail', slug=title.slug)
        else:
            messages.error(request, "Не удалось сохранить: проверьте поля формы.")
    else:
        form = TitleForm(instance=title)

    return render(request, 'manga/create_title.html', {
        'form': form,
        'editing': True,
        'title': title,
    })


@login_required
def delete_title_view(request, slug):
    title = get_object_or_404(Title, slug=slug)

    if not _can_edit_title(request.user, title):
        return HttpResponseForbidden("Удалить тайтл может только его автор.")

    if request.method == 'POST':
        name = title.name
        if title.cover:
            title.cover.delete(save=False)
        title.delete()  # главы и страницы удалятся каскадно (файлы — сигналами)
        messages.success(request, f"Тайтл «{name}» удалён.")
        return redirect('my_titles')

    ref = request.META.get('HTTP_REFERER')
    if ref and ref != request.build_absolute_uri():
        return redirect(ref)
    return redirect('title_detail', slug=title.slug)
