import logging
from django.core.mail import send_mail, EmailMultiAlternatives
from django.template.loader import render_to_string
from django.conf import settings
from django.utils.html import strip_tags
from typing import List, Optional, Dict, Any

logger = logging.getLogger(__name__)

# Brand configuration
BRAND_CONFIG = {
    'site_name': 'Makela',
    'primary_color': '#7C3AED',      # Purple - matches frontend
    'primary_color_dark': '#6D28D9', # Darker purple for gradients
}

def get_brand_context(overrides: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Get base brand context with optional overrides"""
    from django.conf import settings
    context = BRAND_CONFIG.copy()
    context['logo_url'] = f"{getattr(settings, 'FRONTEND_URL', 'https://makelacosmetic.uk')}/logo.webp"
    if overrides:
        context.update(overrides)
    return context

class EmailService:
    """
    Centralized email service for consistent email sending across the application
    """
    
    @staticmethod
    def send_email(
        subject: str,
        template_name: str,
        context: Dict[str, Any],
        recipient_list: List[str],
        from_email: Optional[str] = None,
        fail_silently: bool = False,
        plain_template_name: Optional[str] = None
    ) -> bool:
        """
        Send an email using HTML template with optional plain text fallback
        
        Args:
            subject: Email subject
            template_name: Path to HTML template
            context: Template context variables
            recipient_list: List of recipient email addresses
            from_email: Sender email (defaults to DEFAULT_FROM_EMAIL)
            fail_silently: Whether to suppress exceptions
            plain_template_name: Optional plain text template
            
        Returns:
            bool: True if email was sent successfully, False otherwise
        """
        try:
            if not recipient_list:
                logger.warning("No recipients provided for email")
                return False
                
            from_email = from_email or settings.DEFAULT_FROM_EMAIL
            
            # Merge brand context with provided context
            full_context = get_brand_context(context)
            
            # Render HTML content
            html_content = render_to_string(template_name, full_context)
            
            # Create plain text version
            if plain_template_name:
                plain_content = render_to_string(plain_template_name, full_context)
            else:
                plain_content = strip_tags(html_content)
            
            # Create email message
            email = EmailMultiAlternatives(
                subject=subject,
                body=plain_content,
                from_email=from_email,
                to=recipient_list
            )
            email.attach_alternative(html_content, "text/html")
            
            # Send email
            result = email.send(fail_silently=fail_silently)
            
            if result:
                logger.info(f"Email sent successfully to {', '.join(recipient_list)}: {subject}")
                return True
            else:
                logger.error(f"Failed to send email to {', '.join(recipient_list)}: {subject}")
                return False
                
        except Exception as e:
            logger.error(f"Error sending email to {', '.join(recipient_list)}: {str(e)}")
            if not fail_silently:
                raise
            return False
    
    @staticmethod
    def send_welcome_email(user) -> bool:
        """Send welcome email to new user"""
        context = get_brand_context({
            'user': user,
            'frontend_url': settings.FRONTEND_URL,
        })
        
        return EmailService.send_email(
            subject=f"Welcome to {BRAND_CONFIG['site_name']}, {user.first_name or user.username}!",
            template_name='emails/welcome.html',
            context=context,
            recipient_list=[user.email],
            plain_template_name='emails/welcome.txt'
        )
    
    @staticmethod
    def send_order_confirmation_email(order) -> bool:
        """Send order confirmation email"""
        context = get_brand_context({
            'order': order,
            'user': order.user,
            'frontend_url': settings.FRONTEND_URL,
            'order_items': order.items.all(),
        })
        
        return EmailService.send_email(
            subject=f"Order Confirmation - #{order.order_number}",
            template_name='emails/order_confirmation.html',
            context=context,
            recipient_list=[order.user.email],
            plain_template_name='emails/order_confirmation.txt'
        )
    
    @staticmethod
    def send_order_status_update_email(order) -> bool:
        """Send order status update email"""
        context = get_brand_context({
            'order': order,
            'user': order.user,
            'frontend_url': settings.FRONTEND_URL,
            'status_display': order.get_status_display(),
        })
        
        return EmailService.send_email(
            subject=f"Order Update - #{order.order_number}",
            template_name='emails/order_status_update.html',
            context=context,
            recipient_list=[order.user.email],
            plain_template_name='emails/order_status_update.txt'
        )
    
    @staticmethod
    def send_password_reset_email(reset_password_token) -> bool:
        """Send password reset email"""
        context = get_brand_context({
            'user': reset_password_token.user,
            'reset_password_token': reset_password_token,
            'frontend_url': settings.FRONTEND_URL,
            'reset_url': f"{settings.FRONTEND_URL}/auth/reset-password?token={reset_password_token.key}",
        })
        
        return EmailService.send_email(
            subject=f"Password Reset Request - {BRAND_CONFIG['site_name']}",
            template_name='emails/password_reset.html',
            context=context,
            recipient_list=[reset_password_token.user.email],
            plain_template_name='emails/password_reset.txt'
        )
    
    @staticmethod
    def send_contact_form_notification(contact_message) -> bool:
        """Send contact form notification to admins"""
        context = get_brand_context({
            'contact_message': contact_message,
        })
        
        # Get admin emails
        admin_emails = [admin[1] for admin in settings.ADMINS]
        
        return EmailService.send_email(
            subject=f"New Contact Message: {contact_message.subject}",
            template_name='emails/contact_form_notification.html',
            context=context,
            recipient_list=admin_emails
        )