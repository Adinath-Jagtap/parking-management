import os
import logging
from datetime import datetime, timedelta
import math
from functools import wraps
from werkzeug.utils import secure_filename
from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify, send_file
from flask_wtf import FlaskForm
from flask_wtf.csrf import CSRFProtect
from wtforms import StringField, PasswordField, SelectField, FloatField, IntegerField, BooleanField
from wtforms.validators import DataRequired, Email, Length, EqualTo, ValidationError, NumberRange
from flask_bcrypt import Bcrypt
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from pymongo import MongoClient, ASCENDING, DESCENDING, ReturnDocument
from bson.objectid import ObjectId
from dotenv import load_dotenv
import secrets
import base64
from io import BytesIO
import json
import qrcode
import re
import hmac
import hashlib
import razorpay
from apscheduler.schedulers.background import BackgroundScheduler
from zoneinfo import ZoneInfo
IST = ZoneInfo('Asia/Kolkata')

def now_ist():
    """Return current IST time as a naive datetime.
    
    PyMongo auto-converts timezone-aware datetimes to UTC before storing.
    By stripping tzinfo, the literal IST value is stored as-is in MongoDB.
    """
    return datetime.now(IST).replace(tzinfo=None)

# Load environment variables
load_dotenv()

# Initialize Flask app
app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', secrets.token_hex(32))
app.config['MONGO_URI'] = os.getenv('MONGO_URI', 'mongodb://localhost:27017/parking_management')
app.config['UPLOAD_FOLDER'] = 'static/uploads'
app.config['MAX_CONTENT_LENGTH'] = 5 * 1024 * 1024  # 5MB max file size
app.config['RAZORPAY_KEY_ID'] = os.getenv('RAZORPAY_KEY_ID', '')
app.config['RAZORPAY_KEY_SECRET'] = os.getenv('RAZORPAY_KEY_SECRET', '')

# Security headers
@app.after_request
def set_security_headers(response):
    response.headers['X-Frame-Options'] = 'SAMEORIGIN'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    response.headers['Content-Security-Policy'] = (
        "default-src 'self' https://cdn.jsdelivr.net https://cdnjs.cloudflare.com https://unpkg.com "
        "https://checkout.razorpay.com https://prod.spline.design https://*.spline.design "
        "https://www.gstatic.com 'unsafe-inline' 'unsafe-eval' 'wasm-unsafe-eval'; "
        "script-src 'self' https://cdn.jsdelivr.net https://cdnjs.cloudflare.com https://unpkg.com "
        "https://checkout.razorpay.com https://www.gstatic.com 'unsafe-inline' 'unsafe-eval' 'wasm-unsafe-eval'; "
        "media-src 'self' blob:; "
        "img-src 'self' data: blob: https://*.spline.design https://www.gstatic.com; "
        "worker-src 'self' blob: https://www.gstatic.com; "
        "frame-src 'self' https://api.razorpay.com https://checkout.razorpay.com; "
        "connect-src 'self' https://api.razorpay.com https://lumberjack.razorpay.com "
        "https://prod.spline.design https://*.spline.design https://www.gstatic.com;"
    )
    return response

