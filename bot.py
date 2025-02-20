from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes
import mysql.connector
from flask import Flask, jsonify, request, session , make_response
from flask_cors import CORS
import threading
import asyncio
import jwt
from dotenv import load_dotenv
from datetime import datetime,timedelta
from functools import wraps
import os
from flask import send_from_directory
from werkzeug.security import generate_password_hash, check_password_hash

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
SECRET_KEY = os.getenv("SECRET_KEY")

# Database Credentials
DB_HOST = os.getenv("DB_HOST")
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")
DB_NAME = os.getenv("DB_NAME")

# Initialize Flask app
app = Flask(__name__)
app.config['SECRET_KEY'] = SECRET_KEY
app.config['SESSION_TYPE'] = 'filesystem'
CORS(app, resources={r"/*": {'origins':"https://eventapp-zeta.vercel.app/"}},supports_credentials=True )  # better change the origin to "http://localhost:3000 for security purpose"

# ------------------- DATABASE CONNECTION -------------------
def get_db_connection():
    try:
        conn = mysql.connector.connect(
            host=DB_HOST,
            user=DB_USER,
            password=DB_PASSWORD,
            database=DB_NAME
        )
        return conn
    except mysql.connector.Error as err:
        print(f"Database connection error: {err}")  # Handle connection errors
        return None  

