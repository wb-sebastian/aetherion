import sys, os, json, asyncio, base64, threading, re
import asyncio
from datetime import datetime
from flask import Flask, request, jsonify, redirect, session, url_for
from flask_cors import CORS
from dotenv import load_dotenv
import discord
from discord.ext import commands
from discord.utils import get
import easyocr
import face_recognition
from uuid import uuid4
import subprocess  # To run ngrok from within the script
import time
import requests
import os
import json

# Discord OAuth2 Configuration
DISCORD_CLIENT_ID = os.getenv("DISCORD_CLIENT_ID")
DISCORD_CLIENT_SECRET = os.getenv("DISCORD_CLIENT_SECRET")
DISCORD_REDIRECT_URI = os.getenv("DISCORD_REDIRECT_URI")
DISCORD_API_BASE_URL = 'https://discord.com/api/v10'

# Flask App
app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY") # Required for sessions
CORS(app)  # Enable CORS for all routes

SETTINGS_FILE = 'settings.json'

def load_settings():
    if os.path.exists(SETTINGS_FILE):
        with open(SETTINGS_FILE, 'r') as f:
            return json.load(f)
    return {"guild_settings": {}}

def save_settings(settings):
    with open(SETTINGS_FILE, 'w') as f:
        json.dump(settings, f, indent=4)

global_settings = load_settings()

# Load environment variables
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")

# Using current directory for images
IMAGE_FOLDER_PATH = os.path.join(os.getcwd(), "Images")
os.makedirs(IMAGE_FOLDER_PATH, exist_ok=True)

intents = discord.Intents.default()
intents.members = True
intents.message_content = True
bot = commands.Bot(command_prefix="!a ", intents=intents)

GUILD_ID = 1400436272522334218
STAFF_ROLE_NAME = "Staff"
OWNER_ID = 1179896254487089293
ID_ARCHIVE_CHANNEL = "id-archive"
LOG_CHANNEL = "aetherion-logs"
VERIFICATION_CATEGORY = "Verification Protocol"

# Flask App
app = Flask(__name__)
CORS(app)  # Enable CORS for all routes

STATIC_DOMAIN = None  # Initialize it as None
STATIC_SUBDOMAIN = "aetherion.infy.uk"  # Static subdomain for hosting the HTML file

# Start ngrok and return the public URL
def start_ngrok():
    global STATIC_DOMAIN  # Declare as global to update it
    try:
        # Start ngrok in a subprocess
        subprocess.Popen(["ngrok", "http", "5000"], stdout=subprocess.PIPE)
        print("🔄 Starting ngrok...")
        time.sleep(5)  # Wait for ngrok to start

        # Get the public URL from ngrok API
        import requests
        response = requests.get("http://localhost:4040/api/tunnels")
        data = response.json()
        for tunnel in data["tunnels"]:
            if tunnel["proto"] == "https":
                STATIC_DOMAIN = tunnel["public_url"]
                print(f"Ngrok URL: {STATIC_DOMAIN}")
                # Update the static HTML file with the ngrok URL
                # Removed update_static_html as it's not needed for local serving of index.html
                break
    except Exception as e:
        print(f"❌ Error while starting ngrok: {e}")

# Notify Discord channel with ngrok URL
async def notify_ngrok_url(ngrok_url):
    guild = bot.get_guild(GUILD_ID)
    log_channel = discord.utils.get(guild.text_channels, name=LOG_CHANNEL)

    if log_channel and ngrok_url:
        embed = discord.Embed(
            title="Aetherion Verification System Started",
            description=f"**System Status:**\n\n**Flask Server:** Running at {ngrok_url}\n\n**Verification Form:** Available at http://{STATIC_SUBDOMAIN}/?user_id=USER_ID\n\n**How it works:**\n1. Users click the verification link in their private channel\n2. The form at http://{STATIC_SUBDOMAIN} captures ID and selfie\n3. Images are submitted to the Flask server via {ngrok_url}\n4. User returns to Discord and types `!a proceed`",
            color=discord.Color.green()
        )
        embed.set_footer(text="The static HTML has been updated with the current ngrok URL")
        await log_channel.send(embed=embed)