# Initialize extensions
csrf = CSRFProtect(app)
bcrypt = Bcrypt(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'
limiter = Limiter(app=app, key_func=get_remote_address, default_limits=["2000 per day", "500 per hour"])
razorpay_client = razorpay.Client(auth=(app.config['RAZORPAY_KEY_ID'], app.config['RAZORPAY_KEY_SECRET'])) if app.config['RAZORPAY_KEY_ID'] else None

# APScheduler for background jobs (no-show handling)
scheduler = BackgroundScheduler(daemon=True)

# Logging configuration
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# MongoDB connection
try:
    client = MongoClient(
        app.config['MONGO_URI'],
        serverSelectionTimeoutMS=5000,
        connectTimeoutMS=10000
    )
    # Test connection
    client.admin.command('ping')
    db = client.parking_management
    logger.info("MongoDB connected successfully")
except Exception as e:
    logger.error(f"MongoDB connection failed: {str(e)}")
    logger.error("Please check your MONGO_URI in .env file")
    raise Exception("Database connection failed. Check MongoDB Atlas cluster or use local MongoDB.")

# Collections
users_collection = db.users
parking_lots_collection = db.parking_lots
parking_slots_collection = db.parking_slots
vehicles_collection = db.vehicles
bookings_collection = db.bookings
invoices_collection = db.invoices
admin_verification_collection = db.admin_verification
scan_logs_collection = db.scan_logs
wallet_transactions_collection = db.wallet_transactions
subscription_plans_collection = db.subscription_plans
user_subscriptions_collection = db.user_subscriptions
watchman_collections_collection = db.watchman_collections

# MongoDB Indexes (idempotent — safe to run on every startup)
try:
    vehicles_collection.create_index('qr_token', unique=True, sparse=True)
    vehicles_collection.create_index([('user_id', ASCENDING)])
    bookings_collection.create_index([('vehicle_id', ASCENDING), ('status', ASCENDING)])
    bookings_collection.create_index([('slot_id', ASCENDING), ('status', ASCENDING)])
    scan_logs_collection.create_index([('lot_id', ASCENDING), ('timestamp', DESCENDING)])
    logger.info('MongoDB indexes created/verified successfully')
except Exception as e:
    logger.warning(f'Index creation warning: {str(e)}')

# User class for Flask-Login
class User(UserMixin):
    def __init__(self, user_data):
        self.id = str(user_data['_id'])
        self.email = user_data['email']
        self.role = user_data['role']
        self.name = user_data['name']
        self.verified = user_data.get('verified', True)
        self.lot_id = user_data.get('lot_id')

@login_manager.user_loader
def load_user(user_id):
    user_data = users_collection.find_one({'_id': ObjectId(user_id)})
    if user_data:
        # Rule 6: Watchman lot verification — block if assigned lot was deleted
        if user_data.get('role') == 'watchman' and user_data.get('lot_id'):
            lot_exists = parking_lots_collection.find_one({'_id': user_data['lot_id']})
            if not lot_exists:
                users_collection.update_one(
                    {'_id': user_data['_id']},
                    {'$set': {'verified': False}}
                )
                user_data['verified'] = False
                logger.warning(f'Watchman {user_data["email"]} blocked: assigned lot no longer exists')
        return User(user_data)
    return None


# Custom decorators
def role_required(*roles):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated:
                return redirect(url_for('login'))
            if current_user.role not in roles:
                flash('Access denied.', 'danger')
                return redirect(url_for('index'))
            if current_user.role == 'admin' and not current_user.verified:
                flash('Your admin account is pending verification.', 'warning')
                return redirect(url_for('index'))
            return f(*args, **kwargs)
        return decorated_function
    return decorator

# Forms
class RegistrationForm(FlaskForm):
    name = StringField('Name', validators=[DataRequired(), Length(min=2, max=100)])
    email = StringField('Email', validators=[DataRequired(), Email()])
    password = PasswordField('Password', validators=[DataRequired(), Length(min=6)])
    confirm_password = PasswordField('Confirm Password', validators=[DataRequired(), EqualTo('password')])
    role = SelectField('Role', choices=[('user', 'User'), ('admin', 'Admin')], validators=[DataRequired()])
    
    def validate_email(self, email):
        user = users_collection.find_one({'email': email.data.lower()})
        if user:
            raise ValidationError('Email already registered.')

class LoginForm(FlaskForm):
    email = StringField('Email', validators=[DataRequired()])
    password = PasswordField('Password', validators=[DataRequired()])
    remember = BooleanField('Remember Me')

class VehicleForm(FlaskForm):
    vehicle_number = StringField('Vehicle Number', validators=[DataRequired(), Length(min=3, max=20)])
    vehicle_type = SelectField('Vehicle Type', choices=[('2-wheeler', '2-Wheeler'), ('4-wheeler', '4-Wheeler')], validators=[DataRequired()])

class ParkingLotForm(FlaskForm):
    name = StringField('Lot Name', validators=[DataRequired(), Length(min=3, max=100)])
    address = StringField('Address', validators=[DataRequired(), Length(min=5, max=200)])
    pincode = StringField('Pincode', validators=[DataRequired(), Length(min=6, max=6)])
    two_wheeler_slots = IntegerField('2-Wheeler Slots', validators=[DataRequired(), NumberRange(min=0, max=500)])
    two_wheeler_price = FloatField('2-Wheeler Price/Hr (₹)', validators=[DataRequired(), NumberRange(min=0)])
    four_wheeler_slots = IntegerField('4-Wheeler Slots', validators=[DataRequired(), NumberRange(min=0, max=500)])
    four_wheeler_price = FloatField('4-Wheeler Price/Hr (₹)', validators=[DataRequired(), NumberRange(min=0)])
    walkin_ratio = IntegerField('Walk-in %', validators=[DataRequired(), NumberRange(min=0, max=100)], default=70)
    prebook_ratio = IntegerField('Pre-book %', validators=[DataRequired(), NumberRange(min=0, max=100)], default=30)

class ParkingSlotForm(FlaskForm):
    slot_number = StringField('Slot Number', validators=[DataRequired(), Length(min=1, max=10)])
    slot_type = SelectField('Slot Type', choices=[('2-wheeler', '2-Wheeler'), ('4-wheeler', '4-Wheeler')], validators=[DataRequired()])
    price_per_hour = FloatField('Price per Hour', validators=[DataRequired(), NumberRange(min=0)])


class PreBookingForm(FlaskForm):
    vehicle_id = SelectField('Select Vehicle', validators=[DataRequired()])
    start_time = StringField('Start Time', validators=[DataRequired()])
    end_time = StringField('End Time', validators=[DataRequired()])
    
# Helper functions
def allowed_file(filename):
    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def is_vehicle_subscribed(vehicle_id, lot_id):
    """Return True if an active subscription exists for this vehicle at this lot today."""
    today = now_ist()
    sub = user_subscriptions_collection.find_one({
        'vehicle_id': ObjectId(vehicle_id),
        'lot_id': ObjectId(lot_id),
        'start_date': {'$lte': today},
        'end_date': {'$gte': today},
        'status': 'active'
    })
    return sub is not None

def calculate_parking_fee(entry_time, exit_time, price_per_hour):
    duration = exit_time - entry_time
    hours = duration.total_seconds() / 3600
    return round(hours * price_per_hour, 2)

def generate_invoice_number():
    timestamp = now_ist().strftime('%Y%m%d%H%M%S')
    random_suffix = secrets.token_hex(3).upper()
    return f'INV-{timestamp}-{random_suffix}'

def deduct_from_wallet(user_id, amount, reason, reference_id):
    """Atomically deduct from wallet, preventing overdraft. Returns True on success."""
    try:
        result = users_collection.find_one_and_update(
            {'_id': ObjectId(user_id), 'wallet_balance': {'$gte': amount}},
            {'$inc': {'wallet_balance': -amount}}
        )
        if result is None:
            return False
        wallet_transactions_collection.insert_one({
            'user_id': ObjectId(user_id),
            'type': 'debit',
            'amount': round(amount, 2),
            'reason': reason,
            'reference_id': reference_id,
            'balance_after': round(result['wallet_balance'] - amount, 2),
            'created_at': now_ist()
        })
        return True
    except Exception as e:
        logger.error(f'Wallet deduct error: {str(e)}')
        return False

def credit_wallet(user_id, amount, reason, reference_id):
    """Credit amount to wallet. Returns True on success."""
    try:
        result = users_collection.find_one_and_update(
            {'_id': ObjectId(user_id)},
            {'$inc': {'wallet_balance': amount}},
            return_document=ReturnDocument.AFTER
        )
        if result is None:
            return False
        wallet_transactions_collection.insert_one({
            'user_id': ObjectId(user_id),
            'type': 'credit',
            'amount': round(amount, 2),
            'reason': reason,
            'reference_id': reference_id,
            'balance_after': round(result['wallet_balance'], 2),
            'created_at': now_ist()
        })
        return True
    except Exception as e:
        logger.error(f'Wallet credit error: {str(e)}')
        return False

# Routes - Authentication
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/register', methods=['GET', 'POST'])
@limiter.limit("100 per hour")
def register():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    
    form = RegistrationForm()
    if form.validate_on_submit():
        try:
            hashed_password = bcrypt.generate_password_hash(form.password.data).decode('utf-8')
            user_data = {
                'name': form.name.data.strip(),
                'email': form.email.data.lower().strip(),
                'password': hashed_password,
                'role': form.role.data,
                'verified': True if form.role.data == 'user' else False,
                'wallet_balance': 0.0,
                'created_at': now_ist(),
                'profile_image': None
            }
            
            user_id = users_collection.insert_one(user_data).inserted_id
            
            if form.role.data == 'admin':
                admin_verification_collection.insert_one({
                    'admin_id': user_id,
                    'status': 'pending',
                    'verified_by': None,
                    'verified_at': None,
                    'created_at': now_ist()
                })
                flash('Admin registration successful. Awaiting super admin verification.', 'info')
            else:
                flash('Registration successful! Please log in.', 'success')
            
            logger.info(f'New user registered: {form.email.data}')
            return redirect(url_for('login'))
        except Exception as e:
            logger.error(f'Registration error: {str(e)}')
            flash('Registration failed. Please try again.', 'danger')
    
    return render_template('auth/register.html', form=form)

@app.route('/login', methods=['GET', 'POST'])
@limiter.limit("200 per hour")
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    
    form = LoginForm()
    if form.validate_on_submit():
        try:
            user = users_collection.find_one({'email': form.email.data.lower()})
            
            if user and bcrypt.check_password_hash(user['password'], form.password.data):
                if user.get('is_deleted'):
                    flash('This account has been deactivated. Please contact support.', 'danger')
                    return render_template('auth/login.html', form=form)
                
                user_obj = User(user)
                login_user(user_obj, remember=form.remember.data)
                
                next_page = request.args.get('next')
                logger.info(f'User logged in: {form.email.data}')
                return redirect(next_page) if next_page else redirect(url_for('dashboard'))
            else:
                flash('Invalid email or password.', 'danger')
        except Exception as e:
            logger.error(f'Login error: {str(e)}')
            flash('Login failed. Please try again.', 'danger')
    
    return render_template('auth/login.html', form=form)

@app.route('/logout')
@login_required
def logout():
    logger.info(f'User logged out: {current_user.email}')
    logout_user()
    flash('You have been logged out.', 'info')
    return redirect(url_for('index'))

@app.route('/user/vehicle/regenerate-qr/<vehicle_id>')
@login_required
@role_required('user')
def regenerate_vehicle_qr(vehicle_id):
    try:
        vehicle = vehicles_collection.find_one({
            '_id': ObjectId(vehicle_id),
            'user_id': ObjectId(current_user.id)
        })
        if not vehicle:
            flash('Vehicle not found.', 'danger')
            return redirect(url_for('my_vehicles'))

        # Generate new token
        new_token = secrets.token_urlsafe(16)

        # Generate new QR with new token
        qr_data = json.dumps({
            'vehicle_id': str(vehicle['_id']),
            'vehicle_number': vehicle['vehicle_number'],
            'qr_token': new_token,
            'type': 'parking_qr'
        })
        qr = qrcode.QRCode(version=1, error_correction=qrcode.constants.ERROR_CORRECT_H, box_size=10, border=4)
        qr.add_data(qr_data)
        qr.make(fit=True)
        qr_img = qr.make_image(fill_color='black', back_color='white')

        buffer = BytesIO()
        qr_img.save(buffer, format='PNG')
        buffer.seek(0)
        qr_base64 = base64.b64encode(buffer.getvalue()).decode('utf-8')

        # Update both token AND QR image together — they always stay in sync
        vehicles_collection.update_one(
            {'_id': ObjectId(vehicle_id)},
            {'$set': {
                'qr_token': new_token,
                'qr_code_base64': qr_base64,
                'qr_generated_at': now_ist()
            }}
        )

        flash('QR code regenerated successfully! Please download the new QR.', 'success')
    except Exception as e:
        logger.error(f'Regenerate QR error: {str(e)}')
        flash('Failed to regenerate QR code.', 'danger')

    return redirect(url_for('my_vehicles'))

# Routes - Dashboard
@app.route('/dashboard')
@login_required
def dashboard():
    if current_user.role == 'super_admin':
        return redirect(url_for('super_admin_dashboard'))
    elif current_user.role == 'admin':
        return redirect(url_for('admin_dashboard'))
    elif current_user.role == 'watchman':
        return redirect(url_for('watchman_dashboard'))
    else:
        return redirect(url_for('user_dashboard'))

# User Routes
@app.route('/user/dashboard')
@login_required
@role_required('user')
def user_dashboard():
    user_id = ObjectId(current_user.id)
    
    active_bookings = list(bookings_collection.find({
        'user_id': user_id,
        'status': 'active'
    }).sort('entry_time', DESCENDING).limit(5))
    
    for booking in active_bookings:
        booking['slot'] = parking_slots_collection.find_one({'_id': booking['slot_id']})
        booking['vehicle'] = vehicles_collection.find_one({'_id': booking['vehicle_id']})
        booking['lot'] = parking_lots_collection.find_one({'_id': booking['slot']['lot_id']})
    
    total_bookings = bookings_collection.count_documents({'user_id': user_id})
    active_count = bookings_collection.count_documents({'user_id': user_id, 'status': 'active'})
    
    recent_invoices = list(invoices_collection.find({
        'user_id': user_id
    }).sort('generated_at', DESCENDING).limit(5))
    
    total_spent = sum([inv['amount'] for inv in invoices_collection.find({'user_id': user_id})])
    
    return render_template('user/dashboard.html',
                         active_bookings=active_bookings,
                         total_bookings=total_bookings,
                         active_count=active_count,
                         recent_invoices=recent_invoices,
                         total_spent=total_spent)

@app.route('/user/parking-lots')
@login_required
@role_required('user')
def parking_lots():
    page = request.args.get('page', 1, type=int)
    per_page = 10
    search = request.args.get('search', '').strip()
    
    query = {}
    if search:
        query = {'$or': [
            {'name': {'$regex': search, '$options': 'i'}},
            {'address': {'$regex': search, '$options': 'i'}},
            {'pincode': {'$regex': search, '$options': 'i'}}
        ]}
    
    total = parking_lots_collection.count_documents(query)
    lots = list(parking_lots_collection.find(query).skip((page-1)*per_page).limit(per_page))
    
    for lot in lots:
        total_slots = parking_slots_collection.count_documents({'lot_id': lot['_id']})
        available_slots = parking_slots_collection.count_documents({'lot_id': lot['_id'], 'status': 'available'})
        lot['total_slots'] = total_slots
        lot['available_slots'] = available_slots
        lot['walkin_slots'] = parking_slots_collection.count_documents({'lot_id': lot['_id'], 'mode': 'walkin'})
        lot['prebook_slots'] = parking_slots_collection.count_documents({'lot_id': lot['_id'], 'mode': 'prebook'})
        lot['admin'] = users_collection.find_one({'_id': lot['admin_id']})
    
    total_pages = (total + per_page - 1) // per_page
    
    return render_template('user/parking_lots.html',
                         lots=lots,
                         page=page,
                         total_pages=total_pages,
                         search=search)

@app.route('/user/vehicles', methods=['GET', 'POST'])
@login_required
@role_required('user')
def my_vehicles():
    form = VehicleForm()
    
    if form.validate_on_submit():
        try:
            vehicle_number = form.vehicle_number.data.upper().strip()
            
            # Check for duplicate vehicle number
            existing = vehicles_collection.find_one({'vehicle_number': vehicle_number})
            if existing:
                flash('A vehicle with this number is already registered.', 'warning')
                vehicles = list(vehicles_collection.find({'user_id': ObjectId(current_user.id)}))
                return render_template('user/my_vehicles.html', form=form, vehicles=vehicles)
            
            qr_token = secrets.token_urlsafe(16)
            vehicle_data = {
                'user_id': ObjectId(current_user.id),
                'vehicle_number': vehicle_number,
                'vehicle_type': form.vehicle_type.data,
                'qr_token': qr_token,
                'currently_parked': False,
                'created_at': now_ist()
            }
            result = vehicles_collection.insert_one(vehicle_data)
            
            # Generate QR code for the vehicle
            qr_data = json.dumps({
                'vehicle_id': str(result.inserted_id),
                'vehicle_number': vehicle_data['vehicle_number'],
                'qr_token': qr_token,
                'type': 'parking_qr'
            })
            qr = qrcode.QRCode(
                version=1,
                error_correction=qrcode.constants.ERROR_CORRECT_H,  # ✅ 30% recovery
                box_size=10,
                border=4
            )
            qr.add_data(qr_data)
            qr.make(fit=True)
            qr_img = qr.make_image(fill_color='black', back_color='white')
            
            buffer = BytesIO()
            qr_img.save(buffer, format='PNG')
            buffer.seek(0)
            qr_base64 = base64.b64encode(buffer.getvalue()).decode('utf-8')
            
            vehicles_collection.update_one(
                {'_id': result.inserted_id},
                {'$set': {
                    'qr_code_base64': qr_base64,
                    'qr_generated_at': now_ist()
                }}
            )
            
            flash('Vehicle added successfully with QR code!', 'success')
            return redirect(url_for('my_vehicles'))
        except Exception as e:
            logger.error(f'Add vehicle error: {str(e)}')
            flash('Failed to add vehicle.', 'danger')
    
    vehicles = list(vehicles_collection.find({'user_id': ObjectId(current_user.id)}))
    
    return render_template('user/my_vehicles.html', form=form, vehicles=vehicles)

@app.route('/user/vehicle/download-qr/<vehicle_id>')
@login_required
@role_required('user')
def download_vehicle_qr(vehicle_id):
    try:
        vehicle = vehicles_collection.find_one({'_id': ObjectId(vehicle_id)})
        if not vehicle:
            flash('Vehicle not found.', 'danger')
            return redirect(url_for('my_vehicles'))
        
        if vehicle['user_id'] != ObjectId(current_user.id):
            flash('Access denied.', 'danger')
            return redirect(url_for('my_vehicles')), 403
        
        if not vehicle.get('qr_code_base64'):
            flash('QR code not available for this vehicle.', 'warning')
            return redirect(url_for('my_vehicles'))
        
        qr_binary = base64.b64decode(vehicle['qr_code_base64'])
        buffer = BytesIO(qr_binary)
        buffer.seek(0)
        
        filename = f"QR_{vehicle['vehicle_number']}.png"
        return send_file(buffer, mimetype='image/png', as_attachment=True, download_name=filename)
    except Exception as e:
        logger.error(f'Download QR error: {str(e)}')
        flash('Failed to download QR code.', 'danger')
        return redirect(url_for('my_vehicles'))

@app.route('/user/vehicle/delete/<vehicle_id>')
@login_required
@role_required('user')
def delete_vehicle(vehicle_id):
    try:
        # Rule 8: Prevent deleting a vehicle that is currently parked
        vehicle = vehicles_collection.find_one({
            '_id': ObjectId(vehicle_id),
            'user_id': ObjectId(current_user.id)
        })
        if not vehicle:
            flash('Vehicle not found.', 'danger')
            return redirect(url_for('my_vehicles'))
        
        if vehicle.get('currently_parked'):
            flash('Cannot delete vehicle while it is parked. Please check out first.', 'danger')
            return redirect(url_for('my_vehicles'))
        
        # Block deletion if vehicle has any reserved (pre-booked) booking
        reserved_booking = bookings_collection.find_one({
            'vehicle_id': vehicle['_id'],
            'status': 'reserved'
        })
        if reserved_booking:
            flash('Cannot delete vehicle with an active pre-booking. Please cancel the pre-booking first.', 'danger')
            return redirect(url_for('my_vehicles'))
        
        vehicles_collection.delete_one({'_id': vehicle['_id']})
        flash('Vehicle deleted successfully!', 'success')
    except Exception as e:
        logger.error(f'Delete vehicle error: {str(e)}')
        flash('Failed to delete vehicle.', 'danger')
    
    return redirect(url_for('my_vehicles'))


@app.route('/user/bookings')
@login_required
@role_required('user')
def my_bookings():
    page = request.args.get('page', 1, type=int)
    per_page = 10
    
    total = bookings_collection.count_documents({'user_id': ObjectId(current_user.id)})
    bookings = list(bookings_collection.find({
        'user_id': ObjectId(current_user.id)
    }).sort('created_at', DESCENDING).skip((page-1)*per_page).limit(per_page))
    
    for booking in bookings:
        booking['slot'] = parking_slots_collection.find_one({'_id': booking['slot_id']})
        booking['vehicle'] = vehicles_collection.find_one({'_id': booking['vehicle_id']})
        booking['lot'] = parking_lots_collection.find_one({'_id': booking['slot']['lot_id']})
    
    total_pages = (total + per_page - 1) // per_page
    
    return render_template('user/my_bookings.html',
                         bookings=bookings,
                         page=page,
                         total_pages=total_pages,
                         now=now_ist())


@app.route('/user/invoices')
@login_required
@role_required('user')
def invoices():
    page = request.args.get('page', 1, type=int)
    per_page = 10
    
    total = invoices_collection.count_documents({'user_id': ObjectId(current_user.id)})
    invoices_list = list(invoices_collection.find({
        'user_id': ObjectId(current_user.id)
    }).sort('generated_at', DESCENDING).skip((page-1)*per_page).limit(per_page))
    
    for invoice in invoices_list:
        booking = bookings_collection.find_one({'_id': invoice['booking_id']})
        slot = parking_slots_collection.find_one({'_id': booking['slot_id']})
        lot = parking_lots_collection.find_one({'_id': slot['lot_id']})
        vehicle = vehicles_collection.find_one({'_id': booking['vehicle_id']})
        
        invoice['booking'] = booking
        invoice['lot'] = lot
        invoice['vehicle'] = vehicle
    
    total_pages = (total + per_page - 1) // per_page
    
    return render_template('user/invoices.html',
                         invoices=invoices_list,
                         page=page,
                         total_pages=total_pages)

@app.route('/user/profile', methods=['GET', 'POST'])
@login_required
@role_required('user')
def user_profile():
    if request.method == 'POST':
        try:
            name = request.form.get('name', '').strip()
            
            update_data = {'name': name}
            
            if 'profile_image' in request.files:
                file = request.files['profile_image']
                if file and file.filename and allowed_file(file.filename):
                    filename = secure_filename(f"{current_user.id}_{file.filename}")
                    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
                    file.save(filepath)
                    update_data['profile_image'] = filename
            
            users_collection.update_one(
                {'_id': ObjectId(current_user.id)},
                {'$set': update_data}
            )
            
            flash('Profile updated successfully!', 'success')
            return redirect(url_for('user_profile'))
        except Exception as e:
            logger.error(f'Profile update error: {str(e)}')
            flash('Failed to update profile.', 'danger')
    
    user = users_collection.find_one({'_id': ObjectId(current_user.id)})
    return render_template('user/profile.html', user=user)

@app.route('/user/subscriptions')
@login_required
@role_required('user')
def user_subscriptions():
    user_id = ObjectId(current_user.id)
    now = now_ist()

    # Get user's vehicles to find relevant vehicle types
    user_vehicles = list(vehicles_collection.find({'user_id': user_id}))

    # Active plans grouped by lot
    active_plans = list(subscription_plans_collection.find({'active': True}))
    lots_map = {}
    for plan in active_plans:
        lot = parking_lots_collection.find_one({'_id': plan['lot_id']})
        if lot:
            lot_key = str(lot['_id'])
            if lot_key not in lots_map:
                lots_map[lot_key] = {'lot': lot, 'plans': []}
            lots_map[lot_key]['plans'].append(plan)
    grouped_plans = list(lots_map.values())

    # User's active subscriptions with expiry
    my_subs = list(user_subscriptions_collection.find({
        'user_id': user_id,
        'status': 'active',
        'end_date': {'$gte': now}
    }).sort('end_date', ASCENDING))
    for sub in my_subs:
        sub['plan'] = subscription_plans_collection.find_one({'_id': sub['plan_id']})
        sub['lot'] = parking_lots_collection.find_one({'_id': sub['lot_id']})
        sub['vehicle'] = vehicles_collection.find_one({'_id': sub['vehicle_id']})
        sub['days_left'] = (sub['end_date'] - now).days

    user_doc = users_collection.find_one({'_id': user_id})
    wallet_balance = user_doc.get('wallet_balance', 0.0)

    return render_template('user/subscriptions.html',
                         grouped_plans=grouped_plans,
                         my_subs=my_subs,
                         user_vehicles=user_vehicles,
                         wallet_balance=wallet_balance)

@app.route('/user/subscription/buy/<plan_id>', methods=['POST'])
@login_required
@role_required('user')
def buy_subscription(plan_id):
    try:
        plan = subscription_plans_collection.find_one({
            '_id': ObjectId(plan_id),
            'active': True
        })
        if not plan:
            flash('Subscription plan not found or is inactive.', 'danger')
            return redirect(url_for('user_subscriptions'))

        vehicle_id = request.form.get('vehicle_id', '')
        if not vehicle_id:
            flash('Please select a vehicle.', 'danger')
            return redirect(url_for('user_subscriptions'))

        vehicle = vehicles_collection.find_one({
            '_id': ObjectId(vehicle_id),
            'user_id': ObjectId(current_user.id)
        })
        if not vehicle:
            flash('Vehicle not found.', 'danger')
            return redirect(url_for('user_subscriptions'))

        if vehicle['vehicle_type'] != plan['vehicle_type']:
            flash(f'This plan is for {plan["vehicle_type"]} vehicles only.', 'danger')
            return redirect(url_for('user_subscriptions'))

        # Check if vehicle already has an active subscription at this lot
        existing = user_subscriptions_collection.find_one({
            'vehicle_id': vehicle['_id'],
            'lot_id': plan['lot_id'],
            'status': 'active',
            'end_date': {'$gte': now_ist()}
        })
        if existing:
            flash('This vehicle already has an active subscription at this lot.', 'warning')
            return redirect(url_for('user_subscriptions'))

        # Verify wallet balance
        user_doc = users_collection.find_one({'_id': ObjectId(current_user.id)})
        wallet_balance = user_doc.get('wallet_balance', 0.0)
        if wallet_balance < plan['price']:
            flash(f'Insufficient wallet balance. Required: ₹{plan["price"]:.2f}, Available: ₹{wallet_balance:.2f}. Please top up your wallet.', 'danger')
            return redirect(url_for('user_subscriptions'))

        # Create subscription record
        start_date = now_ist()
        end_date = start_date + timedelta(days=plan['duration_days'])
        sub_data = {
            'user_id': ObjectId(current_user.id),
            'plan_id': plan['_id'],
            'lot_id': plan['lot_id'],
            'vehicle_id': vehicle['_id'],
            'start_date': start_date,
            'end_date': end_date,
            'price_paid': plan['price'],
            'status': 'active',
            'created_at': now_ist()
        }
        sub_id = user_subscriptions_collection.insert_one(sub_data).inserted_id

        # Deduct from wallet
        success = deduct_from_wallet(
            user_id=current_user.id,
            amount=plan['price'],
            reason='subscription_purchase',
            reference_id=str(sub_id)
        )
        if not success:
            # Rollback subscription if wallet deduction failed
            user_subscriptions_collection.delete_one({'_id': sub_id})
            flash('Wallet deduction failed. Please try again.', 'danger')
            return redirect(url_for('user_subscriptions'))

        flash(f'Subscription "{plan["name"]}" purchased successfully! Valid until {end_date.strftime("%d %b %Y")}.', 'success')
        logger.info(f'Subscription purchased: User {current_user.email}, Plan {plan["name"]}, Vehicle {vehicle["vehicle_number"]}')
    except Exception as e:
        logger.error(f'Buy subscription error: {str(e)}')
        flash('Failed to purchase subscription.', 'danger')

    return redirect(url_for('user_subscriptions'))

# Wallet Routes
@app.route('/user/wallet')
@login_required
@role_required('user')
def user_wallet():
    page = request.args.get('page', 1, type=int)
    per_page = 10
    
    user = users_collection.find_one({'_id': ObjectId(current_user.id)})
    balance = user.get('wallet_balance', 0.0)
    
    total = wallet_transactions_collection.count_documents({'user_id': ObjectId(current_user.id)})
    transactions = list(wallet_transactions_collection.find({
        'user_id': ObjectId(current_user.id)
    }).sort('created_at', DESCENDING).skip((page-1)*per_page).limit(per_page))
    
    total_pages = (total + per_page - 1) // per_page
    
    return render_template('user/wallet.html',
                         balance=balance,
                         transactions=transactions,
                         page=page,
                         total_pages=total_pages,
                         razorpay_key_id=app.config['RAZORPAY_KEY_ID'])

@app.route('/user/wallet/topup/create', methods=['POST'])
@login_required
@role_required('user')
def wallet_topup_create():
    try:
        if not razorpay_client:
            return jsonify({'success': False, 'message': 'Payment gateway not configured'}), 503
        
        data = request.get_json()
        amount = float(data.get('amount', 0))
        
        if amount < 50:
            return jsonify({'success': False, 'message': 'Minimum top-up amount is ₹50'}), 400
        
        if amount > 10000:
            return jsonify({'success': False, 'message': 'Maximum top-up amount is ₹10,000'}), 400
        
        # Razorpay expects amount in paise
        order_data = {
            'amount': int(amount * 100),
            'currency': 'INR',
            'receipt': f'wallet_{current_user.id}_{secrets.token_hex(4)}',
            'notes': {
                'user_id': current_user.id,
                'purpose': 'wallet_topup'
            }
        }
        
        order = razorpay_client.order.create(data=order_data)
        
        return jsonify({
            'success': True,
            'order_id': order['id'],
            'amount': order['amount'],
            'currency': order['currency'],
            'key_id': app.config['RAZORPAY_KEY_ID']
        })
    except Exception as e:
        logger.error(f'Wallet topup create error: {str(e)}')
        return jsonify({'success': False, 'message': 'Failed to create payment order'}), 500

@app.route('/user/wallet/topup/verify', methods=['POST'])
@login_required
@role_required('user')
def wallet_topup_verify():
    try:
        data = request.get_json()
        razorpay_order_id = data.get('razorpay_order_id', '')
        razorpay_payment_id = data.get('razorpay_payment_id', '')
        razorpay_signature = data.get('razorpay_signature', '')
        
        if not all([razorpay_order_id, razorpay_payment_id, razorpay_signature]):
            return jsonify({'success': False, 'message': 'Missing payment details'}), 400
        
        # Verify Razorpay signature
        message = f'{razorpay_order_id}|{razorpay_payment_id}'
        generated_signature = hmac.new(
            app.config['RAZORPAY_KEY_SECRET'].encode(),
            message.encode(),
            hashlib.sha256
        ).hexdigest()
        
        if generated_signature != razorpay_signature:
            logger.warning(f'Razorpay signature mismatch for user {current_user.id}')
            return jsonify({'success': False, 'message': 'Payment verification failed'}), 400
        
        # Fetch order from Razorpay to get verified amount (don't trust client)
        order = razorpay_client.order.fetch(razorpay_order_id)
        amount = order['amount'] / 100
        
        success = credit_wallet(
            user_id=current_user.id,
            amount=amount,
            reason='Wallet top-up via Razorpay',
            reference_id=razorpay_payment_id
        )
        
        if success:
            logger.info(f'Wallet topped up: User {current_user.email}, Amount: ₹{amount}, PaymentID: {razorpay_payment_id}')
            return jsonify({'success': True, 'message': f'₹{amount:.2f} added to wallet successfully!'})
        else:
            return jsonify({'success': False, 'message': 'Failed to credit wallet'}), 500
    except Exception as e:
        logger.error(f'Wallet topup verify error: {str(e)}')
        return jsonify({'success': False, 'message': 'Payment verification failed'}), 500

# Fee Estimation API
@app.route('/api/estimate-fee/<lot_id>')
@login_required
def estimate_fee_api(lot_id):
    try:
        lot = parking_lots_collection.find_one({'_id': ObjectId(lot_id)})
        if not lot:
            return jsonify({'success': False, 'message': 'Lot not found'}), 404
        
        start_str = request.args.get('start_time', '')
        end_str = request.args.get('end_time', '')
        vehicle_type = request.args.get('vehicle_type', '2-wheeler')
        
        if not start_str or not end_str:
            return jsonify({'success': False, 'message': 'start_time and end_time required'}), 400
        
        start_time = datetime.fromisoformat(start_str)
        end_time = datetime.fromisoformat(end_str)
        
        if end_time <= start_time:
            return jsonify({'success': False, 'message': 'end_time must be after start_time'}), 400
        
        sample_slot = parking_slots_collection.find_one({
            'lot_id': ObjectId(lot_id),
            'slot_type': vehicle_type
        })
        if not sample_slot:
            return jsonify({'success': False, 'message': 'No slots of that type in this lot'}), 404
        
        price_per_hour = sample_slot['price_per_hour']
        fee = calculate_parking_fee(start_time, end_time, price_per_hour)
        hours = (end_time - start_time).total_seconds() / 3600
        
        return jsonify({
            'success': True,
            'estimated_fee': fee,
            'hours': round(hours, 2),
            'price_per_hour': price_per_hour,
            'vehicle_type': vehicle_type
        })
    except ValueError:
        return jsonify({'success': False, 'message': 'Invalid datetime format. Use ISO format.'}), 400
    except Exception as e:
        logger.error(f'Estimate fee error: {str(e)}')
        return jsonify({'success': False, 'message': 'Failed to estimate fee'}), 500

# Pre-booking Routes
@app.route('/user/prebook/available-slots/<lot_id>')
@login_required
@role_required('user')
def prebook_available_slots(lot_id):
    """Return per-slot availability for a given lot, vehicle_type, and time window."""
    try:
        lot = parking_lots_collection.find_one({'_id': ObjectId(lot_id)})
        if not lot:
            return jsonify({'success': False, 'message': 'Parking lot not found.'}), 404

        start_str = request.args.get('start_time', '').strip()
        end_str = request.args.get('end_time', '').strip()
        vehicle_type = request.args.get('vehicle_type', '').strip()

        if not start_str or not end_str or not vehicle_type:
            return jsonify({'success': False, 'message': 'start_time, end_time, and vehicle_type are required.'})

        try:
            start_time = datetime.fromisoformat(start_str)
            end_time = datetime.fromisoformat(end_str)
        except ValueError:
            return jsonify({'success': False, 'message': 'Invalid datetime format. Use ISO format (YYYY-MM-DDTHH:MM).'})

        if end_time <= start_time:
            return jsonify({'success': False, 'message': 'end_time must be after start_time.'})

        prebook_slots = list(parking_slots_collection.find({
            'lot_id': ObjectId(lot_id),
            'slot_type': vehicle_type,
            'mode': 'prebook'
        }).sort('slot_number', ASCENDING))

        slots_result = []
        for slot in prebook_slots:
            conflicting_bookings = list(bookings_collection.find({
                'slot_id': slot['_id'],
                'status': {'$in': ['reserved', 'active']},
                'booked_start': {'$lt': end_time},
                'booked_end': {'$gt': start_time}
            }))

            if not conflicting_bookings:
                slots_result.append({
                    'slot_id': str(slot['_id']),
                    'slot_number': slot['slot_number'],
                    'status': 'available',
                    'free_at': None
                })
            else:
                latest_end = max(b['booked_end'] for b in conflicting_bookings)
                free_at_ist = latest_end + timedelta(minutes=20)
                slots_result.append({
                    'slot_id': str(slot['_id']),
                    'slot_number': slot['slot_number'],
                    'status': 'occupied',
                    'free_at': free_at_ist.strftime('%H:%M')
                })

        # Determine price_per_hour from lot or first slot
        price_per_hour = None
        if vehicle_type == '2-wheeler':
            price_per_hour = lot.get('two_wheeler_price')
        elif vehicle_type == '4-wheeler':
            price_per_hour = lot.get('four_wheeler_price')
        if price_per_hour is None and prebook_slots:
            price_per_hour = prebook_slots[0].get('price_per_hour')

        return jsonify({
            'success': True,
            'slots': slots_result,
            'price_per_hour': price_per_hour
        })
    except Exception as e:
        logger.error(f'Prebook available slots error: {str(e)}')
        return jsonify({'success': False, 'message': 'Failed to fetch available slots.'}), 500

@app.route('/user/prebook/<lot_id>', methods=['GET', 'POST'])
@login_required
@role_required('user')
def prebook_slot(lot_id):
    lot = parking_lots_collection.find_one({'_id': ObjectId(lot_id)})
    if not lot:
        flash('Parking lot not found.', 'danger')
        return redirect(url_for('parking_lots'))
    
    form = PreBookingForm()
    vehicles = list(vehicles_collection.find({'user_id': ObjectId(current_user.id)}))
    form.vehicle_id.choices = [(str(v['_id']), f"{v['vehicle_number']} ({v['vehicle_type']})") for v in vehicles]
    
    if not vehicles:
        flash('Please add a vehicle before booking.', 'warning')
        return redirect(url_for('my_vehicles'))
    
    if form.validate_on_submit():
        try:
            vehicle = vehicles_collection.find_one({'_id': ObjectId(form.vehicle_id.data)})
            start_time = datetime.fromisoformat(form.start_time.data)
            end_time = datetime.fromisoformat(form.end_time.data)
            
            if start_time <= now_ist():
                flash('Start time must be in the future.', 'danger')
                return redirect(url_for('prebook_slot', lot_id=lot_id))
            
            if end_time <= start_time:
                flash('End time must be after start time.', 'danger')
                return redirect(url_for('prebook_slot', lot_id=lot_id))
            
            # Check vehicle not already reserved or active
            conflict = bookings_collection.find_one({
                'vehicle_id': vehicle['_id'],
                'status': {'$in': ['active', 'reserved']}
            })
            if conflict:
                flash('This vehicle already has an active or reserved booking.', 'danger')
                return redirect(url_for('prebook_slot', lot_id=lot_id))
            
            # Find a prebook slot with no conflicting reservation in that time window
            prebook_slots = list(parking_slots_collection.find({
                'lot_id': ObjectId(lot_id),
                'slot_type': vehicle['vehicle_type'],
                'mode': 'prebook'
            }))

            available_slot = None

            # CHANGE 2: Check if user pre-selected a specific slot
            selected_slot_id = request.form.get('selected_slot_id', '').strip()
            if selected_slot_id:
                selected_slot = parking_slots_collection.find_one({
                    '_id': ObjectId(selected_slot_id),
                    'lot_id': ObjectId(lot_id),
                    'mode': 'prebook',
                    'slot_type': vehicle['vehicle_type']
                })
                if not selected_slot:
                    flash('Selected slot not valid.', 'danger')
                    return redirect(url_for('prebook_slot', lot_id=lot_id))
                slot_conflict = bookings_collection.find_one({
                    'slot_id': selected_slot['_id'],
                    'status': {'$in': ['reserved', 'active']},
                    'booked_start': {'$lt': end_time},
                    'booked_end': {'$gt': start_time}
                })
                if slot_conflict:
                    flash('Selected slot is no longer available. Please choose another.', 'danger')
                    return redirect(url_for('prebook_slot', lot_id=lot_id))
                available_slot = selected_slot
            else:
                for slot in prebook_slots:
                    conflict_booking = bookings_collection.find_one({
                        'slot_id': slot['_id'],
                        'status': {'$in': ['reserved', 'active']},
                        'booked_start': {'$lt': end_time},
                        'booked_end': {'$gt': start_time}
                    })
                    if not conflict_booking:
                        available_slot = slot
                        break

            if not available_slot:
                flash('No pre-book slots available for your vehicle type in that time window.', 'danger')
                return redirect(url_for('prebook_slot', lot_id=lot_id))
            
            # Calculate estimated fee
            estimated_fee = calculate_parking_fee(start_time, end_time, available_slot['price_per_hour'])
            
            # Check wallet balance
            user_doc = users_collection.find_one({'_id': ObjectId(current_user.id)})
            wallet_balance = user_doc.get('wallet_balance', 0.0)
            if wallet_balance < estimated_fee:
                flash(f'Insufficient wallet balance. Required: ₹{estimated_fee:.2f}, Available: ₹{wallet_balance:.2f}. Please top up your wallet.', 'danger')
                return redirect(url_for('prebook_slot', lot_id=lot_id))
            
            # Hold full estimated amount
            booking_data = {
                'user_id': ObjectId(current_user.id),
                'slot_id': available_slot['_id'],
                'vehicle_id': vehicle['_id'],
                'lot_id': ObjectId(lot_id),
                'entry_time': None,
                'exit_time': None,
                'status': 'reserved',
                'booking_type': 'prebook',
                'booked_start': start_time,
                'booked_end': end_time,
                'hold_amount': estimated_fee,
                'checked_in_lot_id': ObjectId(lot_id),
                'created_at': now_ist()
            }
            booking_id = bookings_collection.insert_one(booking_data).inserted_id
            
            deduct_from_wallet(
                user_id=current_user.id,
                amount=estimated_fee,
                reason='Booking hold for pre-book reservation',
                reference_id=str(booking_id)
            )
            
            # Schedule no-show job at booked_start + 20 minutes
            noshow_time = start_time + timedelta(minutes=20)
            scheduler.add_job(
                func=handle_noshow,
                trigger='date',
                run_date=noshow_time,
                args=[str(booking_id)],
                id=f'noshow_{booking_id}',
                replace_existing=True
            )
            
            flash(f'Pre-booking confirmed! ₹{estimated_fee:.2f} held from wallet. Slot: {available_slot["slot_number"]}', 'success')
            logger.info(f'Pre-booking created: User {current_user.email}, Slot {available_slot["slot_number"]}, {start_time} to {end_time}')
            return redirect(url_for('my_bookings'))
        except ValueError:
            flash('Invalid date/time format.', 'danger')
        except Exception as e:
            logger.error(f'Pre-booking error: {str(e)}')
            flash('Pre-booking failed. Please try again.', 'danger')
    
    # GET: show available prebook slots count
    prebook_2w = parking_slots_collection.count_documents({
        'lot_id': ObjectId(lot_id), 'slot_type': '2-wheeler', 'mode': 'prebook'
    })
    prebook_4w = parking_slots_collection.count_documents({
        'lot_id': ObjectId(lot_id), 'slot_type': '4-wheeler', 'mode': 'prebook'
    })
    
    user_doc = users_collection.find_one({'_id': ObjectId(current_user.id)})
    wallet_balance = user_doc.get('wallet_balance', 0.0)
    
    return render_template('user/prebook_slot.html',
                         form=form, lot=lot,
                         prebook_2w=prebook_2w, prebook_4w=prebook_4w,
                         wallet_balance=wallet_balance)

@app.route('/user/booking/cancel/<booking_id>', methods=['POST'])
@login_required
@role_required('user')
def cancel_booking(booking_id):
    try:
        booking = bookings_collection.find_one({
            '_id': ObjectId(booking_id),
            'user_id': ObjectId(current_user.id),
            'status': 'reserved'
        })
        if not booking:
            flash('Booking not found or cannot be cancelled.', 'danger')
            return redirect(url_for('my_bookings'))
        
        hold_amount = booking.get('hold_amount', 0)
        booked_start = booking['booked_start']
        time_until_start = (booked_start - now_ist()).total_seconds() / 3600
        
        if time_until_start > 2:
            # More than 2 hours before start: full refund
            credit_wallet(
                user_id=current_user.id,
                amount=hold_amount,
                reason='Full refund - booking cancelled (>2h before start)',
                reference_id=str(booking['_id'])
            )
            flash(f'Booking cancelled. Full refund of ₹{hold_amount:.2f} credited to wallet.', 'success')
        else:
            # Less than 2 hours: no refund
            flash('Booking cancelled. No refund (cancelled within 2 hours of start time).', 'warning')
        
        bookings_collection.update_one(
            {'_id': booking['_id']},
            {'$set': {'status': 'cancelled', 'cancelled_at': now_ist()}}
        )
        
        # Remove scheduled no-show job
        try:
            scheduler.remove_job(f'noshow_{booking_id}')
        except Exception:
            pass
        
        logger.info(f'Booking {booking_id} cancelled by user {current_user.email}')
        return redirect(url_for('my_bookings'))
    except Exception as e:
        logger.error(f'Cancel booking error: {str(e)}')
        flash('Failed to cancel booking.', 'danger')
        return redirect(url_for('my_bookings'))

# Admin Routes
@app.route('/admin/dashboard')
@login_required
@role_required('admin')
def admin_dashboard():
    admin_id = ObjectId(current_user.id)
    
    lots = list(parking_lots_collection.find({'admin_id': admin_id}))
    lot_ids = [lot['_id'] for lot in lots]
    
    total_slots = parking_slots_collection.count_documents({'lot_id': {'$in': lot_ids}})
    occupied_slots = parking_slots_collection.count_documents({'lot_id': {'$in': lot_ids}, 'status': 'occupied'})
    
    slot_ids = [slot['_id'] for slot in parking_slots_collection.find({'lot_id': {'$in': lot_ids}})]
    total_bookings = bookings_collection.count_documents({'slot_id': {'$in': slot_ids}})
    
    booking_ids = [b['_id'] for b in bookings_collection.find({'slot_id': {'$in': slot_ids}})]
    total_revenue = sum([inv['amount'] for inv in invoices_collection.find({'booking_id': {'$in': booking_ids}})])
    
    occupancy_rate = (occupied_slots / total_slots * 100) if total_slots > 0 else 0
    
    recent_bookings = list(bookings_collection.find({
        'slot_id': {'$in': slot_ids}
    }).sort('entry_time', DESCENDING).limit(10))
    
    for booking in recent_bookings:
        booking['user'] = users_collection.find_one({'_id': booking['user_id']})
        booking['vehicle'] = vehicles_collection.find_one({'_id': booking['vehicle_id']})
        booking['slot'] = parking_slots_collection.find_one({'_id': booking['slot_id']})
    
    return render_template('admin/dashboard.html',
                         total_lots=len(lots),
                         total_slots=total_slots,
                         occupied_slots=occupied_slots,
                         total_bookings=total_bookings,
                         total_revenue=total_revenue,
                         occupancy_rate=occupancy_rate,
                         recent_bookings=recent_bookings)

@app.route('/admin/manage-slots', methods=['GET', 'POST'])
@login_required
@role_required('admin')
def manage_slots():
    lot_form = ParkingLotForm()
    slot_form = ParkingSlotForm()
    
    if request.method == 'POST' and 'create_lot' in request.form:
        if lot_form.validate_on_submit():
            try:
                walkin_pct = lot_form.walkin_ratio.data or 70
                prebook_pct = lot_form.prebook_ratio.data or 30
                if walkin_pct + prebook_pct != 100:
                    flash('Walk-in % + Pre-book % must equal 100.', 'danger')
                    lots = list(parking_lots_collection.find({'admin_id': ObjectId(current_user.id)}))
                    for lt in lots:
                        lt['slots'] = list(parking_slots_collection.find({'lot_id': lt['_id']}))
                    return render_template('admin/manage_slots.html', lot_form=lot_form, slot_form=slot_form, lots=lots)

                lot_data = {
                    'admin_id': ObjectId(current_user.id),
                    'name': lot_form.name.data.strip(),
                    'address': lot_form.address.data.strip(),
                    'pincode': lot_form.pincode.data.strip(),
                    'walkin_ratio': walkin_pct,
                    'prebook_ratio': prebook_pct,
                    'created_at': now_ist()
                }
                lot_id = parking_lots_collection.insert_one(lot_data).inserted_id
                
                # Create slots based on admin-specified counts, split by walkin/prebook ratio
                two_wheeler_count = lot_form.two_wheeler_slots.data
                two_wheeler_price = lot_form.two_wheeler_price.data
                four_wheeler_count = lot_form.four_wheeler_slots.data
                four_wheeler_price = lot_form.four_wheeler_price.data
                
                def split_slots(total, walkin_pct):
                    walkin = math.floor(total * walkin_pct / 100)
                    prebook = total - walkin
                    return walkin, prebook
                
                tw_walkin, tw_prebook = split_slots(two_wheeler_count, walkin_pct)
                fw_walkin, fw_prebook = split_slots(four_wheeler_count, walkin_pct)
                
                slots_to_create = []
                
                # Create 2-wheeler walk-in slots
                for i in range(1, tw_walkin + 1):
                    slots_to_create.append({
                        'lot_id': lot_id,
                        'slot_number': f'A{i}',
                        'slot_type': '2-wheeler',
                        'mode': 'walkin',
                        'price_per_hour': two_wheeler_price,
                        'status': 'available',
                        'created_at': now_ist()
                    })
                # Create 2-wheeler prebook slots
                for i in range(tw_walkin + 1, two_wheeler_count + 1):
                    slots_to_create.append({
                        'lot_id': lot_id,
                        'slot_number': f'A{i}',
                        'slot_type': '2-wheeler',
                        'mode': 'prebook',
                        'price_per_hour': two_wheeler_price,
                        'status': 'available',
                        'created_at': now_ist()
                    })
                
                # Create 4-wheeler walk-in slots
                for i in range(1, fw_walkin + 1):
                    slots_to_create.append({
                        'lot_id': lot_id,
                        'slot_number': f'B{i}',
                        'slot_type': '4-wheeler',
                        'mode': 'walkin',
                        'price_per_hour': four_wheeler_price,
                        'status': 'available',
                        'created_at': now_ist()
                    })
                # Create 4-wheeler prebook slots
                for i in range(fw_walkin + 1, four_wheeler_count + 1):
                    slots_to_create.append({
                        'lot_id': lot_id,
                        'slot_number': f'B{i}',
                        'slot_type': '4-wheeler',
                        'mode': 'prebook',
                        'price_per_hour': four_wheeler_price,
                        'status': 'available',
                        'created_at': now_ist()
                    })
                
                if slots_to_create:
                    parking_slots_collection.insert_many(slots_to_create)
                
                # Auto-generate watchman account for this lot
                lot_name_slug = re.sub(r'[^a-z0-9_]', '', lot_form.name.data.strip().lower().replace(' ', '_'))
                random_digits = secrets.token_hex(2)[:4]
                watchman_email = f'watchman_{lot_name_slug}_{random_digits}@parking.local'
                watchman_plain_pwd = secrets.token_urlsafe(6)
                watchman_hashed_pwd = bcrypt.generate_password_hash(watchman_plain_pwd).decode('utf-8')
                
                watchman_user = {
                    'name': f'Watchman - {lot_form.name.data.strip()}',
                    'email': watchman_email,
                    'password': watchman_hashed_pwd,
                    'role': 'watchman',
                    'verified': True,
                    'lot_id': lot_id,
                    'created_at': now_ist(),
                    'profile_image': None
                }
                watchman_id = users_collection.insert_one(watchman_user).inserted_id
                
                # Store watchman credentials in lot document for admin reference
                parking_lots_collection.update_one(
                    {'_id': lot_id},
                    {'$set': {
                        'watchman_user_id': watchman_id,
                        'watchman_username': watchman_email,
                        'watchman_plain_password': watchman_plain_pwd
                    }}
                )
                
                logger.info(f'Watchman created for lot {lot_form.name.data}: {watchman_email}')
                flash(f'Parking lot created with {two_wheeler_count} 2-wheeler and {four_wheeler_count} 4-wheeler slots! Watchman account generated.', 'success')
                return redirect(url_for('manage_slots'))
            except Exception as e:
                logger.error(f'Create lot error: {str(e)}')
                flash('Failed to create parking lot.', 'danger')
        else:
            for field, errors in lot_form.errors.items():
                for error in errors:
                    flash(f'{field}: {error}', 'danger')
    
    lots = list(parking_lots_collection.find({'admin_id': ObjectId(current_user.id)}))
    
    for lot in lots:
        lot['slots'] = list(parking_slots_collection.find({'lot_id': lot['_id']}))
    
    return render_template('admin/manage_slots.html',
                         lot_form=lot_form,
                         slot_form=slot_form,
                         lots=lots)

@app.route('/admin/add-slot/<lot_id>', methods=['POST'])
@login_required
@role_required('admin')
def add_slot(lot_id):
    try:
        lot = parking_lots_collection.find_one({
            '_id': ObjectId(lot_id),
            'admin_id': ObjectId(current_user.id)
        })
        
        if not lot:
            flash('Parking lot not found.', 'danger')
            return redirect(url_for('manage_slots'))
        
        mode_val = request.form.get('mode', 'walkin').strip()
        if mode_val not in ('walkin', 'prebook'):
            mode_val = 'walkin'
        slot_data = {
            'lot_id': ObjectId(lot_id),
            'slot_number': request.form.get('slot_number', '').strip(),
            'slot_type': request.form.get('slot_type'),
            'mode': mode_val,
            'price_per_hour': float(request.form.get('price_per_hour', 0)),
            'status': 'available',
            'created_at': now_ist()
        }
        
        parking_slots_collection.insert_one(slot_data)
        flash('Slot added successfully!', 'success')
    except Exception as e:
        logger.error(f'Add slot error: {str(e)}')
        flash('Failed to add slot.', 'danger')
    
    return redirect(url_for('manage_slots'))

@app.route('/admin/delete-slot/<slot_id>')
@login_required
@role_required('admin')
def delete_slot(slot_id):
    try:
        slot = parking_slots_collection.find_one({'_id': ObjectId(slot_id)})
        if not slot:
            flash('Slot not found.', 'danger')
            return redirect(url_for('manage_slots'))
        
        lot = parking_lots_collection.find_one({
            '_id': slot['lot_id'],
            'admin_id': ObjectId(current_user.id)
        })
        
        if not lot:
            flash('Unauthorized action.', 'danger')
            return redirect(url_for('manage_slots'))
        
        # Rule 7: Cannot delete slot with active booking
        active_on_slot = bookings_collection.count_documents({
            'slot_id': slot['_id'],
            'status': 'active'
        })
        if active_on_slot > 0:
            flash('Cannot delete slot with an active booking. Please wait for checkout.', 'danger')
            return redirect(url_for('manage_slots'))
        
        parking_slots_collection.delete_one({'_id': ObjectId(slot_id)})
        flash('Slot deleted successfully!', 'success')
    except Exception as e:
        logger.error(f'Delete slot error: {str(e)}')
        flash('Failed to delete slot.', 'danger')
    
    return redirect(url_for('manage_slots'))

@app.route('/admin/lot/<lot_id>/watchman-credentials')
@login_required
@role_required('admin')
def watchman_credentials(lot_id):
    try:
        lot = parking_lots_collection.find_one({
            '_id': ObjectId(lot_id),
            'admin_id': ObjectId(current_user.id)
        })
        
        if not lot:
            return jsonify({'error': 'Lot not found or access denied'}), 403
        
        return jsonify({
            'username': lot.get('watchman_username', ''),
            'password': lot.get('watchman_plain_password', '')
        })
    except Exception as e:
        logger.error(f'Watchman credentials error: {str(e)}')
        return jsonify({'error': 'Failed to fetch credentials'}), 500

@app.route('/admin/lot-users')
@login_required
@role_required('admin')
def lot_users():
    lots = list(parking_lots_collection.find({'admin_id': ObjectId(current_user.id)}))
    lot_ids = [lot['_id'] for lot in lots]
    slot_ids = [slot['_id'] for slot in parking_slots_collection.find({'lot_id': {'$in': lot_ids}})]
    
    bookings = list(bookings_collection.find({'slot_id': {'$in': slot_ids}}))
    user_ids = list(set([b['user_id'] for b in bookings]))
    
    users = list(users_collection.find({'_id': {'$in': user_ids}}))
    
    for user in users:
        user['vehicles'] = list(vehicles_collection.find({'user_id': user['_id']}))
        user['booking_count'] = bookings_collection.count_documents({
            'user_id': user['_id'],
            'slot_id': {'$in': slot_ids}
        })
    
    return render_template('admin/lot_users.html', users=users)

@app.route('/admin/invoices')
@login_required
@role_required('admin')
def admin_invoices():
    page = request.args.get('page', 1, type=int)
    per_page = 10
    
    lots = list(parking_lots_collection.find({'admin_id': ObjectId(current_user.id)}))
    lot_ids = [lot['_id'] for lot in lots]
    slot_ids = [slot['_id'] for slot in parking_slots_collection.find({'lot_id': {'$in': lot_ids}})]
    booking_ids = [b['_id'] for b in bookings_collection.find({'slot_id': {'$in': slot_ids}})]
    
    total = invoices_collection.count_documents({'booking_id': {'$in': booking_ids}})
    invoices_list = list(invoices_collection.find({
        'booking_id': {'$in': booking_ids}
    }).sort('generated_at', DESCENDING).skip((page-1)*per_page).limit(per_page))
    
    for invoice in invoices_list:
        booking = bookings_collection.find_one({'_id': invoice['booking_id']})
        user = users_collection.find_one({'_id': invoice['user_id']})
        vehicle = vehicles_collection.find_one({'_id': booking['vehicle_id']})
        
        invoice['booking'] = booking
        invoice['user'] = user
        invoice['vehicle'] = vehicle
    
    total_pages = (total + per_page - 1) // per_page
    
    return render_template('admin/invoices.html',
                         invoices=invoices_list,
                         page=page,
                         total_pages=total_pages)

@app.route('/admin/watchman-audit')
@login_required
@role_required('admin')
def admin_watchman_audit():
    """Show all watchman cash/UPI collections for admin's lots, grouped by watchman with date filter."""
    admin_id = ObjectId(current_user.id)
    lots = list(parking_lots_collection.find({'admin_id': admin_id}))
    lot_ids = [lot['_id'] for lot in lots]
    
    from_date_str = request.args.get('from_date', '')
    to_date_str = request.args.get('to_date', '')
    
    query = {'lot_id': {'$in': lot_ids}}
    
    if from_date_str:
        try:
            from_date = datetime.strptime(from_date_str, '%Y-%m-%d')
            query['collected_at'] = {'$gte': from_date}
        except ValueError:
            pass
    if to_date_str:
        try:
            to_date = datetime.strptime(to_date_str, '%Y-%m-%d') + timedelta(days=1)
            if 'collected_at' in query:
                query['collected_at']['$lt'] = to_date
            else:
                query['collected_at'] = {'$lt': to_date}
        except ValueError:
            pass
    
    collections = list(watchman_collections_collection.find(query).sort('collected_at', DESCENDING))
    
    # Group by watchman
    watchman_groups = {}
    for c in collections:
        wid = str(c['watchman_id'])
        if wid not in watchman_groups:
            watchman_doc = users_collection.find_one({'_id': c['watchman_id']})
            lot_doc = parking_lots_collection.find_one({'_id': c['lot_id']})
            watchman_groups[wid] = {
                'watchman_name': watchman_doc['name'] if watchman_doc else 'Unknown',
                'watchman_email': watchman_doc['email'] if watchman_doc else '',
                'lot_name': lot_doc['name'] if lot_doc else 'Unknown',
                'total_cash': 0,
                'total_upi': 0,
                'count': 0,
                'records': []
            }
        grp = watchman_groups[wid]
        grp['count'] += 1
        if c['method'] == 'cash':
            grp['total_cash'] += c['amount']
        elif c['method'] == 'upi':
            grp['total_upi'] += c['amount']
        
        inv = invoices_collection.find_one({'_id': c['invoice_id']})
        vehicle_number = 'N/A'
        if inv:
            booking = bookings_collection.find_one({'_id': inv['booking_id']})
            if booking:
                v = vehicles_collection.find_one({'_id': booking['vehicle_id']})
                vehicle_number = v['vehicle_number'] if v else 'N/A'
        
        grp['records'].append({
            'amount': c['amount'],
            'method': c['method'],
            'vehicle_number': vehicle_number,
            'invoice_number': inv.get('invoice_number', 'N/A') if inv else 'N/A',
            'collected_at': c['collected_at'].strftime('%Y-%m-%d %H:%M:%S')
        })
    
    # Round totals
    for grp in watchman_groups.values():
        grp['total_cash'] = round(grp['total_cash'], 2)
        grp['total_upi'] = round(grp['total_upi'], 2)
        grp['total'] = round(grp['total_cash'] + grp['total_upi'], 2)
    
    grand_cash = round(sum(g['total_cash'] for g in watchman_groups.values()), 2)
    grand_upi = round(sum(g['total_upi'] for g in watchman_groups.values()), 2)
    
    return render_template('admin/watchman_audit.html',
                         watchman_groups=watchman_groups,
                         grand_cash=grand_cash,
                         grand_upi=grand_upi,
                         grand_total=round(grand_cash + grand_upi, 2),
                         from_date=from_date_str,
                         to_date=to_date_str)

@app.route('/admin/profile', methods=['GET', 'POST'])
@login_required
@role_required('admin')
def admin_profile():
    if request.method == 'POST':
        try:
            name = request.form.get('name', '').strip()
            
            update_data = {'name': name}
            
            if 'profile_image' in request.files:
                file = request.files['profile_image']
                if file and file.filename and allowed_file(file.filename):
                    filename = secure_filename(f"{current_user.id}_{file.filename}")
                    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
                    file.save(filepath)
                    update_data['profile_image'] = filename
            
            users_collection.update_one(
                {'_id': ObjectId(current_user.id)},
                {'$set': update_data}
            )
            
            flash('Profile updated successfully!', 'success')
            return redirect(url_for('admin_profile'))
        except Exception as e:
            logger.error(f'Profile update error: {str(e)}')
            flash('Failed to update profile.', 'danger')
    
    user = users_collection.find_one({'_id': ObjectId(current_user.id)})
    return render_template('admin/profile.html', user=user)

@app.route('/admin/subscriptions', methods=['GET', 'POST'])
@login_required
@role_required('admin')
def admin_subscriptions():
    admin_id = ObjectId(current_user.id)
    lots = list(parking_lots_collection.find({'admin_id': admin_id}))
    lot_ids = [lot['_id'] for lot in lots]

    if request.method == 'POST':
        action = request.form.get('action', 'create')

        if action == 'toggle':
            plan_id = request.form.get('plan_id')
            try:
                plan = subscription_plans_collection.find_one({
                    '_id': ObjectId(plan_id),
                    'lot_id': {'$in': lot_ids}
                })
                if plan:
                    new_status = not plan.get('active', True)
                    subscription_plans_collection.update_one(
                        {'_id': plan['_id']},
                        {'$set': {'active': new_status}}
                    )
                    flash(f'Plan {"activated" if new_status else "deactivated"} successfully.', 'success')
                else:
                    flash('Plan not found or access denied.', 'danger')
            except Exception as e:
                logger.error(f'Toggle subscription plan error: {str(e)}')
                flash('Failed to toggle plan status.', 'danger')
            return redirect(url_for('admin_subscriptions'))

        # Create new plan
        try:
            name = request.form.get('name', '').strip()
            duration_days = int(request.form.get('duration_days', 30))
            price = float(request.form.get('price', 0))
            vehicle_type = request.form.get('vehicle_type', '2-wheeler')
            lot_id = request.form.get('lot_id', '')

            if not name or price <= 0 or duration_days <= 0:
                flash('Please fill all fields with valid values.', 'danger')
                return redirect(url_for('admin_subscriptions'))

            if ObjectId(lot_id) not in lot_ids:
                flash('Invalid lot selected.', 'danger')
                return redirect(url_for('admin_subscriptions'))

            plan_data = {
                'name': name,
                'duration_days': duration_days,
                'price': round(price, 2),
                'vehicle_type': vehicle_type,
                'lot_id': ObjectId(lot_id),
                'admin_id': admin_id,
                'active': True,
                'created_at': now_ist()
            }
            subscription_plans_collection.insert_one(plan_data)
            flash(f'Subscription plan "{name}" created successfully!', 'success')
            logger.info(f'Subscription plan created: {name} by admin {current_user.email}')
        except Exception as e:
            logger.error(f'Create subscription plan error: {str(e)}')
            flash('Failed to create subscription plan.', 'danger')
        return redirect(url_for('admin_subscriptions'))

    # GET: show all plans for admin's lots
    plans = list(subscription_plans_collection.find({'lot_id': {'$in': lot_ids}}).sort('created_at', DESCENDING))
    for plan in plans:
        plan['lot'] = parking_lots_collection.find_one({'_id': plan['lot_id']})
        plan['subscriber_count'] = user_subscriptions_collection.count_documents({
            'plan_id': plan['_id'],
            'status': 'active'
        })

    return render_template('admin/subscriptions.html', plans=plans, lots=lots)

# Super Admin Routes
@app.route('/super-admin/dashboard')
@login_required
@role_required('super_admin')
def super_admin_dashboard():
    total_users = users_collection.count_documents({'role': 'user'})
    total_admins = users_collection.count_documents({'role': 'admin', 'verified': True})
    pending_admins = users_collection.count_documents({'role': 'admin', 'verified': False})
    total_lots = parking_lots_collection.count_documents({})
    total_slots = parking_slots_collection.count_documents({})
    total_bookings = bookings_collection.count_documents({})
    total_revenue = sum([inv['amount'] for inv in invoices_collection.find({})])
    
    recent_users = list(users_collection.find({'role': 'user'}).sort('created_at', DESCENDING).limit(10))
    recent_bookings = list(bookings_collection.find({}).sort('entry_time', DESCENDING).limit(10))
    
    for booking in recent_bookings:
        booking['user'] = users_collection.find_one({'_id': booking['user_id']})
        booking['slot'] = parking_slots_collection.find_one({'_id': booking['slot_id']})
        booking['vehicle'] = vehicles_collection.find_one({'_id': booking['vehicle_id']})
    
    return render_template('super_admin/dashboard.html',
                         total_users=total_users,
                         total_admins=total_admins,
                         pending_admins=pending_admins,
                         total_lots=total_lots,
                         total_slots=total_slots,
                         total_bookings=total_bookings,
                         total_revenue=total_revenue,
                         recent_users=recent_users,
                         recent_bookings=recent_bookings)

@app.route('/super-admin/manage-admins')
@login_required
@role_required('super_admin')
def manage_admins():
    unverified = list(users_collection.find({'role': 'admin', 'verified': False}))
    verified = list(users_collection.find({'role': 'admin', 'verified': True}))
    
    # Separate unverified into pending (new) and disabled (previously active)
    pending = []
    disabled = []
    for admin in unverified:
        verification = admin_verification_collection.find_one({'admin_id': admin['_id']})
        if verification and verification.get('status') == 'disabled':
            disabled.append(admin)
        else:
            pending.append(admin)
    
    for admin in pending + verified + disabled:
        admin['lots_count'] = parking_lots_collection.count_documents({'admin_id': admin['_id']})
    
    return render_template('super_admin/manage_admins.html',
                         pending_admins=pending,
                         verified_admins=verified,
                         disabled_admins=disabled)

@app.route('/super-admin/verify-admin/<admin_id>')
@login_required
@role_required('super_admin')
def verify_admin(admin_id):
    try:
        users_collection.update_one(
            {'_id': ObjectId(admin_id), 'role': 'admin'},
            {'$set': {'verified': True}}
        )
        
        admin_verification_collection.update_one(
            {'admin_id': ObjectId(admin_id)},
            {'$set': {
                'status': 'verified',
                'verified_by': ObjectId(current_user.id),
                'verified_at': now_ist()
            }}
        )
        
        flash('Admin verified successfully!', 'success')
        logger.info(f'Admin verified: {admin_id} by {current_user.email}')
    except Exception as e:
        logger.error(f'Verify admin error: {str(e)}')
        flash('Failed to verify admin.', 'danger')
    
    return redirect(url_for('manage_admins'))

@app.route('/super-admin/reject-admin/<admin_id>')
@login_required
@role_required('super_admin')
def reject_admin(admin_id):
    try:
        users_collection.delete_one({'_id': ObjectId(admin_id), 'role': 'admin'})
        admin_verification_collection.delete_one({'admin_id': ObjectId(admin_id)})
        
        flash('Admin registration rejected.', 'info')
        logger.info(f'Admin rejected: {admin_id} by {current_user.email}')
    except Exception as e:
        logger.error(f'Reject admin error: {str(e)}')
        flash('Failed to reject admin.', 'danger')
    
    return redirect(url_for('manage_admins'))

@app.route('/super-admin/disable-admin/<admin_id>')
@login_required
@role_required('super_admin')
def disable_admin(admin_id):
    try:
        users_collection.update_one(
            {'_id': ObjectId(admin_id), 'role': 'admin'},
            {'$set': {'verified': False}}
        )
        
        admin_verification_collection.update_one(
            {'admin_id': ObjectId(admin_id)},
            {'$set': {
                'status': 'disabled',
                'disabled_by': ObjectId(current_user.id),
                'disabled_at': now_ist()
            }}
        )
        
        flash('Admin has been disabled.', 'warning')
        logger.info(f'Admin disabled: {admin_id} by {current_user.email}')
    except Exception as e:
        logger.error(f'Disable admin error: {str(e)}')
        flash('Failed to disable admin.', 'danger')
    
    return redirect(url_for('manage_admins'))

@app.route('/super-admin/all-users')
@login_required
@role_required('super_admin')
def all_users():
    page = request.args.get('page', 1, type=int)
    per_page = 20
    search = request.args.get('search', '').strip()
    
    query = {'role': 'user'}
    if search:
        query['$or'] = [
            {'name': {'$regex': search, '$options': 'i'}},
            {'email': {'$regex': search, '$options': 'i'}}
        ]
    
    total = users_collection.count_documents(query)
    users = list(users_collection.find(query).skip((page-1)*per_page).limit(per_page))
    
    for user in users:
        user['vehicles_count'] = vehicles_collection.count_documents({'user_id': user['_id']})
        user['bookings_count'] = bookings_collection.count_documents({'user_id': user['_id']})
    
    total_pages = (total + per_page - 1) // per_page
    
    return render_template('super_admin/all_users.html',
                         users=users,
                         page=page,
                         total_pages=total_pages,
                         search=search)

@app.route('/super-admin/all-lots')
@login_required
@role_required('super_admin')
def all_lots():
    lots = list(parking_lots_collection.find({}))
    
    for lot in lots:
        lot['admin'] = users_collection.find_one({'_id': lot['admin_id']})
        lot['total_slots'] = parking_slots_collection.count_documents({'lot_id': lot['_id']})
        lot['occupied_slots'] = parking_slots_collection.count_documents({'lot_id': lot['_id'], 'status': 'occupied'})
    
    return render_template('super_admin/all_lots.html', lots=lots)

@app.route('/invoice/<invoice_id>')
@login_required
def view_invoice(invoice_id):
    try:
        invoice = invoices_collection.find_one({'_id': ObjectId(invoice_id)})
        if not invoice:
            flash('Invoice not found.', 'danger')
            return redirect(url_for('dashboard'))

        booking = bookings_collection.find_one({'_id': invoice['booking_id']})
        slot = parking_slots_collection.find_one({'_id': booking['slot_id']})
        lot = parking_lots_collection.find_one({'_id': slot['lot_id']})
        vehicle = vehicles_collection.find_one({'_id': booking['vehicle_id']})
        user = users_collection.find_one({'_id': invoice['user_id']})

        # Access control: invoice owner, admin of lot, watchman of lot, super_admin
        allowed = False
        if current_user.role == 'super_admin':
            allowed = True
        elif current_user.role == 'user' and str(invoice['user_id']) == current_user.id:
            allowed = True
        elif current_user.role == 'admin' and str(lot['admin_id']) == current_user.id:
            allowed = True
        elif current_user.role == 'watchman' and current_user.lot_id and current_user.lot_id == lot['_id']:
            allowed = True

        if not allowed:
            flash('Access denied.', 'danger')
            return render_template('errors/403.html'), 403

        return render_template('invoices/view.html',
                             invoice=invoice,
                             booking=booking,
                             slot=slot,
                             lot=lot,
                             vehicle=vehicle,
                             user=user)
    except Exception as e:
        logger.error(f'View invoice error: {str(e)}')
        flash('Failed to load invoice.', 'danger')
        return redirect(url_for('dashboard'))

@app.route('/super-admin/analytics')
@login_required
@role_required('super_admin')
def platform_analytics():
    # Platform revenue last 30 days
    platform_revenue = []
    for i in range(29, -1, -1):
        date = now_ist() - timedelta(days=i)
        start = date.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=1)
        day_invoices = list(invoices_collection.find({'generated_at': {'$gte': start, '$lt': end}}))
        revenue = sum([inv['amount'] for inv in day_invoices])
        platform_revenue.append({'date': start.strftime('%Y-%m-%d'), 'revenue': round(revenue, 2)})

    # Top 5 lots by revenue
    all_lots = list(parking_lots_collection.find({}))
    lot_revenue = []
    lot_bookings_count = []
    for lot in all_lots:
        lot_slot_ids = [s['_id'] for s in parking_slots_collection.find({'lot_id': lot['_id']})]
        lot_booking_ids = [b['_id'] for b in bookings_collection.find({'slot_id': {'$in': lot_slot_ids}})]
        rev = sum([inv['amount'] for inv in invoices_collection.find({'booking_id': {'$in': lot_booking_ids}})])
        lot_revenue.append({'lot_name': lot['name'], 'revenue': round(rev, 2)})
        lot_bookings_count.append({'lot_name': lot['name'], 'count': len(lot_booking_ids)})
    top_lots_revenue = sorted(lot_revenue, key=lambda x: x['revenue'], reverse=True)[:5]
    top_lots_bookings = sorted(lot_bookings_count, key=lambda x: x['count'], reverse=True)[:5]

    # User growth last 6 months
    user_growth = []
    for i in range(5, -1, -1):
        now = now_ist()
        month_start = (now.replace(day=1) - timedelta(days=i * 30)).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        if month_start.month == 12:
            month_end = month_start.replace(year=month_start.year + 1, month=1)
        else:
            month_end = month_start.replace(month=month_start.month + 1)
        count = users_collection.count_documents({
            'role': 'user',
            'created_at': {'$gte': month_start, '$lt': month_end}
        })
        user_growth.append({'month': month_start.strftime('%Y-%m'), 'count': count})

    # Booking type breakdown
    walkin_count = bookings_collection.count_documents({'booking_type': {'$exists': False}})
    walkin_count += bookings_collection.count_documents({'booking_type': 'walkin'})
    prebooked_count = bookings_collection.count_documents({'booking_type': 'prebook'})
    subscription_count = invoices_collection.count_documents({'payment_status': 'subscription'})
    noshow_count = bookings_collection.count_documents({'status': 'noshow'})
    booking_type_breakdown = {
        'walkin': walkin_count,
        'prebooked': prebooked_count,
        'subscription': subscription_count,
        'noshow': noshow_count
    }

    # Unpaid invoices older than 1 hour
    one_hour_ago = now_ist() - timedelta(hours=1)
    unpaid_raw = list(invoices_collection.find({
        'payment_status': {'$in': ['pending', 'unpaid']},
        'generated_at': {'$lt': one_hour_ago}
    }).sort('generated_at', DESCENDING).limit(50))
    unpaid_invoices = []
    for inv in unpaid_raw:
        u = users_collection.find_one({'_id': inv['user_id']})
        b = bookings_collection.find_one({'_id': inv['booking_id']})
        s = parking_slots_collection.find_one({'_id': b['slot_id']}) if b else None
        l = parking_lots_collection.find_one({'_id': s['lot_id']}) if s else None
        unpaid_invoices.append({
            'invoice_number': inv.get('invoice_number', ''),
            'amount': inv['amount'],
            'generated_at': inv['generated_at'].strftime('%Y-%m-%d %H:%M'),
            'user_name': u['name'] if u else 'Unknown',
            'user_email': u['email'] if u else '',
            'lot_name': l['name'] if l else 'Unknown'
        })

    return render_template('super_admin/platform_analytics.html',
                         platform_revenue=platform_revenue,
                         top_lots_revenue=top_lots_revenue,
                         top_lots_bookings=top_lots_bookings,
                         user_growth=user_growth,
                         booking_type_breakdown=booking_type_breakdown,
                         unpaid_invoices=unpaid_invoices)

