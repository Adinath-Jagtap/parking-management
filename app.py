import os
import logging
from datetime import datetime, timedelta
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
from flask_babel import Babel, gettext as _
from pymongo import MongoClient, ASCENDING, DESCENDING
from bson.objectid import ObjectId
from dotenv import load_dotenv
import secrets
import base64
from io import BytesIO
import json
import qrcode
import re

# Load environment variables
load_dotenv()

# Initialize Flask app
app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', secrets.token_hex(32))
app.config['MONGO_URI'] = os.getenv('MONGO_URI', 'mongodb://localhost:27017/parking_management')
app.config['UPLOAD_FOLDER'] = 'static/uploads'
app.config['MAX_CONTENT_LENGTH'] = 5 * 1024 * 1024  # 5MB max file size
app.config['BABEL_DEFAULT_LOCALE'] = 'en'
app.config['BABEL_TRANSLATION_DIRECTORIES'] = 'translations'
app.config['LANGUAGES'] = {'en': 'English', 'hi': 'Hindi', 'es': 'Spanish'}

# Security headers
@app.after_request
def set_security_headers(response):
    response.headers['X-Frame-Options'] = 'SAMEORIGIN'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    response.headers['Content-Security-Policy'] = "default-src 'self' https://cdn.jsdelivr.net https://cdnjs.cloudflare.com https://unpkg.com 'unsafe-inline'; media-src 'self' blob:; img-src 'self' data: blob:; worker-src 'self' blob:"
    return response

