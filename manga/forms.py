from datetime import date

from django import forms
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm
from django.contrib.auth import get_user_model
from .models import Title, Chapter, Genre, Comment

User = get_user_model()

# Общий стиль для полей ввода в формах
INPUT_STYLE = 'width: 100%; padding: 8px; margin-bottom: 10px;'


def _clean_birth_date(birth_date):
    if birth_date and birth_date > date.today():
        raise forms.ValidationError("Дата рождения не может быть в будущем.")
    return birth_date


# Виджет загрузки сразу нескольких файлов (input с атрибутом multiple)
class MultipleFileInput(forms.FileInput):
    def __init__(self, attrs=None):
        super().__init__(attrs)
        if attrs is not None:
            self.attrs.update(attrs)
        self.attrs['multiple'] = True


class RegisterForm(UserCreationForm):
    ROLE_CHOICES = [
        (User.Role.READER, 'Читатель'),
        (User.Role.AUTHOR, 'Автор / Переводчик'),
    ]

    username = forms.CharField(
        label="Имя пользователя",
        min_length=2,
        max_length=150,
        widget=forms.TextInput(attrs={'style': INPUT_STYLE})
    )

    birth_date = forms.DateField(
        label="Дата рождения",
        required=False,
        widget=forms.DateInput(attrs={'type': 'date', 'style': INPUT_STYLE})
    )

    role = forms.ChoiceField(
        choices=ROLE_CHOICES,
        initial=User.Role.READER,
        label="Кем вы хотите быть?",
        widget=forms.RadioSelect(attrs={'class': 'role-options'}),
    )

    class Meta:
        model = User
        fields = ['username', 'email', 'role', 'birth_date']

    def clean_birth_date(self):
        return _clean_birth_date(self.cleaned_data.get('birth_date'))

    def save(self, commit=True):
        user = super().save(commit=False)
        role = self.cleaned_data.get('role')
        # При регистрации можно выбрать только читателя или автора
        user.role = role if role in (User.Role.READER, User.Role.AUTHOR) else User.Role.READER
        user.birth_date = self.cleaned_data.get('birth_date')
        if commit:
            user.save()
        return user


class AccountForm(forms.ModelForm):
    """Настройки аккаунта: дата рождения, закрытый аккаунт, видимость закладок."""

    birth_date = forms.DateField(
        label="Дата рождения",
        required=False,
        widget=forms.DateInput(attrs={'type': 'date', 'style': INPUT_STYLE})
    )

    is_closed = forms.BooleanField(
        label="Закрытый аккаунт",
        required=False,
        help_text="Профиль, тайтлы и закладки смогут смотреть только друзья."
    )

    hide_nsfw = forms.BooleanField(
        label="Скрывать NSFW-тайтлы",
        required=False,
        help_text="Тайтлы с меткой 18+ не будут вам показываться."
    )

    bookmarks_visibility = forms.ChoiceField(
        choices=User.BookmarksVisibility.choices,
        label="Кто может смотреть мои закладки",
        widget=forms.RadioSelect(attrs={'class': 'visibility-options'}),
    )

    class Meta:
        model = User
        fields = ['birth_date', 'is_closed', 'hide_nsfw', 'bookmarks_visibility']

    def clean_birth_date(self):
        return _clean_birth_date(self.cleaned_data.get('birth_date'))


class LoginForm(AuthenticationForm):
    pass