@app.route('/admin/analytics')
@login_required
@role_required('admin')
def admin_analytics():
    admin_id = ObjectId(current_user.id)
    lots = list(parking_lots_collection.find({'admin_id': admin_id}))
    lot_ids = [lot['_id'] for lot in lots]
    slot_ids = [s['_id'] for s in parking_slots_collection.find({'lot_id': {'$in': lot_ids}})]

    # Revenue daily last 30 days
    booking_ids_all = [b['_id'] for b in bookings_collection.find({'slot_id': {'$in': slot_ids}})]
    revenue_daily = []
    for i in range(29, -1, -1):
        date = now_ist() - timedelta(days=i)
        start = date.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=1)
        day_inv = list(invoices_collection.find({
            'booking_id': {'$in': booking_ids_all},
            'generated_at': {'$gte': start, '$lt': end}
        }))
        rev = sum([inv['amount'] for inv in day_inv])
        revenue_daily.append({'date': start.strftime('%Y-%m-%d'), 'revenue': round(rev, 2)})

    # Peak hours
    all_bookings = list(bookings_collection.find({'slot_id': {'$in': slot_ids}, 'entry_time': {'$exists': True, '$ne': None}}))
    peak_hours = []
    hour_day_counts = {}
    for b in all_bookings:
        if b.get('entry_time'):
            h = b['entry_time'].hour
            d = b['entry_time'].weekday()
            key = (h, d)
            hour_day_counts[key] = hour_day_counts.get(key, 0) + 1
    for (h, d), cnt in hour_day_counts.items():
        peak_hours.append({'hour': h, 'day_of_week': d, 'count': cnt})
    peak_hours.sort(key=lambda x: x['count'], reverse=True)

    # Occupancy percent per lot
    occupancy_percent = []
    for lot in lots:
        total = parking_slots_collection.count_documents({'lot_id': lot['_id']})
        occupied = parking_slots_collection.count_documents({'lot_id': lot['_id'], 'status': 'occupied'})
        occupancy_percent.append({'lot_name': lot['name'], 'occupied': occupied, 'total': total})

    # Booking type breakdown for admin lots
    walkin = bookings_collection.count_documents({'slot_id': {'$in': slot_ids}, 'booking_type': {'$exists': False}})
    walkin += bookings_collection.count_documents({'slot_id': {'$in': slot_ids}, 'booking_type': 'walkin'})
    prebooked = bookings_collection.count_documents({'slot_id': {'$in': slot_ids}, 'booking_type': 'prebook'})
    sub_count = invoices_collection.count_documents({'booking_id': {'$in': booking_ids_all}, 'payment_status': 'subscription'})
    noshow = bookings_collection.count_documents({'slot_id': {'$in': slot_ids}, 'status': 'noshow'})
    booking_type_breakdown = {'walkin': walkin, 'prebooked': prebooked, 'subscription': sub_count, 'noshow': noshow}

    # Watchman collections per watchman
    watchman_collections_data = []
    watchmen = list(users_collection.find({'role': 'watchman', 'lot_id': {'$in': lot_ids}}))
    for w in watchmen:
        collections = list(watchman_collections_collection.find({'watchman_id': w['_id']}))
        total_cash = sum(c['amount'] for c in collections if c['method'] == 'cash')
        total_upi = sum(c['amount'] for c in collections if c['method'] == 'upi')
        watchman_collections_data.append({'name': w['name'], 'total_cash': round(total_cash, 2), 'total_upi': round(total_upi, 2)})

    return render_template('admin/analytics.html',
                         revenue_daily=revenue_daily,
                         peak_hours=peak_hours,
                         occupancy_percent=occupancy_percent,
                         booking_type_breakdown=booking_type_breakdown,
                         watchman_collections=watchman_collections_data)

