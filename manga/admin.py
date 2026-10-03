from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import (
    User, Genre, Title, Chapter, Page,
    Bookmark, Rating, Comment, ReadingHistory, Notification
)


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    model = User
    list_display = ('username', 'email', 'role', 'display_level', 'display_xp', 'is_staff', 'is_superuser')
    list_filter = ('role', 'is_staff', 'is_superuser')
    search_fields = ('username', 'email')

    fieldsets = UserAdmin.fieldsets + (
        ('Дополнительная информация (MangaLib)', {'fields': ('role', 'avatar')}),
    )
    add_fieldsets = UserAdmin.add_fieldsets + (
        ('Дополнительная информация (MangaLib)', {'fields': ('role', 'avatar')}),
    )

    @admin.display(description='XP')
    def display_xp(self, obj):
        return obj.xp

    @admin.display(description='Уровень')
    def display_level(self, obj):
        return f"{obj.level} ({obj.rank_name})"


class PageInline(admin.TabularInline):
    model = Page
    extra = 1


@admin.register(Genre)
class GenreAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug')
    search_fields = ('name',)
    prepopulated_fields = {'slug': ('name',)}


@admin.register(Title)
class TitleAdmin(admin.ModelAdmin):
    list_display = ('name', 'type', 'status', 'author', 'get_rating', 'created_at')
    list_filter = ('type', 'status', 'genres')
    search_fields = ('name', 'original_name')
    readonly_fields = ('slug',)  # slug генерируется автоматически в save()
    filter_horizontal = ('genres',)

    @admin.display(description='Средний рейтинг')
    def get_rating(self, obj):
        return obj.average_rating()


@admin.register(Chapter)
class ChapterAdmin(admin.ModelAdmin):
    list_display = ('title', 'volume', 'number', 'name', 'created_at')
    list_filter = ('title', 'volume')
    search_fields = ('title__name', 'name', 'number')
    inlines = [PageInline]


@admin.register(Bookmark)
class BookmarkAdmin(admin.ModelAdmin):
    list_display = ('user', 'title', 'status', 'created_at')
    list_filter = ('status', 'created_at')
    search_fields = ('user__username', 'title__name')


@admin.register(Rating)
class RatingAdmin(admin.ModelAdmin):
    list_display = ('user', 'title', 'score')
    list_filter = ('score',)
    search_fields = ('user__username', 'title__name')


@admin.register(Comment)
class CommentAdmin(admin.ModelAdmin):
    list_display = ('user', 'title', 'created_at', 'parent')
    list_filter = ('created_at',)
    search_fields = ('user__username', 'title__name', 'text')


@admin.register(ReadingHistory)
class ReadingHistoryAdmin(admin.ModelAdmin):
    list_display = ('user', 'chapter', 'updated_at')
    list_filter = ('updated_at',)
    search_fields = ('user__username', 'chapter__title__name')


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ('user', 'title', 'is_read', 'created_at')
    list_filter = ('is_read', 'created_at')
    search_fields = ('user__username', 'title', 'message')