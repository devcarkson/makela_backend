from django.contrib import admin
from django import forms
from django.utils.html import format_html
from .models import Category, Product, ProductImage, Notification, Size, Color, ProductVariant


class ColorForm(forms.ModelForm):
    """Custom form for Color with color picker widget"""
    
    class Meta:
        model = Color
        fields = '__all__'
        widgets = {
            'hex_code': forms.TextInput(attrs={
                'type': 'color',
                'class': 'color-picker-input',
                'title': 'Click to pick a color'
            }),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if 'hex_code' in self.fields:
            self.fields['hex_code'].help_text = 'Pick a color from the picker or type a hex code (e.g., #FF0000)'


class ProductImageInline(admin.TabularInline):
    model = ProductImage
    extra = 3
    readonly_fields = ['image_preview']
    
    def image_preview(self, obj):
        return format_html('<img src="{}" style="max-height: 100px; max-width: 100px;" />', obj.image.url) if obj.image else ''
    image_preview.short_description = 'Preview'

class ProductAdminForm(forms.ModelForm):
    """Stock is derived from the variants, so it is read-only for variant products."""

    class Meta:
        model = Product
        fields = '__all__'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if 'stock' in self.fields and self.instance and self.instance.has_variants:
            self.fields['stock'].disabled = True
            self.fields['stock'].help_text = (
                'Auto-calculated from the active size/color variants below. '
                'Edit the stock on each variant instead.'
            )


class ProductVariantInline(admin.TabularInline):
    model = ProductVariant
    extra = 3
    can_delete = True
    verbose_name_plural = "Product Variants (Size/Color combinations)"

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == 'color':
            # Show color swatches in the dropdown using Select with choices
            from .models import Color
            colors = Color.objects.all()
            choices = [('', '---------')]
            for color in colors:
                swatch = f"● " if not color.hex_code else ""
                if color.hex_code:
                    choices.append((color.id, f"{color.name} ({color.hex_code})"))
                else:
                    choices.append((color.id, color.name))
            kwargs['widget'] = forms.Select(attrs={
                'class': 'color-variant-select',
                'data-show-swatch': 'true',
            })
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

@admin.register(Size)
class SizeAdmin(admin.ModelAdmin):
    list_display = ['name', 'display_name', 'sort_order']
    ordering = ['sort_order', 'name']

@admin.register(Color)
class ColorAdmin(admin.ModelAdmin):
    form = ColorForm
    list_display = ['name', 'color_preview', 'hex_code']
    change_form_template = 'admin/products/color/change_form.html'
    
    def color_preview(self, obj):
        if obj.hex_code:
            return format_html(
                '<span style="display:inline-block;width:28px;height:28px;border:2px solid #ddd;background-color:{};border-radius:6px;vertical-align:middle;"></span> <span style="vertical-align:middle;font-weight:bold;">{}</span>',
                obj.hex_code,
                obj.hex_code
            )
        return mark_safe('<span style="color:#999;">No hex set</span>')
    color_preview.short_description = 'Color Preview'

@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ['name', 'slug', 'product_count']
    prepopulated_fields = {'slug': ('name',)}
    search_fields = ['name']
    
    def product_count(self, obj):
        return obj.product_set.count()
    product_count.short_description = 'Products'

@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    form = ProductAdminForm
    list_display = ['name', 'category', 'price', 'stock', 'has_variants', 'is_active', 'created_at']
    list_filter = ['category', 'is_active', 'has_variants', 'created_at']
    search_fields = ['name', 'description']
    prepopulated_fields = {'slug': ('name',)}
    inlines = [ProductImageInline, ProductVariantInline]
    readonly_fields = ['created_at', 'updated_at', 'total_stock']
    change_form_template = 'admin/products/product/change_form.html'
    fieldsets = (
        ('Basic Information', {
            'fields': ('name', 'slug', 'category', 'description', 'is_featured', 'is_new_arrival')
        }),
        ('Variant Options', {
            'fields': ('has_variants',),
            'classes': ('collapse',)
        }),
        ('Pricing', {
            'fields': ('price', 'discount_price')
        }),
        ('Inventory', {
            'fields': ('stock', 'total_stock', 'is_active')
        }),
        ('Metadata', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    actions = ['activate_products', 'deactivate_products', 'set_has_variants_true', 'set_has_variants_false', 'resync_variant_stock']
    
    def total_stock(self, obj):
        return obj.total_stock
    total_stock.short_description = 'Total Stock'
    
    def activate_products(self, request, queryset):
        updated = queryset.update(is_active=True)
        self.message_user(request, f'{updated} products activated.')
    activate_products.short_description = "Activate selected products"
    
    def deactivate_products(self, request, queryset):
        updated = queryset.update(is_active=False)
        self.message_user(request, f'{updated} products deactivated.')
    deactivate_products.short_description = "Deactivate selected products"
    
    def set_has_variants_true(self, request, queryset):
        for product in queryset.filter(has_variants=False):
            product.has_variants = True
            product.save()
        self.message_user(request, f'{queryset.count()} products set to have variants.')
    set_has_variants_true.short_description = "Set as variant product"
    
    def set_has_variants_false(self, request, queryset):
        for product in queryset.filter(has_variants=True):
            product.has_variants = False
            product.save()
        self.message_user(request, f'{queryset.count()} products set to not have variants.')
    set_has_variants_false.short_description = "Set as non-variant product"

    def resync_variant_stock(self, request, queryset):
        """Repair the cached product stock from the current variants."""
        resynced = 0
        for product in queryset.filter(has_variants=True):
            previous = product.stock
            product.sync_variant_stock()
            if product.stock != previous:
                resynced += 1
        self.message_user(request, f'{resynced} products resynced with their variants.')
    resync_variant_stock.short_description = "Resync stock from variants"

@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ['user', 'message_preview', 'read', 'created_at']
    list_filter = ['read', 'created_at']
    search_fields = ['user__email', 'user__first_name', 'user__last_name', 'message']
    readonly_fields = ['created_at']
    actions = ['mark_as_read', 'mark_as_unread']
    
    def message_preview(self, obj):
        return obj.message[:50] + '...' if len(obj.message) > 50 else obj.message
    message_preview.short_description = 'Message'
    
    def mark_as_read(self, request, queryset):
        updated = queryset.update(read=True)
        self.message_user(request, f'{updated} notifications marked as read.')
    mark_as_read.short_description = "Mark selected notifications as read"
    
    def mark_as_unread(self, request, queryset):
        updated = queryset.update(read=False)
        self.message_user(request, f'{updated} notifications marked as unread.')
    mark_as_unread.short_description = "Mark selected notifications as unread"