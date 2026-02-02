from flask import Flask, render_template, request, send_file, flash, redirect, url_for, session
from converter import convert_bygglosen_data
from models import db, User, LoginLog
import io
from datetime import datetime
import os
from authlib.integrations.flask_client import OAuth
from dotenv import load_dotenv
from werkzeug.middleware.proxy_fix import ProxyFix

# Load environment variables from .env file
load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'supersecretkey')  # Use env var or default
app.config['SESSION_COOKIE_NAME'] = 'bygglosen-session'
app.config['PREFERRED_URL_SCHEME'] = 'https'
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

# --- Database Config ---
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL', 'sqlite:///app.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db.init_app(app)

# --- OAuth Config ---
oauth = OAuth(app)

# Google OAuth
google = oauth.register(
    name='google',
    client_id=os.getenv("GOOGLE_CLIENT_ID"),
    client_secret=os.getenv("GOOGLE_CLIENT_SECRET"),
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
    client_kwargs={'scope': 'openid email profile'}
)

# Microsoft OAuth (multi-tenant, skip issuer validation)
# For multi-tenant apps using /common, the issuer varies per tenant
# so we must skip issuer validation
microsoft = oauth.register(
    name='microsoft',
    client_id=os.getenv("MICROSOFT_CLIENT_ID"),
    client_secret=os.getenv("MICROSOFT_CLIENT_SECRET"),
    authorize_url='https://login.microsoftonline.com/common/oauth2/v2.0/authorize',
    access_token_url='https://login.microsoftonline.com/common/oauth2/v2.0/token',
    jwks_uri='https://login.microsoftonline.com/common/discovery/v2.0/keys',
    client_kwargs={
        'scope': 'openid email profile',
        'token_endpoint_auth_method': 'client_secret_post'
    }
)

# Helper function to create tables if they don't exist
with app.app_context():
    db.create_all()

@app.route('/')
def index():
    user = session.get('user')
    return render_template('index.html', user=user)

# --- Google Login ---
@app.route('/login/google')
def login_google():
    redirect_uri = url_for('auth_google', _external=True)
    return google.authorize_redirect(redirect_uri)

@app.route('/auth/google')
def auth_google():
    try:
        token = google.authorize_access_token()
        user_info = google.userinfo(token=token)
        
        provider_id = str(user_info.get('sub') or user_info.get('id'))
        email = user_info.get('email')
        
        # 1. Försök hitta på Google ID
        existing_user = User.query.filter_by(google_id=provider_id).first()
        
        # 2. Om inte hittad, försök hitta på e-post (kontolänkning)
        if not existing_user and email:
            existing_user = User.query.filter_by(email=email).first()
            if existing_user:
                existing_user.google_id = provider_id
        
        # 3. Om fortfarande inte hittad, skapa ny
        if not existing_user:
            existing_user = User(
                google_id=provider_id,
                email=email,
                name=user_info.get('name'),
                picture=user_info.get('picture')
            )
            db.session.add(existing_user)
        else:
            # Uppdatera info
            existing_user.name = user_info.get('name')
            existing_user.picture = user_info.get('picture')
        
        log_entry = LoginLog(user=existing_user)
        db.session.add(log_entry)
        db.session.commit()

        session['user'] = dict(user_info)
        return redirect('/')
    except Exception as e:
        flash(f'Google-inloggning misslyckades: {str(e)}')
        return redirect('/')

# --- Microsoft Login ---
@app.route('/login/microsoft')
def login_microsoft():
    redirect_uri = url_for('auth_microsoft', _external=True)
    return microsoft.authorize_redirect(redirect_uri)

