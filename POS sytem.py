# backend/app.py
from flask import Flask, request, jsonify, send_from_directory
from flask_sqlalchemy import SQLAlchemy
# Conditional SocketIO import: on Vercel we use a no-op fallback
from datetime import datetime, timedelta
import json
import hashlib
import qrcode
import base64
import io
import uuid
import threading
import time
from sqlalchemy import func, and_
from sqlalchemy.dialects.postgresql import JSONB
import os
from dotenv import load_dotenv
import logging

load_dotenv()

# Disable default static serving to prevent exposing source code

# Fix for Render/Heroku postgres URLs
database_url = os.getenv('DATABASE_URL', 'postgresql://user:password@localhost/pos_db')
if database_url and database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1)

app.config['SQLALCHEMY_DATABASE_URI'] = database_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'your-secret-key-here')

app = Flask(__name__, static_folder=None)

# Configure SocketIO: use a dummy implementation on Vercel (serverless)
if os.environ.get('VERCEL'):
    class _DummySocketIO:
        def emit(self, *args, **kwargs):
            return None
        def on(self, event):
            def decorator(f):
                return f
            return decorator
    socketio = _DummySocketIO()
    def emit(*args, **kwargs):
        return None
else:
    from flask_socketio import SocketIO, emit
    async_mode = 'threading'
    socketio = SocketIO(app, cors_allowed_origins="*", async_mode=async_mode)

db = SQLAlchemy(app)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Serve Frontend
@app.route('/')
def index():
    return send_from_directory(os.path.dirname(os.path.abspath(__file__)), 'index.html')

