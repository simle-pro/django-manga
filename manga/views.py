from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden, Http404
from django.contrib.auth import login, logout
from django.db.models import Q
from .models import *
from .forms import *


def home_view(request):
    query = request.GET.get('q', '').strip()
    if query:
        titles = Title.objects.filter(
            Q(name__icontains=query) | Q(original_name__icontains=query)
        ).order_by('-created_at')
    else:
        titles = Title.objects.all().order_by('-created_at')

    return render(request, 'manga/home.html', {
        'titles': titles,
        'query': query
    })


def catalog_view(request):
    query = request.GET.get('q', '').strip()
    genre_filter = request.GET.get('genre', '')
    status_filter = request.GET.get('status', '')

    titles = Title.objects.all().order_by('-created_at')

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


from django.shortcuts import render, get_object_or_404
from .models import Title, Bookmark, Rating, ReadingHistory  # Добавили ReadingHistory
from .forms import CommentForm

def title_detail_view(request, slug):
    title = get_object_or_404(Title, slug=slug)
    chapters = title.chapters.all().order_by('volume', 'number')
    
    comments = title.comments.filter(parent__isnull=True)\
                             .select_related('user')\
                             .prefetch_related('replies__user')\
                             .order_by('-created_at')

    user_bookmark = None
    user_rating = None
    read_chapter_ids = []
    last_read_chapter = None

    if request.user.is_authenticated:
        user_bookmark = Bookmark.objects.filter(user=request.user, title=title).first()
        user_rating = Rating.objects.filter(user=request.user, title=title).first()

        # 1. Получаем список ID всех прочитанных глав этого тайтла для текущего пользователя
        read_chapter_ids = ReadingHistory.objects.filter(
            user=request.user, 
            chapter__title=title
        ).values_list('chapter_id', flat=True)

        # 2. Находим последнюю прочитанную главу (для кнопки «Продолжить чтение»)
        last_history = ReadingHistory.objects.filter(
            user=request.user, 
            chapter__title=title
        ).select_related('chapter').first()

        if last_history:
            last_read_chapter = last_history.chapter

    comment_form = CommentForm()

    return render(request, 'manga/title_detail.html', {
        'title': title,
        'chapters': chapters,
        'comments': comments,
        'user_bookmark': user_bookmark,
        'user_rating': user_rating,
        'comment_form': comment_form,
        'read_chapter_ids': read_chapter_ids,      # Передаем в шаблон
        'last_read_chapter': last_read_chapter,    # Передаем в шаблон
    })


def reader_view(request, slug, volume, number):
    title = get_object_or_404(Title, slug=slug)
    chapter = Chapter.objects.filter(title=title, volume=volume, number=number).first()
    
    if not chapter:
        raise Http404("Глава не найдена")

    pages = chapter.pages.all().order_by('page_number')

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
            return redirect('title_detail', slug=title.slug)
    else:
        form = TitleForm()

    return render(request, 'manga/create_title.html', {'form': form})


from django.shortcuts import render, get_object_or_404, redirect
from django.http import HttpResponseForbidden
from django.contrib.auth.decorators import login_required
from .models import Title, Chapter, Page, Bookmark, Notification  # Добавили Bookmark и Notification
from .forms import ChapterForm, PageForm

@login_required
def add_chapter_view(request, slug):
    title = get_object_or_404(Title, slug=slug)

    if request.user != title.author and request.user.role != 'admin' and not request.user.is_superuser:
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
            images.sort(key=lambda x: x.name)

            pages_to_create = [
                Page(
                    chapter=chapter,
                    image=image,
                    page_number=index
                )
                for index, image in enumerate(images, start=start_number)
            ]
            Page.objects.bulk_create(pages_to_create)

            # --- ОТПРАВКА УВЕДОМЛЕНИЙ ---
            # Отправляем только при первом создании главы (created=True)
            if created:
                bookmarks = Bookmark.objects.filter(
                    title=title,
                    status__in=['reading', 'favorite']
                ).select_related('user')

                notifications_to_create = [
                    Notification(
                        user=b.user,
                        title=f"Новая глава в «{title.name}»!",
                        message=f"Вышла Том {chapter.volume} Глава {chapter.number}",
                        link=f"/manga/{title.slug}/read/{chapter.volume}/{chapter.number}/"
                    )
                    for b in bookmarks if b.user != request.user  # Не отправляем автору, загрузившему главу
                ]

                if notifications_to_create:
                    Notification.objects.bulk_create(notifications_to_create)
            # ---------------------------

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
    title = get_object_or_404(Title, slug=slug)
    if request.method == 'POST':
        text = request.POST.get('text')
        parent_id = request.POST.get('parent_id')

        if text:
            parent_comment = None
            if parent_id:
                parent_comment = Comment.objects.filter(id=parent_id).first()

            Comment.objects.create(
                title=title,
                user=request.user,
                text=text,
                parent=parent_comment
            )
    return redirect('title_detail', slug=title.slug)


