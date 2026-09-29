from django.test import TestCase
from django.contrib.auth import get_user_model
from .models import Product, Category, Size, Color, ProductVariant, ProductImage
from orders.models import Cart, CartItem
from decimal import Decimal

User = get_user_model()


class SizeColorModelTest(TestCase):
    def test_create_size(self):
        size = Size.objects.create(name='M', display_name='Medium', sort_order=2)
        self.assertEqual(str(size), 'M (Medium)')
        self.assertEqual(size.name, 'M')

    def test_create_color(self):
        color = Color.objects.create(name='Red', hex_code='#FF0000')
        self.assertEqual(str(color), 'Red (#FF0000)')
        self.assertEqual(color.hex_code, '#FF0000')


class ProductVariantModelTest(TestCase):
    def setUp(self):
        self.category = Category.objects.create(name='Test Category')
        self.product = Product.objects.create(
            name='Test Product',
            description='Test description',
            price=Decimal('10.00'),
            stock=10,
            category=self.category,
            has_variants=True
        )
        self.size = Size.objects.create(name='M', display_name='Medium')
        self.color = Color.objects.create(name='Red', hex_code='#FF0000')

    def test_create_variant(self):
        variant = ProductVariant.objects.create(
            product=self.product,
            size=self.size,
            color=self.color,
            price=Decimal('12.00'),
            stock=5
        )
        self.assertEqual(str(variant), 'Test Product - M / Red')
        self.assertEqual(variant.effective_price, Decimal('12.00'))
        self.assertEqual(variant.current_price, Decimal('12.00'))

    def test_variant_falls_back_to_product_price(self):
        variant = ProductVariant.objects.create(
            product=self.product,
            size=self.size,
            color=self.color,
            stock=5
        )
        # When variant has no price, should fall back to product price
        self.assertEqual(variant.effective_price, Decimal('10.00'))

    def test_variant_discount_price(self):
        self.product.discount_price = Decimal('8.00')
        self.product.save()
        variant = ProductVariant.objects.create(
            product=self.product,
            size=self.size,
            color=self.color,
            price=Decimal('12.00'),
            stock=5
        )
        # current_price should use product discount price
        self.assertEqual(variant.current_price, Decimal('8.00'))

    def test_total_stock_calculation(self):
        Size.objects.create(name='S', display_name='Small')
        Size.objects.create(name='L', display_name='Large')
        Color.objects.create(name='Blue', hex_code='#0000FF')

        ProductVariant.objects.create(
            product=self.product, size=self.size, color=self.color, stock=5
        )
        ProductVariant.objects.create(
            product=self.product, size=Size.objects.get(name='S'), color=self.color, stock=3
        )
        ProductVariant.objects.create(
            product=self.product, size=Size.objects.get(name='L'), color=Color.objects.get(name='Blue'), stock=7
        )

        self.assertEqual(self.product.total_stock, 15)

    def test_available_sizes_and_colors(self):
        Size.objects.create(name='S', display_name='Small')
        Size.objects.create(name='L', display_name='Large')
        Color.objects.create(name='Blue', hex_code='#0000FF')

        ProductVariant.objects.create(
            product=self.product, size=self.size, color=self.color, stock=5
        )
        ProductVariant.objects.create(
            product=self.product, size=Size.objects.get(name='S'), color=self.color, stock=3
        )
        ProductVariant.objects.create(
            product=self.product, size=Size.objects.get(name='L'), color=Color.objects.get(name='Blue'), stock=7
        )

        sizes = self.product.available_sizes
        colors = self.product.available_colors

        self.assertIn('M', sizes)
        self.assertIn('S', sizes)
        self.assertIn('L', sizes)
        self.assertIn('Red', colors)
        self.assertIn('Blue', colors)


class CartWithVariantsTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser',
            email='test@test.com',
            password='testpass123',
            first_name='Test',
            last_name='User'
        )
        self.category = Category.objects.create(name='Test Category')
        self.product = Product.objects.create(
            name='Test Product',
            description='Test description',
            price=Decimal('10.00'),
            stock=10,
            category=self.category,
            has_variants=True
        )
        self.size = Size.objects.create(name='M', display_name='Medium')
        self.color = Color.objects.create(name='Red', hex_code='#FF0000')
        self.variant = ProductVariant.objects.create(
            product=self.product,
            size=self.size,
            color=self.color,
            price=Decimal('12.00'),
            stock=5
        )
        self.cart = Cart.get_or_create_cart(self.user)

    def test_add_variant_to_cart(self):
        cart_item = CartItem.objects.create(
            cart=self.cart,
            product=self.product,
            variant=self.variant,
            quantity=2
        )
        self.assertEqual(cart_item.total_price, Decimal('24.00'))
        self.assertEqual(cart_item.size_name, 'M')
        self.assertEqual(cart_item.color_name, 'Red')

    def test_cart_unique_constraint(self):
        CartItem.objects.create(
            cart=self.cart,
            product=self.product,
            variant=self.variant,
            quantity=2
        )
        # Adding same variant again should fail due to unique constraint
        from django.db import IntegrityError
        with self.assertRaises(IntegrityError):
            CartItem.objects.create(
                cart=self.cart,
                product=self.product,
                variant=self.variant,
                quantity=3
            )

    def test_cart_without_variant(self):
        cart_item = CartItem.objects.create(
            cart=self.cart,
            product=self.product,
            quantity=1
        )
        self.assertEqual(cart_item.total_price, Decimal('10.00'))
        self.assertIsNone(cart_item.variant)


