from django.db import models
from django.utils.text import slugify
from django.conf import settings
from PIL import Image
from .utils import compress_image_on_upload
from cloudinary.models import CloudinaryField

class Category(models.Model):
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=100, unique=True)
    image = CloudinaryField('image', folder='categories', blank=True, null=True)
    
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = "Categories"
        ordering = ['name']

    def __str__(self):
        return self.name

    def get_thumbnail_url(self):
        if self.image:
            return self.image.build_url(
                width=150, height=150, crop='fill',
                format='webp', quality='auto'
            )
        return None

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

class Size(models.Model):
    """Product size options (e.g., S, M, L, XL)"""
    name = models.CharField(max_length=50, unique=True, help_text="e.g., S, M, L, XL, 6, 7, 8")
    display_name = models.CharField(max_length=50, help_text="e.g., Small, Medium, Large, 6, 7, 8")
    sort_order = models.PositiveIntegerField(default=0, help_text="For ordering sizes")

    class Meta:
        ordering = ['sort_order', 'name']
        verbose_name_plural = "Sizes"

    def __str__(self):
        return f"{self.name} ({self.display_name})"


class Color(models.Model):
    """Product color options"""
    name = models.CharField(max_length=50, unique=True, help_text="e.g., Red, Navy Blue")
    hex_code = models.CharField(max_length=7, blank=True, help_text="e.g., #FF0000")

    class Meta:
        ordering = ['name']
        verbose_name_plural = "Colors"

    def __str__(self):
        if self.hex_code:
            return f"{self.name} ({self.hex_code})"
        return self.name


class Product(models.Model):
    category = models.ForeignKey(Category, on_delete=models.CASCADE)
    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=200, unique=True)
    description = models.TextField()
    price = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True, help_text="Base price (used if no variant price set)")
    discount_price = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    stock = models.PositiveIntegerField(default=0, help_text="Total stock across all variants (auto-calculated)")
    has_variants = models.BooleanField(default=False, help_text="Whether this product has size/color variants")
    is_featured = models.BooleanField(default=False)
    is_new_arrival = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['is_featured']),
            models.Index(fields=['is_new_arrival']),
            models.Index(fields=['category']),
            models.Index(fields=['price']),
            models.Index(fields=['created_at']),
            models.Index(fields=['slug']),
        ]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)
        # For variant products the stock field is derived from the variants
        if self.has_variants:
            self.sync_variant_stock()

    def sync_variant_stock(self):
        """Recalculate the denormalized `stock` field from the active variants.

        Uses a queryset update so that it never triggers save()/signals again and
        never clobbers a caller supplied `update_fields`.
        """
        if not self.pk or not self.has_variants:
            return self.stock

        total = self.variants.filter(is_active=True).aggregate(
            total=models.Sum('stock')
        )['total'] or 0

        if total != self.stock:
            Product.objects.filter(pk=self.pk).update(stock=total)
            self.stock = total
        return self.stock

    @property
    def current_price(self):
        return self.discount_price if self.discount_price else self.price

    @property
    def available_sizes(self):
        """Return list of available size names for this product"""
        if self.has_variants:
            return list(self.variants.values_list('size__display_name', flat=True).distinct())
        return []

    @property
    def available_colors(self):
        """Return list of available color names for this product"""
        if self.has_variants:
            return list(self.variants.values_list('color__name', flat=True).distinct())
        return []

    @property
    def total_stock(self):
        """Total stock across all active variants (or the plain stock value)"""
        if self.has_variants:
            return self.variants.filter(is_active=True).aggregate(
                total=models.Sum('stock')
            )['total'] or 0
        return self.stock


class ProductVariant(models.Model):
    """A specific size/color combination for a product with its own price and stock"""
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='variants')
    size = models.ForeignKey(Size, on_delete=models.CASCADE, related_name='variants')
    color = models.ForeignKey(Color, on_delete=models.CASCADE, related_name='variants')
    price = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True, help_text="Variant-specific price (overrides product base price)")
    stock = models.PositiveIntegerField(default=0)
    sku = models.CharField(max_length=100, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('product', 'size', 'color')
        ordering = ['size__sort_order', 'color__name']
        indexes = [
            models.Index(fields=['product', 'is_active']),
            models.Index(fields=['stock']),
        ]

    def __str__(self):
        return f"{self.product.name} - {self.size.name} / {self.color.name}"

    @property
    def effective_price(self):
        """Return the variant price if set, otherwise fall back to product base price"""
        if self.price:
            return self.price
        return self.product.price

    @property
    def current_price(self):
        """Return discounted price if available, otherwise effective price"""
        if self.product.discount_price:
            return self.product.discount_price
        return self.effective_price

class ProductImage(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='images')
    image = CloudinaryField('image', folder='products')  # Upload to Cloudinary 'products/' folder
    
    is_primary = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=['product']),
            models.Index(fields=['is_primary']),
            models.Index(fields=['product', 'is_primary']),
        ]

    def __str__(self):
        return f"Image for {self.product.name}"

    def get_thumbnail_small_url(self):
        if self.image:
            return self.image.build_url(
                width=150, height=150, crop='fill',
                format='webp', quality='auto'
            )
        return None

    def get_thumbnail_medium_url(self):
        if self.image:
            return self.image.build_url(
                width=300, height=300, crop='fill',
                format='webp', quality='auto'
            )
        return None

    def get_thumbnail_large_url(self):
        if self.image:
            return self.image.build_url(
                width=600, height=600, crop='limit',
                format='webp', quality='auto'
            )
        return None

class Review(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='reviews')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='reviews')
    rating = models.PositiveSmallIntegerField()
    comment = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('product', 'user')
        ordering = ['-created_at']

    def __str__(self):
        return f"Review by {self.user} for {self.product} ({self.rating} stars)"

class Wishlist(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='wishlist_items')
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='wishlisted_by')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('user', 'product')
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.user} - {self.product}"

class Notification(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='notifications')
    message = models.TextField()
    read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Notification for {self.user}: {self.message[:30]}..."