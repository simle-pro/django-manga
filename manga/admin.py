from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import (
    User, Genre, Title, Chapter, Page,
    Bookmark, Rating, Comment, ReadingHistory, Notification, FriendRequest,
    UserBlock, BookmarkAccess, Message,
    ChatRoom, ChatRoomMessage, ChatRoomRead
)


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    model = User
    list_display = ('username', 'email', 'role', 'public_id', 'display_level', 'display_xp', 'is_staff', 'is_superuser')
    list_filter = ('role', 'is_closed', 'bookmarks_visibility', 'is_staff', 'is_superuser')
    search_fields = ('username', 'email', 'public_id')
    readonly_fields = ('public_id',)

    fieldsets = UserAdmin.fieldsets + (
        ('Дополнительная информация (MangaLib)', {'fields': ('role', 'avatar', 'public_id', 'birth_date', 'is_closed', 'bookmarks_visibility', 'hide_nsfw')}),
    )
    add_fieldsets = UserAdmin.add_fieldsets + (
        ('Дополнительная информация (MangaLib)', {'fields': ('role', 'avatar', 'birth_date', 'is_closed', 'bookmarks_visibility', 'hide_nsfw')}),
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
    list_display = ('name', 'type', 'status', 'author', 'is_nsfw', 'get_rating', 'created_at')
    list_filter = ('type', 'status', 'is_nsfw', 'genres')
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
    list_display = ('user', 'title', 'status', 'short_note', 'created_at')
    list_filter = ('status', 'created_at')
    search_fields = ('user__username', 'title__name', 'note')

    @admin.display(description='Заметка')
    def short_note(self, obj):
        return (obj.note[:50] + '…') if obj.note and len(obj.note) > 50 else obj.note


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


@admin.register(FriendRequest)
class FriendRequestAdmin(admin.ModelAdmin):
    list_display = ('from_user', 'to_user', 'status', 'created_at')
    list_filter = ('status', 'created_at')
    search_fields = ('from_user__username', 'to_user__username')


@admin.register(UserBlock)
class UserBlockAdmin(admin.ModelAdmin):
    list_display = ('blocker', 'blocked', 'created_at')
    search_fields = ('blocker__username', 'blocked__username')


@admin.register(BookmarkAccess)
class BookmarkAccessAdmin(admin.ModelAdmin):
    list_display = ('owner', 'viewer', 'created_at')
    search_fields = ('owner__username', 'viewer__username')


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ('sender', 'recipient', 'short_text', 'is_read', 'created_at')
    list_filter = ('is_read', 'created_at')
    search_fields = ('sender__username', 'recipient__username', 'text')

    @admin.display(description='Текст')
    def short_text(self, obj):
        return (obj.text[:50] + '…') if len(obj.text) > 50 else obj.text


class ChatRoomMessageInline(admin.TabularInline):
    model = ChatRoomMessage
    extra = 0
    fields = ('author', 'text', 'created_at')
    readonly_fields = ('created_at',)


@admin.register(ChatRoom)
class ChatRoomAdmin(admin.ModelAdmin):
    list_display = ('room_type', 'owner', 'created_at')
    list_filter = ('room_type',)
    search_fields = ('owner__username',)
    inlines = [ChatRoomMessageInline]


@admin.register(ChatRoomMessage)
class ChatRoomMessageAdmin(admin.ModelAdmin):
    list_display = ('room', 'author', 'short_text', 'created_at')
    list_filter = ('room__room_type', 'created_at')
    search_fields = ('author__username', 'text')

    @admin.display(description='Текст')
    def short_text(self, obj):
        return (obj.text[:50] + '…') if len(obj.text) > 50 else obj.text


@admin.register(ChatRoomRead)
class ChatRoomReadAdmin(admin.ModelAdmin):
    list_display = ('room', 'user', 'last_read_id')
    search_fields = ('user__username',)