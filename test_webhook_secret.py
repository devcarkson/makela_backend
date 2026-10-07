import os, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'sgb_backend.settings')
django.setup()
from django.conf import settings
import stripe

stripe.api_key = settings.STRIPE_SECRET_KEY
webhook_secret = settings.STRIPE_WEBHOOK_SECRET

test_payload = b'{"id": "evt_test", "type": "checkout.session.completed"}'
test_sig = 't=1234567890,v1=invalid'

try:
    event = stripe.Webhook.construct_event(test_payload, test_sig, webhook_secret)
    print('Webhook secret: VALID')
except stripe.error.SignatureVerificationError as e:
    print(f'Webhook secret: INVALID - {e}')
except Exception as e:
    print(f'Error: {e}')