@app.route('/auth/microsoft')
def auth_microsoft():
    try:
        token = microsoft.authorize_access_token(claims_options={
            'iss': {'essential': False},
            'aud': {'essential': True}
        })
        
        id_token = token.get('id_token')
        if id_token:
            import base64
            import json
            payload = id_token.split('.')[1]
            payload += '=' * (4 - len(payload) % 4)
            user_info = json.loads(base64.urlsafe_b64decode(payload))
        else:
            user_info = token.get('userinfo', {})
        
        provider_id = str(user_info.get('sub') or user_info.get('oid'))
        email = user_info.get('email') or user_info.get('preferred_username')
        
        # 1. Försök hitta på Microsoft ID
        existing_user = User.query.filter_by(microsoft_id=provider_id).first()
        
        # 2. Om inte hittad, försök hitta på e-post (kontolänkning)
        if not existing_user and email:
            existing_user = User.query.filter_by(email=email).first()
            if existing_user:
                existing_user.microsoft_id = provider_id
        
        # 3. Om fortfarande inte hittad, skapa ny
        if not existing_user:
            existing_user = User(
                microsoft_id=provider_id,
                email=email,
                name=user_info.get('name'),
                picture=user_info.get('picture')
            )
            db.session.add(existing_user)
        else:
            # Uppdatera info
            existing_user.name = user_info.get('name')
            existing_user.picture = user_info.get('picture')
        
        log_entry = LoginLog(user=existing_user)
        db.session.add(log_entry)
        db.session.commit()

        # Normalisera user_info för sessionen (så sessionen ser likadan ut oavsett provider om möjligt)
        if 'email' not in user_info and 'preferred_username' in user_info:
            user_info['email'] = user_info['preferred_username']

        session['user'] = dict(user_info)
        return redirect('/')
    except Exception as e:
        flash(f'Microsoft-inloggning misslyckades: {str(e)}')
        return redirect('/')

@app.route('/logout')
def logout():
    session.pop('user', None)
    return redirect('/')

@app.route('/admin')
def admin():
    user = session.get('user')
    
    # Enkel behörighetskontroll: Endast fredrikskonto@gmail.com får komma hit
    if not user or user.get('email') != 'fredrikskonto@gmail.com':
        flash('Du har inte behörighet till adminsidan.')
        return redirect('/')
    
    # Hämta alla användare och räkna inloggningar
    # Vi gör en enkel sats här, i större system skulle vi aggregera i SQL
    all_users = User.query.all()
    
    users_data = []
    for u in all_users:
        login_count = LoginLog.query.filter_by(user_id=u.id).count()
        last_login_entry = LoginLog.query.filter_by(user_id=u.id).order_by(LoginLog.timestamp.desc()).first()
        last_login_time = last_login_entry.timestamp.strftime("%Y-%m-%d %H:%M") if last_login_entry else "Aldrig"
        
        users_data.append({
            'name': u.name,
            'email': u.email,
            'picture': u.picture,
            'login_count': login_count,
            'last_login': last_login_time
        })
    
    # Sortera på senaste inloggning
    users_data.sort(key=lambda x: x['last_login'], reverse=True)
    
    return render_template('admin.html', users=users_data)

@app.route('/convert', methods=['POST'])
def convert():
    if not session.get('user'):
        flash('Du måste logga in för att konvertera filer.')
        return redirect('/')

    xml_files = request.files.getlist('xml_files')
    csv_file = request.files.get('csv_file')
    
    # XML files are required
    if not xml_files or all(f.filename == '' for f in xml_files):
        flash('Du måste ladda upp minst en XML-fil.')
        return redirect('/')
    
    # Filter out empty file inputs
    xml_files = [f for f in xml_files if f.filename != '']
    
    # CSV is optional - check if provided and has content
    csv_stream = None
    if csv_file and csv_file.filename != '':
        csv_stream = csv_file.stream
        
    try:
        xml_streams = [f.stream for f in xml_files]
        result_stream = convert_bygglosen_data(xml_streams, csv_stream)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"LOSEN_konverterad_{timestamp}.xml"
        return send_file(
            result_stream,
            as_attachment=True,
            download_name=filename,
            mimetype='application/xml'
        )
    except Exception as e:
        flash(f'Ett fel uppstod vid konvertering: {str(e)}')
        return redirect('/')

if __name__ == '__main__':
    app.run(debug=True)
