from rest_framework import serializers
from .models import Category, Product, ProductImage, Review, Wishlist, Notification, Size, Color, ProductVariant
from django.contrib.auth import get_user_model


class SizeSerializer(serializers.ModelSerializer):
    class Meta:
        model = Size
        fields = ['id', 'name', 'display_name', 'sort_order']


class ColorSerializer(serializers.ModelSerializer):
    class Meta:
        model = Color
        fields = ['id', 'name', 'hex_code']


class ProductVariantSerializer(serializers.ModelSerializer):
    size = SizeSerializer(read_only=True)
    color = ColorSerializer(read_only=True)
    size_id = serializers.PrimaryKeyRelatedField(queryset=Size.objects.all(), source='size', write_only=True)
    color_id = serializers.PrimaryKeyRelatedField(queryset=Color.objects.all(), source='color', write_only=True)
    effective_price = serializers.SerializerMethodField()
    current_price = serializers.SerializerMethodField()

    class Meta:
        model = ProductVariant
        fields = ['id', 'size', 'color', 'size_id', 'color_id', 'price', 'stock', 'sku', 'is_active', 'effective_price', 'current_price']
        read_only_fields = ['id', 'created_at', 'updated_at']

    def get_effective_price(self, obj):
        return obj.effective_price

    def get_current_price(self, obj):
        return obj.current_price

class ProductImageSerializer(serializers.ModelSerializer):
    image = serializers.SerializerMethodField()
    thumbnail_small = serializers.SerializerMethodField()
    thumbnail_medium = serializers.SerializerMethodField()
    thumbnail_large = serializers.SerializerMethodField()
    
    class Meta:
        model = ProductImage
        fields = ['id', 'image', 'thumbnail_small', 'thumbnail_medium', 'thumbnail_large', 'is_primary']
    
    def get_image(self, obj):
        return secure_url(obj.image.url) if obj.image else None
    
    def get_thumbnail_small(self, obj):
        try:
            if obj.image:
                return obj.get_thumbnail_small_url()
        except:
            pass
        return None
    
    def get_thumbnail_medium(self, obj):
        try:
            if obj.image:
                return obj.get_thumbnail_medium_url()
        except:
            pass
        return None
    
    def get_thumbnail_large(self, obj):
        try:
            if obj.image:
                return obj.get_thumbnail_large_url()
        except:
            pass
        return None

class CategorySerializer(serializers.ModelSerializer):
    image = serializers.SerializerMethodField()
    thumbnail = serializers.SerializerMethodField()
    
    class Meta:
        model = Category
        fields = ['id', 'name', 'slug', 'image', 'thumbnail']

    def get_image(self, obj):
        return secure_url(obj.image.url) if obj.image else None
    
    def get_thumbnail(self, obj):
        try:
            if obj.image:
                return obj.get_thumbnail_url()
        except:
            pass
        return None

# class ProductSerializer(serializers.ModelSerializer):
#     images = ProductImageSerializer(many=True, read_only=True)
#     category = CategorySerializer(read_only=True)
    
#     class Meta:
#         model = Product
#         fields = [
#             'id', 'name', 'slug', 'description', 'price', 'stock', 
#             'rating', 'review_count', 'category', 'images', 'created_at'
#         ]

# products/serializers.py
class ReviewSerializer(serializers.ModelSerializer):
    user = serializers.StringRelatedField(read_only=True)

    class Meta:
        model = Review
        fields = ['id', 'user', 'rating', 'comment', 'created_at']
        read_only_fields = ['id', 'user', 'created_at']

def secure_url(url):
    """Cloudinary's default build_url() is http, which triggers mixed-content on https sites."""
    if url and url.startswith('http://'):
        return 'https://' + url[len('http://'):]
    return url


def variant_options(variants, size_key='name', color_key='name'):
    """Collect distinct size/color option names from already fetched variants.

    Uses the prefetch cache when the queryset prefetched the variants, which
    avoids the per-product queries a values_list().distinct() lookup would run.
    """
    sizes = []
    colors = []
    for variant in variants:
        size = getattr(variant.size, size_key, None)
        if size and size not in sizes:
            sizes.append(size)
        color = getattr(variant.color, color_key, None)
        if color and color not in colors:
            colors.append(color)
    return sizes, colors


