from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

def broadcast_realtime_update(user_id, data):
    """
    Broadcasts a realtime update to any websocket listeners for this user_id.
    Example: data = {'type': 'cart_update', ...}
    """
    channel_layer = get_channel_layer()
    if channel_layer is None:
        return
    async_to_sync(channel_layer.group_send)(
        f'user_{user_id}',
        {
            'type': 'realtime_update',  # Calls method on consumer
            'data': data,
        }
    )

def broadcast_realtime_update_safe(user_id, data):
    """
    Same as broadcast_realtime_update but swallows exceptions so it can be
    called from model save() / signals without breaking the request.
    """
    try:
        broadcast_realtime_update(user_id, data)
    except Exception:
        pass
