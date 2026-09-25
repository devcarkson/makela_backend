import requests
import hashlib
import hmac
import stripe
from django.conf import settings
from django.core.cache import cache
import logging
from decimal import Decimal
from .models import Payment

logger = logging.getLogger(__name__)

class FlutterwaveService:
    BASE_URL = "https://api.flutterwave.com/v3"
    TIMEOUT = 30
    MAX_RETRIES = 3

    @classmethod
    def initialize_payment(cls, order):
        """Initialize a Flutterwave payment for an order"""
        try:
            # Check if there's already a pending payment for this order
            existing_payment = Payment.objects.filter(
                order=order,
                status='pending',
                gateway='flutterwave'
            ).first()
            
            if existing_payment:
                logger.info(f"Found existing pending payment {existing_payment.payment_id} for order {order.order_number}")
                logger.info(f"Existing payment amount: {existing_payment.amount}, Current order total: {order.total}")
                
                # Check if the existing payment amount matches the current order total
                if existing_payment.amount == order.total:
                    # Try to get the payment link from the existing payment
                    if existing_payment.gateway_response and existing_payment.gateway_response.get('data', {}).get('link'):
                        logger.info(f"Reusing existing payment with matching amount")
                        return {
                            'status': 'success',
                            'data': {
                                'link': existing_payment.gateway_response['data']['link'],
                                'payment_id': str(existing_payment.payment_id),
                                'tx_ref': str(existing_payment.payment_id)
                            }
                        }
                else:
                    logger.info(f"Existing payment amount ({existing_payment.amount}) doesn't match current order total ({order.total}). Creating new payment.")
                    # Mark the old payment as cancelled and create a new one
                    existing_payment.status = 'cancelled'
                    existing_payment.save()
            
            # Create a new payment record
            payment = Payment.objects.create(
                order=order,
                gateway='flutterwave',
                amount=order.total,
                currency='NGN',
                status='pending'
            )
            
            headers = {
                "Authorization": f"Bearer {settings.FLW_SECRET_KEY}",
                "Content-Type": "application/json"
            }

            # Prepare customer data
            customer_name = f"{order.user.first_name} {order.user.last_name}".strip()
            if not customer_name:
                customer_name = order.user.email.split('@')[0]

            # Get user phone number safely
            phone_number = ""
            if hasattr(order.user, 'phone') and order.user.phone:
                phone_number = str(order.user.phone)
            elif hasattr(order.user, 'profile') and hasattr(order.user.profile, 'phone') and order.user.profile.phone:
                phone_number = str(order.user.profile.phone)

            # Ensure amount is properly formatted as string without decimals for Flutterwave
            amount_str = f"{float(order.total):.2f}"
            
            payload = {
                "tx_ref": str(payment.payment_id),  # Use payment ID as transaction reference
                "amount": amount_str,
                "currency": "NGN",
                "redirect_url": f"{settings.FRONTEND_URL}/payment/callback",
                "customer": {
                    "email": order.user.email,
                    "name": customer_name,
                    "phone_number": phone_number
                },
                "customizations": {
                    "title": "SGB Store Payment",
                    "description": f"Payment for Order #{order.order_number}",
                    "logo": f"{settings.FRONTEND_URL}/logo.png"
                },
                "meta": {
                    "order_id": order.id,
                    "order_number": order.order_number,
                    "payment_id": str(payment.payment_id)
                }
            }

            logger.info(f"=== FLUTTERWAVE PAYMENT DEBUG ===")
            logger.info(f"Order Number: {order.order_number}")
            logger.info(f"Order ID: {order.id}")
            logger.info(f"Order Details:")
            logger.info(f"  - Subtotal: {order.subtotal}")
            logger.info(f"  - Shipping Fee: {order.shipping_fee}")
            logger.info(f"  - Tax: {order.tax}")
            logger.info(f"  - Total: {order.total}")
            logger.info(f"  - Shipping City: {order.shipping_city}")
            logger.info(f"  - Shipping State: {order.shipping_state}")
            logger.info(f"Payment Record:")
            logger.info(f"  - Payment ID: {payment.payment_id}")
            logger.info(f"  - Payment Amount: {payment.amount}")
            logger.info(f"Flutterwave Payload:")
            logger.info(f"  - Amount String: {amount_str}")
            logger.info(f"  - TX Ref: {payload['tx_ref']}")
            logger.info(f"  - Currency: {payload['currency']}")
            logger.info(f"=== END DEBUG ===")
            
            response = requests.post(
                f"{cls.BASE_URL}/payments",
                headers=headers,
                json=payload,
                timeout=cls.TIMEOUT
            )

            data = response.json()
            
            # Log the response for debugging (without sensitive data)
            safe_data = {k: v for k, v in data.items() if k not in ['data']}
            if 'data' in data and isinstance(data['data'], dict):
                safe_data['data'] = {k: v for k, v in data['data'].items() if k != 'link'}
                safe_data['data']['link_available'] = bool(data['data'].get('link'))
            
            logger.info(f"Flutterwave payment response for order {order.order_number}: {safe_data}")
            
            # Check for successful initialization
            if data.get('status') == 'success' and data.get('data', {}).get('link'):
                # Update payment record with gateway reference
                payment.gateway_reference = data.get('data', {}).get('tx_ref', '')
                payment.gateway_response = data
                payment.save()
                
                return {
                    'status': 'success',
                    'data': {
                        'link': data['data']['link'],
                        'payment_id': str(payment.payment_id),
                        'tx_ref': str(payment.payment_id)
                    }
                }
            else:
                # Mark payment as failed
                error_message = data.get('message', 'Payment initialization failed')
                payment.mark_as_failed(gateway_response=data, error_message=error_message)
                logger.error(f"Flutterwave payment initialization failed for order {order.order_number}: {error_message}")
                raise Exception(f"Payment initialization failed: {error_message}")
                
        except requests.RequestException as e:
            logger.error(f"Network error during Flutterwave payment initialization: {str(e)}")
            if 'payment' in locals():
                payment.mark_as_failed(error_message=f"Network error: {str(e)}")
            raise Exception(f"Network error: {str(e)}")
        except Exception as e:
            logger.error(f"Error initializing Flutterwave payment: {str(e)}")
            if 'payment' in locals():
                payment.mark_as_failed(error_message=str(e))
            raise

    @classmethod
    def verify_payment(cls, transaction_id):
        """Verify a Flutterwave payment transaction"""
        try:
            # Check cache first to avoid repeated API calls
            cache_key = f"flw_verify_{transaction_id}"
            cached_result = cache.get(cache_key)
            if cached_result:
                logger.info(f"Using cached verification result for transaction {transaction_id}")
                return cached_result

            headers = {
                "Authorization": f"Bearer {settings.FLW_SECRET_KEY}",
                "Content-Type": "application/json"
            }

            logger.info(f"Verifying Flutterwave transaction: {transaction_id}")
            
            response = requests.get(
                f"{cls.BASE_URL}/transactions/{transaction_id}/verify",
                headers=headers,
                timeout=cls.TIMEOUT
            )

            data = response.json()
            logger.info(f"Flutterwave verification response for {transaction_id}: status={data.get('status')}")
            
            # Cache successful verifications for 5 minutes
            if data.get('status') == 'success':
                cache.set(cache_key, data, 300)
            
            return data
            
        except requests.RequestException as e:
            logger.error(f"Network error during Flutterwave payment verification: {str(e)}")
            raise Exception(f"Network error: {str(e)}")
        except Exception as e:
            logger.error(f"Error verifying Flutterwave payment: {str(e)}")
            raise

    @classmethod
    def process_webhook(cls, webhook_data):
        """Process Flutterwave webhook data with enhanced security"""
        try:
            tx_ref = webhook_data.get('tx_ref')
            status = webhook_data.get('status')
            transaction_id = webhook_data.get('id')
            
            logger.info(f"Processing Flutterwave webhook for tx_ref: {tx_ref}, status: {status}")
            
            if not tx_ref:
                logger.error("No tx_ref in webhook data")
                return False
            
            # Find the payment record
            try:
                payment = Payment.objects.get(payment_id=tx_ref)
            except Payment.DoesNotExist:
                logger.error(f"Payment not found for tx_ref: {tx_ref}")
                return False
            
            # Prevent processing the same webhook multiple times
            webhook_cache_key = f"webhook_processed_{tx_ref}_{transaction_id}"
            if cache.get(webhook_cache_key):
                logger.info(f"Webhook already processed for tx_ref: {tx_ref}")
                return True
            
            # Update payment based on status
            if status == 'successful':
                # Verify the payment with Flutterwave to ensure authenticity
                verification_data = cls.verify_payment(transaction_id)
                
                if (verification_data.get('status') == 'success' and 
                    verification_data.get('data', {}).get('status') == 'successful'):
                    
                    # Additional security check: verify amount matches
                    webhook_amount = webhook_data.get('amount')
                    verified_amount = verification_data.get('data', {}).get('amount')
                    
                    if webhook_amount and verified_amount and float(webhook_amount) != float(verified_amount):
                        logger.error(f"Amount mismatch for tx_ref {tx_ref}: webhook={webhook_amount}, verified={verified_amount}")
                        return False
                    
                    # Mark payment as successful
                    payment.mark_as_successful(
                        gateway_transaction_id=transaction_id,
                        gateway_response=webhook_data
                    )
                    
                    # Cache that this webhook was processed
                    cache.set(webhook_cache_key, True, 3600)  # Cache for 1 hour
                    
                    logger.info(f"Payment {payment.payment_id} marked as successful")
                    return True
                else:
                    logger.warning(f"Payment verification failed for tx_ref: {tx_ref}")
                    payment.mark_as_failed(gateway_response=verification_data)
                    return False
            
            elif status in ['failed', 'cancelled']:
                payment.mark_as_failed(gateway_response=webhook_data)
                cache.set(webhook_cache_key, True, 3600)
                logger.info(f"Payment {payment.payment_id} marked as failed/cancelled")
                return True
            
            else:
                logger.info(f"Payment {payment.payment_id} status updated to: {status}")
                payment.status = 'processing' if status == 'pending' else payment.status
                payment.gateway_response = webhook_data
                payment.save()
                return True
                
        except Exception as e:
            logger.error(f"Error processing Flutterwave webhook: {str(e)}")
            return False

    @classmethod
    def validate_webhook_signature(cls, payload, signature):
        """Validate Flutterwave webhook signature"""
        try:
            if not settings.FLW_WEBHOOK_HASH:
                logger.warning("FLW_WEBHOOK_HASH not configured")
                return False
                
            expected_signature = hmac.new(
                settings.FLW_WEBHOOK_HASH.encode('utf-8'),
                payload.encode('utf-8'),
                hashlib.sha256
            ).hexdigest()
            
            return hmac.compare_digest(signature, expected_signature)
        except Exception as e:
            logger.error(f"Error validating webhook signature: {str(e)}")
            return False

    @classmethod
    def retry_failed_payment(cls, payment):
        """Retry a failed payment"""
        try:
            if not payment.can_retry:
                raise Exception("Payment cannot be retried (max retries reached or not failed)")
            
            payment.increment_retry_count()
            payment.status = 'pending'
            payment.save()
            
            # Re-initialize the payment
            return cls.initialize_payment(payment.order)
            
        except Exception as e:
            logger.error(f"Error retrying payment {payment.payment_id}: {str(e)}")
            raise

    @classmethod
    def get_payment_status(cls, payment_id):
        """Get current payment status from Flutterwave"""
        try:
            payment = Payment.objects.get(payment_id=payment_id)
            
            if payment.gateway_transaction_id:
                verification_data = cls.verify_payment(payment.gateway_transaction_id)
                return verification_data
            else:
                return {"status": "error", "message": "No transaction ID available"}
                
        except Payment.DoesNotExist:
            return {"status": "error", "message": "Payment not found"}
        except Exception as e:
            logger.error(f"Error getting payment status: {str(e)}")
            return {"status": "error", "message": str(e)}


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

            line_items = []
            for cart_item in order.__class__._default_manager.none():
                pass

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
        try:
            stripe_client = cls._get_stripe_client()
            webhook_secret = getattr(settings, 'STRIPE_WEBHOOK_SECRET', None)

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

            if event['type'] == 'checkout.session.completed':
                session = event['data']['object']
                payment_intent = session.get('payment_intent')

                payment_id = session.get('metadata', {}).get('payment_id')
                if not payment_id:
                    logger.error(f"No payment_id in webhook metadata for session {session.get('id')}")
                    return False

                try:
                    payment = Payment.objects.get(payment_id=payment_id)
                except Payment.DoesNotExist:
                    logger.error(f"Payment not found for payment_id: {payment_id}")
                    return False

                payment.mark_as_successful(
                    gateway_transaction_id=payment_intent if isinstance(payment_intent, str) else (payment_intent.get('id') if payment_intent else None),
                    gateway_response={
                        'session_id': session.get('id'),
                        'payment_intent': payment_intent,
                    }
                )
                logger.info(f"Stripe payment {payment.payment_id} marked as successful for order {payment.order.order_number}")

            elif event['type'] == 'payment_intent.payment_failed':
                session_id = event['data']['object'].get('metadata', {}).get('payment_id')
                if session_id:
                    try:
                        payment = Payment.objects.get(payment_id=session_id)
                        payment.mark_as_failed(
                            gateway_response=event['data']['object'],
                            error_message=event['data']['object'].get('last_payment_error', {}).get('message', 'Payment failed')
                        )
                    except Payment.DoesNotExist:
                        logger.error(f"Payment not found for payment_id: {session_id}")

            return True

        except Exception as e:
            logger.error(f"Error processing Stripe webhook: {str(e)}")
            return False