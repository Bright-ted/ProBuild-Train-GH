from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
import os
from dotenv import load_dotenv
from supabase import create_client, Client
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
import random
from datetime import datetime, timedelta, timezone
import time
from werkzeug.utils import secure_filename

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "dev-key-123")

# Connect to Supabase
url = os.getenv("SUPABASE_URL")
key = os.getenv("SUPABASE_KEY")
supabase: Client = None

if url and key:
    try:
        supabase = create_client(url, key)
        print("✅ Connected to Supabase!")
    except Exception as e:
        print(f"❌ Supabase connection error: {e}")
        supabase = None
else:
    print("❌ Missing Supabase credentials")

# Helper functions
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'role' not in session or session['role'] != 'admin':
            flash("Admin access required", "error")
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated_function

def setup_admin_user():
    """Ensure admin user exists in database"""
    if supabase:
        try:
            # Check if admin exists
            existing = supabase.table('users').select("*").eq('email', 'ekpebright57@gmail.com').execute()
            if not existing.data:
                # Create admin user
                admin_data = {
                    "email": "ekpebright57@gmail.com",
                    "password": generate_password_hash("Br1ght47"),
                    "full_name": "Admin Bright",
                    "phone": "0551234567",
                    "role": "admin"
                }
                supabase.table('users').insert(admin_data).execute()
                print("✅ Admin user created in database")
        except Exception as e:
            print(f"❌ Error creating admin: {e}")

# Call this function when app starts (before first request)
@app.before_request
def initialize_admin():
    if not hasattr(app, 'admin_initialized'):
        setup_admin_user()
        app.admin_initialized = True

# ==========================================
# MAIN ROUTES
# ==========================================

@app.route('/')
def index():
    """Homepage - shows verified artisans"""
    search_query = request.args.get('q', '').strip()
    location_query = request.args.get('loc', '').strip()
    
    # Default artisans if database fails
    default_artisans = [
        {
            'id': 1,
            'full_name': 'Kofi Mensah',
            'trade': 'Carpenter',
            'location': 'East Legon',
            'price_range': 150,
            'rating': 4.8,
            'status': 'Available',
            'image_url': 'https://ui-avatars.com/api/?name=Kofi+Mensah&background=FF4500&color=fff'
        },
        {
            'id': 2,
            'full_name': 'Paul Osei',
            'trade': 'Plumber',
            'location': 'Madina',
            'price_range': 120,
            'rating': 4.5,
            'status': 'Available',
            'image_url': 'https://ui-avatars.com/api/?name=Paul+Osei&background=FF4500&color=fff'
        },
        {
            'id': 3,
            'full_name': 'Emmanuel Yeboah',
            'trade': 'Mason',
            'location': 'Kasoa',
            'price_range': 200,
            'rating': 4.9,
            'status': 'Busy',
            'image_url': 'https://ui-avatars.com/api/?name=Emmanuel+Yeboah&background=FF4500&color=fff'
        }
    ]
    
    artisans = default_artisans
    
    if supabase:
        try:
            query = supabase.table('artisans').select("*").eq('is_verified', True).eq('subscription_active', True)
            
            if search_query:
                query = query.ilike('trade', f'%{search_query}%')
            if location_query:
                query = query.ilike('location', f'%{location_query}%')
            
            response = query.execute()
            artisans = response.data if response.data else default_artisans
        except Exception as e:
            print(f"Database error: {e}")
            artisans = default_artisans
    
    return render_template('index.html', 
                         artisans=artisans, 
                         search_query=search_query, 
                         location_query=location_query)

@app.route('/book/<int:artisan_id>', methods=['GET', 'POST'])
def book_artisan(artisan_id):
    """Book an artisan"""
    if 'user_id' not in session:
        flash("Please login to book", "warning")
        return redirect(url_for('login'))
    
    # Get artisan details
    artisan = None
    if supabase:
        try:
            response = supabase.table('artisans').select("*").eq('id', artisan_id).eq('is_verified', True).execute()
            if response.data:
                artisan = response.data[0]
        except Exception as e:
            print(f"Error fetching artisan: {e}")
    
    if not artisan:
        flash("Artisan not found", "error")
        return redirect(url_for('index'))
    
    if request.method == 'POST':
        location = request.form.get('location')
        job_title = request.form.get('job_title')
        notify_others = request.form.get('notify_others') == 'on'
        
        try:
            # Create job booking
            job_data = {
                "client_id": session['user_id'],
                "artisan_id": artisan_id,
                "job_title": job_title,
                "location": location,
                "amount": artisan.get('price_range', 0),
                "status": "Pending",
                "notify_others": notify_others
            }
            
            if supabase:
                supabase.table('jobs').insert(job_data).execute()
            
            flash(f"Booking confirmed! GH₵ {job_data['amount']} held in escrow.", "success")
            return redirect(url_for('dashboard'))
        except Exception as e:
            flash(f"Booking failed: {e}", "error")
    
    return render_template('booking.html', artisan=artisan)

@app.route('/dashboard')
def dashboard():
    """User dashboard"""
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    # Redirect artisans to their portal
    if session['role'] == 'artisan':
        return redirect(url_for('artisan_dashboard'))
    
    # Get user info (for general users)
    user = {'full_name': session.get('user_name', 'User'), 'email': '', 'phone': ''}
    
    # Get user's jobs
    active_jobs = []
    history_jobs = []
    
    if supabase and session['role'] == 'general':
        try:
            # Get user details
            user_resp = supabase.table('users').select("*").eq('id', session['user_id']).execute()
            if user_resp.data:
                user = user_resp.data[0]
            
            # Get jobs for this user
            jobs_resp = supabase.table('jobs').select('*, artisans(full_name, trade)').eq('client_id', session['user_id']).execute()
            if jobs_resp.data:
                for job in jobs_resp.data:
                    job_data = {
                        'id': job['id'],
                        'title': job['job_title'],
                        'artisan': job['artisans']['full_name'] if job.get('artisans') else 'Unknown',
                        'trade': job['artisans']['trade'] if job.get('artisans') else 'General',
                        'date': job['created_at'][:10] if job.get('created_at') else '',
                        'status': job.get('status', 'Pending'),
                        'amount': job.get('amount', 0),
                        'rating': job.get('rating'),
                        'review': job.get('review')
                    }
                    
                    if job['status'] == 'Pending' or job['status'] == 'In Progress':
                        active_jobs.append(job_data)
                    else:
                        history_jobs.append(job_data)
        except Exception as e:
            print(f"Dashboard error: {e}")
    
    return render_template('dashboard.html', 
                         user=user, 
                         active_jobs=active_jobs, 
                         jobs=history_jobs)

