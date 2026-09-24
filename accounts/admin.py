# accounts/admin.py
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.models import Group
from rest_framework.authtoken.models import TokenProxy
from django_rest_passwordreset.models import ResetPasswordToken
from rest_framework_simplejwt.token_blacklist.models import OutstandingToken, BlacklistedToken
from .models import User, ContactMessage


# Hide token/password-related models from admin
admin.site.unregister(Group)
admin.site.unregister(TokenProxy)
admin.site.unregister(ResetPasswordToken)
admin.site.unregister(OutstandingToken)
admin.site.unregister(BlacklistedToken)


class ContactMessageAdmin(admin.ModelAdmin):
    list_display = ('id', 'first_name', 'last_name', 'email', 'subject', 'created_at')
    list_filter = ('created_at',)
    search_fields = ('first_name', 'last_name', 'email', 'subject', 'message')
    readonly_fields = ('created_at',)
    list_per_page = 25
    ordering = ('-created_at',)
    date_hierarchy = 'created_at'


class CustomUserAdmin(UserAdmin):
    list_display = ('email', 'username', 'is_active', 'is_staff', 'date_joined')
    list_filter = ('is_staff', 'is_active')
    search_fields = ('email', 'username')
    ordering = ('-date_joined',)
    
    fieldsets = (
        (None, {'fields': ('email', 'password')}),
        ('Personal info', {'fields': ('username', 'phone', 'address')}),
        ('Permissions', {'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions')}),
        ('Important dates', {'fields': ('last_login', 'date_joined')}),
    )
    
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('email', 'username', 'password1', 'password2'),
        }),
    )

admin.site.register(User, CustomUserAdmin)
admin.site.register(ContactMessage, ContactMessageAdmin)