# Start Flask and ngrok, then notify Discord
async def start_server():
    start_ngrok()  # Start ngrok and update STATIC_DOMAIN
    if STATIC_DOMAIN:
        await notify_ngrok_url(STATIC_DOMAIN)

# Flask server in a thread
def run_flask():
    app.run(host="0.0.0.0", port=5000)

threading.Thread(target=run_flask, daemon=True).start()

@bot.event
async def on_ready():
    print(f"Aetherion is online as {bot.user}")
    # Start the Flask server and ngrok when the bot is ready
    await start_server()

@app.route('/')
def index():
    return app.send_static_file('index.html')

@app.route('/test')
def test():
    return app.send_static_file('test.html')

@app.route('/login')
def login():
    return redirect(f"https://discord.com/oauth2/authorize?client_id={DISCORD_CLIENT_ID}&redirect_uri={DISCORD_REDIRECT_URI}&response_type=code&scope=identify%20guilds")

@app.route('/callback')
def callback():
    code = request.args.get('code')
    if not code:
        return jsonify({"error": "No code provided"}), 400

    data = {
        'client_id': DISCORD_CLIENT_ID,
        'client_secret': DISCORD_CLIENT_SECRET,
        'grant_type': 'authorization_code',
        'code': code,
        'redirect_uri': DISCORD_REDIRECT_URI,
        'scope': 'identify guilds'
    }
    headers = {
        'Content-Type': 'application/x-www-form-urlencoded'
    }

    try:
        response = requests.post(f"{DISCORD_API_BASE_URL}/oauth2/token", data=data, headers=headers)
        response.raise_for_status()
        token_data = response.json()

        access_token = token_data['access_token']
        refresh_token = token_data.get('refresh_token')
        expires_in = token_data['expires_in']

        session['discord_access_token'] = access_token
        session['discord_refresh_token'] = refresh_token
        session['discord_expires_at'] = datetime.now().timestamp() + expires_in

        # Fetch user info
        user_headers = {
            'Authorization': f'Bearer {access_token}'
        }
        user_response = requests.get(f"{DISCORD_API_BASE_URL}/users/@me", headers=user_headers)
        user_response.raise_for_status()
        user_info = user_response.json()
        session['discord_user_id'] = user_info['id']
        session['discord_username'] = user_info['username']

        # Fetch user guilds
        guilds_response = requests.get(f"{DISCORD_API_BASE_URL}/users/@me/guilds", headers=user_headers)
        guilds_response.raise_for_status()
        guilds_info = guilds_response.json()
        session['discord_guilds'] = guilds_info

        return redirect(url_for('dashboard')) # Redirect to a dashboard or success page

    except requests.exceptions.RequestException as e:
        print(f"Error during OAuth2 callback: {e}")
        return jsonify({"error": "Failed to get access token"}), 500

@app.route('/refresh_token')
def refresh_token():
    if 'discord_refresh_token' not in session:
        return jsonify({"error": "No refresh token available"}), 400

    data = {
        'client_id': DISCORD_CLIENT_ID,
        'client_secret': DISCORD_CLIENT_SECRET,
        'grant_type': 'refresh_token',
        'refresh_token': session['discord_refresh_token']
    }
    headers = {
        'Content-Type': 'application/x-www-form-urlencoded'
    }

    try:
        response = requests.post(f"{DISCORD_API_BASE_URL}/oauth2/token", data=data, headers=headers)
        response.raise_for_status()
        token_data = response.json()

        access_token = token_data['access_token']
        refresh_token = token_data.get('refresh_token', session['discord_refresh_token']) # Refresh token might not be returned
        expires_in = token_data['expires_in']

        session['discord_access_token'] = access_token
        session['discord_refresh_token'] = refresh_token
        session['discord_expires_at'] = datetime.now().timestamp() + expires_in

        return jsonify({"message": "Token refreshed successfully"}), 200

    except requests.exceptions.RequestException as e:
        print(f"Error refreshing token: {e}")
        return jsonify({"error": "Failed to refresh token"}), 500