@app.route('/user/analytics')
@login_required
@role_required('user')
def user_analytics():
    user_id = ObjectId(current_user.id)

    # Monthly spending last 6 months
    monthly_spending = []
    for i in range(5, -1, -1):
        now = now_ist()
        month_start = (now.replace(day=1) - timedelta(days=i * 30)).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        if month_start.month == 12:
            month_end = month_start.replace(year=month_start.year + 1, month=1)
        else:
            month_end = month_start.replace(month=month_start.month + 1)
        month_inv = list(invoices_collection.find({
            'user_id': user_id,
            'generated_at': {'$gte': month_start, '$lt': month_end}
        }))
        amount = sum([inv['amount'] for inv in month_inv])
        monthly_spending.append({'month': month_start.strftime('%Y-%m'), 'amount': round(amount, 2)})

    # Average duration
    completed = list(bookings_collection.find({'user_id': user_id, 'status': 'completed', 'entry_time': {'$ne': None}, 'exit_time': {'$ne': None}}))
    if completed:
        total_mins = sum([(b['exit_time'] - b['entry_time']).total_seconds() / 60 for b in completed])
        avg_duration_minutes = round(total_mins / len(completed), 1)
    else:
        avg_duration_minutes = 0

    # Most visited lot
    lot_visits = {}
    user_bookings = list(bookings_collection.find({'user_id': user_id}))
    for b in user_bookings:
        slot = parking_slots_collection.find_one({'_id': b['slot_id']})
        if slot:
            lid = str(slot['lot_id'])
            lot_visits[lid] = lot_visits.get(lid, 0) + 1
    most_visited_lot = {'name': 'N/A', 'count': 0}
    if lot_visits:
        top_lid = max(lot_visits, key=lot_visits.get)
        top_lot = parking_lots_collection.find_one({'_id': ObjectId(top_lid)})
        most_visited_lot = {'name': top_lot['name'] if top_lot else 'Unknown', 'count': lot_visits[top_lid]}

    # Booking type breakdown
    walkin = bookings_collection.count_documents({'user_id': user_id, 'booking_type': {'$exists': False}})
    walkin += bookings_collection.count_documents({'user_id': user_id, 'booking_type': 'walkin'})
    prebooked = bookings_collection.count_documents({'user_id': user_id, 'booking_type': 'prebook'})
    sub_count = invoices_collection.count_documents({'user_id': user_id, 'payment_status': 'subscription'})
    booking_type_breakdown = {'walkin': walkin, 'prebooked': prebooked, 'subscription': sub_count}

    # Total spent
    total_spent = sum([inv['amount'] for inv in invoices_collection.find({'user_id': user_id})])

    return render_template('user/analytics.html',
                         monthly_spending=monthly_spending,
                         avg_duration_minutes=avg_duration_minutes,
                         most_visited_lot=most_visited_lot,
                         booking_type_breakdown=booking_type_breakdown,
                         total_spent=round(total_spent, 2))