# Initialize extensions
csrf = CSRFProtect(app)
bcrypt = Bcrypt(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'
limiter = Limiter(app=app, key_func=get_remote_address, default_limits=["2000 per day", "500 per hour"])
babel = Babel()

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
        self.language = user_data.get('language', 'en')
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

def get_locale():
    if current_user.is_authenticated:
        return current_user.language
    return request.accept_languages.best_match(app.config['LANGUAGES'].keys())

babel.init_app(app, locale_selector=get_locale)

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

class ResetPasswordForm(FlaskForm):
    email = StringField('Email', validators=[DataRequired(), Email()])
    new_password = PasswordField('New Password', validators=[DataRequired(), Length(min=6)])
    confirm_password = PasswordField('Confirm Password', validators=[DataRequired(), EqualTo('new_password')])

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

class ParkingSlotForm(FlaskForm):
    slot_number = StringField('Slot Number', validators=[DataRequired(), Length(min=1, max=10)])
    slot_type = SelectField('Slot Type', choices=[('2-wheeler', '2-Wheeler'), ('4-wheeler', '4-Wheeler')], validators=[DataRequired()])
    price_per_hour = FloatField('Price per Hour', validators=[DataRequired(), NumberRange(min=0)])

class BookingForm(FlaskForm):
    vehicle_id = SelectField('Select Vehicle', validators=[DataRequired()])
    
# Helper functions
def allowed_file(filename):
    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def calculate_parking_fee(entry_time, exit_time, price_per_hour):
    duration = exit_time - entry_time
    hours = duration.total_seconds() / 3600
    return round(hours * price_per_hour, 2)

def generate_invoice_number():
    timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
    random_suffix = secrets.token_hex(3).upper()
    return f'INV-{timestamp}-{random_suffix}'

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
                'language': 'en',
                'created_at': datetime.now(),
                'profile_image': None
            }
            
            user_id = users_collection.insert_one(user_data).inserted_id
            
            if form.role.data == 'admin':
                admin_verification_collection.insert_one({
                    'admin_id': user_id,
                    'status': 'pending',
                    'verified_by': None,
                    'verified_at': None,
                    'created_at': datetime.now()
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

@app.route('/reset-password', methods=['GET', 'POST'])
@limiter.limit("100 per hour")
def reset_password():
    form = ResetPasswordForm()
    if form.validate_on_submit():
        try:
            user = users_collection.find_one({'email': form.email.data.lower()})
            if user:
                hashed_password = bcrypt.generate_password_hash(form.new_password.data).decode('utf-8')
                users_collection.update_one(
                    {'_id': user['_id']},
                    {'$set': {'password': hashed_password}}
                )
                flash('Password reset successful! Please log in.', 'success')
                logger.info(f'Password reset for: {form.email.data}')
                return redirect(url_for('login'))
            else:
                flash('Email not found.', 'danger')
        except Exception as e:
            logger.error(f'Password reset error: {str(e)}')
            flash('Password reset failed. Please try again.', 'danger')
    
    return render_template('auth/reset_password.html', form=form)

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
                'created_at': datetime.now()
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
                    'qr_generated_at': datetime.now()
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
        
        vehicles_collection.delete_one({'_id': vehicle['_id']})
        flash('Vehicle deleted successfully!', 'success')
    except Exception as e:
        logger.error(f'Delete vehicle error: {str(e)}')
        flash('Failed to delete vehicle.', 'danger')
    
    return redirect(url_for('my_vehicles'))

@app.route('/user/book-slot/<lot_id>', methods=['GET', 'POST'])
@login_required
@role_required('user')
def book_slot(lot_id):
    lot = parking_lots_collection.find_one({'_id': ObjectId(lot_id)})
    if not lot:
        flash('Parking lot not found.', 'danger')
        return redirect(url_for('parking_lots'))
    
    form = BookingForm()
    
    vehicles = list(vehicles_collection.find({'user_id': ObjectId(current_user.id)}))
    form.vehicle_id.choices = [(str(v['_id']), f"{v['vehicle_number']} ({v['vehicle_type']})") for v in vehicles]
    
    if not vehicles:
        flash('Please add a vehicle before booking.', 'warning')
        return redirect(url_for('my_vehicles'))
    
    if form.validate_on_submit():
        try:
            vehicle = vehicles_collection.find_one({'_id': ObjectId(form.vehicle_id.data)})
            
            # Rule 1: One active booking per vehicle (global)
            active_exists = bookings_collection.find_one({
                'vehicle_id': vehicle['_id'],
                'status': 'active'
            })
            if active_exists:
                flash('This vehicle is already parked. Please check out first.', 'danger')
                return redirect(url_for('book_slot', lot_id=lot_id))
            
            available_slot = parking_slots_collection.find_one({
                'lot_id': ObjectId(lot_id),
                'slot_type': vehicle['vehicle_type'],
                'status': 'available'
            })
            
            if not available_slot:
                flash('No available slots for your vehicle type.', 'danger')
                return redirect(url_for('book_slot', lot_id=lot_id))
            
            booking_data = {
                'user_id': ObjectId(current_user.id),
                'slot_id': available_slot['_id'],
                'vehicle_id': vehicle['_id'],
                'lot_id': ObjectId(lot_id),
                'entry_time': datetime.now(),
                'exit_time': None,
                'status': 'active',
                'checked_in_lot_id': ObjectId(lot_id),
                'created_at': datetime.now()
            }
            
            bookings_collection.insert_one(booking_data)
            
            parking_slots_collection.update_one(
                {'_id': available_slot['_id']},
                {'$set': {'status': 'occupied'}}
            )
            
            # Mark vehicle as currently parked
            vehicles_collection.update_one(
                {'_id': vehicle['_id']},
                {'$set': {'currently_parked': True}}
            )
            
            flash('Slot booked successfully!', 'success')
            logger.info(f'Booking created: User {current_user.email}, Slot {available_slot["slot_number"]}')
            return redirect(url_for('my_bookings'))
        except Exception as e:
            logger.error(f'Booking error: {str(e)}')
            flash('Booking failed. Please try again.', 'danger')
    
    available_slots = parking_slots_collection.count_documents({
        'lot_id': ObjectId(lot_id),
        'status': 'available'
    })
    
    slots_2w = parking_slots_collection.count_documents({
        'lot_id': ObjectId(lot_id),
        'slot_type': '2-wheeler',
        'status': 'available'
    })
    
    slots_4w = parking_slots_collection.count_documents({
        'lot_id': ObjectId(lot_id),
        'slot_type': '4-wheeler',
        'status': 'available'
    })
    
    return render_template('user/book_slot.html',
                         form=form,
                         lot=lot,
                         available_slots=available_slots,
                         slots_2w=slots_2w,
                         slots_4w=slots_4w)

@app.route('/user/bookings')
@login_required
@role_required('user')
def my_bookings():
    page = request.args.get('page', 1, type=int)
    per_page = 10
    
    total = bookings_collection.count_documents({'user_id': ObjectId(current_user.id)})
    bookings = list(bookings_collection.find({
        'user_id': ObjectId(current_user.id)
    }).sort('entry_time', DESCENDING).skip((page-1)*per_page).limit(per_page))
    
    for booking in bookings:
        booking['slot'] = parking_slots_collection.find_one({'_id': booking['slot_id']})
        booking['vehicle'] = vehicles_collection.find_one({'_id': booking['vehicle_id']})
        booking['lot'] = parking_lots_collection.find_one({'_id': booking['slot']['lot_id']})
    
    total_pages = (total + per_page - 1) // per_page
    
    return render_template('user/my_bookings.html',
                         bookings=bookings,
                         page=page,
                         total_pages=total_pages)

@app.route('/user/booking/exit/<booking_id>')
@login_required
@role_required('user')
def exit_booking(booking_id):
    try:
        booking = bookings_collection.find_one({
            '_id': ObjectId(booking_id),
            'user_id': ObjectId(current_user.id),
            'status': 'active'
        })
        
        if not booking:
            flash('Booking not found or already completed.', 'danger')
            return redirect(url_for('my_bookings'))
        
        exit_time = datetime.now()
        slot = parking_slots_collection.find_one({'_id': booking['slot_id']})
        
        amount = calculate_parking_fee(booking['entry_time'], exit_time, slot['price_per_hour'])
        
        bookings_collection.update_one(
            {'_id': booking['_id']},
            {'$set': {'exit_time': exit_time, 'status': 'completed'}}
        )
        
        parking_slots_collection.update_one(
            {'_id': slot['_id']},
            {'$set': {'status': 'available'}}
        )
        
        # Clear currently_parked flag on vehicle
        vehicles_collection.update_one(
            {'_id': booking['vehicle_id']},
            {'$set': {'currently_parked': False}}
        )
        
        invoice_data = {
            'booking_id': booking['_id'],
            'user_id': booking['user_id'],
            'invoice_number': generate_invoice_number(),
            'amount': amount,
            'payment_status': 'paid',
            'generated_at': datetime.now()
        }
        
        invoices_collection.insert_one(invoice_data)
        
        flash(f'Parking completed! Invoice generated. Amount: ₹{amount}', 'success')
        logger.info(f'Booking completed: {booking_id}')
        return redirect(url_for('invoices'))
    except Exception as e:
        logger.error(f'Exit booking error: {str(e)}')
        flash('Failed to complete booking.', 'danger')
        return redirect(url_for('my_bookings'))

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
            language = request.form.get('language', 'en')
            
            update_data = {'name': name, 'language': language}
            
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
    return render_template('user/profile.html', user=user, languages=app.config['LANGUAGES'])

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
                lot_data = {
                    'admin_id': ObjectId(current_user.id),
                    'name': lot_form.name.data.strip(),
                    'address': lot_form.address.data.strip(),
                    'pincode': lot_form.pincode.data.strip(),
                    'created_at': datetime.now()
                }
                lot_id = parking_lots_collection.insert_one(lot_data).inserted_id
                
                # Create slots based on admin-specified counts
                two_wheeler_count = lot_form.two_wheeler_slots.data
                two_wheeler_price = lot_form.two_wheeler_price.data
                four_wheeler_count = lot_form.four_wheeler_slots.data
                four_wheeler_price = lot_form.four_wheeler_price.data
                total_slots = two_wheeler_count + four_wheeler_count
                
                slots_to_create = []
                
                # Create 2-wheeler slots
                for i in range(1, two_wheeler_count + 1):
                    slots_to_create.append({
                        'lot_id': lot_id,
                        'slot_number': f'A{i}',
                        'slot_type': '2-wheeler',
                        'price_per_hour': two_wheeler_price,
                        'status': 'available',
                        'created_at': datetime.now()
                    })
                
                # Create 4-wheeler slots
                for i in range(1, four_wheeler_count + 1):
                    slots_to_create.append({
                        'lot_id': lot_id,
                        'slot_number': f'B{i}',
                        'slot_type': '4-wheeler',
                        'price_per_hour': four_wheeler_price,
                        'status': 'available',
                        'created_at': datetime.now()
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
                    'language': 'en',
                    'created_at': datetime.now(),
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
        
        slot_data = {
            'lot_id': ObjectId(lot_id),
            'slot_number': request.form.get('slot_number', '').strip(),
            'slot_type': request.form.get('slot_type'),
            'price_per_hour': float(request.form.get('price_per_hour', 0)),
            'status': 'available',
            'created_at': datetime.now()
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

@app.route('/admin/profile', methods=['GET', 'POST'])
@login_required
@role_required('admin')
def admin_profile():
    if request.method == 'POST':
        try:
            name = request.form.get('name', '').strip()
            language = request.form.get('language', 'en')
            
            update_data = {'name': name, 'language': language}
            
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
    return render_template('admin/profile.html', user=user, languages=app.config['LANGUAGES'])

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
                'verified_at': datetime.now()
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
                'disabled_at': datetime.now()
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

@app.route('/super-admin/analytics')
@login_required
@role_required('super_admin')
def platform_analytics():
    # Daily booking trends (last 7 days)
    booking_trends = []
    for i in range(6, -1, -1):
        date = datetime.now() - timedelta(days=i)
        start = date.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=1)
        count = bookings_collection.count_documents({
            'entry_time': {'$gte': start, '$lt': end}
        })
        booking_trends.append({'date': start.strftime('%Y-%m-%d'), 'count': count})
    
    # Revenue trends
    revenue_trends = []
    for i in range(6, -1, -1):
        date = datetime.now() - timedelta(days=i)
        start = date.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=1)
        invoices = list(invoices_collection.find({
            'generated_at': {'$gte': start, '$lt': end}
        }))
        revenue = sum([inv['amount'] for inv in invoices])
        revenue_trends.append({'date': start.strftime('%Y-%m-%d'), 'revenue': revenue})
    
    return render_template('super_admin/platform_analytics.html',
                         booking_trends=booking_trends,
                         revenue_trends=revenue_trends)

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
                'timestamp': datetime.now()
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
                'timestamp': datetime.now()
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
                    'timestamp': datetime.now()
                })
                return jsonify({
                    'success': False,
                    'message': f'Vehicle checked in at a different lot ({other_lot_name}). Cannot check out here. Please contact that lot\'s watchman.'
                })
            
            # Same lot — proceed with checkout
            exit_time = datetime.now()
            slot = parking_slots_collection.find_one({'_id': active_booking['slot_id']})
            fee = calculate_parking_fee(active_booking['entry_time'], exit_time, slot['price_per_hour'])
            
            duration_seconds = (exit_time - active_booking['entry_time']).total_seconds()
            hours = int(duration_seconds // 3600)
            minutes = int((duration_seconds % 3600) // 60)
            duration_str = f'{hours}h {minutes}m'
            
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
            
            invoices_collection.insert_one({
                'booking_id': active_booking['_id'],
                'user_id': active_booking['user_id'],
                'invoice_number': generate_invoice_number(),
                'amount': fee,
                'payment_status': 'paid',
                'generated_at': datetime.now()
            })
            
            scan_logs_collection.insert_one({
                'watchman_id': ObjectId(current_user.id),
                'lot_id': watchman_lot_id,
                'vehicle_id': vehicle['_id'],
                'action': 'checkout',
                'result_message': f'Checked out. Duration: {duration_str}, Fee: Rs.{fee}',
                'timestamp': datetime.now()
            })
            
            logger.info(f'Watchman checkout: Vehicle {vehicle_number}, Slot {slot["slot_number"]}, Fee: {fee}')
            return jsonify({
                'success': True,
                'action': 'checkout',
                'slot_number': slot['slot_number'],
                'duration': duration_str,
                'fee': fee,
                'message': f'Vehicle {vehicle_number} checked out. Duration: {duration_str}. Fee: Rs.{fee}'
            })
        
        else:
            # CHECK-IN LOGIC
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
                    'timestamp': datetime.now()
                })
                return jsonify({
                    'success': False,
                    'message': f'Vehicle is already parked at {parked_lot_name}. It must be checked out there first.'
                })
            
            # Find available slot matching vehicle type
            available_slot = parking_slots_collection.find_one({
                'lot_id': watchman_lot_id,
                'slot_type': vehicle['vehicle_type'],
                'status': 'available'
            })
            
            if not available_slot:
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
                    'result_message': f'No available {vehicle["vehicle_type"]} slots',
                    'timestamp': datetime.now()
                })
                return jsonify({
                    'success': False,
                    'message': f'No available {vehicle["vehicle_type"]} slots in this lot.'
                })
            
            # Create booking
            booking_data = {
                'user_id': vehicle['user_id'],
                'slot_id': available_slot['_id'],
                'vehicle_id': vehicle['_id'],
                'lot_id': watchman_lot_id,
                'entry_time': datetime.now(),
                'exit_time': None,
                'status': 'active',
                'checked_in_by_watchman_id': ObjectId(current_user.id),
                'checked_in_lot_id': watchman_lot_id,
                'created_at': datetime.now()
            }
            bookings_collection.insert_one(booking_data)
            
            parking_slots_collection.update_one(
                {'_id': available_slot['_id']},
                {'$set': {'status': 'occupied'}}
            )
            
            scan_logs_collection.insert_one({
                'watchman_id': ObjectId(current_user.id),
                'lot_id': watchman_lot_id,
                'vehicle_id': vehicle['_id'],
                'action': 'checkin',
                'result_message': f'Checked in at slot {available_slot["slot_number"]}',
                'timestamp': datetime.now()
            })
            
            logger.info(f'Watchman checkin: Vehicle {vehicle_number}, Slot {available_slot["slot_number"]}')
            return jsonify({
                'success': True,
                'action': 'checkin',
                'slot_number': available_slot['slot_number'],
                'message': f'Vehicle {vehicle_number} checked in at slot {available_slot["slot_number"]}'
            })
    
    except Exception as e:
        logger.error(f'Watchman scan error: {str(e)}')
        return jsonify({'success': False, 'message': 'An error occurred processing the scan'}), 500

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
            'language': 'en',
            'created_at': datetime.now(),
            'profile_image': None
        })
        logger.info('Super admin created: superadmin@parking.com / superadmin123')

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

if __name__ == '__main__':
    create_super_admin()
    migrate_currently_parked()
    app.run(debug=True, host='0.0.0.0', port=5000)
