from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import *



@admin.register(User)
class CustomUserAdmin(UserAdmin):
    model = User
    list_display = ('username', 'email', 'role', 'is_staff', 'is_superuser')
    list_filter = ('role', 'is_staff', 'is_superuser')
    
    fieldsets = UserAdmin.fieldsets + (
        ('Дополнительная информация (MangaLib)', {'fields': ('role', 'avatar')}),
    )
    add_fieldsets = UserAdmin.add_fieldsets + (
        ('Дополнительная информация (MangaLib)', {'fields': ('role', 'avatar')}),
    )



class PageInline(admin.TabularInline):
    model = Page
    extra = 1


@admin.register(Genre)
class GenreAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug')
    prepopulated_fields = {'slug': ('name',)}


@admin.register(Title)
class TitleAdmin(admin.ModelAdmin):
    list_display = ('name', 'type', 'status', 'author', 'created_at')
    list_filter = ('type', 'status', 'genres')
    search_fields = ('name', 'original_name')
    prepopulated_fields = {'slug': ('name',)}


@admin.register(Chapter)
class ChapterAdmin(admin.ModelAdmin):
    list_display = ('title', 'volume', 'number', 'created_at')
    list_filter = ('title',)
    inlines = [PageInline]  