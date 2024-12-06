from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from flask_jwt_extended import JWTManager
from datetime import datetime, timedelta
import os
from models import db, Booking, TimeSlot, Pricing, Payment
from dotenv import load_dotenv
import traceback
from flask_mail import Mail, Message
import uuid  # Added missing import for uuid

# Load environment variables
load_dotenv()

# Get absolute paths
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
INSTANCE_PATH = os.path.join(BASE_DIR, 'instance')
DB_PATH = os.path.join(INSTANCE_PATH, 'chatbot.db')

# Ensure instance folder exists with proper permissions
try:
    os.makedirs(INSTANCE_PATH, exist_ok=True)
    print(f"Instance directory created/verified at: {INSTANCE_PATH}")
except Exception as e:
    print(f"Error creating instance directory: {str(e)}")
    raise

app = Flask(__name__, 
           static_folder='../frontend/static',
           static_url_path='/static',
           instance_path=INSTANCE_PATH)
           
# Configure CORS - Updated configuration
CORS(app, resources={
    r"/*": {
        "origins": ["http://127.0.0.1:5000", "http://localhost:5000", "http://127.0.0.1:5001", "http://localhost:5001"],
        "methods": ["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        "allow_headers": ["Content-Type", "Authorization", "Accept"],
        "supports_credentials": True,
        "expose_headers": ["Content-Type", "Authorization"]
    }
})

# Configuration from environment
BACKEND_PORT = int(os.getenv('BACKEND_PORT', 5002))

# Configure Flask-SQLAlchemy with absolute path
app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{DB_PATH}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Configure Mail
app.config['MAIL_SERVER'] = os.getenv('MAIL_SERVER', 'smtp.gmail.com')
app.config['MAIL_PORT'] = int(os.getenv('MAIL_PORT', 587))
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = os.getenv('MAIL_USERNAME')
app.config['MAIL_PASSWORD'] = os.getenv('MAIL_PASSWORD')
app.config['MAIL_DEFAULT_SENDER'] = os.getenv('MAIL_DEFAULT_SENDER')

# Initialize extensions
db.init_app(app)
jwt = JWTManager(app)
mail = Mail(app)

def init_db():
    with app.app_context():
        try:
            # Create all tables
            db.create_all()
            print("Database tables created successfully")
            
            # Clear existing pricing data
            try:
                Pricing.query.delete()
                db.session.commit()
                print("Cleared existing pricing data")
            except Exception as e:
                print(f"Error clearing pricing data: {str(e)}")
                db.session.rollback()
            
            # Add default pricing
            today = datetime.now().date()
            future_date = today + timedelta(days=365)
            
            default_pricing = [
                Pricing(
                    nationality='Local',
                    ticket_type='Regular',
                    adult_price=20.0,
                    child_price=10.0,
                    effective_from=today,
                    effective_to=future_date
                ),
                Pricing(
                    nationality='Foreign',
                    ticket_type='Regular',
                    adult_price=30.0,
                    child_price=15.0,
                    effective_from=today,
                    effective_to=future_date
                )
            ]
            
            for pricing in default_pricing:
                try:
                    db.session.add(pricing)
                    db.session.commit()
                    print(f"Added pricing for {pricing.nationality} - {pricing.ticket_type}")
                except Exception as e:
                    print(f"Error adding pricing: {str(e)}")
                    db.session.rollback()
            
            # Verify pricing data
            all_pricing = Pricing.query.all()
            print(f"Total pricing records: {len(all_pricing)}")
            for p in all_pricing:
                print(f"Pricing: {p.nationality} - {p.ticket_type}: Adult=${p.adult_price}, Child=${p.child_price}")
                
        except Exception as e:
            print(f"Error initializing database: {str(e)}")
            traceback.print_exc()
            raise

def send_booking_confirmation(booking):
    try:
        msg = Message(
            'Museum Visit Booking Confirmation',
            recipients=[booking.email]
        )
        msg.body = f'''
Dear Visitor,

Your museum visit booking has been confirmed!

Booking Details:
---------------
Booking ID: {booking.booking_id}
Date: {booking.date.strftime('%Y-%m-%d')}
Time Slot: {booking.time_slot}
Number of Adults: {booking.adults}
Number of Children: {booking.children}
Total Amount: ${booking.total_amount}

Please keep this email for your records. You will need to show this booking ID when you arrive at the museum.

Thank you for choosing to visit our museum!

Best regards,
Museum Team
'''
        mail.send(msg)
        return True
    except Exception as e:
        print(f"Error sending email: {str(e)}")
        return False

# Serve main HTML file
@app.route('/')
def serve_index():
    return send_from_directory('../frontend', 'index.html')

# Booking endpoints
@app.route('/api/bookings/availability/<date>', methods=['GET'])
def check_availability(date):
    try:
        date_obj = datetime.strptime(date, '%Y-%m-%d').date()
        slots = TimeSlot.query.filter_by(date=date_obj).all()
        return jsonify([{
            'time': slot.slot_time,
            'available': slot.capacity - slot.booked_count,
            'ticket_type': slot.ticket_type
        } for slot in slots])
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@app.route('/api/bookings', methods=['GET'])
def get_bookings():
    try:
        date_str = request.args.get('date')
        if not date_str:
            return jsonify({'error': 'Date parameter is required'}), 400
            
        try:
            date_obj = datetime.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            return jsonify({'error': 'Invalid date format. Use YYYY-MM-DD'}), 400
            
        # Get time slots for the date
        slots = TimeSlot.query.filter_by(date=date_obj).all()
        
        # If no slots exist for this date, create them
        if not slots:
            morning_slot = TimeSlot(
                date=date_obj,
                slot_time='10:00 AM',
                capacity=50,  # Back to 50 slots
                ticket_type='Regular',
                booked_count=0
            )
            afternoon_slot = TimeSlot(
                date=date_obj,
                slot_time='2:00 PM',
                capacity=50,  # Back to 50 slots
                ticket_type='Regular',
                booked_count=0
            )
            
            try:
                db.session.add(morning_slot)
                db.session.add(afternoon_slot)
                db.session.commit()
                print(f"Successfully created time slots for {date_obj}")  # Add debug logging
                slots = [morning_slot, afternoon_slot]
            except Exception as e:
                db.session.rollback()
                print(f"Error creating time slots: {str(e)}")
                return jsonify({'error': 'Failed to create time slots'}), 500
        
        # Get bookings for the date
        bookings = Booking.query.filter_by(date=date_obj).all()
        
        return jsonify({
            'slots': [{
                'time': slot.slot_time,
                'available': slot.capacity - slot.booked_count,
                'capacity': slot.capacity,
                'booked': slot.booked_count,
                'ticket_type': slot.ticket_type
            } for slot in slots],
            'bookings': [booking.to_dict() for booking in bookings]
        })
        
    except Exception as e:
        print(f"Error in get_bookings: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500

@app.route('/api/bookings/create', methods=['POST'])
def create_booking():
    try:
        data = request.json
        if not data:
            return jsonify({'error': 'No data provided'}), 400
            
        print("Received booking data:", data)  # Debug log
            
        required_fields = ['date', 'nationality', 'adults', 'children', 'ticketType', 'timeSlot', 'email']
        missing_fields = [field for field in required_fields if field not in data or not data[field]]
        
        if missing_fields:
            return jsonify({'error': f'Missing or empty required fields: {", ".join(missing_fields)}'}), 400
            
        try:
            booking_date = datetime.strptime(data['date'], '%Y-%m-%d').date()
        except ValueError as e:
            print(f"Date parsing error: {str(e)}")
            return jsonify({'error': 'Invalid date format. Use YYYY-MM-DD'}), 400
            
        print("Booking date:", booking_date)  # Debug log
        
        # Validate visitor numbers
        try:
            adults = int(data['adults'])
            children = int(data['children'])
            if adults < 1:
                return jsonify({'error': 'At least one adult is required'}), 400
            if children < 0:
                return jsonify({'error': 'Number of children cannot be negative'}), 400
        except ValueError as e:
            print(f"Visitor number parsing error: {str(e)}")
            return jsonify({'error': 'Invalid visitor numbers'}), 400
        
        # Get pricing information
        try:
            pricing = Pricing.query.filter_by(
                nationality=data['nationality'],
                ticket_type=data['ticketType']
            ).filter(
                Pricing.effective_from <= booking_date,
                Pricing.effective_to >= booking_date
            ).first()
            
            if not pricing:
                print(f"No pricing found for nationality: {data['nationality']}, ticket type: {data['ticketType']}")
                return jsonify({'error': 'No valid pricing found for the selected options'}), 400
                
            print(f"Found pricing: adult=${pricing.adult_price}, child=${pricing.child_price}")
        except Exception as e:
            print(f"Error querying pricing: {str(e)}")
            traceback.print_exc()
            return jsonify({'error': 'Error retrieving pricing information'}), 500
            
        # Calculate total amount
        total_amount = (adults * pricing.adult_price) + (children * pricing.child_price)
        print(f"Calculated total amount: ${total_amount}")
        
        # Check if the time slot exists and has capacity
        try:
            time_slot = TimeSlot.query.filter_by(
                date=booking_date,
                slot_time=data['timeSlot'],
                ticket_type=data['ticketType']
            ).first()
            
            if not time_slot:
                print(f"Creating new time slot for {booking_date} at {data['timeSlot']}")
                time_slot = TimeSlot(
                    date=booking_date,
                    slot_time=data['timeSlot'],
                    capacity=50,  # Each time slot has 50 capacity
                    ticket_type=data['ticketType'],
                    booked_count=0
                )
                db.session.add(time_slot)
                db.session.commit()
                print("Successfully created new time slot")
                
            # Check capacity for this specific time slot
            total_visitors = adults + children
            current_booked = time_slot.booked_count if time_slot.booked_count is not None else 0
            
            if current_booked + total_visitors > time_slot.capacity:
                return jsonify({'error': f'Not enough capacity available for the {data["timeSlot"]} time slot'}), 400
                    
            print(f"Time slot {data['timeSlot']} capacity check passed. Current bookings: {current_booked}, New visitors: {total_visitors}")
        except Exception as e:
            db.session.rollback()
            print(f"Error handling time slot: {str(e)}")
            traceback.print_exc()
            return jsonify({'error': 'Error managing time slot'}), 500
        
        # Create the booking with pending status
        try:
            booking = Booking(
                date=booking_date,
                email=data['email'],
                nationality=data['nationality'],
                adults=adults,
                children=children,
                ticket_type=data['ticketType'],
                time_slot=data['timeSlot'],
                total_amount=float(total_amount),
                status='pending',
                payment_status='pending'
            )
            
            # Update the time slot's booked count (count each person)
            time_slot.booked_count = current_booked + total_visitors
            
            db.session.add(booking)
            db.session.commit()
            print(f"Successfully created booking with ID: {booking.booking_id}")
            print(f"Updated time slot booked count to: {time_slot.booked_count}")
            
            return jsonify({
                'success': True,
                'booking_id': booking.booking_id,
                'amount': total_amount
            })
            
        except Exception as e:
            db.session.rollback()
            print(f"Error saving booking: {str(e)}")
            print(f"Full error traceback:")
            traceback.print_exc()
            return jsonify({'error': 'Failed to save booking. Please try again.'}), 500
            
    except Exception as e:
        print(f"Unexpected error in create_booking: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': f'An unexpected error occurred: {str(e)}'}), 500

@app.route('/api/bookings/<booking_id>', methods=['GET'])
def get_booking(booking_id):
    try:
        booking = Booking.query.filter_by(booking_id=booking_id).first()
        if not booking:
            return jsonify({
                'status': 'error',
                'message': 'Booking not found'
            }), 404
            
        return jsonify({
            'status': 'success',
            'data': {
                'id': booking.booking_id,
                'date': booking.date.strftime('%Y-%m-%d'),
                'time_slot': booking.time_slot,
                'adult_count': booking.adults,
                'child_count': booking.children,
                'total_amount': float(booking.total_amount),
                'status': booking.status.capitalize(),
                'payment_status': booking.payment_status
            }
        })
    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 400

@app.route('/api/bookings', methods=['GET'])
def get_user_bookings():
    try:
        # Get all bookings ordered by date
        bookings = Booking.query.order_by(Booking.date.desc()).all()
        
        bookings_data = []
        for booking in bookings:
            try:
                # Get associated time slot
                time_slot = TimeSlot.query.get(booking.time_slot_id)
                
                # Get associated payment
                payment = Payment.query.filter_by(booking_id=booking.id).first()
                
                # Get pricing info
                pricing = Pricing.query.filter_by(
                    nationality=booking.nationality,
                    ticket_type=booking.ticket_type
                ).first()
                
                # Calculate total amount
                adult_total = booking.adults * (pricing.adult_price if pricing else 0)
                child_total = booking.children * (pricing.child_price if pricing else 0)
                total_amount = adult_total + child_total
                
                booking_info = {
                    'id': booking.id,
                    'date': booking.date.strftime('%Y-%m-%d'),
                    'created_at': booking.created_at.strftime('%Y-%m-%d %I:%M %p'),
                    'nationality': booking.nationality,
                    'adults': booking.adults,
                    'children': booking.children,
                    'ticket_type': booking.ticket_type,
                    'time_slot': f"{time_slot.start_time.strftime('%I:%M %p')} - {time_slot.end_time.strftime('%I:%M %p')}" if time_slot else 'N/A',
                    'status': booking.status,
                    'payment_status': payment.status if payment else 'Not Initiated',
                    'payment_id': payment.payment_id if payment else None,
                    'total_amount': f"${total_amount:.2f}",
                    'pricing_details': {
                        'adult_price': f"${pricing.adult_price:.2f}" if pricing else 'N/A',
                        'child_price': f"${pricing.child_price:.2f}" if pricing else 'N/A',
                        'adult_total': f"${adult_total:.2f}",
                        'child_total': f"${child_total:.2f}"
                    }
                }
                bookings_data.append(booking_info)
            except Exception as e:
                print(f"Error processing booking {booking.id}: {str(e)}")
                continue
        
        return jsonify({'success': True, 'bookings': bookings_data})
    except Exception as e:
        print(f"Error fetching bookings: {str(e)}")
        return jsonify({'success': False, 'error': 'Failed to fetch bookings. Please try again later.'}), 500

@app.route('/api/bookings', methods=['GET'])
def get_bookings_by_date():
    try:
        date_str = request.args.get('date')
        if not date_str:
            return jsonify({'error': 'Date parameter is required'}), 400

        date_obj = datetime.strptime(date_str, '%Y-%m-%d').date()
        
        # Initialize slots for this date if they don't exist
        existing_slots = TimeSlot.query.filter_by(date=date_obj).all()
        if not existing_slots:
            morning_slot = TimeSlot(
                date=date_obj,
                slot_time='10:00 AM',
                capacity=50,
                ticket_type='Regular',
                booked_count=0
            )
            afternoon_slot = TimeSlot(
                date=date_obj,
                slot_time='2:00 PM',
                capacity=50,
                ticket_type='Regular',
                booked_count=0
            )
            
            db.session.add(morning_slot)
            db.session.add(afternoon_slot)
            try:
                db.session.commit()
                existing_slots = [morning_slot, afternoon_slot]
            except Exception as e:
                db.session.rollback()
                print(f"Error creating slots: {str(e)}")
                return jsonify({'error': 'Failed to create time slots'}), 500
        
        slots_info = []
        for slot in existing_slots:
            available = slot.capacity - slot.booked_count
            slots_info.append({
                'time': slot.slot_time,
                'available': available,
                'total': slot.capacity,
                'booked': slot.booked_count,
                'ticket_type': slot.ticket_type
            })
        
        return jsonify({
            'date': date_str,
            'slots': slots_info
        })
        
    except ValueError as e:
        return jsonify({'error': 'Invalid date format. Use YYYY-MM-DD'}), 400
    except Exception as e:
        print(f"Error getting bookings for date: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500

# Pricing endpoint
@app.route('/api/pricing', methods=['GET'])
def get_pricing():
    try:
        nationality = request.args.get('nationality')
        ticket_type = request.args.get('ticketType')
        date_str = request.args.get('date')
        
        if not all([nationality, ticket_type, date_str]):
            return jsonify({'error': 'Missing required parameters'}), 400
            
        try:
            date_obj = datetime.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            return jsonify({'error': 'Invalid date format'}), 400
            
        pricing = Pricing.query.filter_by(
            nationality=nationality,
            ticket_type=ticket_type
        ).filter(
            Pricing.effective_from <= date_obj,
            Pricing.effective_to >= date_obj
        ).first()
        
        if not pricing:
            return jsonify({'error': 'No pricing found for the selected options'}), 404
            
        return jsonify({
            'adult_price': pricing.adult_price,
            'child_price': pricing.child_price
        })
        
    except Exception as e:
        print(f"Error in get_pricing: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500

# Payment endpoints
@app.route('/api/payments/initialize', methods=['POST'])
def initialize_payment():
    try:
        data = request.json
        if not data:
            return jsonify({'error': 'No data provided'}), 400
            
        required_fields = ['booking_id', 'amount', 'payment_method']
        missing_fields = [field for field in required_fields if field not in data]
        if missing_fields:
            return jsonify({'error': f'Missing required fields: {", ".join(missing_fields)}'}), 400
            
        booking = Booking.query.filter_by(booking_id=data['booking_id']).first()
        
        if not booking:
            return jsonify({'error': 'Booking not found'}), 404
            
        if booking.payment_status == 'completed':
            return jsonify({'error': 'Payment already completed'}), 400
            
        # Create payment record
        payment = Payment(
            booking_id=booking.booking_id,
            amount=data['amount'],
            payment_method=data['payment_method'],
            status='pending',
            transaction_id=str(uuid.uuid4())  # Generate a unique transaction ID
        )
        
        try:
            # Start a transaction
            db.session.begin_nested()
            
            db.session.add(payment)
            
            # For demo purposes, automatically mark payment as completed
            payment.status = 'completed'
            booking.payment_status = 'completed'
            booking.status = 'confirmed'
            
            # Update time slot capacity
            time_slot = TimeSlot.query.filter_by(
                date=booking.date,
                slot_time=booking.time_slot,
                ticket_type=booking.ticket_type
            ).first()
            
            if not time_slot:
                db.session.rollback()
                return jsonify({'error': 'Time slot not found'}), 404
                
            if time_slot.booked_count + 1 > time_slot.capacity:
                db.session.rollback()
                return jsonify({'error': 'Not enough capacity available'}), 400
                
            time_slot.booked_count += 1
            
            # Commit the transaction
            db.session.commit()
            
            # Only send confirmation email after successful payment and database updates
            email_sent = send_booking_confirmation(booking)
            if not email_sent:
                print("Warning: Failed to send confirmation email")
                # Don't fail the payment if email fails, but log it
            
            return jsonify({
                'success': True,
                'payment_id': payment.id,
                'status': payment.status,
                'transaction_id': payment.transaction_id
            })
            
        except Exception as e:
            db.session.rollback()
            print(f"Error processing payment: {str(e)}")
            return jsonify({'error': 'Failed to process payment'}), 500
            
    except Exception as e:
        print(f"Error in initialize_payment: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/payments/<payment_id>/status', methods=['GET'])
def get_payment_status(payment_id):
    try:
        payment = Payment.query.get(payment_id)
        if not payment:
            return jsonify({'error': 'Payment not found'}), 404
        return jsonify(payment.to_dict())
    except Exception as e:
        return jsonify({'error': str(e)}), 400

# Calendar endpoints
@app.route('/api/calendar/monthly/<year>/<month>', methods=['GET'])
def get_calendar_data(year, month):
    try:
        print(f"Backend: Processing calendar request for {year}/{month}")  # Debug log
        # Convert string parameters to integers if they aren't already
        year = int(year)
        month = int(month)
        
        # Get the first and last day of the month
        first_day = datetime(year, month, 1).date()
        if month == 12:
            last_day = datetime(year + 1, 1, 1).date() - timedelta(days=1)
        else:
            last_day = datetime(year, month + 1, 1).date() - timedelta(days=1)
        
        print(f"Backend: Fetching slots between {first_day} and {last_day}")  # Debug log
        
        # Get all time slots for the month
        slots = TimeSlot.query.filter(
            TimeSlot.date >= first_day,
            TimeSlot.date <= last_day
        ).all()
        
        print(f"Backend: Found {len(slots)} slots")  # Debug log
        
        # Create calendar data
        calendar_data = {}
        current_date = first_day
        while current_date <= last_day:
            day_slots = [s for s in slots if s.date == current_date]
            
            # If no slots exist for this date and it's not in the past, create default slots
            today = datetime.now().date()
            if not day_slots and current_date >= today:
                try:
                    # Create morning slot
                    morning_slot = TimeSlot(
                        date=current_date,
                        slot_time='10:00 AM',
                        capacity=50,
                        ticket_type='Regular',
                        booked_count=0
                    )
                    # Create afternoon slot
                    afternoon_slot = TimeSlot(
                        date=current_date,
                        slot_time='2:00 PM',
                        capacity=50,
                        ticket_type='Regular',
                        booked_count=0
                    )
                    db.session.add(morning_slot)
                    db.session.add(afternoon_slot)
                    db.session.commit()
                    day_slots = [morning_slot, afternoon_slot]
                    print(f"Created default slots for {current_date}")
                except Exception as e:
                    print(f"Error creating slots for {current_date}: {str(e)}")
                    db.session.rollback()
            
            # Calculate availability
            if day_slots:
                total_availability = 0
                slot_data = []
                
                for slot in day_slots:
                    slot_availability = slot.capacity - slot.booked_count
                    status = 'available'
                    if slot_availability == 0:
                        status = 'full'
                    elif slot_availability <= slot.capacity * 0.2:
                        status = 'limited'
                    
                    slot_data.append({
                        'time': slot.slot_time,
                        'available': slot_availability,
                        'capacity': slot.capacity,
                        'booked': slot.booked_count,
                        'status': status
                    })
                
                # Overall status is the most restrictive status
                if any(s['status'] == 'full' for s in slot_data):
                    status = 'full'
                elif any(s['status'] == 'limited' for s in slot_data):
                    status = 'limited'
                else:
                    status = 'available'
            else:
                status = 'unavailable'
                slot_data = []
            
            calendar_data[current_date.strftime('%Y-%m-%d')] = {
                'status': status,
                'slots': slot_data
            }
            current_date += timedelta(days=1)
        
        print("Backend: Calendar data prepared:", calendar_data)  # Debug log
        return jsonify(calendar_data)
    except Exception as e:
        print(f"Backend: Error processing calendar request - {str(e)}")  # Debug log
        return jsonify({'error': str(e)}), 400

if __name__ == '__main__':
    init_db()
    app.run(port=BACKEND_PORT, debug=True)
