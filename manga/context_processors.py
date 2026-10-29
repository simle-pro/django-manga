from .models import Notification, FriendRequest, Message
from .chat_helpers import feedback_unread_count, admin_chat_unread_count

def notifications_processor(request):
    if request.user.is_authenticated:
        unread_notifications = Notification.objects.filter(user=request.user, is_read=False)
        return {
            'unread_notifications_count': unread_notifications.count(),
            'latest_notifications': Notification.objects.filter(user=request.user)[:5],
            'pending_friends_count': FriendRequest.objects.filter(to_user=request.user, status='pending').count(),
            'unread_messages_count': Message.objects.filter(recipient=request.user, is_read=False).count(),
            'support_unread': feedback_unread_count(request.user),
            'admin_chat_unread': admin_chat_unread_count(request.user),
        }
    return {
        'unread_notifications_count': 0,
        'latest_notifications': [],
        'pending_friends_count': 0,
        'unread_messages_count': 0,
        'support_unread': 0,
        'admin_chat_unread': 0,
    }