@app.route('/complete_job/<int:job_id>', methods=['POST'])
def complete_job(job_id):
    """Mark job as complete with rating"""
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    try:
        rating = request.form.get('rating')
        review = request.form.get('review')
        
        if supabase:
            # Get job amount first
            job_resp = supabase.table('jobs').select('amount, artisan_id').eq('id', job_id).execute()
            if job_resp.data:
                job = job_resp.data[0]
                amount = job['amount']
                artisan_id = job['artisan_id']
                artisan_amount = amount * 0.85
                platform_commission = amount * 0.15
                
                # Update job status
                supabase.table('jobs').update({
                    "status": "Completed",
                    "rating": rating,
                    "review": review
                }).eq('id', job_id).execute()
                
                # Create payment record
                payment_data = {
                    "job_id": job_id,
                    "artisan_id": artisan_id,
                    "total_amount": amount,
                    "artisan_amount": artisan_amount,
                    "platform_commission": platform_commission,
                    "status": "Completed",
                    "client_id": session['user_id']
                }
                
                # Insert into payments table
                supabase.table('payments').insert(payment_data).execute()
        
        flash("Job completed and payment processed! 15% commission deducted.", "success")
    except Exception as e:
        flash(f"Error: {e}", "error")
    
    return redirect(url_for('dashboard'))

# ==========================================
# AUTHENTICATION ROUTES
# ==========================================

@app.route('/register', methods=['GET', 'POST'])
def register():
    """User registration"""
    if request.method == 'POST':
        full_name = request.form.get('full_name')
        email = request.form.get('email')
        phone = request.form.get('phone')
        password = request.form.get('password')
        
        if supabase:
            try:
                # Check if email exists
                existing = supabase.table('users').select("*").eq('email', email).execute()
                if existing.data:
                    flash("Email already registered", "error")
                    return redirect(url_for('register'))
                
                # Create user
                user_data = {
                    "full_name": full_name,
                    "email": email,
                    "phone": phone,
                    "password": generate_password_hash(password),
                    "role": "general"
                }
                
                supabase.table('users').insert(user_data).execute()
                flash("Account created! Please login.", "success")
                return redirect(url_for('login'))
            except Exception as e:
                flash(f"Registration error: {e}", "error")
        else:
            # Mock registration for demo
            flash("Account created! Please login.", "success")
            return redirect(url_for('login'))
    
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    """User login"""
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        
        # Admin login
        if email == 'ekpebright57@gmail.com' and password == 'Br1ght47':
            session['user_id'] = 999
            session['user_name'] = 'Admin Bright'
            session['role'] = 'admin'
            flash("Welcome Admin Bright!", "success")
            return redirect(url_for('admin_dashboard'))
        
        if supabase:
            try:
                # Check users table (general users)
                response = supabase.table('users').select("*").eq('email', email).execute()
                if response.data:
                    user = response.data[0]
                    if check_password_hash(user['password'], password):
                        session['user_id'] = user['id']
                        session['user_name'] = user['full_name']
                        session['role'] = user['role']
                        flash(f"Welcome back, {user['full_name']}!", "success")
                        return redirect(url_for('index'))
                    else:
                        flash("Invalid password", "error")
                else:
                    # Check artisans table (artisan login with phone)
                    response = supabase.table('artisans').select("*").eq('phone', email).execute()
                    if response.data:
                        artisan = response.data[0]
                        # Check password (plain text in your current setup)
                        if artisan['password'] == password:
                            session['user_id'] = artisan['id']
                            session['user_name'] = artisan['full_name']
                            session['role'] = 'artisan'
                            
                            # Check current status and redirect appropriately
                            if not artisan['is_verified']:
                                return redirect(url_for('pending_approval', stage='docs'))
                            elif not artisan['subscription_active']:
                                return redirect(url_for('pending_approval', stage='payment'))
                            else:
                                flash(f"Welcome back, {artisan['full_name']}!", "success")
                                return redirect(url_for('artisan_dashboard'))
                        else:
                            flash("Invalid password", "error")
                    else:
                        flash("Account not found", "error")
            except Exception as e:
                flash(f"Login error: {e}", "error")
        else:
            # Mock login for demo
            if email and password:
                session['user_id'] = 1
                session['user_name'] = 'Demo User'
                session['role'] = 'general'
                flash("Welcome!", "success")
                return redirect(url_for('index'))
    
    return render_template('login.html')

@app.route('/logout')
def logout():
    """Logout user"""
    session.clear()
    flash("Logged out successfully", "success")
    return redirect(url_for('index'))

@app.route('/artisan/check-status-page')
def check_status_page():
    """Redirect to appropriate pending page based on current status"""
    if 'user_id' not in session or session['role'] != 'artisan':
        return redirect(url_for('login'))
    
    if supabase:
        try:
            artisan_resp = supabase.table('artisans')\
                .select('is_verified, subscription_active')\
                .eq('id', session['user_id']).execute()
            
            if artisan_resp.data:
                artisan = artisan_resp.data[0]
                
                if not artisan['is_verified']:
                    return redirect(url_for('pending_approval', stage='docs'))
                elif not artisan['subscription_active']:
                    return redirect(url_for('pending_approval', stage='payment'))
                else:
                    return redirect(url_for('artisan_dashboard'))
        
        except Exception as e:
            print(f"Status check error: {e}")
    
    return redirect(url_for('pending_approval', stage='docs'))