# Super Admin Management Routes
@app.route('/super-admin/delete-user/<user_id>', methods=['POST'])
@login_required
@role_required('super_admin')
def super_admin_delete_user(user_id):
    """Soft-delete a user by setting is_deleted=True."""
    try:
        user = users_collection.find_one({'_id': ObjectId(user_id)})
        if not user:
            flash('User not found.', 'danger')
            return redirect(url_for('all_users'))
        if user.get('role') == 'super_admin':
            flash('Cannot delete a super admin account.', 'danger')
            return redirect(url_for('all_users'))
        users_collection.update_one(
            {'_id': ObjectId(user_id)},
            {'$set': {'is_deleted': True, 'deleted_at': now_ist(), 'deleted_by': ObjectId(current_user.id)}}
        )
        logger.info(f'Super admin {current_user.email} soft-deleted user {user["email"]}')
        flash(f'User {user["name"]} ({user["email"]}) has been deactivated.', 'success')
    except Exception as e:
        logger.error(f'Delete user error: {str(e)}')
        flash('Failed to delete user.', 'danger')
    return redirect(url_for('all_users'))

@app.route('/super-admin/delete-lot/<lot_id>', methods=['POST'])
@login_required
@role_required('super_admin')
def super_admin_delete_lot(lot_id):
    """Delete a lot, its slots, cancel reserved bookings with refund, unverify watchmen."""
    try:
        lot = parking_lots_collection.find_one({'_id': ObjectId(lot_id)})
        if not lot:
            flash('Parking lot not found.', 'danger')
            return redirect(url_for('all_lots'))

        lot_oid = ObjectId(lot_id)
        lot_slot_ids = [s['_id'] for s in parking_slots_collection.find({'lot_id': lot_oid})]

        # Cancel all reserved/active bookings and refund hold_amount
        reserved_bookings = list(bookings_collection.find({
            'slot_id': {'$in': lot_slot_ids},
            'status': {'$in': ['reserved', 'active']}
        }))
        for booking in reserved_bookings:
            hold_amount = booking.get('hold_amount', 0)
            if hold_amount > 0:
                credit_wallet(
                    str(booking['user_id']), hold_amount,
                    'lot_deleted_refund', str(booking['_id'])
                )
            bookings_collection.update_one(
                {'_id': booking['_id']},
                {'$set': {'status': 'cancelled', 'cancelled_reason': 'lot_deleted', 'cancelled_at': now_ist()}}
            )
            # Free vehicle
            vehicles_collection.update_one(
                {'_id': booking['vehicle_id']},
                {'$set': {'currently_parked': False}}
            )

        # Unverify watchmen assigned to this lot
        users_collection.update_many(
            {'role': 'watchman', 'lot_id': lot_oid},
            {'$set': {'verified': False}}
        )

        # Delete all slots
        parking_slots_collection.delete_many({'lot_id': lot_oid})

        # Delete the lot
        parking_lots_collection.delete_one({'_id': lot_oid})

        logger.info(f'Super admin {current_user.email} deleted lot {lot["name"]} (ID: {lot_id})')
        flash(f'Parking lot "{lot["name"]}" and all associated data deleted. {len(reserved_bookings)} bookings cancelled with refunds.', 'success')
    except Exception as e:
        logger.error(f'Delete lot error: {str(e)}')
        flash('Failed to delete parking lot.', 'danger')
    return redirect(url_for('all_lots'))

