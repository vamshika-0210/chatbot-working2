from flask import Flask, request, jsonify
from flask_cors import CORS
from flask_jwt_extended import JWTManager, create_access_token
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import requests
import os
from dotenv import load_dotenv
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# Load environment variables
load_dotenv()

app = Flask(__name__)

# Email Configuration
SMTP_SERVER = os.getenv('SMTP_SERVER')
SMTP_PORT = int(os.getenv('SMTP_PORT', 587))
SMTP_USERNAME = os.getenv('SMTP_USERNAME')
SMTP_PASSWORD = os.getenv('SMTP_PASSWORD')
SENDER_EMAIL = os.getenv('SENDER_EMAIL')

# Configure CORS properly
CORS(app, resources={
    r"/api/*": {
        "origins": ["http://localhost:5000", "http://127.0.0.1:5000"],
        "methods": ["GET", "POST", "OPTIONS"],
        "allow_headers": ["Content-Type", "Authorization"]
    }
})

# Configuration from environment
app.config['JWT_SECRET_KEY'] = os.getenv('JWT_SECRET_KEY', 'your-jwt-secret-key')
BACKEND_URL = os.getenv('BACKEND_URL', 'http://localhost:5002')
GATEWAY_PORT = int(os.getenv('GATEWAY_PORT', 5001))

# Initialize extensions
jwt = JWTManager(app)
limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    default_limits=["200 per day", "50 per hour"]
)

# Chat endpoint with rate limiting
@app.route('/api/chat/message', methods=['POST'])
@limiter.limit("10 per minute")
def handle_chat():
    try:
        message = request.json.get('message')
        # Process chat message and determine intent
        # This is a simple example - you would typically use a more sophisticated NLP service
        response = {
            'message': f"Received: {message}",
            'intent': 'booking',  # Simplified intent detection
            'next_action': 'show_calendar'
        }
        return jsonify(response)
    except Exception as e:
        return jsonify({'error': str(e)}), 400

# Booking endpoints
@app.route('/api/bookings/availability/<date>', methods=['GET'])
def check_availability(date):
    try:
        response = requests.get(f"{BACKEND_URL}/api/bookings/availability/{date}")
        return jsonify(response.json()), response.status_code
    except requests.RequestException as e:
        return jsonify({'error': 'Backend service unavailable'}), 503

@app.route('/api/bookings/create', methods=['POST'])
def create_booking():
    try:
        print("Gateway: Received booking data:", request.json)  # Debug log
        response = requests.post(
            f"{BACKEND_URL}/api/bookings/create",
            json=request.json,
            headers={'Content-Type': 'application/json'}
        )
        if not response.ok:
            print(f"Gateway: Backend error - {response.status_code}")  # Debug log
            return jsonify(response.json()), response.status_code
        return jsonify(response.json()), response.status_code
    except requests.RequestException as e:
        print(f"Gateway: Request exception - {str(e)}")  # Debug log
        return jsonify({'error': 'Backend service unavailable'}), 503

@app.route('/api/bookings/<booking_id>', methods=['GET'])
def get_booking(booking_id):
    try:
        response = requests.get(f"{BACKEND_URL}/api/bookings/{booking_id}")
        return jsonify(response.json()), response.status_code
    except requests.RequestException as e:
        return jsonify({'error': 'Backend service unavailable'}), 503

# Calendar endpoints
@app.route('/api/calendar/monthly/<year>/<month>', methods=['GET'])
def get_calendar(year, month):
    try:
        print(f"Gateway: Fetching calendar for {year}/{month}")  # Debug log
        response = requests.get(
            f"{BACKEND_URL}/api/calendar/monthly/{year}/{month}",
            headers={'Content-Type': 'application/json'}
        )
        if not response.ok:
            print(f"Gateway: Backend error - {response.status_code}")  # Debug log
            error_data = response.json()
            return jsonify(error_data), response.status_code
            
        calendar_data = response.json()
        print("Gateway: Calendar data received:", calendar_data)  # Debug log
        return jsonify(calendar_data), response.status_code
    except requests.RequestException as e:
        print(f"Gateway: Request exception - {str(e)}")  # Debug log
        return jsonify({'error': 'Backend service unavailable'}), 503

# Payment endpoints
@app.route('/api/payments/initialize', methods=['POST'])
def initialize_payment():
    try:
        response = requests.post(
            f"{BACKEND_URL}/api/payments/initialize",
            json=request.json
        )
        return jsonify(response.json()), response.status_code
    except requests.RequestException as e:
        return jsonify({'error': 'Backend service unavailable'}), 503