# ==========================================
# ARTISAN ROUTES
# ==========================================

@app.route('/join-pro')
def join_pro():
    """Artisan registration page"""
    return render_template('artisan_register.html')

@app.route('/artisan/register', methods=['POST'])
def artisan_register():
    """Process artisan registration"""
    try:
        # Get form data
        full_name = request.form.get('full_name')
        phone = request.form.get('phone')
        password = request.form.get('password')
        ghana_card_number = request.form.get('ghana_card_number')
        
        # Handle trade
        trade_select = request.form.get('trade_select')
        custom_trade = request.form.get('custom_trade')
        trade = custom_trade if trade_select == 'Other' else trade_select
        
        region = request.form.get('region')
        town = request.form.get('town')
        digital_address = request.form.get('digital_address')
        
        # Price validation
        try:
            price_range = int(request.form.get('price_range', 0))
        except:
            price_range = 0
        
        if price_range > 500:
            flash("Base fee cannot exceed GH₵ 500", "error")
            return redirect(url_for('join_pro'))
        
        has_certificate = 'has_certificate' in request.form
        
        # Check if phone exists
        existing = None
        if supabase:
            existing = supabase.table('artisans').select("*").eq('phone', phone).execute()
        
        if existing and existing.data:
            flash("Phone number already registered", "error")
            return redirect(url_for('join_pro'))
        
        # Create artisan record
        artisan_data = {
            "full_name": full_name,
            "phone": phone,
            "password": password,
            "trade": trade,
            "region": region,
            "town": town,
            "digital_address": digital_address,
            "location": f"{town}, {region}",
            "price_range": price_range,
            "ghana_card_number": ghana_card_number,
            "has_certificate": has_certificate,
            "image_url": f"https://ui-avatars.com/api/?name={full_name.replace(' ', '+')}&background=FF4500&color=fff",
            "is_verified": False,
            "subscription_active": False,
            "status": "Available",
            "rating": 5.0
        }
        
        if supabase:
            result = supabase.table('artisans').insert(artisan_data).execute()
            if result.data:
                # Don't log them in automatically - just show success message
                flash("Registration submitted! Please login with your phone number to check status.", "success")
                return redirect(url_for('login'))
            else:
                flash("Registration failed. Please try again.", "error")
                return redirect(url_for('join_pro'))
        else:
            flash("Registration submitted! Please login with your phone number to check status.", "success")
            return redirect(url_for('login'))
        
    except Exception as e:
        flash(f"Registration error: {e}", "error")
        return redirect(url_for('join_pro'))