@app.route('/super-admin/force-checkout/<booking_id>', methods=['GET', 'POST'])
@login_required
@role_required('super_admin')
def super_admin_force_checkout(booking_id):
    """Force-checkout an active booking with amount=0 and a logged reason."""
    try:
        booking = bookings_collection.find_one({'_id': ObjectId(booking_id)})
        if not booking:
            flash('Booking not found.', 'danger')
            return redirect(url_for('super_admin_dashboard'))
        if booking['status'] != 'active':
            flash('Only active bookings can be force-checked-out.', 'warning')
            return redirect(url_for('super_admin_dashboard'))

        slot = parking_slots_collection.find_one({'_id': booking['slot_id']})
        vehicle = vehicles_collection.find_one({'_id': booking['vehicle_id']})
        user = users_collection.find_one({'_id': booking['user_id']})
        lot = parking_lots_collection.find_one({'_id': slot['lot_id']}) if slot else None

        if request.method == 'POST':
            reason = request.form.get('reason', '').strip()
            if not reason:
                flash('Reason is required for force checkout.', 'danger')
                return render_template('super_admin/force_checkout.html',
                                     booking=booking, slot=slot, vehicle=vehicle, user=user, lot=lot)

            now = now_ist()

            # Complete the booking
            bookings_collection.update_one(
                {'_id': booking['_id']},
                {'$set': {'status': 'completed', 'exit_time': now, 'force_cleared': True, 'force_cleared_by': ObjectId(current_user.id)}}
            )

            # Free the slot
            if slot:
                parking_slots_collection.update_one(
                    {'_id': slot['_id']},
                    {'$set': {'status': 'available'}}
                )

            # Free the vehicle
            if vehicle:
                vehicles_collection.update_one(
                    {'_id': vehicle['_id']},
                    {'$set': {'currently_parked': False}}
                )

            # Create invoice with amount=0, payment_status=force_cleared
            invoices_collection.insert_one({
                'booking_id': booking['_id'],
                'user_id': booking['user_id'],
                'invoice_number': generate_invoice_number(),
                'amount': 0,
                'payment_status': 'force_cleared',
                'notes': reason,
                'force_cleared_by': ObjectId(current_user.id),
                'generated_at': now
            })

            logger.info(f'Super admin {current_user.email} force-checked-out booking {booking_id}. Reason: {reason}')
            flash('Booking force-checked-out successfully.', 'success')
            return redirect(url_for('super_admin_dashboard'))

        return render_template('super_admin/force_checkout.html',
                             booking=booking, slot=slot, vehicle=vehicle, user=user, lot=lot)
    except Exception as e:
        logger.error(f'Force checkout error: {str(e)}')
        flash('Failed to force checkout.', 'danger')
        return redirect(url_for('super_admin_dashboard'))

@app.route('/super-admin/wallet-adjust/<user_id>', methods=['GET', 'POST'])
@login_required
@role_required('super_admin')
def super_admin_wallet_adjust(user_id):
    """Manually credit or debit a user's wallet with a logged reason."""
    try:
        user = users_collection.find_one({'_id': ObjectId(user_id)})
        if not user:
            flash('User not found.', 'danger')
            return redirect(url_for('all_users'))

        if request.method == 'POST':
            adjustment_type = request.form.get('adjustment_type', '')
            amount = request.form.get('amount', 0, type=float)
            reason = request.form.get('reason', '').strip()

            if adjustment_type not in ('credit', 'debit'):
                flash('Invalid adjustment type.', 'danger')
                return render_template('super_admin/wallet_adjust.html', user=user)
            if amount <= 0:
                flash('Amount must be greater than zero.', 'danger')
                return render_template('super_admin/wallet_adjust.html', user=user)
            if not reason:
                flash('Reason is required.', 'danger')
                return render_template('super_admin/wallet_adjust.html', user=user)

            reference_id = f'manual_adj_{secrets.token_hex(4)}'
            reason_text = f'manual_adjustment: {reason}'

            if adjustment_type == 'credit':
                success = credit_wallet(str(user['_id']), amount, reason_text, reference_id)
            else:
                success = deduct_from_wallet(str(user['_id']), amount, reason_text, reference_id)

            if success:
                logger.info(f'Super admin {current_user.email} {adjustment_type}ed ₹{amount} for user {user["email"]}. Reason: {reason}')
                flash(f'Wallet {adjustment_type} of ₹{amount:.2f} applied successfully.', 'success')
            else:
                flash(f'Wallet {adjustment_type} failed. Check user balance for debits.', 'danger')

            return redirect(url_for('super_admin_wallet_adjust', user_id=user_id))

        return render_template('super_admin/wallet_adjust.html', user=user)
    except Exception as e:
        logger.error(f'Wallet adjust error: {str(e)}')
        flash('Failed to adjust wallet.', 'danger')
        return redirect(url_for('all_users'))

@app.route('/super-admin/watchman-collections')
@login_required
@role_required('super_admin')
def super_admin_watchman_collections():
    """View all watchman collections platform-wide with date filter, grouped by watchman."""
    try:
        date_from = request.args.get('date_from', '')
        date_to = request.args.get('date_to', '')

        query = {}
        if date_from:
            try:
                query['collected_at'] = {'$gte': datetime.strptime(date_from, '%Y-%m-%d')}
            except ValueError:
                pass
        if date_to:
            try:
                end_date = datetime.strptime(date_to, '%Y-%m-%d') + timedelta(days=1)
                if 'collected_at' in query:
                    query['collected_at']['$lt'] = end_date
                else:
                    query['collected_at'] = {'$lt': end_date}
            except ValueError:
                pass

        all_collections = list(watchman_collections_collection.find(query).sort('collected_at', DESCENDING))

        # Group by watchman
        grouped = {}
        for c in all_collections:
            wid = str(c['watchman_id'])
            if wid not in grouped:
                watchman = users_collection.find_one({'_id': c['watchman_id']})
                lot = parking_lots_collection.find_one({'_id': c.get('lot_id')}) if c.get('lot_id') else None
                grouped[wid] = {
                    'watchman_name': watchman['name'] if watchman else 'Unknown',
                    'watchman_email': watchman['email'] if watchman else '',
                    'lot_name': lot['name'] if lot else 'Unknown',
                    'collections': [],
                    'total_cash': 0,
                    'total_upi': 0
                }
            grouped[wid]['collections'].append(c)
            if c.get('method') == 'cash':
                grouped[wid]['total_cash'] += c.get('amount', 0)
            elif c.get('method') == 'upi':
                grouped[wid]['total_upi'] += c.get('amount', 0)

        return render_template('super_admin/watchman_collections.html',
                             grouped_collections=grouped,
                             date_from=date_from,
                             date_to=date_to)
    except Exception as e:
        logger.error(f'Watchman collections error: {str(e)}')
        flash('Failed to load watchman collections.', 'danger')
        return redirect(url_for('super_admin_dashboard'))

# Watchman Routes
@app.route('/watchman/dashboard')
@login_required
@role_required('watchman')
def watchman_dashboard():
    user_data = users_collection.find_one({'_id': ObjectId(current_user.id)})
    lot_id = user_data.get('lot_id')
    
    if not lot_id:
        flash('No lot assigned to this watchman.', 'danger')
        return redirect(url_for('index'))
    
    lot = parking_lots_collection.find_one({'_id': lot_id})
    if not lot:
        flash('Assigned lot not found.', 'danger')
        return redirect(url_for('index'))
    
    total_slots = parking_slots_collection.count_documents({'lot_id': lot_id})
    occupied = parking_slots_collection.count_documents({'lot_id': lot_id, 'status': 'occupied'})
    available = total_slots - occupied
    
    recent_logs = list(scan_logs_collection.find(
        {'lot_id': lot_id}
    ).sort('timestamp', DESCENDING).limit(10))
    
    for log in recent_logs:
        if log.get('vehicle_id'):
            vehicle = vehicles_collection.find_one({'_id': log['vehicle_id']})
            log['vehicle_number'] = vehicle['vehicle_number'] if vehicle else 'Unknown'
    
    return render_template('watchman/dashboard.html',
                         lot=lot,
                         total_slots=total_slots,
                         occupied=occupied,
                         available=available,
                         recent_logs=recent_logs)