@app.route('/dashboard')
@app.route('/dashboard/<int:guild_id>')
def dashboard(guild_id=None):
    if 'discord_user_id' not in session:
        return redirect(url_for('login'))

    user_id = session['discord_user_id']
    username = session['discord_username']
    guilds = session.get('discord_guilds', [])

    # Filter for guilds where the user has 'manage_guild' permission
    managed_guilds = [g for g in guilds if g.get('permissions') and int(g['permissions']) & 0x20]

    if guild_id:
        # Check if the user manages this guild
        if not any(g['id'] == str(guild_id) for g in managed_guilds):
            return jsonify({"error": "Unauthorized: You do not manage this guild."}), 403

        # Get or initialize guild settings
        guild_settings = global_settings['guild_settings'].get(str(guild_id), {
            "log_channel_id": None,
            "info_channel_id": None,
            "age_roles": {},
            "verified_role_id": None,
            "min_age_for_verified_role": None
        })
        return jsonify({"guild_id": guild_id, "settings": guild_settings})
    else:
        return jsonify({
            "user_id": user_id,
            "username": username,
            "managed_guilds": managed_guilds
        })

@app.route('/api/guild_settings/<int:guild_id>', methods=['GET', 'POST'])
def api_guild_settings(guild_id):
    if 'discord_user_id' not in session:
        return jsonify({"error": "Unauthorized"}), 401

    user_id = session['discord_user_id']
    guilds = session.get('discord_guilds', [])

    # Check if the user manages this guild
    if not any(g['id'] == str(guild_id) for g in guilds if g.get('permissions') and int(g['permissions']) & 0x20):
        return jsonify({"error": "Unauthorized: You do not manage this guild."}), 403

    if request.method == 'GET':
        settings = global_settings['guild_settings'].get(str(guild_id), {
            "log_channel_id": None,
            "info_channel_id": None,
            "age_roles": {},
            "verified_role_id": None,
            "min_age_for_verified_role": None
        })
        return jsonify(settings)
    elif request.method == 'POST':
        data = request.get_json()
        if not data:
            return jsonify({"error": "No data provided"}), 400

        # Update settings for the guild
        current_settings = global_settings['guild_settings'].get(str(guild_id), {})
        current_settings.update(data)
        global_settings['guild_settings'][str(guild_id)] = current_settings
        save_settings(global_settings)

        return jsonify({"message": "Settings updated successfully", "settings": current_settings}), 200

@app.route('/submit-images', methods=['POST'])
def submit_images():
    user_id = request.args.get("user_id")
    if not user_id:
        print("❌ Missing user_id in request.")
        return jsonify({"error": "Missing user_id in URL"}), 400

    data = request.get_json()
    id_image_data = data.get('id_image')
    selfie_image_data = data.get('selfie_image')

    if not id_image_data or not selfie_image_data:
        print("❌ Missing one or both image files.")
        return jsonify({"error": "Missing image data"}), 400

    user_directory = os.path.join(IMAGE_FOLDER_PATH, f"user_{user_id}")
    os.makedirs(user_directory, exist_ok=True)

    try:
        save_image(id_image_data, user_directory, f"{user_id}_ID")
        save_image(selfie_image_data, user_directory, f"{user_id}_Selfie")
        print(f"✅ Images saved for user {user_id}")
        return jsonify({"message": "Images received successfully"}), 200
    except Exception as e:
        print(f"❌ Failed to save images: {e}")
        return jsonify({"error": "Failed to save images"}), 500

import base64

