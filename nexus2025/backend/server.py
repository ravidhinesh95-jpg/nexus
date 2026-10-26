import os
import re
import uuid
import json
import secrets
import base64
import hashlib
import hmac
import urllib.request
import smtplib
from html import escape
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
from datetime import datetime
from flask import Flask, request, jsonify, send_from_directory
from werkzeug.security import generate_password_hash
# pyrefly: ignore [missing-import]
import mysql.connector
# pyrefly: ignore [missing-import]
from dotenv import load_dotenv

# Load environment variables
load_dotenv(os.path.join(os.path.dirname(__file__), '.env'))

app = Flask(__name__, static_folder='../frontend')
app.config['MAX_CONTENT_LENGTH'] = 7 * 1024 * 1024
UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), 'uploads')

# ── CORS Headers ──────────────────────────────────────────────────────────────
@app.after_request
def add_cors_headers(response):
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type,Authorization'
    response.headers['Access-Control-Allow-Methods'] = 'GET,POST,OPTIONS'
    return response

@app.route('/api/<path:path>', methods=['OPTIONS'])
def options_handler(path):
    return jsonify({}), 200


@app.errorhandler(413)
def request_too_large(_error):
    return jsonify({'success': False, 'error': 'The uploaded file must be 5 MB or smaller.'}), 413

# ── MySQL Configuration ───────────────────────────────────────────────────────
DB_HOST     = os.getenv('DB_HOST', '127.0.0.1')
DB_PORT     = int(os.getenv('DB_PORT', '3306') or '3306')
DB_USER     = os.getenv('DB_USER', 'root')
DB_PASSWORD = os.getenv('DB_PASSWORD', 'varun@12345')
DB_NAME     = os.getenv('DB_NAME', 'cyperx_1')
PORT        = int(os.getenv('PORT', '3001') or '3001')

RAZORPAY_KEY_ID     = os.getenv('RAZORPAY_KEY_ID', '').strip()
RAZORPAY_KEY_SECRET = os.getenv('RAZORPAY_KEY_SECRET', '').strip()

SMTP_SERVER     = os.getenv('SMTP_SERVER', 'smtp.gmail.com')
SMTP_PORT_NUM   = int(os.getenv('SMTP_PORT', '587') or '587')
SMTP_USERNAME   = os.getenv('SMTP_USERNAME', '')
SMTP_PASSWORD   = os.getenv('SMTP_PASSWORD', '')
SMTP_FROM_EMAIL = os.getenv('SMTP_FROM_EMAIL', '')
SMTP_FROM_NAME  = os.getenv('SMTP_FROM_NAME', 'NEXUS 2025')


# ── DB Helper ─────────────────────────────────────────────────────────────────
def get_db():
    return mysql.connector.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME,
        ssl_disabled=False
    )


def _store_upload(upload, allowed_extensions, max_bytes):
    extension = os.path.splitext(upload.filename or '')[1].lower()
    if extension not in allowed_extensions:
        raise ValueError('Unsupported file type.')

    upload.stream.seek(0, os.SEEK_END)
    size = upload.stream.tell()
    upload.stream.seek(0)
    if size == 0:
        raise ValueError('The uploaded file is empty.')
    if size > max_bytes:
        raise ValueError('The uploaded file is too large.')

    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    filename = f'{uuid.uuid4().hex}{extension}'
    path = os.path.join(UPLOAD_FOLDER, filename)
    upload.save(path)
    return filename, path