@app.route('/watchman/scan-qr', methods=['POST'])
@login_required
@role_required('watchman')
def watchman_scan_qr():
    try:
        data = request.get_json()
        if not data or 'qr_data' not in data:
            return jsonify({'success': False, 'message': 'No QR data received'}), 400
        
        # Parse QR data
        try:
            qr_info = json.loads(data['qr_data'])
        except (json.JSONDecodeError, TypeError):
            return jsonify({'success': False, 'message': 'Invalid QR code format'}), 400
        
        vehicle_id = qr_info.get('vehicle_id')
        vehicle_number = qr_info.get('vehicle_number')
        qr_token = qr_info.get('qr_token')
        
        if not vehicle_id or not vehicle_number:
            return jsonify({'success': False, 'message': 'Incomplete QR code data'}), 400
        
        # Rule 3: Strict QR token validation
        # First look up the vehicle by ID and number
        vehicle = vehicles_collection.find_one({
            '_id': ObjectId(vehicle_id),
            'vehicle_number': vehicle_number
        })
        
        if not vehicle:
            scan_logs_collection.insert_one({
                'watchman_id': ObjectId(current_user.id),
                'lot_id': current_user.lot_id,
                'vehicle_id': None,
                'action': 'invalid_scan',
                'result_message': 'Invalid or tampered QR code',
                'timestamp': now_ist()
            })
            return jsonify({'success': False, 'message': 'Invalid or tampered QR code'})
        
        # Verify qr_token matches exactly — log as security alert if mismatch
        if not qr_token or vehicle.get('qr_token') != qr_token:
            scan_logs_collection.insert_one({
                'watchman_id': ObjectId(current_user.id),
                'lot_id': current_user.lot_id,
                'vehicle_id': vehicle['_id'],
                'action': 'invalid_scan',
                'alert': True,
                'result_message': f'SECURITY ALERT: QR token mismatch for vehicle {vehicle_number}',
                'timestamp': now_ist()
            })
            logger.warning(f'SECURITY ALERT: QR token mismatch for vehicle {vehicle_number} (ID: {vehicle_id})')
            return jsonify({'success': False, 'message': 'Invalid or tampered QR code'})
        
        watchman_lot_id = current_user.lot_id
        
        # Check for active booking
        active_booking = bookings_collection.find_one({
            'vehicle_id': vehicle['_id'],
            'status': 'active'
        })
        
        if active_booking:
            # CHECK-OUT LOGIC
            booking_lot_id = active_booking.get('checked_in_lot_id', active_booking.get('lot_id'))
            
            if booking_lot_id and booking_lot_id != watchman_lot_id:
                # Different lot
                other_lot = parking_lots_collection.find_one({'_id': booking_lot_id})
                other_lot_name = other_lot['name'] if other_lot else 'another lot'
                
                scan_logs_collection.insert_one({
                    'watchman_id': ObjectId(current_user.id),
                    'lot_id': watchman_lot_id,
                    'vehicle_id': vehicle['_id'],
                    'action': 'checkout_denied',
                    'result_message': f'Vehicle checked in at {other_lot_name}',
                    'timestamp': now_ist()
                })
                return jsonify({
                    'success': False,
                    'message': f'Vehicle checked in at a different lot ({other_lot_name}). Cannot check out here. Please contact that lot\'s watchman.'
                })
            
            # Same lot — proceed with checkout
            exit_time = now_ist()
            slot = parking_slots_collection.find_one({'_id': active_booking['slot_id']})
            
            duration_seconds = (exit_time - active_booking['entry_time']).total_seconds()
            hours = int(duration_seconds // 3600)
            minutes = int((duration_seconds % 3600) // 60)
            duration_str = f'{hours}h {minutes}m'
            
            # Check if vehicle has an active subscription at this lot
            if is_vehicle_subscribed(vehicle['_id'], watchman_lot_id):
                # Subscription active — free checkout
                bookings_collection.update_one(
                    {'_id': active_booking['_id']},
                    {'$set': {'exit_time': exit_time, 'status': 'completed', 'checked_out_by_watchman_id': ObjectId(current_user.id)}}
                )
                
                parking_slots_collection.update_one(
                    {'_id': slot['_id']},
                    {'$set': {'status': 'available'}}
                )
                
                vehicles_collection.update_one(
                    {'_id': vehicle['_id']},
                    {'$set': {'currently_parked': False}}
                )
                
                invoices_collection.insert_one({
                    'booking_id': active_booking['_id'],
                    'user_id': active_booking['user_id'],
                    'invoice_number': generate_invoice_number(),
                    'amount': 0,
                    'payment_status': 'subscription',
                    'generated_at': now_ist()
                })
                
                scan_logs_collection.insert_one({
                    'watchman_id': ObjectId(current_user.id),
                    'lot_id': watchman_lot_id,
                    'vehicle_id': vehicle['_id'],
                    'action': 'checkout',
                    'result_message': f'Checked out (subscription). Duration: {duration_str}, Fee: Rs.0',
                    'timestamp': now_ist()
                })
                
                logger.info(f'Watchman checkout (subscription): Vehicle {vehicle_number}, Slot {slot["slot_number"]}')
                return jsonify({
                    'success': True,
                    'action': 'checkout',
                    'slot_number': slot['slot_number'],
                    'duration': duration_str,
                    'fee': 0,
                    'message': f'Vehicle {vehicle_number} checked out (subscription). Duration: {duration_str}. Fee: Rs.0'
                })
            
            fee = calculate_parking_fee(active_booking['entry_time'], exit_time, slot['price_per_hour'])
            
            bookings_collection.update_one(
                {'_id': active_booking['_id']},
                {'$set': {'exit_time': exit_time, 'status': 'completed', 'checked_out_by_watchman_id': ObjectId(current_user.id)}}
            )
            
            parking_slots_collection.update_one(
                {'_id': slot['_id']},
                {'$set': {'status': 'available'}}
            )
            
            # Release currently_parked lock on vehicle
            vehicles_collection.update_one(
                {'_id': vehicle['_id']},
                {'$set': {'currently_parked': False}}
            )
            
            # Create invoice with PENDING status — payment collected separately
            invoice_data = {
                'booking_id': active_booking['_id'],
                'user_id': active_booking['user_id'],
                'invoice_number': generate_invoice_number(),
                'amount': fee,
                'payment_status': 'pending',
                'lot_id': watchman_lot_id,
                'watchman_id': ObjectId(current_user.id),
                'generated_at': now_ist()
            }
            invoice_id = invoices_collection.insert_one(invoice_data).inserted_id
            
            # Fetch user wallet balance for the response
            vehicle_owner = users_collection.find_one({'_id': active_booking['user_id']})
            user_wallet_balance = vehicle_owner.get('wallet_balance', 0.0) if vehicle_owner else 0.0
            shortfall = max(0, round(fee - user_wallet_balance, 2))
            
            scan_logs_collection.insert_one({
                'watchman_id': ObjectId(current_user.id),
                'lot_id': watchman_lot_id,
                'vehicle_id': vehicle['_id'],
                'action': 'checkout',
                'result_message': f'Checked out. Duration: {duration_str}, Fee: Rs.{fee} (payment pending)',
                'timestamp': now_ist()
            })
            
            logger.info(f'Watchman checkout: Vehicle {vehicle_number}, Slot {slot["slot_number"]}, Fee: {fee} (pending)')
            return jsonify({
                'success': True,
                'action': 'checkout_pending',
                'amount_due': fee,
                'user_wallet_balance': round(user_wallet_balance, 2),
                'shortfall': shortfall,
                'invoice_id': str(invoice_id),
                'vehicle_number': vehicle_number,
                'slot_number': slot['slot_number'],
                'duration': duration_str,
                'message': f'Vehicle {vehicle_number} checked out. Duration: {duration_str}. Fee: Rs.{fee} — awaiting payment.'
            })
        
        else:
            # CHECK-IN LOGIC
            now = now_ist()

            # --- Pre-book arrival handling ---
            # Look for a reserved booking for this vehicle at this lot
            reserved_booking = bookings_collection.find_one({
                'vehicle_id': vehicle['_id'],
                'lot_id': watchman_lot_id,
                'status': 'reserved'
            })
            if reserved_booking:
                booked_start = reserved_booking['booked_start']
                booked_end = reserved_booking['booked_end']
                earliest_allowed = booked_start - timedelta(minutes=15)

                if now < earliest_allowed:
                    # Too early — more than 15 mins before window
                    scan_logs_collection.insert_one({
                        'watchman_id': ObjectId(current_user.id),
                        'lot_id': watchman_lot_id,
                        'vehicle_id': vehicle['_id'],
                        'action': 'checkin_denied',
                        'result_message': f'Pre-booked vehicle arrived too early. Window starts at {booked_start.strftime("%H:%M")}',
                        'timestamp': now
                    })
                    return jsonify({
                        'success': False,
                        'message': f'Pre-booked slot window starts at {booked_start.strftime("%H:%M")}. You may arrive up to 15 minutes early.'
                    })

                if now > booked_end:
                    # Window has fully passed — reject
                    scan_logs_collection.insert_one({
                        'watchman_id': ObjectId(current_user.id),
                        'lot_id': watchman_lot_id,
                        'vehicle_id': vehicle['_id'],
                        'action': 'checkin_denied',
                        'result_message': f'Pre-booked window expired at {booked_end.strftime("%H:%M")}',
                        'timestamp': now
                    })
                    return jsonify({
                        'success': False,
                        'message': f'Pre-booked parking window has expired (ended at {booked_end.strftime("%H:%M")}). Please book again.'
                    })

                # Valid arrival window — activate the reserved booking on its pre-assigned slot
                reserved_slot = parking_slots_collection.find_one({'_id': reserved_booking['slot_id']})
                if not reserved_slot or reserved_slot.get('status') == 'occupied':
                    scan_logs_collection.insert_one({
                        'watchman_id': ObjectId(current_user.id),
                        'lot_id': watchman_lot_id,
                        'vehicle_id': vehicle['_id'],
                        'action': 'checkin_denied',
                        'result_message': 'Pre-booked slot is unexpectedly occupied',
                        'timestamp': now
                    })
                    return jsonify({
                        'success': False,
                        'message': 'Pre-booked slot is currently unavailable. Please contact support.'
                    })

                # Activate the booking
                bookings_collection.update_one(
                    {'_id': reserved_booking['_id']},
                    {'$set': {
                        'status': 'active',
                        'entry_time': now,
                        'checked_in_by_watchman_id': ObjectId(current_user.id)
                    }}
                )
                parking_slots_collection.update_one(
                    {'_id': reserved_slot['_id']},
                    {'$set': {'status': 'occupied'}}
                )
                vehicles_collection.update_one(
                    {'_id': vehicle['_id']},
                    {'$set': {'currently_parked': True}}
                )

                # Cancel the no-show scheduler job
                try:
                    scheduler.remove_job(f'noshow_{reserved_booking["_id"]}')
                except Exception:
                    pass

                scan_logs_collection.insert_one({
                    'watchman_id': ObjectId(current_user.id),
                    'lot_id': watchman_lot_id,
                    'vehicle_id': vehicle['_id'],
                    'action': 'checkin',
                    'result_message': f'Pre-booked check-in at slot {reserved_slot["slot_number"]}',
                    'timestamp': now
                })

                logger.info(f'Watchman pre-book checkin: Vehicle {vehicle_number}, Slot {reserved_slot["slot_number"]}')
                return jsonify({
                    'success': True,
                    'action': 'checkin',
                    'slot_number': reserved_slot['slot_number'],
                    'message': f'Vehicle {vehicle_number} checked in (pre-booked) at slot {reserved_slot["slot_number"]}'
                })

            # --- Walk-in check-in logic ---
            # Rule 2: Atomic currently_parked lock to prevent race conditions
            lock_result = vehicles_collection.find_one_and_update(
                {'_id': vehicle['_id'], 'currently_parked': {'$ne': True}},
                {'$set': {'currently_parked': True}}
            )
            if lock_result is None:
                # Vehicle is already parked somewhere — find where
                existing_active = bookings_collection.find_one({
                    'vehicle_id': vehicle['_id'],
                    'status': 'active'
                })
                parked_lot_name = 'another lot'
                if existing_active:
                    parked_lot = parking_lots_collection.find_one({'_id': existing_active.get('checked_in_lot_id', existing_active.get('lot_id'))})
                    parked_lot_name = parked_lot['name'] if parked_lot else 'another lot'
                scan_logs_collection.insert_one({
                    'watchman_id': ObjectId(current_user.id),
                    'lot_id': watchman_lot_id,
                    'vehicle_id': vehicle['_id'],
                    'action': 'checkin_denied',
                    'result_message': f'Vehicle already parked at {parked_lot_name}',
                    'timestamp': now
                })
                return jsonify({
                    'success': False,
                    'message': f'Vehicle is already parked at {parked_lot_name}. It must be checked out there first.'
                })
            
            # CHANGE 3: Return all available walk-in slots to watchman for selection
            available_slots = list(parking_slots_collection.find({
                'lot_id': watchman_lot_id,
                'slot_type': vehicle['vehicle_type'],
                'mode': 'walkin',
                'status': 'available'
            }).sort('slot_number', ASCENDING))

            if not available_slots:
                # Release the lock since we can't actually park
                vehicles_collection.update_one(
                    {'_id': vehicle['_id']},
                    {'$set': {'currently_parked': False}}
                )
                scan_logs_collection.insert_one({
                    'watchman_id': ObjectId(current_user.id),
                    'lot_id': watchman_lot_id,
                    'vehicle_id': vehicle['_id'],
                    'action': 'checkin_denied',
                    'result_message': f'No available walkin {vehicle["vehicle_type"]} slots',
                    'timestamp': now
                })
                return jsonify({
                    'success': False,
                    'message': f'No available walk-in {vehicle["vehicle_type"]} slots in this lot.'
                })

            # Slots are available — release the temporary lock now.
            # The actual lock will be re-acquired atomically in /watchman/checkin-assign-slot.
            vehicles_collection.update_one(
                {'_id': vehicle['_id']},
                {'$set': {'currently_parked': False}}
            )

            return jsonify({
                'success': True,
                'action': 'walkin_select_slot',
                'vehicle_id': str(vehicle['_id']),
                'vehicle_number': vehicle_number,
                'vehicle_type': vehicle['vehicle_type'],
                'slots': [{'slot_id': str(s['_id']), 'slot_number': s['slot_number']} for s in available_slots]
            })
    
    except Exception as e:
        logger.error(f'Watchman scan error: {str(e)}')
        return jsonify({'success': False, 'message': 'An error occurred processing the scan'}), 500

# CHANGE 4: Watchman assigns a specific slot and completes walk-in check-in
@app.route('/watchman/checkin-assign-slot', methods=['POST'])
@login_required
@role_required('watchman')
@csrf.exempt
def watchman_checkin_assign_slot():
    """Watchman selects a specific walk-in slot and checks the vehicle in atomically."""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'message': 'JSON body required.'}), 400

        vehicle_id = data.get('vehicle_id', '').strip()
        slot_id = data.get('slot_id', '').strip()

        if not vehicle_id or not slot_id:
            return jsonify({'success': False, 'message': 'vehicle_id and slot_id are required.'}), 400

        # 2. Find vehicle
        try:
            vehicle = vehicles_collection.find_one({'_id': ObjectId(vehicle_id)})
        except Exception:
            return jsonify({'success': False, 'message': 'Invalid vehicle_id.'}), 400
        if not vehicle:
            return jsonify({'success': False, 'message': 'Vehicle not found.'}), 404

        watchman_lot_id = current_user.lot_id

        # 3. Find and validate slot
        try:
            slot = parking_slots_collection.find_one({
                '_id': ObjectId(slot_id),
                'lot_id': watchman_lot_id,
                'mode': 'walkin',
                'status': 'available'
            })
        except Exception:
            return jsonify({'success': False, 'message': 'Invalid slot_id.'}), 400
        if not slot or slot.get('status') != 'available':
            return jsonify({'success': False, 'message': 'Slot is no longer available. Please select another.'})

        # 4. Atomic lock on vehicle
        lock_result = vehicles_collection.find_one_and_update(
            {'_id': vehicle['_id'], 'currently_parked': {'$ne': True}},
            {'$set': {'currently_parked': True}}
        )
        if lock_result is None:
            return jsonify({'success': False, 'message': 'Vehicle is already parked somewhere.'})

        # 5. Re-check slot is still available after acquiring vehicle lock
        slot_check = parking_slots_collection.find_one({'_id': ObjectId(slot_id), 'status': 'available'})
        if not slot_check:
            # Release vehicle lock
            vehicles_collection.update_one(
                {'_id': vehicle['_id']},
                {'$set': {'currently_parked': False}}
            )
            return jsonify({'success': False, 'message': 'Slot was just taken. Please select another slot.'})

        now = now_ist()

        # 6. Create walk-in booking
        booking_data = {
            'user_id': vehicle['user_id'],
            'slot_id': slot['_id'],
            'vehicle_id': vehicle['_id'],
            'lot_id': watchman_lot_id,
            'booking_type': 'walkin',
            'entry_time': now,
            'exit_time': None,
            'status': 'active',
            'checked_in_by_watchman_id': ObjectId(current_user.id),
            'checked_in_lot_id': watchman_lot_id,
            'created_at': now
        }
        bookings_collection.insert_one(booking_data)

        # 7. Update slot status to occupied
        parking_slots_collection.update_one(
            {'_id': slot['_id']},
            {'$set': {'status': 'occupied'}}
        )

        # 8. Insert scan log
        scan_logs_collection.insert_one({
            'watchman_id': ObjectId(current_user.id),
            'lot_id': watchman_lot_id,
            'vehicle_id': vehicle['_id'],
            'action': 'checkin',
            'result_message': f'Walk-in checked in at slot {slot["slot_number"]} (watchman slot selection)',
            'timestamp': now
        })

        logger.info(f'Watchman slot-assign checkin: Vehicle {vehicle["vehicle_number"]}, Slot {slot["slot_number"]}')

        # 9. Return success
        return jsonify({
            'success': True,
            'action': 'checkin',
            'slot_number': slot['slot_number'],
            'vehicle_number': vehicle['vehicle_number'],
            'message': f'Vehicle {vehicle["vehicle_number"]} checked in at slot {slot["slot_number"]}'
        })

    except Exception as e:
        logger.error(f'Checkin assign slot error: {str(e)}')
        return jsonify({'success': False, 'message': 'An error occurred during slot assignment.'}), 500

