import stripe
from django.conf import settings
import logging

logger = logging.getLogger(__name__)


class StripeService:
    """Service class for handling Stripe payment operations."""

    @classmethod
    def _get_stripe_client(cls):
        stripe_key = getattr(settings, 'STRIPE_SECRET_KEY', None)
        if not stripe_key:
            raise Exception("STRIPE_SECRET_KEY is not configured")
        stripe.api_key = stripe_key
        return stripe

    @classmethod
    def initialize_payment(cls, order):
        """Initialize a Stripe Checkout Session for an order.

        Returns a dict with keys:
            - checkout_url: URL to redirect the customer to
            - session_id: Stripe Checkout Session ID
            - payment_id: Our internal Payment model UUID string
        """
        from .models import Payment
        try:
            stripe_client = cls._get_stripe_client()

            existing_payment = Payment.objects.filter(
                order=order,
                status='pending',
                gateway='stripe'
            ).first()

            if existing_payment and existing_payment.gateway_response and existing_payment.gateway_response.get('checkout_url'):
                logger.info(f"Reusing existing Stripe payment {existing_payment.payment_id} for order {order.order_number}")
                return {
                    'status': 'success',
                    'data': {
                        'checkout_url': existing_payment.gateway_response['checkout_url'],
                        'session_id': existing_payment.gateway_response.get('session_id', ''),
                        'payment_id': str(existing_payment.payment_id),
                    }
                }

            if existing_payment and existing_payment.status == 'pending':
                logger.info(f"Existing Stripe payment amount {existing_payment.amount} vs order total {order.total}")
                if existing_payment.amount != order.total:
                    existing_payment.status = 'cancelled'
                    existing_payment.save()

            payment = Payment.objects.create(
                order=order,
                gateway='stripe',
                amount=order.total,
                currency='GBP',
                status='pending'
            )

            success_url = f"{settings.FRONTEND_URL}/payment/success?session_id={{CHECKOUT_SESSION_ID}}"
            cancel_url = f"{settings.FRONTEND_URL}/checkout"

            checkout_session = stripe_client.checkout.Session.create(
                payment_method_types=['card'],
                mode='payment',
                customer_email=order.user.email,
                line_items=[
                    {
                        'price_data': {
                            'currency': 'gbp',
                            'product_data': {
                                'name': f'Order #{order.order_number}',
                            },
                            'unit_amount': int(order.total * 100),
                        },
                        'quantity': 1,
                    }
                ],
                metadata={
                    'order_id': str(order.id),
                    'order_number': order.order_number,
                    'payment_id': str(payment.payment_id),
                    'user_id': str(order.user.id),
                },
                success_url=success_url,
                cancel_url=cancel_url,
            )

            gateway_response = {
                'checkout_url': checkout_session.url,
                'session_id': checkout_session.id,
                'payment_id': str(payment.payment_id),
            }

            payment.gateway_reference = checkout_session.id
            payment.gateway_response = gateway_response
            payment.save()

            # Clear user's cart immediately (backup stored in payment for potential restore on failure)
            try:
                cart = order.user.cart
                backup = cart.clear_for_checkout()
                # Store backup in payment gateway_response for restoration on failure
                payment.gateway_response['cart_backup'] = backup
                payment.save(update_fields=['gateway_response'])
                logger.info(f"Cleared cart for user {order.user.email} during payment initialization for order {order.order_number}")
            except Exception as e:
                logger.error(f"Error clearing cart for user {order.user.email}: {str(e)}")

            logger.info(f"Stripe checkout session created for order {order.order_number}: {checkout_session.id}")

            return {
                'status': 'success',
                'data': gateway_response,
            }

        except Exception as e:
            logger.error(f"Stripe payment initialization error for order {order.order_number}: {str(e)}")
            if 'payment' in locals():
                payment.mark_as_failed(error_message=str(e))
            raise

    @classmethod
    def verify_payment(cls, session_id):
        """Verify a Stripe Checkout Session.

        Returns the session object from Stripe or None if not found.
        """
        try:
            stripe_client = cls._get_stripe_client()

            checkout_session = stripe_client.checkout.Session.retrieve(
                session_id,
                expand=['payment_intent', 'line_items']
            )

            return checkout_session

        except stripe.error.StripeError as e:
            logger.error(f"Stripe verification error for session {session_id}: {str(e)}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error verifying Stripe session {session_id}: {str(e)}")
            return None

    @classmethod
    def process_webhook(cls, payload, sig_header):
        """Process Stripe webhook events.

        Returns True if processed successfully, False otherwise.
        """
        from .models import Payment
        try:
            stripe_client = cls._get_stripe_client()
            webhook_secret = getattr(settings, 'STRIPE_WEBHOOK_SECRET', None)

            if not webhook_secret:
                logger.error("STRIPE_WEBHOOK_SECRET not configured")
                return False

            try:
                event = stripe_client.Webhook.construct_event(
                    payload, sig_header, webhook_secret
                )
            except ValueError:
                logger.error("Invalid payload in Stripe webhook")
                return False
            except stripe.error.SignatureVerificationError:
                logger.error("Invalid signature in Stripe webhook")
                return False

            logger.info(f"Received Stripe webhook event: {event['type']}")

            # Handle checkout.session.completed - primary success event
            if event['type'] == 'checkout.session.completed':
                return cls._handle_checkout_session_completed(event)

            # Handle async payment success (for payment methods like SEPA, Sofort, etc.)
            elif event['type'] == 'checkout.session.async_payment_succeeded':
                return cls._handle_checkout_session_completed(event)

            # Handle async payment failure
            elif event['type'] == 'checkout.session.async_payment_failed':
                return cls._handle_async_payment_failed(event)

            # Handle session expired
            elif event['type'] == 'checkout.session.expired':
                return cls._handle_session_expired(event)

            # Handle payment_intent.payment_failed
            elif event['type'] == 'payment_intent.payment_failed':
                return cls._handle_payment_intent_failed(event)

            # Unhandled event type - still return True so Stripe doesn't retry
            else:
                logger.info(f"Unhandled Stripe event type: {event['type']}")
                return True

        except Exception as e:
            logger.error(f"Error processing Stripe webhook: {str(e)}")
            return False

    @classmethod
    def _to_dict(cls, obj):
        """Convert Stripe object to dict."""
        if hasattr(obj, 'to_dict'):
            return obj.to_dict()
        return obj

    @classmethod
    def _handle_checkout_session_completed(cls, event):
        """Handle checkout.session.completed and async_payment_succeeded."""
        from .models import Payment
        session = cls._to_dict(event['data']['object'])
        session_id = session.get('id')
        payment_intent = session.get('payment_intent')
        payment_status = session.get('payment_status')

        # Only process if payment is actually paid
        if payment_status != 'paid':
            logger.info(f"Checkout session {session_id} payment_status: {payment_status}, not processing")
            return True

        payment_id = session.get('metadata', {}).get('payment_id')
        if not payment_id:
            logger.error(f"No payment_id in webhook metadata for session {session_id}")
            return False

        try:
            payment = Payment.objects.get(payment_id=payment_id)
        except Payment.DoesNotExist:
            logger.error(f"Payment not found for payment_id: {payment_id}")
            return False

        # Idempotency: skip if already processed
        if payment.is_successful:
            logger.info(f"Payment {payment_id} already successful, skipping")
            return True

        # Extract payment intent ID
        pi_id = None
        if payment_intent:
            pi_id = payment_intent if isinstance(payment_intent, str) else payment_intent.get('id')

        payment.mark_as_successful(
            gateway_transaction_id=pi_id,
            gateway_response={
                'session_id': session_id,
                'payment_intent': pi_id,
                'event_type': event['type'],
            }
        )
        logger.info(f"Stripe payment {payment.payment_id} marked as successful for order {payment.order.order_number}")
        return True

    @classmethod
    def _handle_async_payment_failed(cls, event):
        """Handle checkout.session.async_payment_failed."""
        from .models import Payment
        session = cls._to_dict(event['data']['object'])
        session_id = session.get('id')
        payment_id = session.get('metadata', {}).get('payment_id')

        if not payment_id:
            logger.error(f"No payment_id in async_payment_failed metadata for session {session_id}")
            return False

        try:
            payment = Payment.objects.get(payment_id=payment_id)
        except Payment.DoesNotExist:
            logger.error(f"Payment not found for payment_id: {payment_id}")
            return False

        if payment.is_successful:
            logger.info(f"Payment {payment_id} already successful, skipping failure")
            return True

        payment_intent = session.get('payment_intent')
        if isinstance(payment_intent, dict):
            error_msg = payment_intent.get('last_payment_error', {}).get('message', 'Async payment failed')
        else:
            error_msg = 'Async payment failed'
        payment.mark_as_failed(
            gateway_response={'session_id': session_id, 'event_type': event['type']},
            error_message=error_msg
        )
        logger.info(f"Stripe payment {payment.payment_id} marked as failed for order {payment.order.order_number}")
        return True

    @classmethod
    def _handle_session_expired(cls, event):
        """Handle checkout.session.expired."""
        from .models import Payment
        session = cls._to_dict(event['data']['object'])
        session_id = session.get('id')
        payment_id = session.get('metadata', {}).get('payment_id')

        if not payment_id:
            logger.error(f"No payment_id in expired session metadata for session {session_id}")
            return False

        try:
            payment = Payment.objects.get(payment_id=payment_id)
        except Payment.DoesNotExist:
            logger.error(f"Payment not found for payment_id: {payment_id}")
            return False

        if payment.is_successful:
            return True

        payment.mark_as_failed(
            gateway_response={'session_id': session_id, 'event_type': event['type']},
            error_message='Checkout session expired'
        )
        logger.info(f"Stripe payment {payment.payment_id} marked as failed (session expired)")
        return True

    @classmethod
    def _handle_payment_intent_failed(cls, event):
        """Handle payment_intent.payment_failed."""
        from .models import Payment
        pi = cls._to_dict(event['data']['object'])
        pi_id = pi.get('id')
        payment_id = pi.get('metadata', {}).get('payment_id')

        if not payment_id:
            session_id = pi.get('metadata', {}).get('session_id')
            if session_id:
                try:
                    payment = Payment.objects.get(gateway_reference=session_id)
                    payment_id = str(payment.payment_id)
                except Payment.DoesNotExist:
                    pass

        if not payment_id:
            logger.error(f"No payment_id in payment_intent metadata for PI {pi_id}")
            return False

        try:
            payment = Payment.objects.get(payment_id=payment_id)
        except Payment.DoesNotExist:
            logger.error(f"Payment not found for payment_id: {payment_id}")
            return False

        if payment.is_successful:
            logger.info(f"Payment {payment_id} already successful, skipping failure")
            return True

        error_msg = pi.get('last_payment_error', {}).get('message', 'Payment failed')
        payment.mark_as_failed(
            gateway_response={'payment_intent_id': pi_id, 'event_type': event['type']},
            error_message=error_msg
        )
        logger.info(f"Stripe payment {payment.payment_id} marked as failed (PI failed)")
        return True