class ProductStockSyncTest(TestCase):
    """Product.stock must always mirror the stock of its active variants."""

    def setUp(self):
        self.category = Category.objects.create(name='Test Category')
        self.size = Size.objects.create(name='M', display_name='Medium')
        self.other_size = Size.objects.create(name='L', display_name='Large')
        self.color = Color.objects.create(name='Red', hex_code='#FF0000')
        self.product = Product.objects.create(
            name='Variant Product',
            description='Test description',
            price=Decimal('10.00'),
            category=self.category,
            has_variants=True
        )

    def make_variant(self, size=None, color=None, stock=0, is_active=True):
        return ProductVariant.objects.create(
            product=self.product,
            size=size or self.size,
            color=color or self.color,
            stock=stock,
            is_active=is_active
        )

    def db_stock(self):
        """Read the persisted product stock (signals update it on a separate instance)."""
        self.product.refresh_from_db()
        return self.product.stock

    def test_stock_updated_when_variant_created(self):
        self.make_variant(stock=5)
        self.assertEqual(self.db_stock(), 5)

    def test_stock_updated_when_variant_stock_changed(self):
        variant = self.make_variant(stock=5)
        variant.stock = 2
        variant.save()
        self.assertEqual(self.db_stock(), 2)

    def test_stock_updated_when_variant_deleted(self):
        variant = self.make_variant(stock=5)
        variant.delete()
        self.assertEqual(self.db_stock(), 0)

    def test_stock_accumulates_across_variants(self):
        self.make_variant(stock=5)
        self.make_variant(size=self.other_size, stock=7)
        self.assertEqual(self.db_stock(), 12)
        self.assertEqual(self.product.total_stock, 12)

    def test_inactive_variants_excluded(self):
        self.make_variant(stock=5)
        self.make_variant(size=self.other_size, stock=9, is_active=False)
        self.assertEqual(self.db_stock(), 5)
        self.assertEqual(self.product.total_stock, 5)

    def test_deactivating_variant_reduces_stock(self):
        variant = self.make_variant(stock=5)
        variant.is_active = False
        variant.save()
        self.assertEqual(self.db_stock(), 0)

    def test_moving_variant_to_other_product_resyncs_both(self):
        variant = self.make_variant(stock=5)
        other_product = Product.objects.create(
            name='Other Product',
            description='Test description',
            price=Decimal('20.00'),
            category=self.category,
            has_variants=True
        )
        variant.product = other_product
        variant.save()

        self.assertEqual(self.db_stock(), 0)
        other_product.refresh_from_db()
        self.assertEqual(other_product.stock, 5)

    def test_toggling_has_variants_resyncs_stock(self):
        self.make_variant(stock=6)
        self.product.refresh_from_db()

        self.product.has_variants = False
        self.product.save()
        self.assertEqual(self.db_stock(), 6)

        self.product.has_variants = True
        self.product.save()
        self.assertEqual(self.db_stock(), 6)

    def test_enabling_variants_recomputes_stale_stock(self):
        self.product.stock = 99
        self.product.save()
        self.make_variant(stock=4)
        self.assertEqual(self.db_stock(), 4)

    def test_non_variant_product_keeps_manual_stock(self):
        product = Product.objects.create(
            name='Simple Product',
            description='Test description',
            price=Decimal('10.00'),
            stock=4,
            category=self.category
        )
        product.refresh_from_db()
        self.assertEqual(product.stock, 4)
        self.assertEqual(product.total_stock, 4)

    def test_save_with_update_fields_persists_other_changes(self):
        variant = self.make_variant(stock=3)
        self.product.refresh_from_db()
        self.product.discount_price = Decimal('7.00')
        self.product.save(update_fields=['discount_price'])
        self.product.refresh_from_db()
        self.assertEqual(self.product.discount_price, Decimal('7.00'))
        self.assertEqual(self.product.stock, 3)


class ProductSerializerTest(TestCase):
    def test_product_serializer_includes_variants(self):
        from products.serializers import ProductSerializer
        category = Category.objects.create(name='Test Category')
        product = Product.objects.create(
            name='Test Product',
            description='Test description',
            price=Decimal('10.00'),
            stock=10,
            category=category,
            has_variants=True
        )
        size = Size.objects.create(name='M', display_name='Medium')
        color = Color.objects.create(name='Red', hex_code='#FF0000')
        ProductVariant.objects.create(
            product=product, size=size, color=color, stock=5
        )

        serializer = ProductSerializer(product)
        data = serializer.data

        self.assertTrue(data['has_variants'])
        self.assertEqual(len(data['variants']), 1)
        self.assertEqual(data['variants'][0]['size']['name'], 'M')
        self.assertEqual(data['variants'][0]['color']['name'], 'Red')
        self.assertIn('M', data['available_sizes'])
        self.assertIn('Red', data['available_colors'])