@app.route('/watchman/recent-scans')
@login_required
@role_required('watchman')
def watchman_recent_scans():
    try:
        logs = list(scan_logs_collection.find(
            {'lot_id': current_user.lot_id}
        ).sort('timestamp', DESCENDING).limit(20))
        
        result = []
        for log in logs:
            vehicle_number = ''
            if log.get('vehicle_id'):
                vehicle = vehicles_collection.find_one({'_id': log['vehicle_id']})
                vehicle_number = vehicle['vehicle_number'] if vehicle else 'Unknown'
            
            result.append({
                'action': log['action'],
                'vehicle_number': vehicle_number,
                'result_message': log['result_message'],
                'timestamp': log['timestamp'].strftime('%Y-%m-%d %H:%M:%S')
            })
        
        return jsonify(result)
    except Exception as e:
        logger.error(f'Recent scans error: {str(e)}')
        return jsonify([]), 500

@app.route('/watchman/invoice/pay/<invoice_id>', methods=['POST'])
@login_required
@role_required('watchman')
@csrf.exempt
def watchman_pay_invoice(invoice_id):
    """Collect payment for a pending checkout invoice. Accepts wallet/cash/upi."""
    try:
        data = request.get_json()
        if not data or 'payment_method' not in data:
            return jsonify({'success': False, 'message': 'payment_method is required (wallet/cash/upi)'}), 400
        
        payment_method = data['payment_method']
        if payment_method not in ('wallet', 'cash', 'upi'):
            return jsonify({'success': False, 'message': 'Invalid payment_method. Use wallet, cash, or upi.'}), 400
        
        invoice = invoices_collection.find_one({
            '_id': ObjectId(invoice_id),
            'payment_status': 'pending'
        })
        if not invoice:
            return jsonify({'success': False, 'message': 'Invoice not found or already paid.'}), 404
        
        amount = invoice['amount']
        user_id = invoice['user_id']
        
        if payment_method == 'wallet':
            success = deduct_from_wallet(
                user_id=str(user_id),
                amount=amount,
                reason='Parking fee (wallet)',
                reference_id=str(invoice['_id'])
            )
            if not success:
                user_doc = users_collection.find_one({'_id': user_id})
                wallet_balance = user_doc.get('wallet_balance', 0.0) if user_doc else 0.0
                shortfall = round(amount - wallet_balance, 2)
                return jsonify({
                    'success': False,
                    'message': f'Insufficient wallet balance. Shortfall: Rs.{shortfall}',
                    'shortfall': shortfall,
                    'wallet_balance': round(wallet_balance, 2)
                })
            invoices_collection.update_one(
                {'_id': invoice['_id']},
                {'$set': {'payment_status': 'paid_wallet', 'paid_at': now_ist()}}
            )
            # CHANGE 5: Update the matching 'payment pending' scan_log to reflect wallet payment
            recent_log = scan_logs_collection.find_one(
                {
                    'lot_id': current_user.lot_id,
                    'action': 'checkout',
                    'result_message': {'$regex': 'payment pending', '$options': 'i'}
                },
                sort=[('timestamp', DESCENDING)]
            )
            if recent_log:
                scan_logs_collection.update_one(
                    {'_id': recent_log['_id']},
                    {'$set': {'result_message': f'Checked out. Fee: Rs.{amount} — paid via wallet.'}}
                )
            logger.info(f'Invoice {invoice_id} paid via wallet')
            return jsonify({'success': True, 'message': f'Rs.{amount} deducted from wallet successfully.', 'payment_status': 'paid_wallet'})
        
        elif payment_method in ('cash', 'upi'):
            status_label = f'paid_{payment_method}'
            invoices_collection.update_one(
                {'_id': invoice['_id']},
                {'$set': {'payment_status': status_label, 'paid_at': now_ist()}}
            )
            watchman_collections_collection.insert_one({
                'watchman_id': ObjectId(current_user.id),
                'lot_id': current_user.lot_id,
                'invoice_id': invoice['_id'],
                'user_id': user_id,
                'amount': amount,
                'method': payment_method,
                'collected_at': now_ist()
            })
            logger.info(f'Invoice {invoice_id} paid via {payment_method}, collected by watchman {current_user.email}')
            return jsonify({'success': True, 'message': f'Rs.{amount} collected via {payment_method}.', 'payment_status': status_label})
    
    except Exception as e:
        logger.error(f'Watchman pay invoice error: {str(e)}')
        return jsonify({'success': False, 'message': 'An error occurred processing payment'}), 500

@app.route('/watchman/collections')
@login_required
@role_required('watchman')
def watchman_collections():
    """Show this watchman's cash/UPI collection log with optional date filter."""
    try:
        from_date_str = request.args.get('from_date', '')
        to_date_str = request.args.get('to_date', '')
        
        query = {'watchman_id': ObjectId(current_user.id)}
        
        if from_date_str:
            try:
                from_date = datetime.strptime(from_date_str, '%Y-%m-%d')
                query['collected_at'] = {'$gte': from_date}
            except ValueError:
                pass
        if to_date_str:
            try:
                to_date = datetime.strptime(to_date_str, '%Y-%m-%d') + timedelta(days=1)
                if 'collected_at' in query:
                    query['collected_at']['$lt'] = to_date
                else:
                    query['collected_at'] = {'$lt': to_date}
            except ValueError:
                pass
        
        collections = list(watchman_collections_collection.find(query).sort('collected_at', DESCENDING))
        
        for c in collections:
            inv = invoices_collection.find_one({'_id': c['invoice_id']})
            if inv:
                booking = bookings_collection.find_one({'_id': inv['booking_id']})
                vehicle = vehicles_collection.find_one({'_id': booking['vehicle_id']}) if booking else None
                c['invoice_number'] = inv.get('invoice_number', '')
                c['vehicle_number'] = vehicle['vehicle_number'] if vehicle else 'N/A'
            else:
                c['invoice_number'] = 'N/A'
                c['vehicle_number'] = 'N/A'
        
        total_cash = sum(c['amount'] for c in collections if c['method'] == 'cash')
        total_upi = sum(c['amount'] for c in collections if c['method'] == 'upi')
        
        return jsonify({
            'success': True,
            'total_cash': round(total_cash, 2),
            'total_upi': round(total_upi, 2),
            'total_collected': round(total_cash + total_upi, 2),
            'count': len(collections),
            'collections': [{
                'amount': c['amount'],
                'method': c['method'],
                'vehicle_number': c['vehicle_number'],
                'invoice_number': c['invoice_number'],
                'invoice_id': str(c['invoice_id']) if c.get('invoice_id') else '',
                'collected_at': c['collected_at'].strftime('%Y-%m-%d %H:%M:%S')
            } for c in collections]
        })
    except Exception as e:
        logger.error(f'Watchman collections error: {str(e)}')
        return jsonify({'success': False, 'message': 'Failed to fetch collections'}), 500

@app.route('/watchman/collections/page')
@login_required
@role_required('watchman')
def watchman_collections_page():
    """Render the watchman collections HTML page."""
    from_date = request.args.get('from_date', '')
    to_date = request.args.get('to_date', '')
    return render_template('watchman/collections.html',
                           from_date=from_date,
                           to_date=to_date)

# API Routes
@app.route('/api/slot-status/<lot_id>')
@login_required
def api_slot_status(lot_id):
    try:
        total = parking_slots_collection.count_documents({'lot_id': ObjectId(lot_id)})
        available = parking_slots_collection.count_documents({'lot_id': ObjectId(lot_id), 'status': 'available'})
        occupied = parking_slots_collection.count_documents({'lot_id': ObjectId(lot_id), 'status': 'occupied'})
        
        return jsonify({
            'total': total,
            'available': available,
            'occupied': occupied
        })
    except Exception as e:
        logger.error(f'API error: {str(e)}')
        return jsonify({'error': 'Failed to fetch slot status'}), 500

# Health check
@app.route('/health')
def health_check():
    return jsonify({'status': 'healthy'}), 200

# Error handlers
@app.errorhandler(404)
def not_found(error):
    return render_template('errors/404.html'), 404

@app.errorhandler(500)
def internal_error(error):
    logger.error(f'Internal error: {str(error)}')
    return render_template('errors/500.html'), 500

@app.errorhandler(403)
def forbidden(error):
    return render_template('errors/403.html'), 403

# Create super admin if not exists
def create_super_admin():
    super_admin = users_collection.find_one({'role': 'super_admin'})
    if not super_admin:
        hashed_password = bcrypt.generate_password_hash('superadmin123').decode('utf-8')
        users_collection.insert_one({
            'name': 'Super Admin',
            'email': 'superadmin@parking.com',
            'password': hashed_password,
            'role': 'super_admin',
            'verified': True,
            'wallet_balance': 0.0,
            'created_at': now_ist(),
            'profile_image': None
        })
        logger.info('Super admin created: superadmin@parking.com / superadmin123')

# No-show handler for APScheduler
def handle_noshow(booking_id):
    """Called 20 minutes after booked_start. If still reserved, mark as noshow."""
    try:
        booking = bookings_collection.find_one({
            '_id': ObjectId(booking_id),
            'status': 'reserved'
        })
        if not booking:
            return  # Already checked in, cancelled, or completed
        
        slot = parking_slots_collection.find_one({'_id': booking['slot_id']})
        price_per_hour = slot['price_per_hour'] if slot else 0
        
        # Charge for 20 minutes of occupancy
        noshow_fee = round(price_per_hour * (20 / 60), 2)
        hold_amount = booking.get('hold_amount', 0)
        refund_amount = round(hold_amount - noshow_fee, 2)
        
        if refund_amount > 0:
            credit_wallet(
                user_id=str(booking['user_id']),
                amount=refund_amount,
                reason=f'Partial refund - no-show (20-min fee: Rs.{noshow_fee})',
                reference_id=str(booking['_id'])
            )
        
        bookings_collection.update_one(
            {'_id': booking['_id']},
            {'$set': {
                'status': 'noshow',
                'noshow_fee': noshow_fee,
                'refund_amount': refund_amount,
                'noshow_at': now_ist()
            }}
        )
        
        # Free the slot back
        if slot:
            parking_slots_collection.update_one(
                {'_id': slot['_id']},
                {'$set': {'status': 'available'}}
            )
        
        logger.info(f'No-show processed: Booking {booking_id}, Fee: {noshow_fee}, Refund: {refund_amount}')
    except Exception as e:
        logger.error(f'No-show handler error for booking {booking_id}: {str(e)}')

def reschedule_noshow_jobs():
    """On startup, reschedule no-show jobs for all reserved bookings with future booked_start."""
    try:
        reserved_bookings = list(bookings_collection.find({
            'status': 'reserved',
            'booked_start': {'$gt': now_ist()}
        }))
        count = 0
        for booking in reserved_bookings:
            noshow_time = booking['booked_start'] + timedelta(minutes=20)
            if noshow_time > now_ist():
                scheduler.add_job(
                    func=handle_noshow,
                    trigger='date',
                    run_date=noshow_time,
                    args=[str(booking['_id'])],
                    id=f'noshow_{booking["_id"]}',
                    replace_existing=True
                )
                count += 1
        logger.info(f'Rescheduled {count} no-show jobs on startup')
    except Exception as e:
        logger.error(f'Reschedule noshow jobs error: {str(e)}')

# Rule 10: Migration — sync currently_parked flag on startup
def migrate_currently_parked():
    try:
        # Get all vehicle IDs that have an active booking
        active_vehicle_ids = bookings_collection.distinct('vehicle_id', {'status': 'active'})
        
        # Set currently_parked = True for vehicles with active bookings
        if active_vehicle_ids:
            vehicles_collection.update_many(
                {'_id': {'$in': active_vehicle_ids}},
                {'$set': {'currently_parked': True}}
            )
        
        # Set currently_parked = False for all other vehicles
        vehicles_collection.update_many(
            {'_id': {'$nin': active_vehicle_ids}},
            {'$set': {'currently_parked': False}}
        )
        
        logger.info(f'Migration: currently_parked synced for {len(active_vehicle_ids)} active vehicles')
    except Exception as e:
        logger.error(f'Migration currently_parked error: {str(e)}')

@app.context_processor
def inject_wallet_balance():
    balance = 0.0
    if current_user.is_authenticated and getattr(current_user, 'role', None) == 'user':
        try:
            user_doc = users_collection.find_one({'_id': ObjectId(current_user.id)})
            if user_doc:
                balance = user_doc.get('wallet_balance', 0.0)
        except Exception as e:
            logger.error(f"Context processor error: {str(e)}")
    return dict(wallet_balance=balance)

@app.route('/super-admin/unpaid-invoices')
@login_required
@role_required('super_admin')
def super_admin_unpaid_invoices():
    try:
        one_hour_ago = now_ist() - timedelta(hours=1)
        pending_raw = list(invoices_collection.find({
            'payment_status': {'$in': ['pending', 'unpaid']},
            'generated_at': {'$lt': one_hour_ago}
        }).sort('generated_at', ASCENDING))

        invoices_enriched = []
        for inv in pending_raw:
            booking = bookings_collection.find_one({'_id': inv['booking_id']})
            slot = parking_slots_collection.find_one({'_id': booking['slot_id']}) if booking else None
            lot = parking_lots_collection.find_one({'_id': slot['lot_id']}) if slot else None
            vehicle = vehicles_collection.find_one({'_id': booking['vehicle_id']}) if booking else None
            user = users_collection.find_one({'_id': inv['user_id']})
            age_hours = round((now_ist() - inv['generated_at']).total_seconds() / 3600, 1)
            invoices_enriched.append({
                '_id': inv['_id'],
                'invoice_number': inv.get('invoice_number', ''),
                'amount': inv['amount'],
                'generated_at': inv['generated_at'],
                'age_hours': age_hours,
                'booking': booking,
                'lot': lot,
                'vehicle': vehicle,
                'user': user
            })

        return render_template('super_admin/unpaid_invoices.html', invoices=invoices_enriched)
    except Exception as e:
        logger.error(f'Unpaid invoices error: {str(e)}')
        flash('Failed to load unpaid invoices.', 'danger')
        return redirect(url_for('super_admin_dashboard'))

# ─────────────────────────────────────────────────────────────
# SEO — Public utility routes (no auth required)
# ─────────────────────────────────────────────────────────────
@app.route('/robots.txt')
def robots_txt():
    content = (
        "User-agent: *\n"
        "Allow: /\n"
        "Allow: /user/parking-lots\n"
        "Disallow: /admin/\n"
        "Disallow: /super-admin/\n"
        "Disallow: /watchman/\n"
        "Disallow: /user/dashboard\n"
        "Disallow: /user/wallet\n"
        "Disallow: /user/my-bookings\n"
        "Sitemap: https://parking-management-afot.onrender.com/sitemap.xml\n"
    )
    return content, 200, {'Content-Type': 'text/plain; charset=utf-8'}

@app.route('/sitemap.xml')
def sitemap_xml():
    from flask import make_response
    content = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        '  <url><loc>https://parking-management-afot.onrender.com/</loc>'
        '<priority>1.0</priority><changefreq>weekly</changefreq></url>\n'
        '  <url><loc>https://parking-management-afot.onrender.com/auth/login</loc>'
        '<priority>0.8</priority><changefreq>monthly</changefreq></url>\n'
        '  <url><loc>https://parking-management-afot.onrender.com/auth/register</loc>'
        '<priority>0.8</priority><changefreq>monthly</changefreq></url>\n'
        '  <url><loc>https://parking-management-afot.onrender.com/user/parking-lots</loc>'
        '<priority>0.9</priority><changefreq>daily</changefreq></url>\n'
        '</urlset>'
    )
    resp = make_response(content)
    resp.headers['Content-Type'] = 'application/xml; charset=utf-8'
    return resp

if __name__ == '__main__':
    create_super_admin()
    migrate_currently_parked()
    reschedule_noshow_jobs()
    scheduler.start()
    app.run(debug=True, host='0.0.0.0', port=5000)
