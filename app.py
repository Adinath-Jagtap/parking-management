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
from io import BytesIO
import json

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
    response.headers['Content-Security-Policy'] = "default-src 'self' https://cdn.jsdelivr.net https://cdnjs.cloudflare.com 'unsafe-inline'"
    return response

# Initialize extensions
csrf = CSRFProtect(app)
bcrypt = Bcrypt(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'
limiter = Limiter(app=app, key_func=get_remote_address, default_limits=["200 per day", "50 per hour"])
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

# User class for Flask-Login
class User(UserMixin):
    def __init__(self, user_data):
        self.id = str(user_data['_id'])
        self.email = user_data['email']
        self.role = user_data['role']
        self.name = user_data['name']
        self.verified = user_data.get('verified', True)
        self.language = user_data.get('language', 'en')

@login_manager.user_loader
def load_user(user_id):
    user_data = users_collection.find_one({'_id': ObjectId(user_id)})
    if user_data:
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
    email = StringField('Email', validators=[DataRequired(), Email()])
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
    total_slots = IntegerField('Total Slots', validators=[DataRequired(), NumberRange(min=1, max=1000)])

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
@limiter.limit("5 per hour")
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
@limiter.limit("10 per hour")
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
@limiter.limit("3 per hour")
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
            vehicle_data = {
                'user_id': ObjectId(current_user.id),
                'vehicle_number': form.vehicle_number.data.upper().strip(),
                'vehicle_type': form.vehicle_type.data,
                'created_at': datetime.now()
            }
            vehicles_collection.insert_one(vehicle_data)
            flash('Vehicle added successfully!', 'success')
            return redirect(url_for('my_vehicles'))
        except Exception as e:
            logger.error(f'Add vehicle error: {str(e)}')
            flash('Failed to add vehicle.', 'danger')
    
    vehicles = list(vehicles_collection.find({'user_id': ObjectId(current_user.id)}))
    
    return render_template('user/my_vehicles.html', form=form, vehicles=vehicles)

@app.route('/user/vehicle/delete/<vehicle_id>')
@login_required
@role_required('user')
def delete_vehicle(vehicle_id):
    try:
        vehicles_collection.delete_one({
            '_id': ObjectId(vehicle_id),
            'user_id': ObjectId(current_user.id)
        })
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
                'entry_time': datetime.now(),
                'exit_time': None,
                'status': 'active',
                'created_at': datetime.now()
            }
            
            bookings_collection.insert_one(booking_data)
            
            parking_slots_collection.update_one(
                {'_id': available_slot['_id']},
                {'$set': {'status': 'occupied'}}
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
                
                # Auto-create slots based on total_slots value
                total_slots = lot_form.total_slots.data
                slots_to_create = []
                
                # Create 60% 2-wheeler slots and 40% 4-wheeler slots
                two_wheeler_count = int(total_slots * 0.6)
                four_wheeler_count = total_slots - two_wheeler_count
                
                slot_num = 1
                # Create 2-wheeler slots
                for i in range(two_wheeler_count):
                    slots_to_create.append({
                        'lot_id': lot_id,
                        'slot_number': f'A{slot_num}',
                        'slot_type': '2-wheeler',
                        'price_per_hour': 10.0,
                        'status': 'available',
                        'created_at': datetime.now()
                    })
                    slot_num += 1
                
                # Create 4-wheeler   slots
                slot_num = 1
                for i in range(four_wheeler_count):
                    slots_to_create.append({
                        'lot_id': lot_id,
                        'slot_number': f'B{slot_num}',
                        'slot_type': '4-wheeler',
                        'price_per_hour': 20.0,
                        'status': 'available',
                        'created_at': datetime.now()
                    })
                    slot_num += 1
                
                if slots_to_create:
                    parking_slots_collection.insert_many(slots_to_create)
                
                flash(f'Parking lot created with {total_slots} slots successfully!', 'success')
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
        lot = parking_lots_collection.find_one({
            '_id': slot['lot_id'],
            'admin_id': ObjectId(current_user.id)
        })
        
        if not lot:
            flash('Unauthorized action.', 'danger')
            return redirect(url_for('manage_slots'))
        
        parking_slots_collection.delete_one({'_id': ObjectId(slot_id)})
        flash('Slot deleted successfully!', 'success')
    except Exception as e:
        logger.error(f'Delete slot error: {str(e)}')
        flash('Failed to delete slot.', 'danger')
    
    return redirect(url_for('manage_slots'))

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
    pending = list(users_collection.find({'role': 'admin', 'verified': False}))
    verified = list(users_collection.find({'role': 'admin', 'verified': True}))
    
    for admin in pending + verified:
        admin['lots_count'] = parking_lots_collection.count_documents({'admin_id': admin['_id']})
    
    return render_template('super_admin/manage_admins.html',
                         pending_admins=pending,
                         verified_admins=verified)

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

if __name__ == '__main__':
    create_super_admin()
    app.run(debug=True, host='0.0.0.0', port=5000)
