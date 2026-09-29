from django.core.management.base import BaseCommand
from django.core.files import File
from products.models import Category, Product, ProductImage, Size, Color, ProductVariant
import os
from pathlib import Path

class Command(BaseCommand):
    help = 'Set up test data with products and images, including size/color variants'

    def handle(self, *args, **options):
        self.stdout.write('Setting up test data...')
        
        # Create default sizes and colors
        sizes_data = [
            ('XS', 'Extra Small', 1),
            ('S', 'Small', 2),
            ('M', 'Medium', 3),
            ('L', 'Large', 4),
            ('XL', 'X-Large', 5),
            ('XXL', 'XX-Large', 6),
            ('XXXL', 'XXX-Large', 7),
            ('4XL', '4X-Large', 8),
            ('5XL', '5X-Large', 9),
            ('6', '6', 10),
            ('7', '7', 11),
            ('8', '8', 12),
            ('9', '9', 13),
            ('10', '10', 14),
            ('11', '11', 15),
            ('12', '12', 16),
            ('13', '13', 17),
            ('14', '14', 18),
            ('15', '15', 19),
            ('16', '16', 20),
            ('17', '17', 21),
            ('18', '18', 22),
            ('19', '19', 23),
            ('20', '20', 24),
            ('21', '21', 25),
            ('22', '22', 26),
            ('23', '23', 27),
            ('24', '24', 28),
            ('25', '25', 29),
            ('OS', 'One Size', 30),
            ('FM', 'Free Size', 31),
        ]
        for code, display, order in sizes_data:
            Size.objects.get_or_create(name=code, defaults={'display_name': display, 'sort_order': order})
        
        colors_data = [
            ('Black', '#000000'),
            ('White', '#FFFFFF'),
            ('Red', '#FF0000'),
            ('Blue', '#0000FF'),
            ('Green', '#008000'),
            ('Navy Blue', '#000080'),
            ('Gray', '#808080'),
        ]
        for name, hex_code in colors_data:
            Color.objects.get_or_create(name=name, defaults={'hex_code': hex_code})
        
        self.stdout.write('Created default sizes and colors')
        
        # Create categories
        electronics, created = Category.objects.get_or_create(
            name='Electronics',
            defaults={'slug': 'electronics'}
        )
        if created:
            self.stdout.write(f'Created category: {electronics.name}')
        
        clothing, created = Category.objects.get_or_create(
            name='Clothing',
            defaults={'slug': 'clothing'}
        )
        if created:
            self.stdout.write(f'Created category: {clothing.name}')
        
        # Create products
        products_data = [
            {
                'name': 'Wireless Headphones',
                'description': 'High-quality wireless headphones with noise cancellation and 30-hour battery life.',
                'price': 199.99,
                'stock': 15,
                'category': electronics,
                'is_featured': True,
                'image_file': '1.jpg'
            },
            {
                'name': 'Smart Watch',
                'description': 'Feature-rich smartwatch with health tracking, GPS, and water resistance.',
                'price': 299.99,
                'stock': 8,
                'category': electronics,
                'is_featured': True,
                'image_file': 'SnapInsta.to_517195513_18114381490497623_4672993102228973079_n.jpg'
            },
            {
                'name': 'Cotton T-Shirt',
                'description': 'Comfortable 100% cotton t-shirt available in multiple colors and sizes.',
                'price': 24.99,
                'stock': 50,
                'category': clothing,
                'is_featured': False,
                'image_file': 'SnapInsta.to_518212817_18114381505497623_2927998923866283814_n.jpg',
                'has_variants': True
            },
            {
                'name': 'Yoga Mat',
                'description': 'Non-slip yoga mat perfect for home workouts and studio sessions.',
                'price': 39.99,
                'stock': 30,
                'category': clothing,
                'is_featured': True,
                'image_file': 'SnapInsta.to_517338646_18114381514497623_5110580454683062765_n.jpg'
            }
        ]
        
        for product_data in products_data:
            product, created = Product.objects.get_or_create(
                name=product_data['name'],
                defaults={
                    'description': product_data['description'],
                    'price': product_data['price'],
                    'stock': product_data['stock'],
                    'category': product_data['category'],
                    'is_featured': product_data['is_featured'],
                    'is_new_arrival': True,
                    'has_variants': product_data.get('has_variants', False)
                }
            )
            
            if created:
                self.stdout.write(f'Created product: {product.name}')
                
                # Add image to product
                image_path = Path(__file__).parent.parent.parent.parent / 'media' / 'products' / product_data['image_file']
                if image_path.exists():
                    with open(image_path, 'rb') as img_file:
                        product_image = ProductImage.objects.create(
                            product=product,
                            image=File(img_file, name=product_data['image_file']),
                            is_primary=True
                        )
                    self.stdout.write(f'Added image to {product.name}: {product_data["image_file"]}')
                else:
                    self.stdout.write(f'Warning: Image file not found: {image_path}')
                
                # Create variants for products with has_variants=True
                if product.has_variants:
                    self._create_sample_variants(product)
        
        self.stdout.write(self.style.SUCCESS('Test data setup completed!'))
    
    def _create_sample_variants(self, product):
        """Create sample variants for a product"""
        sizes = Size.objects.all()
        colors = Color.objects.all()
        
        # For T-shirt: create variants for all sizes and a few colors
        if 'T-Shirt' in product.name:
            selected_colors = ['Black', 'White', 'Red', 'Navy Blue']
            for size in sizes:
                for color_name in selected_colors:
                    color = Color.objects.get(name=color_name)
                    ProductVariant.objects.create(
                        product=product,
                        size=size,
                        color=color,
                        price=product.price,
                        stock=10,
                        sku=f"{product.name[:3].upper()}-{size.name}-{color_name[:3].upper()}"
                    )
            self.stdout.write(f'Created variants for {product.name}')
        else:
            # For other variant products, create a few sample variants
            for size in [sizes.first(), sizes.last()]:
                for color in [colors.first(), colors.last()]:
                    ProductVariant.objects.create(
                        product=product,
                        size=size,
                        color=color,
                        price=product.price,
                        stock=5,
                        sku=f"{product.name[:3].upper()}-{size.name}-{color.name[:3].upper()}"
                    )
            self.stdout.write(f'Created variants for {product.name}') 