@login_required
def set_bookmark_view(request, slug):
    title = get_object_or_404(Title, slug=slug)
    status = request.POST.get('status')

    if status in dict(Bookmark.STATUS_CHOICES):
        Bookmark.objects.update_or_create(
            user=request.user,
            title=title,
            defaults={'status': status}
        )
    elif status == 'remove':
        Bookmark.objects.filter(user=request.user, title=title).delete()

    return redirect('title_detail', slug=title.slug)


@login_required
def set_rating_view(request, slug):
    title = get_object_or_404(Title, slug=slug)
    try:
        score = int(request.POST.get('score', 0))
        if 1 <= score <= 10:
            Rating.objects.update_or_create(
                user=request.user,
                title=title,
                defaults={'score': score}
            )
    except ValueError:
        pass

    return redirect('title_detail', slug=title.slug)


@login_required
def my_titles_view(request):
    titles = Title.objects.filter(author=request.user).order_by('-created_at')
    return render(request, 'manga/my_titles.html', {'titles': titles})


@login_required
def my_bookmarks_view(request):
    status_filter = request.GET.get('status', 'reading')
    bookmarks = Bookmark.objects.filter(user=request.user, status=status_filter).select_related('title')
    
    return render(request, 'manga/my_bookmarks.html', {
        'bookmarks': bookmarks,
        'current_status': status_filter,
        'status_choices': Bookmark.STATUS_CHOICES,
    })




def reader(request, slug, volume, number):
    title = get_object_or_404(Title, slug=slug)
    chapter = get_object_or_404(Chapter, title=title, volume=volume, number=number)
    
    # Сохраняем в историю, если пользователь авторизован
    if request.user.is_authenticated:
        ReadingHistory.objects.update_or_create(
            user=request.user,
            chapter=chapter
        )
        
    next_chapter = Chapter.objects.filter(title=title, id__gt=chapter.id).order_by('id').first()
    prev_chapter = Chapter.objects.filter(title=title, id__lt=chapter.id).order_by('-id').first()

    context = {
        'title': title,
        'chapter': chapter,
        'next_chapter': next_chapter,
        'prev_chapter': prev_chapter,
    }
    return render(request, 'manga/reader.html', context)


#сделано через ИИ
from django.http import JsonResponse

@login_required
def mark_notifications_read(request):
    Notification.objects.filter(user=request.user, is_read=False).update(is_read=True)
    return JsonResponse({'status': 'ok'})





from django.shortcuts import get_object_or_404, redirect
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from .models import Chapter

@login_required
def delete_chapter_view(request, chapter_id):
    chapter = get_object_or_404(Chapter, pk=chapter_id)
    title = chapter.title

    # Проверка прав: Автор тайтла ИЛИ Администратор/Модератор
    is_author = (request.user == title.author)
    is_admin_or_staff = (getattr(request.user, 'role', '') == 'admin' or request.user.is_staff or request.user.is_superuser)

    if not (is_author or is_admin_or_staff):
        messages.error(request, "У вас нет прав на удаление этой главы.")
        return redirect('title_detail', slug=title.slug)

    if request.method == 'POST':
        # При удалении главы удалятся все связанные страницы (Page), 
        # и сработает сигнал post_delete, который физически сотрет файлы из media/
        chapter.delete()
        messages.success(request, f"Глава Том {chapter.volume} №{chapter.number} и её файлы успешно удалены!")
        return redirect('title_detail', slug=title.slug)

    return redirect('title_detail', slug=title.slug)




# views.py
from django.shortcuts import render, get_object_or_404
from django.contrib.auth import get_user_model

User = get_user_model()

from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from .models import Bookmark, ReadingHistory

@login_required
def profile_view(request):
    user = request.user
    
    # Обработка обновления аватарки
    if request.method == 'POST':
        if 'avatar' in request.FILES:
            user.avatar = request.FILES['avatar']
            user.save()
            return redirect('profile')

    # Получаем закладки пользователя с группировкой по статусам
    bookmarks = Bookmark.objects.filter(user=user).select_related('title')
    
    # Последние прочитанные главы
    history = ReadingHistory.objects.filter(user=user).select_related('chapter__title')[:10]

    context = {
        'user_profile': user,
        'bookmarks': bookmarks,
        'history': history,
    }
    return render(request, 'manga/profile.html', context)