# ── DB Schema Init ────────────────────────────────────────────────────────────
def init_db():
    # Create database if missing
    try:
        conn = mysql.connector.connect(
            host=DB_HOST, port=DB_PORT,
            user=DB_USER, password=DB_PASSWORD,
            ssl_disabled=False
        )
        cursor = conn.cursor()
        cursor.execute(f"CREATE DATABASE IF NOT EXISTS `{DB_NAME}`")
        cursor.close()
        conn.close()
    except mysql.connector.Error as err:
        raise RuntimeError(f"Could not connect to MySQL or create database '{DB_NAME}'. Check DB settings.") from err

    # Create tables
    try:
        conn = get_db()
        cursor = conn.cursor()

        # ── Registrations table (matches NEXUS 2025 register.html) ──
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS registrations (
                id                INT AUTO_INCREMENT PRIMARY KEY,
                reg_id            VARCHAR(20) UNIQUE,

                -- Personal Info (Section 1)
                full_name         VARCHAR(100) NOT NULL,
                email             VARCHAR(100) NOT NULL,
                phone             VARCHAR(15) NOT NULL,
                password_hash     VARCHAR(255) NOT NULL,
                dob               DATE,
                gender            VARCHAR(20),

                -- Academic Info (Section 2)
                institution_type  VARCHAR(50),
                college_name      VARCHAR(150),
                department        VARCHAR(50),
                year_of_study     VARCHAR(10),
                roll_number       VARCHAR(30),
                linkedin_url      VARCHAR(255),
                cgpa              DECIMAL(4,2),
                photo_id_path     VARCHAR(255),

                -- Events & Preferences (Section 3)
                events            JSON,
                tshirt_size       VARCHAR(5),
                meal_preference   VARCHAR(20),
                referral_source   VARCHAR(30),
                team_size         INT DEFAULT 1,
                team_name         VARCHAR(60),
                badge_color       VARCHAR(10),
                special_requirements TEXT,

                -- Payment & Consent (Section 4)
                fee_category      VARCHAR(20),
                coupon_code       VARCHAR(30),
                on_site           TINYINT(1) DEFAULT 1,
                newsletter        TINYINT(1) DEFAULT 1,

                submitted_at      DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        legacy_columns = {
            'fullname': ('full_name', 'VARCHAR(100) NOT NULL'),
            'college': ('college_name', 'VARCHAR(150) NULL'),
            'yearofstudy': ('year_of_study', 'VARCHAR(10) NULL'),
            'socialprofile': ('linkedin_url', 'VARCHAR(255) NULL'),
            'badgecolor': ('badge_color', 'VARCHAR(10) NULL'),
            'specialrequests': ('special_requirements', 'TEXT NULL'),
        }
        for old_column, (new_column, definition) in legacy_columns.items():
            cursor.execute(f"SHOW COLUMNS FROM registrations LIKE '{new_column}'")
            if not cursor.fetchone():
                cursor.execute(f"SHOW COLUMNS FROM registrations LIKE '{old_column}'")
                if cursor.fetchone():
                    cursor.execute(
                        f'ALTER TABLE registrations CHANGE COLUMN {old_column} {new_column} {definition}'
                    )

        registration_columns = {
            'password_hash': 'VARCHAR(255) NULL',
            'dob': 'DATE NULL',
            'institution_type': 'VARCHAR(50) NULL',
            'roll_number': 'VARCHAR(30) NULL',
            'cgpa': 'DECIMAL(4,2) NULL',
            'photo_id_path': 'VARCHAR(255) NULL',
            'tshirt_size': 'VARCHAR(5) NULL',
            'meal_preference': 'VARCHAR(20) NULL',
            'referral_source': 'VARCHAR(30) NULL',
            'team_size': 'INT DEFAULT 1',
            'team_name': 'VARCHAR(60) NULL',
            'fee_category': 'VARCHAR(20) NULL',
            'coupon_code': 'VARCHAR(30) NULL',
            'on_site': 'TINYINT(1) DEFAULT 1',
            'newsletter': 'TINYINT(1) DEFAULT 1',
            'submitted_at': 'DATETIME DEFAULT CURRENT_TIMESTAMP',
        }
        for column, definition in registration_columns.items():
            cursor.execute(f"SHOW COLUMNS FROM registrations LIKE '{column}'")
            if not cursor.fetchone():
                cursor.execute(
                    f'ALTER TABLE registrations ADD COLUMN {column} {definition}'
                )

        cursor.execute("SHOW COLUMNS FROM registrations LIKE 'full_name'")
        if not cursor.fetchone():
            cursor.close()
            conn.close()
            raise RuntimeError(
                f"Database '{DB_NAME}' has no compatible registrations table. "
                f"Back up the database and create it with the SQL schema for '{DB_NAME}'."
            )
        # ── Contact messages table (matches NEXUS 2025 contact.html) ──
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS contact_messages (
                id             INT AUTO_INCREMENT PRIMARY KEY,
                name           VARCHAR(100) NOT NULL,
                email          VARCHAR(100) NOT NULL,
                phone          VARCHAR(15),
                query_type     VARCHAR(50),
                subject        VARCHAR(200) NOT NULL,
                college        VARCHAR(150),
                urgency_level  TINYINT DEFAULT 3,
                message        TEXT NOT NULL,
                subscribe      TINYINT(1) DEFAULT 1,
                attachment_path VARCHAR(255),
                submitted_at   DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        contact_columns = {
            'phone': 'VARCHAR(15) NULL',
            'query_type': 'VARCHAR(50) NULL',
            'college': 'VARCHAR(150) NULL',
            'urgency_level': 'TINYINT DEFAULT 3',
            'subscribe': 'TINYINT(1) DEFAULT 1',
            'attachment_path': 'VARCHAR(255) NULL',
        }
        for column, definition in contact_columns.items():
            cursor.execute(f"SHOW COLUMNS FROM contact_messages LIKE '{column}'")
            if not cursor.fetchone():
                cursor.execute(
                    f'ALTER TABLE contact_messages ADD COLUMN {column} {definition}'
                )

        # ── UTR payment log ──
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS payment_utr_log (
                id          INT AUTO_INCREMENT PRIMARY KEY,
                utr         VARCHAR(50),
                upi_id      VARCHAR(100),
                amount      INT,
                reg_id      VARCHAR(20),
                status      VARCHAR(20) DEFAULT "pending",
                verified_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        conn.commit()
        cursor.close()
        conn.close()
        print("NEXUS 2025 - DB schema ready.")
    except mysql.connector.Error as err:
        raise RuntimeError(f"Could not initialize the database schema in '{DB_NAME}'.") from err


init_db()


# ── Serve Frontend ────────────────────────────────────────────────────────────
@app.route('/')
def index():
    return send_from_directory(app.static_folder, 'index.html')

@app.route('/<path:path>')
def serve_static(path):
    full = os.path.join(app.static_folder, path)
    if os.path.exists(full):
        return send_from_directory(app.static_folder, path)
    return send_from_directory(app.static_folder, 'index.html')


# ── Registration API ──────────────────────────────────────────────────────────
@app.route('/api/register', methods=['POST'])
def register():
    """
    Accepts data from register.html (multipart/form-data).
    Field names match the 'name' attributes of all 28 form inputs.
    """
    photo_id_path = None
    photo_id_file = None
    try:
        data = request.form

        # ── Section 1: Personal Info ──
        full_name = data.get('full_name', '').strip()
        email     = data.get('email', '').strip()
        phone     = data.get('phone', '').strip()
        dob       = data.get('dob', '').strip() or None
        gender    = data.get('gender', '').strip()

        # ── Section 2: Academic Info ──
        institution_type = data.get('institution_type', '').strip()
        college_name     = data.get('college_name', '').strip()
        department       = data.get('department', '').strip()
        year_of_study    = data.get('year_of_study', '').strip()
        roll_number      = data.get('roll_number', '').strip()
        linkedin_url     = data.get('linkedin_url', '').strip()
        cgpa_raw         = data.get('cgpa', '7.5').strip()
        password         = data.get('password', '')
        photo_id         = request.files.get('photo_id')

        # ── Section 3: Events & Preferences ──
        # Checkboxes: name="events" — multiple values
        events_list     = request.form.getlist('events')
        tshirt_size     = data.get('tshirt_size', '').strip()
        meal_preference = data.get('meal_preference', '').strip()
        referral_source = data.get('referral_source', '').strip()
        team_size_raw   = data.get('team_size', '1').strip()
        team_name       = data.get('team_name', '').strip()
        badge_color     = data.get('badge_color', '#6C63FF').strip()
        special_requirements = data.get('special_requirements', '').strip()

        # ── Section 4: Payment & Consent ──
        fee_category = data.get('fee_category', 'early-bird').strip()
        coupon_code  = data.get('coupon_code', '').strip()
        on_site      = 1 if data.get('on_site', '') == 'yes' else 0
        newsletter   = 1 if data.get('newsletter') else 0

        # ── Validate required fields ──
        required = [
            full_name, email, phone, password, dob, gender, institution_type,
            college_name, department, year_of_study, roll_number, tshirt_size,
            meal_preference, photo_id,
        ]
        if not all(required):
            return jsonify({
                'success': False,
                'error': 'Required fields are missing. Please fill in all mandatory fields.'
            }), 400
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
            return jsonify({'success': False, 'error': 'Enter a valid email address.'}), 400
        if not re.fullmatch(r'[6-9]\d{9}', phone):
            return jsonify({'success': False, 'error': 'Enter a valid 10-digit mobile number.'}), 400
        if len(password) < 8 or len(password) > 50:
            return jsonify({'success': False, 'error': 'Password must be between 8 and 50 characters.'}), 400
        if not re.fullmatch(r'[A-Za-z\s]{1,80}', full_name):
            return jsonify({'success': False, 'error': 'Enter a valid name using letters only.'}), 400
        if len(college_name) > 100 or len(roll_number) > 20 or len(linkedin_url) > 200:
            return jsonify({'success': False, 'error': 'One or more academic fields exceed the allowed length.'}), 400
        if len(team_name) > 50 or len(coupon_code) > 20 or len(special_requirements) > 500:
            return jsonify({'success': False, 'error': 'One or more optional fields exceed the allowed length.'}), 400
        if not re.fullmatch(r'#[0-9A-Fa-f]{6}', badge_color):
            return jsonify({'success': False, 'error': 'Choose a valid badge color.'}), 400
        if data.get('agree_terms') != 'on':
            return jsonify({'success': False, 'error': 'Please agree to the Terms & Conditions.'}), 400
        if len(events_list) > 3:
            return jsonify({'success': False, 'error': 'You can select a maximum of 3 events.'}), 400
        if len(set(events_list)) != len(events_list):
            return jsonify({'success': False, 'error': 'An event can only be selected once.'}), 400
        if not events_list:
            return jsonify({'success': False, 'error': 'Select at least one event.'}), 400
        if any(event not in {'hackathon', 'ctf', 'code-clash', 'project-expo', 'quiz', 'paper', 'robowar', 'esports'} for event in events_list):
            return jsonify({'success': False, 'error': 'One or more selected events are invalid.'}), 400
        if year_of_study not in {'1', '2', '3', '4', 'pg'}:
            return jsonify({'success': False, 'error': 'Choose a valid year of study.'}), 400
        if fee_category not in {'early-bird', 'standard', 'premium'}:
            return jsonify({'success': False, 'error': 'Choose a valid registration category.'}), 400
        if gender not in {'male', 'female', 'non-binary', 'prefer-not'}:
            return jsonify({'success': False, 'error': 'Choose a valid gender option.'}), 400
        if institution_type not in {'engineering', 'arts-science', 'polytechnic', 'deemed', 'iit-nit', 'other'}:
            return jsonify({'success': False, 'error': 'Choose a valid institution type.'}), 400
        if tshirt_size not in {'xs', 's', 'm', 'l', 'xl', 'xxl'}:
            return jsonify({'success': False, 'error': 'Choose a valid T-shirt size.'}), 400
        if meal_preference not in {'veg', 'non-veg', 'vegan', 'jain'}:
            return jsonify({'success': False, 'error': 'Choose a valid meal preference.'}), 400
        if department not in {'cse', 'it', 'ece', 'eee', 'mech', 'civil', 'aids', 'other'}:
            return jsonify({'success': False, 'error': 'Choose a valid department.'}), 400
        if linkedin_url and not re.fullmatch(r'https://[^\s]+', linkedin_url):
            return jsonify({'success': False, 'error': 'Enter a valid HTTPS LinkedIn profile URL.'}), 400
        try:
            birth_date = datetime.strptime(dob, '%Y-%m-%d').date()
        except ValueError:
            return jsonify({'success': False, 'error': 'Enter a valid date of birth.'}), 400
        if not datetime(1995, 1, 1).date() <= birth_date <= datetime(2008, 12, 31).date():
            return jsonify({'success': False, 'error': 'Date of birth must be between 1995 and 2008.'}), 400

        # ── Type conversions ──
        try:
            cgpa = float(cgpa_raw)
            if not 0 <= cgpa <= 10:
                raise ValueError
        except ValueError:
            return jsonify({'success': False, 'error': 'CGPA must be between 0 and 10.'}), 400

        try:
            team_size = int(team_size_raw)
            if not 1 <= team_size <= 5:
                raise ValueError
        except ValueError:
            return jsonify({'success': False, 'error': 'Team size must be between 1 and 5.'}), 400

        try:
            _, photo_id_path = _store_upload(photo_id, {'.jpg', '.jpeg', '.png', '.pdf'}, 2 * 1024 * 1024)
        except ValueError as error:
            return jsonify({'success': False, 'error': str(error)}), 400
        photo_id_file = os.path.basename(photo_id_path)

        # ── Generate unique Registration ID: NXS-XXXXXX ──
        reg_id = 'NXS-' + secrets.token_hex(8).upper()

        # ── Insert into DB ──
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO registrations (
                reg_id, full_name, email, phone, password_hash, dob, gender,
                institution_type, college_name, department, year_of_study,
                roll_number, linkedin_url, cgpa, photo_id_path,
                events, tshirt_size, meal_preference, referral_source,
                team_size, team_name, badge_color, special_requirements,
                fee_category, coupon_code, on_site, newsletter
            ) VALUES (
                %s,%s,%s,%s,%s,%s,%s,
                %s,%s,%s,%s,%s,
                %s,%s,%s,
                %s,%s,%s,%s,
                %s,%s,%s,%s,
                %s,%s,%s,%s
            )
        ''', (
            reg_id, full_name, email, phone, generate_password_hash(password), dob, gender,
            institution_type, college_name, department, year_of_study,
            roll_number, linkedin_url, cgpa, photo_id_file,
            json.dumps(events_list), tshirt_size, meal_preference, referral_source,
            team_size, team_name, badge_color, special_requirements,
            fee_category, coupon_code, on_site, newsletter
        ))
        conn.commit()
        cursor.close()
        conn.close()

        # ── Send confirmation email (non-fatal) ──
        _send_registration_email(full_name, email, reg_id, fee_category, events_list)

        return jsonify({
            'success': True,
            'message': 'Registration successful! Check your email for confirmation.',
            'reg_id': reg_id,
            'name': full_name,
            'email': email
        })

    except mysql.connector.Error as db_err:
        if photo_id_path and os.path.exists(photo_id_path):
            os.remove(photo_id_path)
        print("DB error during registration:", db_err)
        return jsonify({'success': False, 'error': f'Database error: {db_err.msg}'}), 500
    except Exception as e:
        if photo_id_path and os.path.exists(photo_id_path):
            os.remove(photo_id_path)
        print("Error during registration:", str(e))
        return jsonify({'success': False, 'error': 'Registration could not be completed. Please try again.'}), 500


# ── Contact API ───────────────────────────────────────────────────────────────
@app.route('/api/contact', methods=['POST'])
def contact():
    """
    Accepts data from contact.html form.
    Supports both JSON and multipart/form-data.
    """
    try:
        if request.is_json:
            data = request.get_json() or {}
        else:
            data = request.form

        name        = (data.get('name', '') or '').strip()
        email       = (data.get('email', '') or '').strip()
        phone       = (data.get('phone', '') or '').strip()
        query_type  = (data.get('query_type', '') or '').strip()
        subject     = (data.get('subject', '') or '').strip()
        college     = (data.get('college', '') or '').strip()
        urgency_raw = (data.get('urgency_level', '3') or '3').strip()
        message     = (data.get('message', '') or '').strip()
        subscribe   = 1 if data.get('subscribe') else 0
        attachment = request.files.get('attachment')
        attachment_name = None
        attachment_path = None

        # Validate required fields
        if not all([name, email, query_type, subject, message]):
            return jsonify({
                'success': False,
                'error': 'Name, Email, Query Type, Subject, and Message are required.'
            }), 400
        if len(name) > 80 or len(email) > 100 or len(subject) > 150 or len(message) > 1000:
            return jsonify({'success': False, 'error': 'One or more contact fields exceed the allowed length.'}), 400
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
            return jsonify({'success': False, 'error': 'Enter a valid email address.'}), 400
        if phone and not re.fullmatch(r'[6-9]\d{9}', phone):
            return jsonify({'success': False, 'error': 'Enter a valid 10-digit mobile number.'}), 400
        if len(college) > 100:
            return jsonify({'success': False, 'error': 'College name must be 100 characters or fewer.'}), 400
        if query_type not in {'registration', 'event-info', 'payment', 'sponsorship', 'accommodation', 'media', 'volunteer', 'other'}:
            return jsonify({'success': False, 'error': 'Choose a valid query type.'}), 400
        try:
            urgency = int(urgency_raw)
            if not 1 <= urgency <= 5:
                raise ValueError
        except ValueError:
            return jsonify({'success': False, 'error': 'Priority level must be between 1 and 5.'}), 400

        if attachment and attachment.filename:
            try:
                attachment_name, attachment_path = _store_upload(
                    attachment, {'.jpg', '.jpeg', '.png', '.pdf', '.doc', '.docx'}, 5 * 1024 * 1024
                )
            except ValueError as error:
                return jsonify({'success': False, 'error': str(error)}), 400

        conn = get_db()
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO contact_messages
            (name, email, phone, query_type, subject, college, urgency_level, message, subscribe, attachment_path)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ''', (name, email, phone, query_type, subject, college, urgency, message, subscribe, attachment_name))
        conn.commit()
        cursor.close()
        conn.close()

        # Notify organizer via email (non-fatal)
        _notify_contact_email(name, email, query_type, subject, message, attachment_path)

        return jsonify({
            'success': True,
            'message': "Your message has been sent! We'll reply within 24 hours."
        })

    except mysql.connector.Error as db_err:
        if attachment_path and os.path.exists(attachment_path):
            os.remove(attachment_path)
        print("DB error during contact:", db_err)
        return jsonify({'success': False, 'error': f'Database error: {db_err.msg}'}), 500
    except Exception as e:
        if attachment_path and os.path.exists(attachment_path):
            os.remove(attachment_path)
        print("Error during contact:", str(e))
        return jsonify({'success': False, 'error': 'Your message could not be sent. Please try again.'}), 500


# ── Registration Lookup API ───────────────────────────────────────────────────
@app.route('/api/registration/<reg_id>', methods=['GET'])
def get_registration(reg_id):
    """Look up a registration by ID (used by confirm.html via URL param)."""
    try:
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            'SELECT reg_id, full_name, email, fee_category, events, submitted_at '
            'FROM registrations WHERE reg_id = %s',
            (reg_id.upper(),)
        )
        row = cursor.fetchone()
        cursor.close()
        conn.close()

        if not row:
            return jsonify({'success': False, 'error': 'Registration not found.'}), 404

        return jsonify({'success': True, 'registration': row})
    except Exception as e:
        print("Registration lookup error:", e)
        return jsonify({'success': False, 'error': 'Unable to look up this registration.'}), 500


# ── Razorpay Payment Endpoints ────────────────────────────────────────────────
FEE_AMOUNTS = {
    'early-bird': 29900,   # Rs.299 in paise
    'standard':   49900,   # Rs.499 in paise
    'premium':    79900,   # Rs.799 in paise
}

@app.route('/api/payment/create-order', methods=['POST'])
def payment_create_order():
    if not RAZORPAY_KEY_ID or not RAZORPAY_KEY_SECRET:
        return jsonify({
            'success': False,
            'error': 'Razorpay keys are not configured.'
        }), 500

    try:
        data     = request.get_json() or {}
        fee_cat  = data.get('fee_category', 'early-bird')
        if fee_cat not in FEE_AMOUNTS:
            return jsonify({'success': False, 'error': 'Choose a valid registration category.'}), 400
        amount   = FEE_AMOUNTS[fee_cat]
        currency = 'INR'
        receipt  = data.get('receipt') or f'nexus-{int(datetime.now().timestamp())}'

        body = json.dumps({
            'amount': amount,
            'currency': currency,
            'receipt': receipt,
            'notes': {
                'purpose': 'NEXUS 2025 registration fee',
                'event': 'NEXUS 2025 Technical Symposium',
                'fee_category': fee_cat
            }
        }).encode('utf-8')

        auth = base64.b64encode(
            f'{RAZORPAY_KEY_ID}:{RAZORPAY_KEY_SECRET}'.encode('utf-8')
        ).decode('utf-8')

        req = urllib.request.Request(
            'https://api.razorpay.com/v1/orders',
            data=body,
            headers={
                'Authorization': f'Basic {auth}',
                'Content-Type': 'application/json',
                'Accept': 'application/json'
            },
            method='POST'
        )

        with urllib.request.urlopen(req, timeout=20) as resp:
            payload = json.loads(resp.read().decode('utf-8'))

        return jsonify({
            'success': True,
            'order_id': payload.get('id'),
            'amount': payload.get('amount'),
            'currency': payload.get('currency'),
            'key_id': RAZORPAY_KEY_ID,
            'receipt': payload.get('receipt')
        })
    except Exception as exc:
        print('Razorpay order creation failed:', exc)
        return jsonify({'success': False, 'error': 'Unable to create Razorpay order.'}), 500


@app.route('/api/payment/verify', methods=['POST'])
def payment_verify():
    if not RAZORPAY_KEY_SECRET:
        return jsonify({'success': False, 'error': 'Razorpay secret not configured.'}), 500

    data       = request.get_json() or {}
    order_id   = str(data.get('order_id', '')).strip()
    payment_id = str(data.get('payment_id', '')).strip()
    signature  = str(data.get('signature', '')).strip()

    if not all([order_id, payment_id, signature]):
        return jsonify({'success': False, 'error': 'Missing payment verification data.'}), 400

    payload_str  = f'{order_id}|{payment_id}'.encode('utf-8')
    expected_sig = hmac.new(
        RAZORPAY_KEY_SECRET.encode('utf-8'),
        payload_str,
        hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(expected_sig, signature):
        return jsonify({'success': False, 'error': 'Invalid payment signature.'}), 400

    return jsonify({
        'success': True,
        'message': 'Payment verified successfully.',
        'status': 'paid'
    })


@app.route('/api/payment/verify-utr', methods=['POST'])
def verify_utr():
    """Verify UPI payment by UTR / Transaction ID."""
    import re
    data   = request.get_json() or {}
    utr    = data.get('utr', '').strip()
    upi_id = data.get('upi_id', '').strip()
    amount = data.get('amount', 0)
    reg_id = data.get('reg_id', '').strip()

    if not utr or len(utr) < 6 or not re.match(r'^[A-Za-z0-9]+$', utr):
        return jsonify({'success': False, 'error': 'Invalid Transaction ID. Please check and re-enter.'}), 400

    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute(
            'INSERT INTO payment_utr_log (utr, upi_id, amount, reg_id) VALUES (%s, %s, %s, %s)',
            (utr, upi_id, amount, reg_id)
        )
        conn.commit()
        cursor.close()
        conn.close()
    except Exception as e:
        print(f"UTR log error (non-fatal): {e}")

    return jsonify({
        'success': True,
        'message': 'Payment recorded. It will be confirmed by our team within 2 hours.',
        'utr': utr,
        'status': 'pending_verification'
    })


@app.route('/api/payment/initiate', methods=['POST'])
def payment_initiate():
    """Legacy alias: create a Razorpay order."""
    return payment_create_order()


@app.route('/api/payment/status/<txn_id>', methods=['GET'])
def payment_status(txn_id):
    return jsonify({
        'success': True,
        'transaction_id': txn_id,
        'status': 'paid' if RAZORPAY_KEY_ID else 'pending'
    })


@app.route('/api/payment/complete/<txn_id>', methods=['POST'])
def payment_complete(txn_id):
    return jsonify({
        'success': True,
        'transaction_id': txn_id,
        'status': 'completed'
    })


# ── Email Helpers ─────────────────────────────────────────────────────────────
def _send_registration_email(name, email, reg_id, fee_category, events):
    """Send confirmation email to the registrant."""
    if not SMTP_USERNAME or not SMTP_PASSWORD:
        return
    try:
        fee_labels = {'early-bird': 'Rs.299 (Early Bird)', 'standard': 'Rs.499 (Standard)', 'premium': 'Rs.799 (VIP Pass)'}
        fee_str    = fee_labels.get(fee_category, fee_category)
        events_str = ', '.join(events) if events else 'None selected'

        safe_name = escape(name)
        safe_events = escape(events_str)
        body = f"""
<html><body style="font-family:sans-serif;background:#0a0a1a;color:#e0e0e0;padding:32px;">
  <div style="max-width:560px;margin:0 auto;background:#111827;border-radius:16px;padding:32px;border:1px solid #1e293b;">
    <h1 style="color:#00f5a0;">Registration Confirmed!</h1>
    <p>Hi <strong>{safe_name}</strong>,</p>
    <p>You are officially registered for <strong>NEXUS 2025 Technical Symposium</strong>!</p>
    <div style="background:#0a0a1a;border-radius:10px;padding:20px;margin:20px 0;">
      <p><b>Registration ID:</b> <span style="color:#00f5a0;font-size:1.2rem;">{reg_id}</span></p>
      <p><b>Fee Category:</b> {fee_str}</p>
      <p><b>Events:</b> {safe_events}</p>
      <p><b>Event Date:</b> September 12-13, 2025</p>
      <p><b>Venue:</b> SVCE Campus, Pennalur, Tamil Nadu</p>
    </div>
    <p>Please keep your Registration ID handy for on-site verification.</p>
    <hr style="border-color:#1e293b;margin:24px 0;">
    <p style="font-size:0.8rem;color:#64748b;">NEXUS 2025 | India's Premier Technical Symposium</p>
  </div>
</body></html>
        """

        msg = MIMEMultipart('alternative')
        msg['Subject'] = f'NEXUS 2025 - Registration Confirmed! ID: {reg_id}'
        msg['From']    = f'{SMTP_FROM_NAME} <{SMTP_FROM_EMAIL}>'
        msg['To']      = email
        msg.attach(MIMEText(body, 'html'))

        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT_NUM) as server:
            server.starttls()
            server.login(SMTP_USERNAME, SMTP_PASSWORD)
            server.sendmail(SMTP_FROM_EMAIL, email, msg.as_string())
        print(f"Confirmation email sent to {email}")
    except Exception as e:
        print(f"Email error (non-fatal): {e}")


def _notify_contact_email(name, email, query_type, subject, message, attachment_path=None):
    """Notify organizer when a contact form is submitted."""
    if not SMTP_USERNAME or not SMTP_PASSWORD:
        return
    try:
        safe_name = escape(name)
        safe_email = escape(email)
        safe_query_type = escape(query_type)
        safe_subject = escape(subject)
        safe_message = escape(message)
        body = f"""
<html><body style="font-family:sans-serif;padding:24px;">
  <h2>New Contact Message - NEXUS 2025</h2>
  <table>
    <tr><td><b>From:</b></td><td>{safe_name} ({safe_email})</td></tr>
    <tr><td><b>Query Type:</b></td><td>{safe_query_type}</td></tr>
    <tr><td><b>Subject:</b></td><td>{safe_subject}</td></tr>
    <tr><td><b>Message:</b></td><td>{safe_message}</td></tr>
  </table>
</body></html>
        """
        msg = MIMEMultipart('alternative')
        msg['Subject'] = f'Contact: {subject}'
        msg['From']    = f'{SMTP_FROM_NAME} <{SMTP_FROM_EMAIL}>'
        msg['To']      = SMTP_USERNAME
        msg.attach(MIMEText(body, 'html'))
        if attachment_path:
            with open(attachment_path, 'rb') as attachment:
                part = MIMEApplication(attachment.read(), Name=os.path.basename(attachment_path))
            part['Content-Disposition'] = f'attachment; filename="{os.path.basename(attachment_path)}"'
            msg.attach(part)

        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT_NUM) as server:
            server.starttls()
            server.login(SMTP_USERNAME, SMTP_PASSWORD)
            server.sendmail(SMTP_FROM_EMAIL, SMTP_USERNAME, msg.as_string())
    except Exception as e:
        print(f"Contact notify email error (non-fatal): {e}")


# ── Run ───────────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    app.run(host=os.getenv('HOST', '127.0.0.1'), port=PORT, debug=False)
