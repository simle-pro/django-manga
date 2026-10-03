from .models import Notification

def notifications_processor(request):
    if request.user.is_authenticated:
        unread_notifications = Notification.objects.filter(user=request.user, is_read=False)
        return {
            'unread_notifications_count': unread_notifications.count(),
            'latest_notifications': Notification.objects.filter(user=request.user)[:5]
        }
    return {
        'unread_notifications_count': 0,
        'latest_notifications': []
    }