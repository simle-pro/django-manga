from django.urls import path
from . import views

urlpatterns = [
    path('', views.home_view, name='home'),
    path('catalog/', views.catalog_view, name='catalog'),
    path('title/add/', views.create_title_view, name='create_title'),
    path('title/<slug:slug>/', views.title_detail_view, name='title_detail'),
    path('title/<slug:slug>/volume/<int:volume>/number/<str:number>/', views.reader_view, name='reader'),
    path('title/<slug:slug>/add-chapter/', views.add_chapter_view, name='add_chapter'),
    
    # Интерактив
    path('title/<slug:slug>/comment/', views.add_comment_view, name='add_comment'),
    path('title/<slug:slug>/bookmark/', views.set_bookmark_view, name='set_bookmark'),
    path('title/<slug:slug>/rate/', views.set_rating_view, name='set_rating'),
    
    # Авторизация
    path('register/', views.register_view, name='register'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    
    # Кабинеты
    path('my-titles/', views.my_titles_view, name='my_titles'),
    path('bookmarks/', views.my_bookmarks_view, name='my_bookmarks'),
    path('notifications/read-all/', views.mark_notifications_read, name='mark_notifications_read'),
    path('chapter/<int:chapter_id>/delete/', views.delete_chapter_view, name='delete_chapter'),
    path('profile/', views.profile_view, name='profile'),
]