# ------------------- TELEGRAM BOT HANDLERS -------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the /start command"""
    keyboard = [[InlineKeyboardButton("View Events", url="https://eventapp-zeta.vercel.app/")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        "Welcome to the Event Organizer Bot!\nClick below to see upcoming events:",
        reply_markup=reply_markup
    )

async def button_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles button clicks in inline keyboard"""
    query = update.callback_query
    await query.answer()

    if query.data == "view_events":
        events = get_events()  # Fetch events from database
        event_list = "\n".join([f"{e['title']} - {e['date']}" for e in events])
        await query.message.reply_text(f"Upcoming Events:\n{event_list}" if events else "No events found.")
# ------------------- AUTHENTICATION -------------------
def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.headers.get('Authorization')
        if not token:
            return jsonify({"error": "Token is missing!"}), 401

        try:
            data = jwt.decode(token, app.config['SECRET_KEY'], algorithms=["HS256"])
            current_user = data['user_id']
        except:
            return jsonify({"error": "Invalid or expired token!"}), 401

        return f(current_user, *args, **kwargs)
    
    return decorated

@app.route('/api/signup', methods=['POST', 'OPTIONS'])
def signup():
    """ Register a new user """
    if request.method == "OPTIONS":
        response = make_response()
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Methods"] = "POST, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
        return response, 200

    try:
         # Print raw request data to check if it's being received
        print("Raw Request Data:", request.data)

        data = request.get_json()
        if not data:
            print("Error: No JSON data received")
            return jsonify({"error": "Missing JSON data"}), 400

        email = data.get('email')
        password = data.get('password')

        # Debugging: Print received values
        print("Received Email:", email)
        print("Received Password:", password)

        if not email or not password:
            print("Error: Missing email or password")
            return jsonify({"error": "Missing required fields"}), 400

        # Hash the password
        from werkzeug.security import generate_password_hash
        hashed_password = generate_password_hash(password)
        print("Hashed Password:", hashed_password)

        # Connect to the database
        conn = get_db_connection()
        cursor = conn.cursor()

        # Check if user already exists
        cursor.execute("SELECT * FROM users WHERE email = %s", (email,))
        existing_user = cursor.fetchone()
        if existing_user:
            cursor.close()
            conn.close()
            return jsonify({"error": "User already exists"}), 400

        # Insert new user (fixing missing name and role)
        cursor.execute("INSERT INTO users (email, password) VALUES (%s, %s)", (email, password))
        conn.commit()

        cursor.close()
        conn.close()

        return jsonify({"message": "User registered successfully!"}), 201

    except Exception as e:
        print("Error:", str(e))  # Debugging
        return jsonify({"error": "Internal Server Error"}), 500
   

    

@app.route('/api/login', methods=['POST' ,'OPTIONS'])
def login():
    """ User Login """
    if request.method == "OPTIONS":
        response = make_response()
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Methods"] = "POST, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
        return response, 200
    data = request.json
    email = data['email']
    password = data['password']

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM users WHERE email = %s", (email,))
    user = cursor.fetchone()
    cursor.close()
    conn.close()

    if not user or not check_password_hash(user["password"], password):
        return jsonify({"error": "Invalid credentials"}), 401

    token = jwt.encode(
        {"user_id": user["id"], "exp": datetime.datetime.utcnow() + timedelta(hours=24)},
        app.config["SECRET_KEY"], algorithm="HS256"
    )

    return jsonify({"token": token, "role": user["role"], "user_id": user["id"]}), 200



# ------------------- EVENT API ENDPOINTS -------------------
app.static_folder = 'images'  # This is crucial!
@app.route('/images/<filename>')
def serve_image(filename):
    return send_from_directory('/images', filename)
@app.route('/api/events', methods=['GET'])
def get_events():
    """ Fetch all events """
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM events")
    events = cursor.fetchall()
    for event in events:
        # Convert 'time' if it's a timedelta object
        if "time" in event and isinstance(event["time"], timedelta):
            event["time"] = (datetime.min + event["time"]).time().isoformat() 
    for event in events:
        if "image" in event and event["image"]:
            event["image_url"] = f"http://localhost:5000/images/{event['image']}"
        else:
            event["image_url"] = None
    cursor.close()
    conn.close()
    return jsonify(events), 200

@app.route("/api/events/<int:event_id>", methods=["GET"])
def get_event(event_id):
    """ Fetch a single event """
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM events WHERE id = %s", (event_id,))
    event = cursor.fetchone()
    
    if event:
        # Convert 'time' if it's a timedelta object
        if "time" in event and isinstance(event["time"], timedelta):
            event["time"] = (datetime.min + event["time"]).time().isoformat()

        cursor.close()
        conn.close()
        return jsonify(event), 200  

    cursor.close()
    conn.close()
    return jsonify({"error": "Event not found"}), 404

@app.route('/api/events', methods=['POST'])
@token_required
def add_event(current_user):
    """ Add a new event (Organizers Only) """
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("SELECT role FROM users WHERE id = %s", (current_user,))
    user = cursor.fetchone()

    if user["role"] != "organizer":
        return jsonify({"error": "Permission denied"}), 403

    data = request.json
    sql = "INSERT INTO events (title, image, date, time, location, organizer_id) VALUES (%s, %s, %s, %s, %s, %s)"
    values = (data['title'], data['image'], data['date'], data['time'], data['location'], current_user)

    cursor.execute(sql, values)
    conn.commit()
    cursor.close()
    conn.close()
    return jsonify({"message": "Event added successfully"}), 201

@app.route('/api/events/<int:event_id>', methods=['PUT'])
@token_required
def update_event(current_user, event_id):
    """ Update an existing event (Organizers Only) """
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("SELECT * FROM events WHERE id = %s AND organizer_id = %s", (event_id, current_user))
    event = cursor.fetchone()

    if not event:
        return jsonify({"error": "Event not found or unauthorized"}), 403

    data = request.json
    sql = "UPDATE events SET title = %s, image = %s, date = %s, time = %s, location = %s WHERE id = %s"
    values = (data['title'], data['image'], data['date'], data['date_time'], data['location'], event_id)

    cursor.execute(sql, values)
    conn.commit()
    cursor.close()
    conn.close()
    return jsonify({"message": "Event updated successfully"}), 200

@app.route('/api/events/<int:event_id>', methods=['DELETE'])
@token_required
def delete_event(current_user, event_id):
    """ Delete an event (Organizers Only) """
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("SELECT * FROM events WHERE id = %s AND organizer_id = %s", (event_id, current_user))
    event = cursor.fetchone()

    if not event:
        return jsonify({"error": "Event not found or unauthorized"}), 403

    cursor.execute("DELETE FROM events WHERE id = %s", (event_id,))
    conn.commit()
    cursor.close()
    conn.close()
    return jsonify({"message": "Event deleted successfully"}), 200

# ------------------- RUN BOTH FLASK & TELEGRAM BOT -------------------
def run_bot():
    """ Run Telegram bot in a separate thread """
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    application = ApplicationBuilder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(button_click))

    loop.run_until_complete(application.run_polling())

if __name__ == "__main__":
    bot_thread = threading.Thread(target=run_bot, daemon=True)
    bot_thread.start()
    app.run(debug=True, port=5000, use_reloader=False)