@app.route('/api/payments/<payment_id>/status', methods=['GET'])
def get_payment_status(payment_id):
    try:
        response = requests.get(
            f"{BACKEND_URL}/api/payments/{payment_id}/status"
        )
        return jsonify(response.json()), response.status_code
    except requests.RequestException as e:
        return jsonify({'error': 'Backend service unavailable'}), 503

# Email endpoint
@app.route('/api/email/send', methods=['POST'])
def send_email():
    try:
        print("Gateway: Received email request")  # Debug log
        data = request.json
        to_email = data.get('to_email')
        booking_id = data.get('booking_id')
        booking_details = data.get('booking_details', {})

        print(f"Gateway: Email data - To: {to_email}, Booking ID: {booking_id}")  # Debug log

        if not all([to_email, booking_id, booking_details]):
            print("Gateway: Missing required email fields")  # Debug log
            return jsonify({'error': 'Missing required fields'}), 400

        # Create email message
        msg = MIMEMultipart()
        msg['From'] = SENDER_EMAIL
        msg['To'] = to_email
        msg['Subject'] = 'Museum Booking Confirmation'

        # Create email body
        body = f"""
Dear Visitor,

Thank you for booking with us! Your booking has been confirmed.

Booking Details:
----------------
Booking ID: {booking_id}
Date: {booking_details.get('date')}
Time Slot: {booking_details.get('timeSlot')}
Number of Visitors:
- Adults: {booking_details.get('adults')}
- Children: {booking_details.get('children')}
Total Amount: ₹{booking_details.get('amount')}

Please keep this booking ID for future reference.
We look forward to your visit!

Best regards,
Museum Management Team
"""

        msg.attach(MIMEText(body, 'plain'))

        print("Gateway: Attempting to connect to SMTP server...")  # Debug log
        try:
            # Print email configuration (without password)
            print(f"Gateway: SMTP Configuration - Server: {SMTP_SERVER}, Port: {SMTP_PORT}, Username: {SMTP_USERNAME}")
            
            # Connect to SMTP server
            server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
            server.set_debuglevel(1)  # Enable SMTP debug output
            
            # Start TLS
            print("Gateway: Starting TLS connection...")
            server.starttls()
            
            # Login
            print("Gateway: Attempting login...")
            server.login(SMTP_USERNAME, SMTP_PASSWORD)
            
            # Send email
            print("Gateway: Sending email...")
            server.send_message(msg)
            
            # Quit server
            server.quit()
            print(f"Gateway: Email sent successfully to {to_email}")
            return jsonify({'message': 'Email sent successfully'}), 200
            
        except smtplib.SMTPAuthenticationError as auth_error:
            print(f"Gateway: SMTP Authentication failed: {str(auth_error)}")
            return jsonify({'error': 'Email authentication failed'}), 500
        except smtplib.SMTPException as smtp_error:
            print(f"Gateway: SMTP error occurred: {str(smtp_error)}")
            return jsonify({'error': f'SMTP error: {str(smtp_error)}'}), 500
        except Exception as e:
            print(f"Gateway: Failed to send email: {str(e)}")
            return jsonify({'error': f'Failed to send email: {str(e)}'}), 500

    except Exception as e:
        print(f"Gateway: Email error: {str(e)}")
        return jsonify({'error': str(e)}), 500

# User session management
@app.route('/api/users/session', methods=['POST'])
def create_session():
    try:
        # Simple session creation - you would typically validate credentials here
        access_token = create_access_token(identity=request.json.get('user_id'))
        return jsonify({'token': access_token})
    except Exception as e:
        return jsonify({'error': str(e)}), 400

# Add CORS headers to handle OPTIONS requests
@app.after_request
def after_request(response):
    # Allow specific origins
    allowed_origins = ["http://localhost:5000", "http://127.0.0.1:5000"]
    origin = request.headers.get('Origin')
    if origin in allowed_origins:
        response.headers.add('Access-Control-Allow-Origin', origin)
        
    # Allow specific headers and methods
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization')
    response.headers.add('Access-Control-Allow-Methods', 'GET,POST,OPTIONS')
    response.headers.add('Access-Control-Allow-Credentials', 'true')
    return response

if __name__ == '__main__':
    app.run(port=GATEWAY_PORT, debug=True)