def save_image(image_data_base64, directory, image_type):
    try:
        # Remove the 'data:image/jpeg;base64,' prefix if present
        if ',' in image_data_base64:
            header, base64_string = image_data_base64.split(',', 1)
        else:
            base64_string = image_data_base64

        image_bytes = base64.b64decode(base64_string)
        file_path = os.path.join(directory, f"{image_type}.png")
        with open(file_path, 'wb') as f:
            f.write(image_bytes)
    except Exception as e:
        print(f"Error saving {image_type}: {e}")
        raise

@bot.command()
async def verify(ctx):
    guild = ctx.guild
    user = ctx.author

    if discord.utils.get(guild.text_channels, name=str(user.id)):
        await ctx.send(f"You already have an active session.")
        return

    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        user: discord.PermissionOverwrite(view_channel=True, send_messages=True),
        get(guild.roles, name=STAFF_ROLE_NAME): discord.PermissionOverwrite(view_channel=True),
        guild.me: discord.PermissionOverwrite(view_channel=True)
    }

    category = discord.utils.get(guild.categories, name=VERIFICATION_CATEGORY)
    if not category:
        category = await guild.create_category(VERIFICATION_CATEGORY)

    channel = await guild.create_text_channel(str(user.id), overwrites=overwrites, category=category)

    # Send immediate verification channel message
    await ctx.send(f"Your verification channel has been opened in {channel.mention}.")

    # ToS Embed
    tos_embed = discord.Embed(
        title="Terms of Service Agreement",
        description="By reacting to this message with a ☑️, you agree to our Terms of Service and Privacy Policy found in `#aetherion-info`.",
        color=discord.Color.orange()
    )
    tos_msg = await channel.send(content=user.mention, embed=tos_embed)
    await tos_msg.add_reaction("☑️")

    def check(reaction, reactor):
        return reactor == user and str(reaction.emoji) == "☑️" and reaction.message.id == tos_msg.id

    try:
        await bot.wait_for('reaction_add', check=check, timeout=300)
    except asyncio.TimeoutError:
        await channel.send("⏰ Verification timed out. Please start again.")
        return

    # Check if ngrok tunnel is started
    if STATIC_DOMAIN is None:
        await channel.send("⚠️ Ngrok tunnel hasn't started yet, please try again.")
        return

    # Verification form link using the static subdomain
    verify_embed = discord.Embed(
        title="Click here to start the verification",
        url=f"http://{STATIC_SUBDOMAIN}/?user_id={user.id}",
        description="After submitting both images, please return to this channel and run `!a proceed` to continue with your verification.",
        color=discord.Color.blue()
    )
    await channel.send(embed=verify_embed)

@bot.command()
async def proceed(ctx):
    user_id = str(ctx.author.id)
    guild = ctx.guild

    if guild is None:
        await ctx.send("This command can only be used in a server channel.")
        return
    user_dir = os.path.join(IMAGE_FOLDER_PATH, f"user_{user_id}")
    id_path = os.path.join(user_dir, f"{user_id}_ID.png")
    selfie_path = os.path.join(user_dir, f"{user_id}_Selfie.png")

    if not os.path.exists(id_path) or not os.path.exists(selfie_path):
        await ctx.send("❌ Missing one or both images. Please upload your images first.")
        return

    await ctx.send("🔍 Verifying...")

    reader = easyocr.Reader(['en'], gpu=False)
    result = reader.readtext(id_path, detail=0)
    text = ' '.join(result)

    dob_str = extract_dob_from_text(text)
    if not dob_str:
        await send_result(ctx, False, "OCR001", "Could not extract date of birth.")
        return

    age = calculate_age(dob_str)
    role_name = get_role_based_on_age(age)

    id_img = face_recognition.load_image_file(id_path)
    selfie_img = face_recognition.load_image_file(selfie_path)

    id_encodings = face_recognition.face_encodings(id_img)
    selfie_encodings = face_recognition.face_encodings(selfie_img)

    if not id_encodings or not selfie_encodings:
        await send_result(ctx, False, "FACE001", "No face detected in one or both images.")
        return

    match = face_recognition.compare_faces([id_encodings[0]], selfie_encodings[0])[0]
    if not match:
        await send_result(ctx, False, "FACE002", "Face mismatch between ID and selfie.")
        return

    member = guild.get_member(int(user_id))
    role = get(guild.roles, name=role_name) if role_name else None
    if member and role:
        await member.add_roles(role)
    
        unverified_role_name = f"{role_name} UnV"
        unverified_role = get(guild.roles, name=unverified_role_name)
        if unverified_role in member.roles:
            await member.remove_roles(unverified_role)

    await send_result(ctx, True, age=age, role=role_name)

    verification_channel = discord.utils.get(guild.text_channels, name=user_id)
    if verification_channel:
        await asyncio.sleep(3)
        await verification_channel.delete()

    # Log result
    await log_verification_info(ctx.author, age, role_name, id_path, selfie_path)