class TitleForm(forms.ModelForm):
    genres = forms.ModelMultipleChoiceField(
        queryset=Genre.objects.all(),
        widget=forms.CheckboxSelectMultiple(attrs={'class': 'genre-checkboxes'}),
        label='Жанры',
        required=False
    )

    is_nsfw = forms.BooleanField(
        required=False,
        label='NSFW — контент 18+',
        help_text='Тайтл не будет показан пользователям младше 18 лет.',
        widget=forms.CheckboxInput(attrs={'class': 'nsfw-check'})
    )

    new_genres = forms.CharField(
        required=False,
        label='Новые жанры / теги (через запятую)',
        widget=forms.TextInput(attrs={
            'style': INPUT_STYLE,
            'placeholder': 'Например: Киберпанк, Магия, Исекай'
        }),
        help_text='Жанров, которых ещё нет в списке, — они создадутся автоматически и добавятся к тайтлу.'
    )

    def clean_name(self):
        name = (self.cleaned_data.get('name') or '').strip()
        if name:
            qs = Title.objects.filter(name__iexact=name)
            if self.instance and self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise forms.ValidationError(
                    "Такой тайтл уже есть на сайте — дубликаты создавать нельзя. "
                    "Откройте существующий тайтл и запросите у автора общий перевод."
                )
        return name

    def clean_original_name(self):
        original_name = (self.cleaned_data.get('original_name') or '').strip()
        if original_name:
            qs = Title.objects.filter(original_name__iexact=original_name)
            if self.instance and self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise forms.ValidationError(
                    "Тайтл с таким оригинальным названием уже есть на сайте."
                )
        return original_name

    class Meta:
        model = Title
        fields = ['name', 'original_name', 'cover', 'description', 'type', 'status', 'genres', 'is_nsfw']
        widgets = {
            'name': forms.TextInput(attrs={'style': INPUT_STYLE}),
            'original_name': forms.TextInput(attrs={'style': INPUT_STYLE}),
            'description': forms.Textarea(attrs={'style': 'width: 100%; padding: 8px; height: 100px; margin-bottom: 10px;'}),
            'type': forms.Select(attrs={'style': INPUT_STYLE}),
            'status': forms.Select(attrs={'style': INPUT_STYLE}),
        }

    # Создаёт жанры из поля new_genres и возвращает список готовых Genre
    def create_new_genres(self):
        from pytils.translit import slugify

        raw = self.cleaned_data.get('new_genres', '')
        if not raw:
            return []

        created = []
        for chunk in raw.split(','):
            name = chunk.strip()
            if not name:
                continue

            genre = Genre.objects.filter(name__iexact=name).first()
            if genre:
                created.append(genre)
                continue

            slug = slugify(name) or 'genre'
            base_slug = slug
            counter = 1
            while Genre.objects.filter(slug=slug).exists():
                slug = f'{base_slug}-{counter}'
                counter += 1

            genre = Genre.objects.create(name=name, slug=slug)
            created.append(genre)

        return created


class ChapterForm(forms.ModelForm):
    class Meta:
        model = Chapter
        fields = ['volume', 'number', 'name']
        widgets = {
            'volume': forms.NumberInput(attrs={'style': INPUT_STYLE}),
            'number': forms.NumberInput(attrs={'style': INPUT_STYLE}),
            'name': forms.TextInput(attrs={'style': INPUT_STYLE}),
        }


class PageForm(forms.Form):
    images = forms.FileField(
        widget=MultipleFileInput(attrs={'style': 'margin-bottom: 10px;'}),
        label='Картинки главы (выдели все страницы сразу)',
        required=False
    )
    zip_file = forms.FileField(
        widget=forms.FileInput(attrs={'accept': '.zip', 'style': 'margin-bottom: 10px;'}),
        label='ZIP-архив (внутри картинки, распакуется автоматически)',
        required=False
    )

    def clean(self):
        cleaned = super().clean()
        images = cleaned.get('images')
        zip_file = cleaned.get('zip_file')
        if not images and not zip_file:
            raise forms.ValidationError('Загрузите хотя бы изображения или ZIP-архив с картинками.')
        return cleaned


class CommentForm(forms.ModelForm):
    class Meta:
        model = Comment
        fields = ['text']
        widgets = {
            'text': forms.Textarea(attrs={
                'style': 'width: 100%; height: 90px; padding: 10px; border-radius: 5px; border: 1px solid #ccc; font-family: inherit;',
                'placeholder': 'Напишите ваш отзыв или мнение о тайтле...'
            })
        }