@app.route('/artisan/check-status')
def check_artisan_status():
    """API endpoint to check artisan verification and subscription status"""
    if 'user_id' not in session or session['role'] != 'artisan':
        return jsonify({'error': 'Not logged in as artisan'}), 401
    
    try:
        if supabase:
            artisan_resp = supabase.table('artisans')\
                .select('is_verified, subscription_active')\
                .eq('id', session['user_id']).execute()
            
            if artisan_resp.data:
                artisan = artisan_resp.data[0]
                return jsonify({
                    'is_verified': artisan['is_verified'],
                    'subscription_active': artisan['subscription_active']
                })
        
        return jsonify({'error': 'Artisan not found'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ==========================================
# ARTISAN SEPARATE PAGES ROUTES
# ==========================================

@app.route('/artisan/dashboard')
def artisan_dashboard():
    """Artisan main dashboard page"""
    if 'user_id' not in session or session['role'] != 'artisan':
        flash("Artisan access required", "error")
        return redirect(url_for('login'))
    
    return render_template('artisan_dashboard.html',
                         artisan=get_artisan_data(),
                         current_date=datetime.now().strftime('%d %b, %Y'),
                         **get_artisan_stats())

@app.route('/artisan/jobs')
def artisan_jobs():
    """Artisan available jobs page"""
    if 'user_id' not in session or session['role'] != 'artisan':
        flash("Artisan access required", "error")
        return redirect(url_for('login'))
    
    available_jobs = get_available_jobs()
    return render_template('artisan_jobs.html',
                         artisan=get_artisan_data(),
                         available_jobs=available_jobs,
                         available_jobs_count=len(available_jobs))

@app.route('/artisan/my-jobs')
def artisan_my_jobs():
    """Artisan my jobs page"""
    if 'user_id' not in session or session['role'] != 'artisan':
        flash("Artisan access required", "error")
        return redirect(url_for('login'))
    
    active_jobs, completed_jobs, pending_payments = get_my_jobs_data()
    return render_template('artisan_my_jobs.html',
                         artisan=get_artisan_data(),
                         active_jobs=active_jobs,
                         completed_jobs=completed_jobs,
                         pending_payments=pending_payments)

@app.route('/artisan/earnings')
def artisan_earnings():
    """Artisan earnings page"""
    if 'user_id' not in session or session['role'] != 'artisan':
        flash("Artisan access required", "error")
        return redirect(url_for('login'))
    
    return render_template('artisan_earnings.html',
                         artisan=get_artisan_data(),
                         **get_earnings_data())

@app.route('/artisan/location')
def artisan_location():
    """Artisan location page"""
    if 'user_id' not in session or session['role'] != 'artisan':
        flash("Artisan access required", "error")
        return redirect(url_for('login'))
    
    regions = [
        "Ahafo", "Ashanti", "Bono", "Bono East", "Central", "Eastern",
        "Greater Accra", "North East", "Northern", "Oti", "Savannah",
        "Upper East", "Upper West", "Volta", "Western", "Western North"
    ]
    
    return render_template('artisan_location.html',
                         artisan=get_artisan_data(),
                         regions=regions)

@app.route('/artisan/profile')
def artisan_profile():
    """Artisan profile page"""
    if 'user_id' not in session or session['role'] != 'artisan':
        flash("Artisan access required", "error")
        return redirect(url_for('login'))
    
    trades = [
        "Plumber", "Carpenter", "Electrician", "Mason", "Painter",
        "Welder", "AC Technician", "Tiler", "Steel Bender", "POP Designer"
    ]
    
    experience_levels = [
        "Less than 1 year", "1-3 years", "3-5 years", "5-10 years", "10+ years"
    ]
    
    return render_template('artisan_profile.html',
                         artisan=get_artisan_data(),
                         trades=trades,
                         experience_levels=experience_levels)

# Helper functions for artisan data
def get_artisan_data():
    """Get artisan data for templates"""
    if supabase:
        try:
            artisan_resp = supabase.table('artisans').select("*").eq('id', session['user_id']).execute()
            if artisan_resp.data:
                return artisan_resp.data[0]
        except Exception as e:
            print(f"Error getting artisan data: {e}")
    
    # Return default data if database fails
    return {
        'full_name': session.get('user_name', 'Artisan'),
        'trade': 'Carpenter',
        'phone': '0551234567',
        'rating': 4.8,
        'status': 'Available',
        'location': 'Accra, Ghana',
        'town': 'Accra',
        'region': 'Greater Accra',
        'image_url': f"https://ui-avatars.com/api/?name={session.get('user_name', 'Artisan')}&background=FF4500&color=fff",
        'is_verified': True,
        'subscription_active': True,
        'price_range': 150,
        'ghana_card_number': 'GHA-123456789-0',
        'has_certificate': True
    }

def get_artisan_stats():
    """Get artisan statistics"""
    stats = {
        'available_jobs_count': 0,
        'active_jobs_count': 0,
        'monthly_earnings': 0,
        'completed_jobs_count': 0,
        'recent_activities': []
    }
    
    if supabase:
        try:
            # Get available jobs count
            artisan = get_artisan_data()
            jobs_resp = supabase.table('jobs').select('id')\
                .eq('status', 'Pending')\
                .ilike('location', f'%{artisan["town"]}%')\
                .execute()
            stats['available_jobs_count'] = len(jobs_resp.data) if jobs_resp.data else 0
            
            # Get active jobs count
            active_resp = supabase.table('jobs').select('id')\
                .eq('artisan_id', session['user_id'])\
                .eq('status', 'In Progress')\
                .execute()
            stats['active_jobs_count'] = len(active_resp.data) if active_resp.data else 0
            
            # Get monthly earnings
            current_month = datetime.now().strftime('%Y-%m')
            earnings_resp = supabase.table('payments')\
                .select('artisan_amount')\
                .eq('artisan_id', session['user_id'])\
                .ilike('created_at', f'{current_month}%')\
                .execute()
            
            if earnings_resp.data:
                stats['monthly_earnings'] = sum(float(p['artisan_amount']) for p in earnings_resp.data)
            
            # Get completed jobs count
            completed_resp = supabase.table('jobs').select('id')\
                .eq('artisan_id', session['user_id'])\
                .eq('status', 'Completed')\
                .execute()
            stats['completed_jobs_count'] = len(completed_resp.data) if completed_resp.data else 0
            
            # Get recent activities (simplified)
            stats['recent_activities'] = [
                {'title': 'Job Completed', 'description': 'Fixed plumbing issue', 'time': '2 hours ago', 'amount': 150},
                {'title': 'New Job Accepted', 'description': 'Electrical wiring', 'time': 'Yesterday', 'amount': 200},
                {'title': 'Payment Received', 'description': 'For carpentry work', 'time': '2 days ago', 'amount': 180}
            ]
            
        except Exception as e:
            print(f"Error getting artisan stats: {e}")
    
    return stats

def get_available_jobs():
    """Get available jobs for artisan"""
    jobs = []
    
    if supabase:
        try:
            artisan = get_artisan_data()
            jobs_resp = supabase.table('jobs').select('*, users(full_name)')\
                .eq('status', 'Pending')\
                .ilike('location', f'%{artisan["town"]}%')\
                .execute()
            
            if jobs_resp.data:
                for job in jobs_resp.data:
                    jobs.append({
                        'id': job['id'],
                        'job_title': job['job_title'],
                        'location': job['location'],
                        'amount': job['amount'],
                        'distance': round(2 + (job['id'] % 5), 1),  # Simulated distance
                        'created_at': job['created_at'][:10] if job.get('created_at') else '',
                        'client_name': job['users']['full_name'] if job.get('users') else 'Client',
                        'notify_others': job.get('notify_others', False),
                        'category': job.get('category', 'General')
                    })
        except Exception as e:
            print(f"Error getting available jobs: {e}")
    
    return jobs

def get_my_jobs_data():
    """Get artisan's jobs data"""
    active_jobs = []
    completed_jobs = []
    pending_payments = []
    
    if supabase:
        try:
            # Get active jobs
            active_resp = supabase.table('jobs').select('*, users(full_name)')\
                .eq('artisan_id', session['user_id'])\
                .eq('status', 'In Progress')\
                .execute()
            
            if active_resp.data:
                for job in active_resp.data:
                    active_jobs.append({
                        'id': job['id'],
                        'job_title': job['job_title'],
                        'client_name': job['users']['full_name'] if job.get('users') else 'Client',
                        'location': job['location'],
                        'amount': job['amount'],
                        'start_date': job['created_at'][:10] if job.get('created_at') else ''
                    })
            
            # Get completed jobs
            completed_resp = supabase.table('jobs').select('*, users(full_name)')\
                .eq('artisan_id', session['user_id'])\
                .eq('status', 'Completed')\
                .execute()
            
            if completed_resp.data:
                for job in completed_resp.data:
                    completed_jobs.append({
                        'id': job['id'],
                        'job_title': job['job_title'],
                        'client_name': job['users']['full_name'] if job.get('users') else 'Client',
                        'location': job['location'],
                        'amount': job['amount'],
                        'completed_date': job.get('completed_at', job['created_at'])[:10] if job.get('completed_at') else job['created_at'][:10],
                        'rating': job.get('rating')
                    })
            
            # Get pending payments
            payments_resp = supabase.table('payments').select('*, jobs(job_title)')\
                .eq('artisan_id', session['user_id'])\
                .eq('status', 'Processing')\
                .execute()
            
            if payments_resp.data:
                for payment in payments_resp.data:
                    pending_payments.append({
                        'id': payment['id'],
                        'job_title': payment['jobs']['job_title'] if payment.get('jobs') else 'Unknown Job',
                        'amount': payment['artisan_amount'],
                        'status': payment['status'],
                        'expected_date': (datetime.now() + timedelta(days=2)).strftime('%Y-%m-%d')
                    })
                    
        except Exception as e:
            print(f"Error getting my jobs data: {e}")
    
    return active_jobs, completed_jobs, pending_payments

def get_earnings_data():
    """Get artisan earnings data"""
    data = {
        'total_earned': 0,
        'monthly_earnings': 0,
        'available_balance': 0,
        'recent_transactions': [],
        'transactions': []
    }
    
    if supabase:
        try:
            # Calculate total earned
            payments_resp = supabase.table('payments')\
                .select('artisan_amount, status, created_at')\
                .eq('artisan_id', session['user_id'])\
                .execute()
            
            if payments_resp.data:
                total_earned = 0
                current_month_earned = 0
                current_month = datetime.now().strftime('%Y-%m')
                
                for payment in payments_resp.data:
                    amount = float(payment['artisan_amount'])
                    total_earned += amount
                    
                    if payment.get('created_at') and payment['created_at'][:7] == current_month:
                        current_month_earned += amount
                    
                    # Add to transactions
                    data['transactions'].append({
                        'date': payment['created_at'][:10] if payment.get('created_at') else '',
                        'description': 'Job Payment',
                        'amount': f'GH₵ {amount:.2f}',
                        'status': payment['status'],
                        'type': 'credit'
                    })
                
                data['total_earned'] = int(total_earned)
                data['monthly_earnings'] = int(current_month_earned)
                data['available_balance'] = int(total_earned * 0.8)  # 80% available for withdrawal
            
            # Recent transactions (last 5)
            data['recent_transactions'] = data['transactions'][:5] if len(data['transactions']) > 5 else data['transactions']
            
        except Exception as e:
            print(f"Error getting earnings data: {e}")
    
    return data

# Add route for updating profile
@app.route('/artisan/update-profile', methods=['POST'])
def update_artisan_profile():
    """Update artisan profile"""
    if 'user_id' not in session or session['role'] != 'artisan':
        return jsonify({'error': 'Unauthorized'}), 401
    
    try:
        data = request.get_json()
        
        if supabase:
            supabase.table('artisans').update({
                'full_name': data.get('full_name'),
                'phone': data.get('phone'),
                'trade': data.get('trade'),
                'price_range': data.get('price_range'),
                'bio': data.get('bio'),
                'experience': data.get('experience')
            }).eq('id', session['user_id']).execute()
        
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# Add route for updating location from location page
@app.route('/artisan/update-location-full', methods=['POST'])
def update_artisan_location_full():
    """Update artisan location from location page"""
    if 'user_id' not in session or session['role'] != 'artisan':
        return jsonify({'error': 'Unauthorized'}), 401
    
    try:
        data = request.get_json()
        
        if supabase:
            supabase.table('artisans').update({
                'location': data.get('address'),
                'town': data.get('town'),
                'region': data.get('region'),
                'digital_address': data.get('gps')
            }).eq('id', session['user_id']).execute()
        
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# Add route for updating coverage distance
@app.route('/artisan/update-coverage-distance', methods=['POST'])
def update_coverage_distance():
    """Update artisan's coverage distance preference"""
    if 'user_id' not in session or session['role'] != 'artisan':
        return jsonify({'error': 'Unauthorized'}), 401
    
    try:
        data = request.get_json()
        distance = data.get('distance')
        
        # Store this preference (you might need a new table for user preferences)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# Add route for job details
@app.route('/artisan/job-details/<int:job_id>')
def job_details(job_id):
    """Get job details for modal"""
    if 'user_id' not in session or session['role'] != 'artisan':
        return jsonify({'error': 'Unauthorized'}), 401
    
    try:
        job_data = {}
        if supabase:
            job_resp = supabase.table('jobs').select('*, users(full_name)').eq('id', job_id).execute()
            if job_resp.data:
                job = job_resp.data[0]
                job_data = {
                    'job_title': job['job_title'],
                    'client_name': job['users']['full_name'] if job.get('users') else 'Client',
                    'location': job['location'],
                    'amount': job['amount'],
                    'created_at': job['created_at'][:10] if job.get('created_at') else '',
                    'description': job.get('description', 'No additional details provided.')
                }
        
        return jsonify({'success': True, 'job': job_data})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# Add route for job history
@app.route('/artisan/job-history/<int:job_id>')
def job_history(job_id):
    """Get job history details"""
    if 'user_id' not in session or session['role'] != 'artisan':
        return jsonify({'error': 'Unauthorized'}), 401
    
    try:
        job_data = {}
        if supabase:
            job_resp = supabase.table('jobs').select('*, users(full_name)').eq('id', job_id).execute()
            if job_resp.data:
                job = job_resp.data[0]
                job_data = {
                    'job_title': job['job_title'],
                    'client_name': job['users']['full_name'] if job.get('users') else 'Client',
                    'location': job['location'],
                    'amount': job['amount'],
                    'completed_date': job.get('completed_at', job['created_at'])[:10] if job.get('completed_at') else job['created_at'][:10],
                    'rating': job.get('rating')
                }
        
        return jsonify({'success': True, 'job': job_data})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ==========================================
# ARTISAN ACTION ROUTES (from original portal)
# ==========================================

@app.route('/artisan/accept-job/<int:job_id>', methods=['POST'])
def accept_job(job_id):
    """Artisan accepts a job"""
    if 'user_id' not in session or session['role'] != 'artisan':
        return jsonify({'error': 'Unauthorized'}), 401
    
    try:
        if supabase:
            # Update job status and assign artisan
            supabase.table('jobs').update({
                'artisan_id': session['user_id'],
                'status': 'In Progress',
                'assigned_at': 'now()'
            }).eq('id', job_id).execute()
            
            # Notify client
            job_resp = supabase.table('jobs').select('client_id').eq('id', job_id).execute()
            if job_resp.data:
                client_id = job_resp.data[0]['client_id']
                notification_data = {
                    'user_id': client_id,
                    'title': 'Job Accepted',
                    'message': f'An artisan has accepted your job request.',
                    'type': 'job_update'
                }
                supabase.table('notifications').insert(notification_data).execute()
        
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/artisan/decline-job/<int:job_id>', methods=['POST'])
def decline_job(job_id):
    """Artisan declines a job - makes it available to others"""
    if 'user_id' not in session or session['role'] != 'artisan':
        return jsonify({'error': 'Unauthorized'}), 401
    
    try:
        if supabase:
            # Remove artisan assignment but keep job available
            supabase.table('jobs').update({
                'artisan_id': None,
                'status': 'Pending',
                'declined_by': session['user_id']
            }).eq('id', job_id).execute()
            
            # Notify other artisans in same area (simplified)
            job_resp = supabase.table('jobs').select('location').eq('id', job_id).execute()
            if job_resp.data:
                job_location = job_resp.data[0]['location']
                # In real app, you would notify nearby artisans here
        
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/artisan/complete-job/<int:job_id>', methods=['POST'])
def artisan_complete_job(job_id):
    """Artisan marks job as complete"""
    if 'user_id' not in session or session['role'] != 'artisan':
        return jsonify({'error': 'Unauthorized'}), 401
    
    try:
        if supabase:
            # Get job details
            job_resp = supabase.table('jobs').select('amount, client_id').eq('id', job_id).execute()
            if job_resp.data:
                job = job_resp.data[0]
                amount = job['amount']
                artisan_amount = amount * 0.85
                platform_commission = amount * 0.15
                
                # Update job status
                supabase.table('jobs').update({
                    'status': 'Completed',
                    'completed_at': 'now()'
                }).eq('id', job_id).execute()
                
                # Record payment
                payment_data = {
                    'job_id': job_id,
                    'artisan_id': session['user_id'],
                    'client_id': job['client_id'],
                    'total_amount': amount,
                    'artisan_amount': artisan_amount,
                    'platform_commission': platform_commission,
                    'status': 'Processing'
                }
                supabase.table('payments').insert(payment_data).execute()
                
                # Notify client
                notification_data = {
                    'user_id': job['client_id'],
                    'title': 'Job Completed',
                    'message': f'Your job has been marked as complete by the artisan.',
                    'type': 'job_complete'
                }
                supabase.table('notifications').insert(notification_data).execute()
        
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/artisan/upload-profile-image', methods=['POST'])
def upload_profile_image():
    """Upload profile image for admin approval"""
    if 'user_id' not in session or session['role'] != 'artisan':
        return jsonify({'error': 'Unauthorized'}), 401
    
    try:
        if 'image' not in request.files:
            return jsonify({'error': 'No image file'}), 400
        
        file = request.files['image']
        if file.filename == '':
            return jsonify({'error': 'No selected file'}), 400
        
        # Generate unique filename
        filename = f"artisan_{session['user_id']}_{int(time.time())}_{secure_filename(file.filename)}"
        
        # In production, upload to your Supabase bucket
        # For now, we'll store the filename and mark for admin approval
        if supabase:
            supabase.table('image_approvals').insert({
                'artisan_id': session['user_id'],
                'filename': filename,
                'status': 'pending',
                'image_type': 'profile'
            }).execute()
            
            # Update artisan record with pending image
            supabase.table('artisans').update({
                'pending_image_url': f"/pending-images/{filename}"
            }).eq('id', session['user_id']).execute()
        
        # Save file locally (in production, upload to cloud storage)
        upload_folder = os.path.join(app.root_path, 'static', 'uploads', 'pending')
        os.makedirs(upload_folder, exist_ok=True)
        file.save(os.path.join(upload_folder, filename))
        
        return jsonify({'success': True, 'filename': filename})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/artisan/update-location', methods=['POST'])
def update_artisan_location():
    """Update artisan's location"""
    if 'user_id' not in session or session['role'] != 'artisan':
        return jsonify({'error': 'Unauthorized'}), 401
    
    try:
        data = request.get_json()
        location = data.get('location')
        
        if supabase and location:
            # Parse town from location if possible
            town = location.split(',')[0].strip() if ',' in location else location
            
            supabase.table('artisans').update({
                'location': location,
                'town': town
            }).eq('id', session['user_id']).execute()
        
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/artisan/update-status', methods=['POST'])
def update_artisan_status():
    """Update artisan's availability status"""
    if 'user_id' not in session or session['role'] != 'artisan':
        return jsonify({'error': 'Unauthorized'}), 401
    
    try:
        data = request.get_json()
        status = data.get('status')
        
        if supabase and status in ['Available', 'Busy']:
            supabase.table('artisans').update({
                'status': status
            }).eq('id', session['user_id']).execute()
        
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/artisan/request-withdrawal', methods=['POST'])
def request_withdrawal():
    """Artisan requests withdrawal of earnings"""
    if 'user_id' not in session or session['role'] != 'artisan':
        return jsonify({'error': 'Unauthorized'}), 401
    
    try:
        data = request.get_json()
        amount = float(data.get('amount', 0))
        method = data.get('method', 'momo')
        
        if amount < 10:
            return jsonify({'error': 'Minimum withdrawal is GH₵ 10'}), 400
        
        # Check available balance
        if supabase:
            # Calculate available balance
            payments_resp = supabase.table('payments')\
                .select('artisan_amount')\
                .eq('artisan_id', session['user_id'])\
                .eq('status', 'Completed')\
                .execute()
            
            total_earned = sum(float(p['artisan_amount']) for p in payments_resp.data) if payments_resp.data else 0
            
            # Get previous withdrawals
            withdrawals_resp = supabase.table('withdrawals')\
                .select('amount')\
                .eq('artisan_id', session['user_id'])\
                .eq('status', 'approved')\
                .execute()
            
            total_withdrawn = sum(float(w['amount']) for w in withdrawals_resp.data) if withdrawals_resp.data else 0
            
            available_balance = total_earned - total_withdrawn
            
            if amount > available_balance:
                return jsonify({'error': f'Insufficient balance. Available: GH₵ {available_balance:.2f}'}), 400
            
            # Create withdrawal request
            withdrawal_data = {
                'artisan_id': session['user_id'],
                'amount': amount,
                'method': method,
                'status': 'pending',
                'requested_at': 'now()'
            }
            supabase.table('withdrawals').insert(withdrawal_data).execute()
            
            # Notify admin
            admin_notification = {
                'user_id': 999,  # Admin ID
                'title': 'Withdrawal Request',
                'message': f'Artisan {session["user_name"]} requested withdrawal of GH₵ {amount}',
                'type': 'withdrawal'
            }
            supabase.table('notifications').insert(admin_notification).execute()
        
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/artisan/check-new-jobs')
def check_new_jobs():
    """Check for new jobs (for auto-refresh)"""
    if 'user_id' not in session or session['role'] != 'artisan':
        return jsonify({'error': 'Unauthorized'}), 401
    
    try:
        new_jobs_count = 0
        if supabase:
            # Get artisan's location
            artisan_resp = supabase.table('artisans').select('town').eq('id', session['user_id']).execute()
            if artisan_resp.data:
                town = artisan_resp.data[0]['town']
                
                # Count new jobs in last 5 minutes
                five_min_ago = (datetime.now() - timedelta(minutes=5)).isoformat()
                jobs_resp = supabase.table('jobs')\
                    .select('id')\
                    .eq('status', 'Pending')\
                    .ilike('location', f'%{town}%')\
                    .gte('created_at', five_min_ago)\
                    .execute()
                
                new_jobs_count = len(jobs_resp.data) if jobs_resp.data else 0
        
        return jsonify({'new_jobs': new_jobs_count})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/artisan/confirm-payment', methods=['POST'])
def confirm_payment():
    """Handle artisan payment confirmation (demo version)"""
    if 'user_id' not in session or session['role'] != 'artisan':
        return jsonify({'error': 'Unauthorized'}), 401
    
    try:
        if supabase:
            # Update artisan subscription status
            supabase.table('artisans').update({
                'subscription_active': True
            }).eq('id', session['user_id']).execute()
        
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ==========================================
# ADMIN ROUTES
# ==========================================

@app.route('/admin-login', methods=['GET', 'POST'])
def admin_login():
    """Admin login page"""
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        
        # Admin login
        if email == 'ekpebright57@gmail.com' and password == 'Br1ght47':
            session['user_id'] = 999
            session['user_name'] = 'Admin Bright'
            session['role'] = 'admin'
            flash("Admin login successful!", "success")
            return redirect(url_for('admin_dashboard'))
        else:
            flash("Invalid admin credentials", "error")
    
    return render_template('admin_login.html')

@app.route('/admin/dashboard')
@admin_required
def admin_dashboard():
    """Admin dashboard"""
    # Default empty data
    pending_artisans = []
    pending_payments = []
    verified_count = 0
    total_pros = 0
    
    if supabase:
        try:
            # Get pending artisans (needs document verification)
            pending_resp = supabase.table('artisans').select("*").eq('is_verified', False).execute()
            pending_artisans = pending_resp.data if pending_resp.data else []
            
            # Get artisans needing payment (verified but not subscribed)
            payment_resp = supabase.table('artisans').select("*").eq('is_verified', True).eq('subscription_active', False).execute()
            pending_payments = payment_resp.data if payment_resp.data else []
            
            # Get verified active artisans count
            verified_resp = supabase.table('artisans').select("*").eq('is_verified', True).eq('subscription_active', True).execute()
            verified_count = len(verified_resp.data) if verified_resp.data else 0
            
            # Get total artisans
            total_resp = supabase.table('artisans').select("*").execute()
            total_pros = len(total_resp.data) if total_resp.data else 0
            
        except Exception as e:
            print(f"Admin dashboard error: {e}")
    
    return render_template('admin_dashboard.html',
                         pending_artisans=pending_artisans,
                         pending_payments=pending_payments,
                         verified_count=verified_count,
                         total_pros=total_pros)

@app.route('/admin/approve/<int:artisan_id>')
@admin_required
def admin_approve(artisan_id):
    """Approve artisan documents"""
    try:
        if supabase:
            supabase.table('artisans').update({'is_verified': True}).eq('id', artisan_id).execute()
        flash(f"Artisan #{artisan_id} documents approved!", "success")
    except Exception as e:
        flash(f"Error: {e}", "error")
    
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/reject/<int:artisan_id>')
@admin_required
def admin_reject(artisan_id):
    """Reject artisan application"""
    try:
        if supabase:
            supabase.table('artisans').delete().eq('id', artisan_id).execute()
        flash(f"Artisan #{artisan_id} application rejected", "success")
    except Exception as e:
        flash(f"Error: {e}", "error")
    
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/confirm-sub/<int:artisan_id>')
@admin_required
def admin_confirm_sub(artisan_id):
    """Confirm subscription payment"""
    try:
        if supabase:
            supabase.table('artisans').update({'subscription_active': True}).eq('id', artisan_id).execute()
        flash(f"Artisan #{artisan_id} subscription activated!", "success")
    except Exception as e:
        flash(f"Error: {e}", "error")
    
    return redirect(url_for('admin_dashboard'))

# ==========================================
# UTILITY ROUTES
# ==========================================

@app.route('/pending/<stage>')
def pending_approval(stage):
    """Show pending approval status with real-time checking"""
    if 'user_id' not in session or session['role'] != 'artisan':
        return redirect(url_for('login'))
    
    # Always check actual status from database
    actual_stage = stage
    if supabase:
        try:
            artisan_resp = supabase.table('artisans')\
                .select('is_verified, subscription_active')\
                .eq('id', session['user_id']).execute()
            
            if artisan_resp.data:
                artisan = artisan_resp.data[0]
                
                # Determine actual stage based on database status
                if artisan['is_verified'] and artisan['subscription_active']:
                    actual_stage = 'complete'
                elif artisan['is_verified'] and not artisan['subscription_active']:
                    actual_stage = 'payment'
                else:
                    actual_stage = 'docs'
            else:
                # Artisan not found in database
                return redirect(url_for('logout'))
        
        except Exception as e:
            print(f"Status check error: {e}")
    
    return render_template('pending_approval.html', stage=actual_stage)

@app.route('/update_profile', methods=['POST'])
def update_profile():
    """Update user profile"""
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    try:
        full_name = request.form.get('full_name')
        phone = request.form.get('phone')
        
        if supabase:
            if session['role'] == 'general':
                supabase.table('users').update({
                    "full_name": full_name,
                    "phone": phone
                }).eq('id', session['user_id']).execute()
            elif session['role'] == 'artisan':
                supabase.table('artisans').update({
                    "full_name": full_name,
                    "phone": phone
                }).eq('id', session['user_id']).execute()
        
        # Update session
        session['user_name'] = full_name
        flash("Profile updated", "success")
    except Exception as e:
        flash(f"Update failed: {e}", "error")
    
    # Redirect to appropriate dashboard
    if session['role'] == 'artisan':
        return redirect(url_for('artisan_dashboard'))
    else:
        return redirect(url_for('dashboard'))

@app.route('/delete_account', methods=['POST'])
def delete_account():
    """Delete user account"""
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    try:
        if supabase:
            if session['role'] == 'general':
                supabase.table('users').delete().eq('id', session['user_id']).execute()
            elif session['role'] == 'artisan':
                supabase.table('artisans').delete().eq('id', session['user_id']).execute()
        
        session.clear()
        flash("Account deleted", "success")
    except Exception as e:
        flash(f"Delete failed: {e}", "error")
    
    return redirect(url_for('index'))

@app.route('/artisan/login-page')
def artisan_login_page():
    """Artisan login page"""
    return render_template('artisan_login.html')

@app.route('/artisan/login', methods=['GET', 'POST'])
def artisan_login():
    """Artisan login processing"""
    if request.method == 'POST':
        phone = request.form.get('phone')
        password = request.form.get('password')
        
        if supabase:
            try:
                # Check artisans table with phone
                response = supabase.table('artisans').select("*").eq('phone', phone).execute()
                
                if response.data:
                    artisan = response.data[0]
                    
                    # Check password
                    if artisan['password'] == password:
                        session['user_id'] = artisan['id']
                        session['user_name'] = artisan['full_name']
                        session['role'] = 'artisan'
                        
                        # Check current status and redirect appropriately
                        if not artisan['is_verified']:
                            return redirect(url_for('pending_approval', stage='docs'))
                        elif not artisan['subscription_active']:
                            return redirect(url_for('pending_approval', stage='payment'))
                        else:
                            flash(f"Welcome back, {artisan['full_name']}!", "success")
                            return redirect(url_for('artisan_dashboard'))
                    else:
                        flash("Invalid password", "error")
                        return redirect(url_for('artisan_login_page'))
                else:
                    flash("Artisan not found. Please check your phone number.", "error")
                    return redirect(url_for('artisan_login_page'))
                    
            except Exception as e:
                flash(f"Login error: {e}", "error")
                return redirect(url_for('artisan_login_page'))
    
    return redirect(url_for('artisan_login_page'))

# ==========================================
# TEMPLATE FILTERS
# ==========================================

@app.template_filter('time_ago')
def time_ago_filter(timestamp):
    """Convert timestamp to time ago format"""
    if not timestamp:
        return "Just now"
    
    try:
        # Parse timestamp
        if isinstance(timestamp, str):
            dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
        else:
            dt = timestamp
        
        now = datetime.now(timezone.utc)
        diff = now - dt
        
        if diff.days > 365:
            return f"{diff.days // 365} year{'s' if diff.days // 365 > 1 else ''} ago"
        elif diff.days > 30:
            return f"{diff.days // 30} month{'s' if diff.days // 30 > 1 else ''} ago"
        elif diff.days > 0:
            return f"{diff.days} day{'s' if diff.days > 1 else ''} ago"
        elif diff.seconds > 3600:
            return f"{diff.seconds // 3600} hour{'s' if diff.seconds // 3600 > 1 else ''} ago"
        elif diff.seconds > 60:
            return f"{diff.seconds // 60} minute{'s' if diff.seconds // 60 > 1 else ''} ago"
        else:
            return "Just now"
    except:
        return "Recently"

# ==========================================
# ERROR HANDLERS
# ==========================================

@app.errorhandler(404)
def not_found_error(error):
    return render_template('404.html'), 404

@app.errorhandler(500)
def internal_error(error):
    return render_template('500.html'), 500

# ==========================================
# RUN APPLICATION
# ==========================================

if __name__ == '__main__':
    app.run(debug=True, port=5000)