async def send_result(ctx, success, error_code=None, reason=None, age=None, role=None):
    user = ctx.author
    guild = bot.get_guild(GUILD_ID)
    verification_channel = discord.utils.get(guild.text_channels, name=str(user.id))
    result_embed = discord.Embed()

    if success:
        result_embed.title = "✅ Successfully Verified"
        result_embed.description = f"Your account has been successfully verified in Grayscale.\n**INFO:** extracted age: `{age}`"
        result_embed.color = discord.Color.green()
        log_msg = f"✅ {user} verified successfully (Age: {age}, Role: {role})"
    else:
        result_embed.title = "❌ Verification Failed"
        result_embed.description = f"Your verification at Grayscale has failed. Please try again.\n**INFO:** Error code: `{error_code}` | Reason: `{reason}`"
        result_embed.color = discord.Color.red()
        log_msg = f"❌ {user} verification failed (Code: {error_code}, Reason: {reason})"

    try:
        await user.send(embed=result_embed)
    except discord.Forbidden:
        if verification_channel:
            await verification_channel.send(user.mention, embed=result_embed)

    log_channel = discord.utils.get(guild.text_channels, name=LOG_CHANNEL)
    if log_channel:
        await log_channel.send(log_msg)

    # Try deleting the verification channel, whether success or failure
    if verification_channel:
        await asyncio.sleep(3)
        await verification_channel.delete()

async def log_verification_info(user, age, role, id_image, selfie_image):
    guild = bot.get_guild(GUILD_ID)
    log_channel = discord.utils.get(guild.text_channels, name=LOG_CHANNEL)

    timestamp = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
    log_msg = f"Timestamp: {timestamp}\nUser: {user}\nAge: {age}\nRole: {role}\nID Image: {id_image}\nSelfie Image: {selfie_image}"

    if log_channel:
        await log_channel.send(log_msg)
        # Optional: Send the images as well
        await log_channel.send(file=discord.File(id_image))
        await log_channel.send(file=discord.File(selfie_image))

def dob_from_cnp(cnp):
    try:
        if not cnp.isdigit():
            return None
        if len(cnp) == 12:
            cnp = '5' + cnp # Assume 2000s for 12-digit CNPs (common OCR error)
        elif len(cnp) != 13:
            return None

        # Extract date part: positions 1 to 6 (YYMMDD)
        year = int(cnp[1:3])
        month = int(cnp[3:5])
        day = int(cnp[5:7])
        century_code = cnp[0]

        # Determine century based on the first digit
        if century_code in ['1', '2']:  # 1900–1999
            year += 1900
        elif century_code in ['3', '4']:  # 1800–1899
            year += 1800
        elif century_code in ['5', '6']:  # 2000–2099
            year += 2000
        else:
            return None

        dob = datetime(year, month, day)
        return dob.strftime("%d/%m/%Y")
    except Exception as e:
        print(f"[CNP DOB extraction error] {e}")
        return None


