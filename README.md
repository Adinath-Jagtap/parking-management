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
