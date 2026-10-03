from django import forms
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm
from django.contrib.auth import get_user_model
from .models import Title, Chapter, Genre, Comment

User = get_user_model()


class MultipleFileInput(forms.FileInput):
    def __init__(self, attrs=None):
        super().__init__(attrs)
        if attrs is not None:
            self.attrs.update(attrs)
        self.attrs['multiple'] = True


class RegisterForm(UserCreationForm):
    username = forms.CharField(
        label="Имя пользователя",
        min_length=2,
        max_length=150,
        widget=forms.TextInput(attrs={'style': 'width: 100%; padding: 8px; margin-bottom: 10px;'})
    )

    class Meta:
        model = User
        fields = ['username', 'email']


class LoginForm(AuthenticationForm):
    pass


class TitleForm(forms.ModelForm):
    genres = forms.ModelMultipleChoiceField(
        queryset=Genre.objects.all(),
        widget=forms.CheckboxSelectMultiple(attrs={'class': 'genre-checkboxes'}),
        label='Жанры',
        required=False
    )

    class Meta:
        model = Title
        fields = ['name', 'original_name', 'cover', 'description', 'type', 'status', 'genres']
        widgets = {
            'name': forms.TextInput(attrs={'style': 'width: 100%; padding: 8px; margin-bottom: 10px;'}),
            'original_name': forms.TextInput(attrs={'style': 'width: 100%; padding: 8px; margin-bottom: 10px;'}),
            'description': forms.Textarea(attrs={'style': 'width: 100%; padding: 8px; height: 100px; margin-bottom: 10px;'}),
            'type': forms.Select(attrs={'style': 'width: 100%; padding: 8px; margin-bottom: 10px;'}),
            'status': forms.Select(attrs={'style': 'width: 100%; padding: 8px; margin-bottom: 10px;'}),
        }


class ChapterForm(forms.ModelForm):
    class Meta:
        model = Chapter
        fields = ['volume', 'number', 'name']
        widgets = {
            'volume': forms.NumberInput(attrs={'style': 'width: 100%; padding: 8px; margin-bottom: 10px;'}),
            'number': forms.NumberInput(attrs={'style': 'width: 100%; padding: 8px; margin-bottom: 10px;'}),
            'name': forms.TextInput(attrs={'style': 'width: 100%; padding: 8px; margin-bottom: 10px;'}),
        }


class PageForm(forms.Form):
    images = forms.FileField(
        widget=MultipleFileInput(attrs={'style': 'margin-bottom: 10px;'}),
        label='Картинки главы (выдели все страницы сразу)'
    )


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