# Lightweight serializer for list views (faster loading)
class ProductListSerializer(serializers.ModelSerializer):
    category = CategorySerializer(read_only=True)
    primary_image = serializers.SerializerMethodField()
    rating = serializers.SerializerMethodField()
    review_count = serializers.SerializerMethodField()
    available_sizes = serializers.SerializerMethodField()
    available_colors = serializers.SerializerMethodField()
    has_variants = serializers.BooleanField(read_only=True)
    
    class Meta:
        model = Product
        fields = [
            'id', 'name', 'slug', 'price', 'discount_price', 
            'stock', 'rating', 'review_count', 'category', 
            'primary_image', 'is_featured', 'is_new_arrival',
            'has_variants', 'available_sizes', 'available_colors'
        ]
    
    def get_primary_image(self, obj):
        """Get only the primary image thumbnail for list view"""
        # Read from the prefetch cache; .filter() here would re-query per product
        images = list(obj.images.all())
        primary_image = next((image for image in images if image.is_primary), None)
        if not primary_image and images:
            primary_image = images[0]
        
        if primary_image:
            result = {'id': primary_image.id}
            
            # Get Cloudinary thumbnail URLs
            try:
                result['thumbnail_small'] = primary_image.get_thumbnail_small_url()
            except:
                pass
            
            try:
                result['thumbnail_medium'] = primary_image.get_thumbnail_medium_url()
            except:
                pass

            try:
                result['thumbnail_large'] = primary_image.get_thumbnail_large_url()
            except:
                pass

            return result
        return None
    
    def get_rating(self, obj):
        # Use cached rating if available
        if hasattr(obj, '_cached_rating'):
            return obj._cached_rating
        reviews = getattr(obj, 'prefetched_reviews', obj.reviews.all())
        if not reviews:
            return None
        rating = round(sum([r.rating for r in reviews]) / len(reviews), 2)
        obj._cached_rating = rating
        return rating
    
    def get_review_count(self, obj):
        # Use cached review count if available
        if hasattr(obj, '_cached_review_count'):
            return obj._cached_review_count
        reviews = getattr(obj, 'prefetched_reviews', obj.reviews.all())
        count = len(reviews)
        obj._cached_review_count = count
        return count

    def get_available_sizes(self, obj):
        if obj.has_variants:
            return variant_options(obj.variants.all())[0]
        return []

    def get_available_colors(self, obj):
        if obj.has_variants:
            return variant_options(obj.variants.all())[1]
        return []

# Full serializer for detail views
class ProductSerializer(serializers.ModelSerializer):
    images = ProductImageSerializer(many=True, read_only=True)
    category = CategorySerializer(read_only=True)
    reviews = ReviewSerializer(many=True, read_only=True)
    rating = serializers.SerializerMethodField()
    review_count = serializers.SerializerMethodField()
    primary_image = serializers.SerializerMethodField()
    variants = ProductVariantSerializer(many=True, read_only=True)
    available_sizes = serializers.SerializerMethodField()
    available_colors = serializers.SerializerMethodField()
    total_stock = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields = [
            'id', 'name', 'slug', 'description', 'price', 
            'discount_price', 'stock', 'rating', 'review_count', 'category', 
            'images', 'primary_image', 'created_at', 'is_featured', 'is_new_arrival', 'reviews',
            'has_variants', 'variants', 'available_sizes', 'available_colors', 'total_stock'
        ]

    def get_primary_image(self, obj):
        """Get the primary image or first image for quick loading"""
        primary_image = obj.images.filter(is_primary=True).first()
        if not primary_image:
            primary_image = obj.images.first()
        
        if primary_image:
            return ProductImageSerializer(primary_image, context=self.context).data
        return None
    
    def get_rating(self, obj):
        # Use prefetched reviews to avoid N+1 queries
        reviews = getattr(obj, 'prefetched_reviews', obj.reviews.all())
        if not reviews:
            return None
        return round(sum([r.rating for r in reviews]) / len(reviews), 2)
    
    def get_review_count(self, obj):
        # Use prefetched reviews to avoid N+1 queries
        reviews = getattr(obj, 'prefetched_reviews', obj.reviews.all())
        return len(reviews)

    def get_available_sizes(self, obj):
        if obj.has_variants:
            return variant_options(obj.variants.all(), 'display_name')[0]
        return []

    def get_available_colors(self, obj):
        if obj.has_variants:
            return variant_options(obj.variants.all())[1]
        return []

    def get_total_stock(self, obj):
        return obj.total_stock

# Minimal serializer for better performance in lists
class ProductMinimalSerializer(serializers.ModelSerializer):
    primary_image_url = serializers.SerializerMethodField()
    
    class Meta:
        model = Product
        fields = ['id', 'name', 'slug', 'price', 'discount_price', 'primary_image_url']
    
    def get_primary_image_url(self, obj):
        primary_image = obj.images.filter(is_primary=True).first()
        if not primary_image:
            primary_image = obj.images.first()
        
        if primary_image:
            try:
                # Wishlist cards render wider than 150px, so use the medium thumb.
                return primary_image.get_thumbnail_medium_url()
            except:
                pass
            # Fallback to original image URL
            try:
                if primary_image.image:
                    return str(primary_image.image.url)
            except:
                pass
        return None

class WishlistSerializer(serializers.ModelSerializer):
    product = ProductMinimalSerializer(read_only=True)  # Use minimal serializer
    product_id = serializers.PrimaryKeyRelatedField(queryset=Product.objects.all(), source='product', write_only=True)

    class Meta:
        model = Wishlist
        fields = ['id', 'product', 'product_id', 'created_at']
        read_only_fields = ['id', 'created_at', 'product']

class NotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Notification
        fields = ['id', 'message', 'read', 'created_at']
        read_only_fields = ['id', 'created_at']