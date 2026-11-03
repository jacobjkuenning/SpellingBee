from flask import Flask, render_template, request, redirect, url_for, session, jsonify
import sqlite3
import hashlib
from datetime import date

app = Flask(__name__)
app.secret_key = 'super_secret_key_for_sessions'

def get_db_connection():
    conn = sqlite3.connect('database.db')
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    conn.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL
        )
    ''')
    conn.execute('''
        CREATE TABLE IF NOT EXISTS scores (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            score INTEGER NOT NULL,
            puzzle_date TEXT NOT NULL,
            found_words TEXT DEFAULT '',
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    ''')
    
    conn.commit()
    conn.close()

# Initialize database tables on startup
init_db()

@app.route('/')
def index():
    username = session.get('username')
    current_score = 0
    user_found_words = []
    
    if username:
        conn = get_db_connection()
        today = str(date.today())
        user_row = conn.execute('SELECT id FROM users WHERE username = ?', (username,)).fetchone()
        if user_row:
            score_row = conn.execute(
                'SELECT score, found_words FROM scores WHERE user_id = ? AND puzzle_date = ?',
                (user_row['id'], today)
            ).fetchone()
            if score_row:
                current_score = score_row['score']
                if score_row['found_words']:
                    user_found_words = score_row['found_words'].split(',')
        conn.close()

    return render_template('index.html', username=username, score=current_score, found_words=user_found_words)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        identifier = request.form['identifier']
        password = request.form['password']
        hashed_pw = hashlib.sha256(password.encode()).hexdigest()

        conn = get_db_connection()
        user = conn.execute(
            'SELECT * FROM users WHERE (username = ? OR email = ?) AND password = ?',
            (identifier, identifier, hashed_pw)
        ).fetchone()
        conn.close()

        if user:
            session['username'] = user['username']
            return redirect(url_for('index'))
        else:
            return "Invalid username/email or password!", 400

    return render_template('login.html')

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        password = request.form['password']
        hashed_pw = hashlib.sha256(password.encode()).hexdigest()

        try:
            conn = get_db_connection()
            conn.execute(
                'INSERT INTO users (username, email, password) VALUES (?, ?, ?)',
                (username, email, hashed_pw)
            )
            conn.commit()
            conn.close()
            return redirect(url_for('login'))
        except sqlite3.IntegrityError:
            return "Username or Email already exists!", 400

    return render_template('signup.html')

@app.route('/submit_word', methods=['POST'])
def submit_word():
    data = request.get_json()
    word = data.get('word', '').upper()
    
    valid_words = ['BAKE', 'BEAK', 'LAKE', 'ABLE', 'KALE']
    center_letter = 'K'
    
    if len(word) < 4:
        return jsonify({'success': False, 'message': 'Word is too short (minimum 4 letters)'})
    if center_letter not in word:
        return jsonify({'success': False, 'message': 'Must include center letter (K)'})
    if word not in valid_words:
        return jsonify({'success': False, 'message': 'Not in word list'})
        
    points = 1 if len(word) == 4 else len(word)
    
    # If logged in, save score and found words
    if 'username' in session:
        username = session['username']
        today = str(date.today())
        
        conn = get_db_connection()
        user = conn.execute('SELECT id FROM users WHERE username = ?', (username,)).fetchone()
        user_id = user['id']
        
        score_row = conn.execute(
            'SELECT id, score, found_words FROM scores WHERE user_id = ? AND puzzle_date = ?',
            (user_id, today)
        ).fetchone()
        
        if score_row:
            new_score = score_row['score'] + points
            existing_words = score_row['found_words'].split(',') if score_row['found_words'] else []
            if word not in existing_words:
                existing_words.append(word)
            new_found_words = ','.join(existing_words)
            
            conn.execute(
                'UPDATE scores SET score = ?, found_words = ? WHERE id = ?',
                (new_score, new_found_words, score_row['id'])
            )
        else:
            new_score = points
            new_found_words = word
            conn.execute(
                'INSERT INTO scores (user_id, score, puzzle_date, found_words) VALUES (?, ?, ?, ?)',
                (user_id, new_score, today, new_found_words)
            )
            
        conn.commit()
        conn.close()
        return jsonify({'success': True, 'score': new_score, 'points': points})
    else:
        # If guest, return success so frontend can track score via localStorage
        return jsonify({'success': True, 'points': points})

@app.route('/leaderboard')
def leaderboard():
    conn = get_db_connection()
    today = str(date.today())
    
    top_users = conn.execute('''
        SELECT users.username, scores.score 
        FROM scores 
        JOIN users ON scores.user_id = users.id 
        WHERE scores.puzzle_date = ? 
        ORDER BY scores.score DESC 
        LIMIT 5
    ''', (today,)).fetchall()
    
    conn.close()
    return render_template('leaderboard.html', top_users=top_users, puzzle_date=today)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

if __name__ == '__main__':
    app.run(debug=True)