def extract_dob_from_text(text):
    # Step 1: Look for CNP first
    print(f"[OCR Text Debug] Full OCR text: {text}")
    all_digit_sequences = re.findall(r"\d+", text, re.UNICODE)
    print(f"[CNP DOB Debug] All digit sequences found: {all_digit_sequences}")
    cnp_matches = [s for s in all_digit_sequences if len(s) == 12 or len(s) == 13]
    print(f"[CNP DOB Debug] Found CNP matches: {cnp_matches}")
    for cnp in cnp_matches:
        dob = dob_from_cnp(cnp)
        print(f"[CNP DOB Debug] Processing CNP: {cnp}, Extracted DOB: {dob}")
        if dob:
            print(f"[CNP DOB] Extracted DOB from CNP: {dob}")
            return dob

    # Step 2: Fallback to keyword-based DOB patterns
    dob_keywords = r"(?:DOB|DoB|dob|Date of Birth|DATE OF BIRTH)"
    dob_patterns = [
        rf"{dob_keywords}[^\d]{{0,10}}(\d{{1,2}}[\/\.-]\d{{1,2}}[\/\.-]\d{{2,4}})",
        r"(\d{1,2}[\/\.-]\d{1,2}[\/\.-]\d{2,4})"  # Last-resort fallback
    ]

    for pattern in dob_patterns:
        matches = re.findall(pattern, text, re.IGNORECASE)
        for dob_raw in matches:
            for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%d/%m/%y", "%d-%m/%y", "%d.%m/%y"):
                try:
                    dob_obj = datetime.strptime(dob_raw, fmt)
                    parsed = dob_obj.strftime("%d/%m/%Y")
                    print(f"[Fallback DOB] Extracted DOB from text: {parsed}")
                    return parsed
                except ValueError:
                    continue
    return None

def calculate_age(dob_str):
    dob = datetime.strptime(dob_str, "%d/%m/%Y")
    today = datetime.today()
    return today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))

def get_role_based_on_age(age):
    if age < 16:
        return None
    elif 16 <= age <= 18:
        return "16-18"
    else:
        return "19+"

@bot.command()
async def info(ctx):
    help_embed = discord.Embed(
        title="Aetherion Help",
        description="Here are the available commands for Aetherion.",
        color=discord.Color.blue()
    )
    help_embed.add_field(name="!a verify", value="Start the verification process by opening a verification channel.", inline=False)
    help_embed.add_field(name="!a proceed", value="Complete the verification process by submitting both your ID and selfie.", inline=False)
    help_embed.add_field(name="!a info", value="Displays this help message.", inline=False)
    
    # Add staff commands if the user has permission
    if ctx.author.id == OWNER_ID or any(role.name == STAFF_ROLE_NAME for role in ctx.author.roles):
        help_embed.add_field(name="Staff Commands", value="-----------------", inline=False)
        help_embed.add_field(name="!a sudo apt --shutdown", value="Shuts down the bot (Staff only).", inline=False)
    
    await ctx.send(embed=help_embed)

@bot.command(name="sudo")
async def sudo_command(ctx, apt=None, shutdown=None):
    # Check if the command is "sudo apt --shutdown"
    if apt == "apt" and shutdown == "--shutdown":
        # Check if the user has permission (owner or staff)
        if ctx.author.id == OWNER_ID or any(role.name == STAFF_ROLE_NAME for role in ctx.author.roles):
            shutdown_embed = discord.Embed(
                title="⚠️ Bot Shutdown",
                description="The bot is shutting down...",
                color=discord.Color.red()
            )
            await ctx.send(embed=shutdown_embed)
            await bot.close()
        else:
            no_permission = discord.Embed(
                title="❌ Permission Denied",
                description="You do not have permission to shut down the bot.",
                color=discord.Color.red()
            )
            await ctx.send(embed=no_permission)

bot.run(BOT_TOKEN)