# Database Models
class Product(db.Model):
    __tablename__ = 'products'
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = db.Column(db.String(200), nullable=False)
    price = db.Column(db.Float, nullable=False)
    category = db.Column(db.String(100))
    sku = db.Column(db.String(100), unique=True)
    description = db.Column(db.Text)
    inventory_count = db.Column(db.Integer, default=0)
    is_available = db.Column(db.Boolean, default=True)
    image_url = db.Column(db.String(500))
    online_sync = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class Order(db.Model):
    __tablename__ = 'orders'
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    order_number = db.Column(db.String(50), unique=True, nullable=False)
    total_amount = db.Column(db.Float, nullable=False)
    tax_amount = db.Column(db.Float, default=0.0)
    discount_amount = db.Column(db.Float, default=0.0)
    status = db.Column(db.String(50), default='pending')  # pending, completed, cancelled, refunded
    payment_method = db.Column(db.String(50))  # cash, card, e-wallet
    payment_status = db.Column(db.String(50), default='pending')  # pending, completed, failed
    customer_name = db.Column(db.String(200))
    customer_email = db.Column(db.String(200))
    customer_phone = db.Column(db.String(50))
    is_online = db.Column(db.Boolean, default=False)
    device_id = db.Column(db.String(100))  # For offline mode tracking
    sync_status = db.Column(db.String(20), default='pending')  # pending, synced, failed
    barcode_data = db.Column(db.Text)  # Stores QR code data
    barcode_image = db.Column(db.Text)  # Base64 encoded QR image
    metadata = db.Column(JSONB)  # Store additional data like items, timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class OrderItem(db.Model):
    __tablename__ = 'order_items'
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    order_id = db.Column(db.String(36), db.ForeignKey('orders.id'), nullable=False)
    product_id = db.Column(db.String(36), db.ForeignKey('products.id'), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    unit_price = db.Column(db.Float, nullable=False)
    total_price = db.Column(db.Float, nullable=False)
    product_name = db.Column(db.String(200))  # Cache product name at time of order
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class SyncQueue(db.Model):
    __tablename__ = 'sync_queue'
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    entity_type = db.Column(db.String(50), nullable=False)  # order, product, inventory
    entity_id = db.Column(db.String(36), nullable=False)
    operation = db.Column(db.String(20), nullable=False)  # create, update, delete
    data = db.Column(JSONB, nullable=False)  # The actual data to sync
    device_id = db.Column(db.String(100))
    status = db.Column(db.String(20), default='pending')  # pending, processing, completed, failed
    retry_count = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class Device(db.Model):
    __tablename__ = 'devices'
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    device_id = db.Column(db.String(100), unique=True, nullable=False)
    name = db.Column(db.String(200))
    location = db.Column(db.String(200))
    last_seen = db.Column(db.DateTime, default=datetime.utcnow)
    is_online = db.Column(db.Boolean, default=False)
    ip_address = db.Column(db.String(50))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

# Barcode Generator
class BarcodeGenerator:
    @staticmethod
    def generate_qr_code(order_data):
        """Generate QR code for an order"""
        try:
            # Create order payload for QR code
            qr_payload = {
                'order_id': order_data.get('id'),
                'order_number': order_data.get('order_number'),
                'total': order_data.get('total_amount'),
                'timestamp': order_data.get('created_at'),
                'items': order_data.get('items', []),
                'customer_id': order_data.get('customer_id'),
                'verification_hash': hashlib.sha256(
                    f"{order_data.get('id')}{order_data.get('created_at')}{os.getenv('QR_SECRET', 'default-secret')}".encode()
                ).hexdigest()[:16]
            }
            
            # Convert to JSON string
            qr_string = json.dumps(qr_payload, default=str)
            
            # Generate QR code
            qr = qrcode.QRCode(
                version=1,
                error_correction=qrcode.constants.ERROR_CORRECT_L,
                box_size=10,
                border=4,
            )
            qr.add_data(qr_string)
            qr.make(fit=True)
            
            # Create image
            img = qr.make_image(fill_color="black", back_color="white")
            
            # Convert to base64
            buffered = io.BytesIO()
            img.save(buffered, format="PNG")
            img_str = base64.b64encode(buffered.getvalue()).decode()
            
            return {
                'qr_data': qr_string,
                'qr_image': img_str,
                'qr_type': 'QR_CODE'
            }
        except Exception as e:
            logger.error(f"Error generating QR code: {str(e)}")
            return None

    @staticmethod
    def generate_code128(order_number):
        """Generate Code128 barcode"""
        # This would use a barcode library like python-barcode
        # For now, return a placeholder
        return {
            'barcode_data': order_number,
            'barcode_type': 'CODE128'
        }

# Sync Engine
class SyncEngine:
    def __init__(self):
        self.sync_lock = threading.Lock()
        self.is_syncing = False
    
    def queue_for_sync(self, entity_type, entity_id, operation, data, device_id=None):
        """Add item to sync queue"""
        try:
            sync_item = SyncQueue(
                entity_type=entity_type,
                entity_id=entity_id,
                operation=operation,
                data=data,
                device_id=device_id,
                status='pending'
            )
            db.session.add(sync_item)
            db.session.commit()
            logger.info(f"Queued {operation} for {entity_type} {entity_id}")
            return True
        except Exception as e:
            logger.error(f"Error queuing sync: {str(e)}")
            db.session.rollback()
            return False
    
    def process_sync_queue(self):
        """Process pending sync items"""
        if self.is_syncing:
            return
        
        with self.sync_lock:
            self.is_syncing = True
            try:
                pending_items = SyncQueue.query.filter_by(status='pending').order_by('created_at').limit(50).all()
                
                for item in pending_items:
                    try:
                        item.status = 'processing'
                        db.session.commit()
                        
                        # Process based on entity type
                        if item.entity_type == 'order':
                            self._sync_order(item)
                        elif item.entity_type == 'product':
                            self._sync_product(item)
                        elif item.entity_type == 'inventory':
                            self._sync_inventory(item)
                        
                        item.status = 'completed'
                        item.updated_at = datetime.utcnow()
                        db.session.commit()
                        
                        logger.info(f"Successfully synced {item.entity_type} {item.entity_id}")
                        
                    except Exception as e:
                        logger.error(f"Error syncing {item.entity_type} {item.entity_id}: {str(e)}")
                        item.status = 'failed'
                        item.retry_count += 1
                        db.session.commit()
                
                # Clean up old completed items
                cutoff = datetime.utcnow() - timedelta(days=7)
                SyncQueue.query.filter(
                    and_(
                        SyncQueue.status.in_(['completed', 'failed']),
                        SyncQueue.updated_at < cutoff
                    )
                ).delete(synchronize_session=False)
                db.session.commit()
                
            except Exception as e:
                logger.error(f"Error in sync process: {str(e)}")
            finally:
                self.is_syncing = False
    
    def _sync_order(self, sync_item):
        """Sync order to cloud"""
        order_data = sync_item.data
        
        # Check if order already exists
        existing_order = Order.query.filter_by(id=order_data.get('id')).first()
        
        if sync_item.operation == 'create' and not existing_order:
            # Create new order
            order = Order(
                id=order_data.get('id'),
                order_number=order_data.get('order_number'),
                total_amount=order_data.get('total_amount'),
                tax_amount=order_data.get('tax_amount', 0),
                discount_amount=order_data.get('discount_amount', 0),
                status=order_data.get('status', 'completed'),
                payment_method=order_data.get('payment_method'),
                payment_status=order_data.get('payment_status', 'completed'),
                customer_name=order_data.get('customer_name'),
                customer_email=order_data.get('customer_email'),
                customer_phone=order_data.get('customer_phone'),
                is_online=False,  # This was created offline
                device_id=sync_item.device_id,
                sync_status='synced',
                barcode_data=order_data.get('barcode_data'),
                barcode_image=order_data.get('barcode_image'),
                metadata=order_data.get('metadata', {}),
                created_at=datetime.fromisoformat(order_data.get('created_at')) if order_data.get('created_at') else datetime.utcnow()
            )
            db.session.add(order)
            
            # Add order items
            for item_data in order_data.get('items', []):
                order_item = OrderItem(
                    id=str(uuid.uuid4()),
                    order_id=order_data.get('id'),
                    product_id=item_data.get('product_id'),
                    quantity=item_data.get('quantity'),
                    unit_price=item_data.get('unit_price'),
                    total_price=item_data.get('total_price'),
                    product_name=item_data.get('product_name')
                )
                db.session.add(order_item)
            
            # Update inventory if needed
            if order_data.get('status') == 'completed':
                self._update_inventory_from_order(order_data.get('items', []))
    
    def _sync_product(self, sync_item):
        """Sync product updates"""
        product_data = sync_item.data
        existing_product = Product.query.filter_by(id=product_data.get('id')).first()
        
        if sync_item.operation == 'create' and not existing_product:
            product = Product(
                id=product_data.get('id'),
                name=product_data.get('name'),
                price=product_data.get('price'),
                category=product_data.get('category'),
                sku=product_data.get('sku'),
                description=product_data.get('description'),
                inventory_count=product_data.get('inventory_count', 0),
                is_available=product_data.get('is_available', True),
                image_url=product_data.get('image_url')
            )
            db.session.add(product)
        elif sync_item.operation == 'update' and existing_product:
            for key, value in product_data.items():
                if key != 'id' and hasattr(existing_product, key):
                    setattr(existing_product, key, value)
            existing_product.updated_at = datetime.utcnow()
    
    def _sync_inventory(self, sync_item):
        """Sync inventory changes"""
        inventory_data = sync_item.data
        product = Product.query.filter_by(id=inventory_data.get('product_id')).first()
        
        if product:
            if sync_item.operation == 'update':
                product.inventory_count = inventory_data.get('new_count', product.inventory_count)
                product.updated_at = datetime.utcnow()
    
    def _update_inventory_from_order(self, items):
        """Update inventory counts from order items"""
        for item in items:
            product = Product.query.filter_by(id=item.get('product_id')).first()
            if product and product.inventory_count is not None:
                product.inventory_count -= item.get('quantity', 0)
                product.updated_at = datetime.utcnow()
    
    def pull_updates(self, device_id, last_sync):
        """Pull updates from cloud for a device"""
        updates = {
            'products': [],
            'orders': [],
            'inventory': []
        }
        
        # Get updated products since last sync
        updated_products = Product.query.filter(
            Product.updated_at > last_sync,
            Product.online_sync == True
        ).all()
        
        for product in updated_products:
            updates['products'].append({
                'id': product.id,
                'name': product.name,
                'price': product.price,
                'category': product.category,
                'sku': product.sku,
                'inventory_count': product.inventory_count,
                'is_available': product.is_available,
                'operation': 'update'  # or 'create' based on device's local state
            })
        
        # Get new orders that might affect inventory
        new_orders = Order.query.filter(
            Order.created_at > last_sync,
            Order.device_id != device_id,  # Orders from other devices
            Order.status == 'completed'
        ).limit(100).all()
        
        for order in new_orders:
            updates['orders'].append({
                'id': order.id,
                'order_number': order.order_number,
                'status': order.status
            })
        
        return updates

# Initialize sync engine
sync_engine = SyncEngine()

# API Routes
@app.route('/api/health', methods=['GET'])
def health_check():
    return jsonify({'status': 'healthy', 'timestamp': datetime.utcnow().isoformat()})

@app.route('/api/products', methods=['GET'])
def get_products():
    """Get all products with optional filtering"""
    category = request.args.get('category')
    available_only = request.args.get('available_only', 'false').lower() == 'true'
    
    query = Product.query
    
    if category:
        query = query.filter_by(category=category)
    
    if available_only:
        query = query.filter_by(is_available=True)
    
    products = query.order_by(Product.name).all()
    
    return jsonify([{
        'id': p.id,
        'name': p.name,
        'price': p.price,
        'category': p.category,
        'sku': p.sku,
        'inventory_count': p.inventory_count,
        'is_available': p.is_available,
        'image_url': p.image_url
    } for p in products])

@app.route('/api/products/<product_id>/inventory', methods=['PUT'])
def update_inventory(product_id):
    """Update product inventory"""
    data = request.get_json()
    new_count = data.get('inventory_count')
    
    product = Product.query.get_or_404(product_id)
    old_count = product.inventory_count
    product.inventory_count = new_count
    
    # Queue for sync if changed
    if old_count != new_count:
        sync_engine.queue_for_sync(
            entity_type='inventory',
            entity_id=product_id,
            operation='update',
            data={
                'product_id': product_id,
                'old_count': old_count,
                'new_count': new_count,
                'timestamp': datetime.utcnow().isoformat()
            }
        )
    
    db.session.commit()
    return jsonify({'success': True, 'inventory_count': new_count})

@app.route('/api/orders', methods=['POST'])
def create_order():
    """Create a new order (works online or offline)"""
    data = request.get_json()
    device_id = data.get('device_id')
    is_offline = data.get('is_offline', False)
    
    # Generate order number
    order_number = f"ORD-{datetime.utcnow().strftime('%Y%m%d')}-{str(uuid.uuid4())[:8].upper()}"
    
    # Calculate totals
    items = data.get('items', [])
    subtotal = sum(item['quantity'] * item['unit_price'] for item in items)
    tax = subtotal * 0.1  # 10% tax for example
    total = subtotal + tax - data.get('discount_amount', 0)
    
    # Create order
    order = Order(
        order_number=order_number,
        total_amount=total,
        tax_amount=tax,
        discount_amount=data.get('discount_amount', 0),
        status='pending',
        payment_method=data.get('payment_method'),
        payment_status='pending',
        customer_name=data.get('customer_name'),
        customer_email=data.get('customer_email'),
        customer_phone=data.get('customer_phone'),
        is_online=not is_offline,
        device_id=device_id,
        sync_status='pending' if is_offline else 'synced',
        metadata={
            'items': items,
            'notes': data.get('notes'),
            'source': 'offline' if is_offline else 'online'
        }
    )
    
    db.session.add(order)
    db.session.flush()  # Get the order ID
    
    # Create order items
    order_items = []
    for item in items:
        order_item = OrderItem(
            order_id=order.id,
            product_id=item['product_id'],
            quantity=item['quantity'],
            unit_price=item['unit_price'],
            total_price=item['quantity'] * item['unit_price'],
            product_name=item.get('product_name')
        )
        order_items.append(order_item)
        db.session.add(order_item)
    
    db.session.commit()
    
    # Generate barcode
    order_data = {
        'id': order.id,
        'order_number': order.order_number,
        'total_amount': total,
        'created_at': order.created_at.isoformat(),
        'items': items,
        'customer_id': data.get('customer_id')
    }
    
    barcode_result = BarcodeGenerator.generate_qr_code(order_data)
    
    if barcode_result:
        order.barcode_data = barcode_result['qr_data']
        order.barcode_image = barcode_result['qr_image']
        db.session.commit()
    
    # If offline, queue for sync
    if is_offline:
        sync_engine.queue_for_sync(
            entity_type='order',
            entity_id=order.id,
            operation='create',
            data={
                'id': order.id,
                'order_number': order.order_number,
                'total_amount': total,
                'tax_amount': tax,
                'discount_amount': data.get('discount_amount', 0),
                'status': 'pending',
                'payment_method': data.get('payment_method'),
                'payment_status': 'pending',
                'customer_name': data.get('customer_name'),
                'customer_email': data.get('customer_email'),
                'customer_phone': data.get('customer_phone'),
                'items': items,
                'barcode_data': barcode_result['qr_data'] if barcode_result else None,
                'barcode_image': barcode_result['qr_image'] if barcode_result else None,
                'metadata': order.metadata,
                'created_at': order.created_at.isoformat()
            },
            device_id=device_id
        )
    
    # Emit real-time update
    socketio.emit('order_created', {
        'order_id': order.id,
        'order_number': order_number,
        'status': 'pending',
        'is_offline': is_offline
    })
    
    return jsonify({
        'success': True,
        'order_id': order.id,
        'order_number': order_number,
        'total_amount': total,
        'barcode': barcode_result,
        'sync_required': is_offline
    })

@app.route('/api/orders/<order_id>/complete', methods=['POST'])
def complete_order(order_id):
    """Complete an order and generate final barcode"""
    order = Order.query.get_or_404(order_id)
    data = request.get_json()
    
    # Update order status
    order.status = 'completed'
    order.payment_status = data.get('payment_status', 'completed')
    order.payment_method = data.get('payment_method', order.payment_method)
    order.updated_at = datetime.utcnow()
    
    # Generate final barcode if not already generated
    if not order.barcode_data:
        order_data = {
            'id': order.id,
            'order_number': order.order_number,
            'total_amount': order.total_amount,
            'created_at': order.created_at.isoformat(),
            'items': [{
                'product_id': item.product_id,
                'product_name': item.product_name,
                'quantity': item.quantity,
                'unit_price': item.unit_price
            } for item in order.order_items],
            'customer_id': None
        }
        
        barcode_result = BarcodeGenerator.generate_qr_code(order_data)
        if barcode_result:
            order.barcode_data = barcode_result['qr_data']
            order.barcode_image = barcode_result['qr_image']
    
    # Update inventory if needed
    if order.status == 'completed':
        for item in order.order_items:
            product = Product.query.get(item.product_id)
            if product and product.inventory_count is not None:
                product.inventory_count -= item.quantity
                product.updated_at = datetime.utcnow()
                
                # Queue inventory sync
                sync_engine.queue_for_sync(
                    entity_type='inventory',
                    entity_id=product.id,
                    operation='update',
                    data={
                        'product_id': product.id,
                        'new_count': product.inventory_count,
                        'timestamp': datetime.utcnow().isoformat()
                    },
                    device_id=order.device_id
                )
    
    # Update sync status if this was an offline order
    if not order.is_online and order.sync_status == 'pending':
        order.sync_status = 'queued'
        sync_engine.queue_for_sync(
            entity_type='order',
            entity_id=order.id,
            operation='update',
            data={
                'id': order.id,
                'status': 'completed',
                'payment_status': order.payment_status,
                'payment_method': order.payment_method,
                'barcode_data': order.barcode_data,
                'barcode_image': order.barcode_image,
                'updated_at': order.updated_at.isoformat()
            },
            device_id=order.device_id
        )
    
    db.session.commit()
    
    return jsonify({
        'success': True,
        'order_id': order.id,
        'status': 'completed',
        'barcode': {
            'data': order.barcode_data,
            'image': order.barcode_image
        }
    })

@app.route('/api/orders/<order_id>/scan', methods=['POST'])
def scan_order_barcode(order_id):
    """Scan order barcode for verification"""
    order = Order.query.get_or_404(order_id)
    
    # Check if barcode is valid
    scan_data = request.get_json().get('scan_data')
    
    # Simple validation - in production, verify against stored hash
    is_valid = order.barcode_data and order.barcode_data == scan_data
    
    return jsonify({
        'valid': is_valid,
        'order': {
            'id': order.id,
            'order_number': order.order_number,
            'status': order.status,
            'total_amount': order.total_amount,
            'customer_name': order.customer_name,
            'items': [{
                'product_name': item.product_name,
                'quantity': item.quantity,
                'unit_price': item.unit_price
            } for item in order.order_items],
            'created_at': order.created_at.isoformat()
        }
    })

@app.route('/api/sync/pull', methods=['POST'])
def pull_updates():
    """Pull updates from cloud for offline devices"""
    data = request.get_json()
    device_id = data.get('device_id')
    last_sync_str = data.get('last_sync')
    
    try:
        last_sync = datetime.fromisoformat(last_sync_str)
    except:
        last_sync = datetime.utcnow() - timedelta(hours=24)
    
    updates = sync_engine.pull_updates(device_id, last_sync)
    
    return jsonify({
        'success': True,
        'updates': updates,
        'timestamp': datetime.utcnow().isoformat()
    })

@app.route('/api/sync/push', methods=['POST'])
def push_updates():
    """Push updates from offline device"""
    data = request.get_json()
    device_id = data.get('device_id')
    updates = data.get('updates', {})
    
    try:
        # Process each update
        for order_data in updates.get('orders', []):
            sync_engine.queue_for_sync(
                entity_type='order',
                entity_id=order_data.get('id'),
                operation='create',
                data=order_data,
                device_id=device_id
            )
        
        for product_data in updates.get('products', []):
            sync_engine.queue_for_sync(
                entity_type='product',
                entity_id=product_data.get('id'),
                operation=product_data.get('operation', 'update'),
                data=product_data,
                device_id=device_id
            )
        
        # Process sync queue immediately
        sync_engine.process_sync_queue()
        
        return jsonify({
            'success': True,
            'message': f"Queued {len(updates.get('orders', []))} orders and {len(updates.get('products', []))} products for sync"
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/sync/process', methods=['POST'])
def process_sync():
    """Manually trigger sync processing"""
    sync_engine.process_sync_queue()
    return jsonify({'success': True, 'message': 'Sync processing completed'})

@app.route('/api/devices/register', methods=['POST'])
def register_device():
    """Register a new device for offline operation"""
    data = request.get_json()
    device_id = data.get('device_id')
    name = data.get('name')
    location = data.get('location')
    
    device = Device.query.filter_by(device_id=device_id).first()
    
    if not device:
        device = Device(
            device_id=device_id,
            name=name,
            location=location,
            is_online=True,
            last_seen=datetime.utcnow(),
            ip_address=request.remote_addr
        )
        db.session.add(device)
    else:
        device.is_online = True
        device.last_seen = datetime.utcnow()
        device.ip_address = request.remote_addr
    
    db.session.commit()
    
    return jsonify({
        'success': True,
        'device_id': device.device_id,
        'registered': True
    })

@app.route('/api/dashboard/stats', methods=['GET'])
def get_dashboard_stats():
    """Get dashboard statistics"""
    # Today's sales
    today = datetime.utcnow().date()
    today_start = datetime.combine(today, datetime.min.time())
    
    today_sales = db.session.query(
        func.sum(Order.total_amount).label('total'),
        func.count(Order.id).label('count')
    ).filter(
        Order.created_at >= today_start,
        Order.status == 'completed'
    ).first()
    
    # Offline vs Online sales
    sales_breakdown = db.session.query(
        Order.is_online,
        func.count(Order.id).label('count'),
        func.sum(Order.total_amount).label('total')
    ).filter(
        Order.created_at >= today_start,
        Order.status == 'completed'
    ).group_by(Order.is_online).all()
    
    # Recent orders
    recent_orders = Order.query.filter(
        Order.status == 'completed'
    ).order_by(Order.created_at.desc()).limit(10).all()
    
    return jsonify({
        'today': {
            'total_sales': float(today_sales.total or 0),
            'order_count': today_sales.count or 0
        },
        'breakdown': [
            {
                'type': 'online' if breakdown.is_online else 'offline',
                'count': breakdown.count,
                'total': float(breakdown.total or 0)
            }
            for breakdown in sales_breakdown
        ],
        'recent_orders': [
            {
                'order_number': order.order_number,
                'total': order.total_amount,
                'customer': order.customer_name,
                'status': order.status,
                'created_at': order.created_at.isoformat()
            }
            for order in recent_orders
        ]
    })

# WebSocket -> HTTP fallbacks
@app.route('/api/ws/connect', methods=['POST'])
def ws_connect():
    logger.info('Client connected (HTTP fallback)')
    return jsonify({'connection_status': {'status': 'connected'}})


@app.route('/api/ws/disconnect', methods=['POST'])
def ws_disconnect():
    logger.info('Client disconnected (HTTP fallback)')
    return jsonify({'success': True})


@app.route('/api/device/heartbeat', methods=['POST'])
def http_device_heartbeat():
    data = request.get_json() or {}
    device_id = data.get('device_id')
    if device_id:
        device = Device.query.filter_by(device_id=device_id).first()
        if device:
            device.is_online = True
            device.last_seen = datetime.utcnow()
            db.session.commit()
            return jsonify({'success': True, 'timestamp': datetime.utcnow().isoformat()})
    return jsonify({'success': False}), 400


@app.route('/api/sync/status', methods=['POST'])
def http_sync_status():
    data = request.get_json() or {}
    device_id = data.get('device_id')
    pending_count = SyncQueue.query.filter_by(
        device_id=device_id,
        status='pending'
    ).count()
    return jsonify({
        'pending_items': pending_count,
        'timestamp': datetime.utcnow().isoformat()
    })

# Background sync task
def background_sync_task():
    """Background task to process sync queue periodically"""
    while True:
        try:
            sync_engine.process_sync_queue()
        except Exception as e:
            logger.error(f"Background sync error: {str(e)}")
        time.sleep(60)  # Run every minute

# Start background sync thread
# On Vercel, we use Cron jobs instead of background threads
if not os.environ.get('VERCEL'):
    sync_thread = threading.Thread(target=background_sync_task, daemon=True)
    sync_thread.start()

# Initialize database
# Avoid running `create_all()` on Vercel serverless (cold starts can fail without DB config).
if not os.environ.get('VERCEL'):
    with app.app_context():
        db.create_all()
        logger.info("Database tables created")
else:
    logger.info("Skipping db.create_all() on Vercel serverless; run migrations manually if needed")

if __name__ == '__main__':
    port = int(os.getenv('PORT', 5000))
    socketio.run(app, debug=False, host='0.0.0.0', port=port)