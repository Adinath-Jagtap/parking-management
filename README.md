# Parking Management System

Production-ready parking management web application with user, admin, and super admin roles.

## Features

### User Features
- Register and login
- View available parking lots
- Manage vehicles
- Book parking slots
- View booking history
- Auto-generated invoices
- Multi-language support

### Admin Features
- Create and manage parking lots
- Add/edit/delete parking slots
- View lot users
- View lot-specific analytics
- Invoice management
- Profile management

### Super Admin Features
- Verify/reject admin registrations
- View all platform users
- View all parking lots
- Platform-wide analytics
- System monitoring

## Tech Stack

- **Backend**: Flask (Python)
- **Frontend**: HTML, Bootstrap 5 (CDN), Jinja2
- **Database**: MongoDB
- **Security**: bcrypt, Flask-WTF (CSRF), Flask-Login, Flask-Limiter

## Installation

### Prerequisites
- Python 3.8+
- MongoDB (local or Atlas)

### Setup Steps

1. Clone the repository:
```bash
git clone <repository-url>
cd parking-management
```

2. Create virtual environment:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

4. Configure environment:
```bash
cp .env.example .env
```

Edit `.env` file with your MongoDB Atlas credentials:
```
SECRET_KEY=your-random-secret-key-here
MONGO_URI=mongodb+srv://username:password@cluster0.xxxxx.mongodb.net/parking_management?retryWrites=true&w=majority
```

**Get MongoDB Atlas URI (FREE):**
1. Go to https://www.mongodb.com/cloud/atlas/register
2. Create free cluster (M0 - 512MB)
3. Database Access → Add user (save username/password)
4. Network Access → Add IP: 0.0.0.0/0
5. Cluster → Connect → Connect your application → Copy URI
6. Replace username, password, cluster name in MONGO_URI above

5. Create uploads directory:
```bash
mkdir -p static/uploads
```

6. Run the application:
```bash
python app.py
```

Application will be available at `http://localhost:5000`

## Default Super Admin Credentials

```
Email: superadmin@parking.com
Password: superadmin123
```

**Important**: Change these credentials immediately after first login!

## MongoDB Collections

The application automatically creates these collections:
- `users` - User accounts (user/admin/super_admin)
- `parking_lots` - Parking lot information
- `parking_slots` - Individual parking slots
- `vehicles` - User vehicles
- `bookings` - Parking bookings
- `invoices` - Generated invoices
- `admin_verification` - Admin verification status

## Project Structure

```
parking-management/
├── app.py                      # Main application file (all backend code)
├── templates/                  # HTML templates
│   ├── base.html
│   ├── index.html
│   ├── auth/
│   │   ├── login.html
│   │   ├── register.html
│   │   └── reset_password.html
│   ├── user/
│   │   ├── dashboard.html
│   │   ├── parking_lots.html
│   │   ├── my_vehicles.html
│   │   ├── book_slot.html
│   │   ├── my_bookings.html
│   │   ├── invoices.html
│   │   └── profile.html
│   ├── admin/
│   │   ├── dashboard.html
│   │   ├── manage_slots.html
│   │   ├── lot_users.html
│   │   ├── invoices.html
│   │   └── profile.html
│   ├── super_admin/
│   │   ├── dashboard.html
│   │   ├── manage_admins.html
│   │   ├── all_users.html
│   │   ├── all_lots.html
│   │   └── platform_analytics.html
│   └── errors/
│       ├── 403.html
│       ├── 404.html
│       └── 500.html
├── static/
│   └── uploads/                # Profile images
├── requirements.txt
├── .env.example
├── .gitignore
└── README.md
```

## API Endpoints

### Authentication
- `GET/POST /register` - User/admin registration
- `GET/POST /login` - Login
- `GET /logout` - Logout
- `GET/POST /reset-password` - Password reset

### User Routes
- `GET /user/dashboard` - User dashboard
- `GET /user/parking-lots` - View parking lots
- `GET/POST /user/vehicles` - Manage vehicles
- `GET/POST /user/book-slot/<lot_id>` - Book parking slot
- `GET /user/bookings` - Booking history
- `GET /user/booking/exit/<booking_id>` - Exit parking
- `GET /user/invoices` - View invoices
- `GET/POST /user/profile` - Update profile

### Admin Routes
- `GET /admin/dashboard` - Admin dashboard
- `GET/POST /admin/manage-slots` - Manage parking lots/slots
- `POST /admin/add-slot/<lot_id>` - Add new slot
- `GET /admin/delete-slot/<slot_id>` - Delete slot
- `GET /admin/lot-users` - View lot users
- `GET /admin/invoices` - View invoices
- `GET/POST /admin/profile` - Update profile

### Super Admin Routes
- `GET /super-admin/dashboard` - Super admin dashboard
- `GET /super-admin/manage-admins` - Manage admins
- `GET /super-admin/verify-admin/<admin_id>` - Verify admin
- `GET /super-admin/reject-admin/<admin_id>` - Reject admin
- `GET /super-admin/all-users` - View all users
- `GET /super-admin/all-lots` - View all parking lots
- `GET /super-admin/analytics` - Platform analytics

### API Routes
- `GET /api/slot-status/<lot_id>` - Real-time slot availability
- `GET /health` - Health check endpoint

## Security Features

- Bcrypt password hashing
- CSRF protection on all forms
- Rate limiting (200/day, 50/hour)
- SQL injection prevention (parameterized queries)
- Secure session management
- HTTP security headers
- File upload validation
- Secure filename handling
- Input validation and sanitization

## Deployment

### Using Gunicorn (Production)

```bash
gunicorn -w 4 -b 0.0.0.0:8000 app:app
```

### MongoDB Atlas Setup (Free Tier)

1. Create account at https://www.mongodb.com/cloud/atlas
2. Create free cluster (512MB)
3. Create database user
4. Whitelist IP (0.0.0.0/0 for development)
5. Get connection string
6. Update MONGO_URI in .env

### Render/Railway Deployment

1. Push code to GitHub
2. Connect repository to Render/Railway
3. Set environment variables:
   - SECRET_KEY
   - MONGO_URI
4. Deploy

## Configuration

### Environment Variables

```
SECRET_KEY=your-secret-key-here
MONGO_URI=mongodb://localhost:27017/parking_management
```

### Rate Limiting

Default: 200 requests per day, 50 per hour
Modify in app.py:
```python
limiter = Limiter(app=app, key_func=get_remote_address, 
                  default_limits=["200 per day", "50 per hour"])
```

### File Upload Limits

Max file size: 5MB
Allowed formats: jpg, jpeg, png, gif

## Troubleshooting

### MongoDB Connection Error
- Verify MongoDB is running
- Check MONGO_URI in .env
- For Atlas: whitelist your IP

### Port Already in Use
```bash
# Change port in app.py
app.run(debug=True, host='0.0.0.0', port=5001)
```

### Import Errors
```bash
pip install -r requirements.txt --upgrade
```

## License

MIT License

## Support

For issues and questions, please create an issue in the repository.