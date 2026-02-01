from flask import Flask, render_template, request, send_file, flash, redirect, url_for, session
from converter import convert_bygglosen_data
from models import db, User, LoginLog
import io
from datetime import datetime
import os
from authlib.integrations.flask_client import OAuth
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'supersecretkey')  # Use env var or default
app.config['SESSION_COOKIE_NAME'] = 'google-login-session'

# --- Database Config ---
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL', 'sqlite:///app.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db.init_app(app)

# --- OAuth Config ---
oauth = OAuth(app)
google = oauth.register(
    name='google',
    client_id=os.getenv("GOOGLE_CLIENT_ID"),
    client_secret=os.getenv("GOOGLE_CLIENT_SECRET"),
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
    client_kwargs={'scope': 'openid email profile'}
)

# Helper function to create tables if they don't exist
with app.app_context():
    db.create_all()

@app.route('/')
def index():
    user = session.get('user')
    return render_template('index.html', user=user)

@app.route('/login')
def login():
    redirect_uri = url_for('auth', _external=True)
    return google.authorize_redirect(redirect_uri)

@app.route('/auth')
def auth():
    try:
        token = google.authorize_access_token()
        user_info = google.userinfo(token=token)
        
        # OpenID Connect använder 'sub' (subject) som unik identifierare, inte 'id'
        google_id = user_info.get('sub') or user_info.get('id')
        
        # Spara eller uppdatera användaren i databasen
        existing_user = User.query.filter_by(google_id=google_id).first()
        
        if not existing_user:
            existing_user = User(
                google_id=google_id,
                email=user_info['email'],
                name=user_info.get('name'),
                picture=user_info.get('picture')
            )
            db.session.add(existing_user)
        else:
            # Uppdatera info om det ändrats (t.ex. bild eller namn)
            existing_user.name = user_info.get('name')
            existing_user.picture = user_info.get('picture')
        
        # Logga inloggningstillfället
        log_entry = LoginLog(user=existing_user)
        db.session.add(log_entry)
        db.session.commit()

        # Spara i sessionen
        session['user'] = dict(user_info)
        return redirect('/')
    except Exception as e:
        flash(f'Inloggning misslyckades: {str(e)}')
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
    
    if not xml_files or not csv_file:
        flash('Både XML och CSV måste laddas upp.')
        return redirect('/')
        
    if any(f.filename == '' for f in xml_files) or csv_file.filename == '':
        flash('Ingen fil vald.')
        return redirect('/')
        
    if xml_files and csv_file:
        try:
            xml_streams = [f.stream for f in xml_files]
            result_stream = convert_bygglosen_data(xml_streams, csv_file.stream)
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
    
    return redirect('/')

if __name__ == '__main__':
    app.run(debug=True)
