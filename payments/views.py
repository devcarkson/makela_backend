import json
from django.conf import settings
from django.shortcuts import get_object_or_404
from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_exempt
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status, generics
from rest_framework.permissions import IsAuthenticated
from rest_framework.throttling import UserRateThrottle, AnonRateThrottle
from orders.models import Order
from orders.signals import send_order_confirmation_email
from .services import StripeService
from .models import Payment
from .serializers import (
    PaymentSerializer, 
    PaymentInitializationSerializer,
    PaymentVerificationSerializer,
)
import logging

logger = logging.getLogger(__name__)

class PaymentRateThrottle(UserRateThrottle):
    scope = 'payment'
    rate = '10/min'  # 10 payment requests per minute per user

class WebhookRateThrottle(AnonRateThrottle):
    scope = 'webhook'
    rate = '100/min'  # 100 webhook requests per minute

@method_decorator(never_cache, name='dispatch')
class PaymentInitializeView(APIView):
    """Initialize Stripe payment for an order"""
    permission_classes = [IsAuthenticated]
    throttle_classes = [PaymentRateThrottle]

    def post(self, request, order_number):
        try:
            order = get_object_or_404(
                Order, 
                order_number=order_number, 
                user=request.user
            )
            
            # Check if order is already paid
            if order.payment_status:
                return Response({
                    "error": "Order is already paid",
                    "order_number": order.order_number,
                    "payment_status": True
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Check if there's already a pending Stripe payment
            existing_payment = Payment.objects.filter(
                order=order,
                status='pending',
                gateway='stripe'
            ).first()
            
            if existing_payment and existing_payment.gateway_response and existing_payment.gateway_response.get('checkout_url'):
                return Response({
                    "checkout_url": existing_payment.gateway_response['checkout_url'],
                    "payment_id": str(existing_payment.payment_id),
                    "session_id": existing_payment.gateway_response.get('session_id', ''),
                    "order_number": order.order_number,
                    "amount": str(existing_payment.amount),
                    "currency": existing_payment.currency
                }, status=status.HTTP_200_OK)
            
            # Initialize new Stripe payment
            payment_response = StripeService.initialize_payment(order)
            
            return Response({
                "checkout_url": payment_response.get('data', {}).get('checkout_url'),
                "payment_id": payment_response.get('data', {}).get('payment_id'),
                "session_id": payment_response.get('data', {}).get('session_id'),
                "order_number": order.order_number,
                "amount": str(order.total),
                "currency": "GBP"
            }, status=status.HTTP_200_OK)
            
        except Exception as e:
            logger.error(f"Payment initialization error for order {order_number}: {str(e)}")
            return Response({
                "error": str(e),
                "order_number": order_number
            }, status=status.HTTP_400_BAD_REQUEST)

# Keep the old PaymentView for backward compatibility
@method_decorator(never_cache, name='dispatch')
class PaymentView(PaymentInitializeView):
    """Legacy payment initialization view - redirects to PaymentInitializeView"""
    pass

@method_decorator(never_cache, name='dispatch')
class PaymentVerificationView(APIView):
    """Verify Stripe payment status"""
    permission_classes = [IsAuthenticated]
    throttle_classes = [PaymentRateThrottle]
    
    def get(self, request, payment_id):
        try:
            payment = get_object_or_404(
                Payment,
                payment_id=payment_id,
                order__user=request.user
            )
            
            # If payment is already successful, return success
            if payment.is_successful:
                return Response({
                    "status": "successful",
                    "payment": PaymentSerializer(payment).data,
                    "message": "Payment completed successfully"
                })
            
            # If payment is pending and has a Stripe session, verify with Stripe
            if payment.is_pending and payment.gateway_reference and payment.gateway == 'stripe':
                try:
                    session = StripeService.verify_payment(payment.gateway_reference)
                    if session and session.payment_status == 'paid':
                        payment.mark_as_successful(
                            gateway_transaction_id=session.payment_intent.id if hasattr(session.payment_intent, 'id') else str(session.payment_intent),
                            gateway_response={
                                'session_id': session.id,
                                'payment_intent': session.payment_intent.id if hasattr(session.payment_intent, 'id') else str(session.payment_intent),
                            }
                        )
                        
                        return Response({
                            "status": "successful",
                            "payment": PaymentSerializer(payment).data,
                            "message": "Payment verified and completed successfully"
                        })
                except Exception as e:
                    logger.error(f"Stripe payment verification error: {str(e)}")
            
            # Return current payment status
            return Response({
                "status": payment.status,
                "payment": PaymentSerializer(payment).data,
                "message": f"Payment is currently {payment.status}"
            })
            
        except Exception as e:
            logger.error(f"Payment verification error: {str(e)}")
            return Response({
                "error": str(e)
            }, status=status.HTTP_400_BAD_REQUEST)

@method_decorator(never_cache, name='dispatch')
class PaymentStatusView(APIView):
    """Get payment status for polling"""
    permission_classes = [IsAuthenticated]
    throttle_classes = [PaymentRateThrottle]
    
    def get(self, request, payment_id):
        try:
            payment = get_object_or_404(
                Payment,
                payment_id=payment_id,
                order__user=request.user
            )
            
            return Response({
                "payment": PaymentSerializer(payment).data,
                "order": {
                    "id": payment.order.id,
                    "order_number": payment.order.order_number,
                    "status": payment.order.status,
                    "total": str(payment.order.total)
                }
            })
            
        except Exception as e:
            logger.error(f"Payment status error: {str(e)}")
            return Response({
                "error": str(e)
            }, status=status.HTTP_400_BAD_REQUEST)

@method_decorator(never_cache, name='dispatch')
class PaymentRetryView(APIView):
    """Retry a failed Stripe payment"""
    permission_classes = [IsAuthenticated]
    throttle_classes = [PaymentRateThrottle]
    
    def post(self, request, payment_id):
        try:
            payment = get_object_or_404(
                Payment,
                payment_id=payment_id,
                order__user=request.user
            )
            
            if not payment.can_retry:
                return Response({
                    "error": "Payment cannot be retried",
                    "reason": "Maximum retries reached or payment not failed"
                }, status=status.HTTP_400_BAD_REQUEST)
            
            if payment.gateway != 'stripe':
                return Response({
                    "error": "Only Stripe payments can be retried via this endpoint"
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Increment retry count
            payment.increment_retry_count()
            
            # Re-initialize Stripe payment
            payment_response = StripeService.initialize_payment(payment.order)
            
            return Response({
                "checkout_url": payment_response.get('data', {}).get('checkout_url'),
                "payment_id": payment_response.get('data', {}).get('payment_id'),
                "session_id": payment_response.get('data', {}).get('session_id'),
                "retry_count": payment.retry_count
            }, status=status.HTTP_200_OK)
            
        except Exception as e:
            logger.error(f"Payment retry error: {str(e)}")
            return Response({
                "error": str(e)
            }, status=status.HTTP_400_BAD_REQUEST)

@method_decorator(never_cache, name='dispatch')
class PaymentListView(generics.ListAPIView):
    """List user's payments"""
    serializer_class = PaymentSerializer
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        return Payment.objects.filter(
            order__user=self.request.user
        ).select_related('order').order_by('-created_at')

@method_decorator(csrf_exempt, name='dispatch')
@method_decorator(never_cache, name='dispatch')
class StripeWebhookView(APIView):
    """Handle Stripe webhook notifications."""
    authentication_classes = []
    permission_classes = []
    throttle_classes = [WebhookRateThrottle]

    @staticmethod
    def _to_dict(obj):
        """Convert Stripe object to dict."""
        if hasattr(obj, 'to_dict'):
            return obj.to_dict()
        return obj

    def post(self, request):
        payload = request.body
        sig_header = request.headers.get('Stripe-Signature', '')

        try:
            success = StripeService.process_webhook(payload, sig_header)

            if success:
                # Send order confirmation email for completed payments
                # Re-parse event only for email trigger (lightweight)
                event = None
                try:
                    import stripe as stripe_module
                    stripe_module.api_key = settings.STRIPE_SECRET_KEY
                    event = stripe_module.Webhook.construct_event(
                        payload, sig_header, settings.STRIPE_WEBHOOK_SECRET
                    )
                except Exception:
                    logger.error("Failed to reconstruct Stripe webhook event for email sending")

                # Trigger email for both sync and async payment success
                if event and event['type'] in ('checkout.session.completed', 'checkout.session.async_payment_succeeded'):
                    session = self._to_dict(event['data']['object'])
                    payment_id = session.get('metadata', {}).get('payment_id')
                    payment_status = session.get('payment_status')
                    if payment_id and payment_status == 'paid':
                        try:
                            payment = Payment.objects.get(payment_id=payment_id)
                            if payment.is_successful:
                                send_order_confirmation_email(payment.order)
                        except Payment.DoesNotExist:
                            logger.error(f"Payment not found for payment_id: {payment_id}")

                return Response({"message": "Webhook processed successfully"}, status=status.HTTP_200_OK)
            else:
                return Response({"error": "Webhook processing failed"}, status=status.HTTP_400_BAD_REQUEST)

        except Exception as e:
            logger.error(f"Stripe webhook error: {str(e)}")
            return Response({"error": "Internal server error"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)