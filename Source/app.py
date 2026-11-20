from flask import Flask, render_template, request, redirect, url_for, session, jsonify
import sqlite3
import hashlib
import random
import os
from datetime import date

app = Flask(__name__)
app.secret_key = 'super_secret_key_for_sessions'

# --- Dictionary & Daily Puzzle Setup ---

def load_dictionary(filepath='dictionary.txt'):
    """Loads valid words (4+ letters, alphabetic only) from dictionary.txt."""
    if not os.path.exists(filepath):
        # Fallback list in case dictionary.txt hasn't been created yet
        return {'BAKE', 'BEAK', 'LAKE', 'ABLE', 'KALE', 'BLEAK', 'BACKLOG', 'BLOCKAGE'}
    
    valid_words = set()
    with open(filepath, 'r', encoding='utf-8') as f:
        for line in f:
            word = line.strip().upper()
            if len(word) >= 4 and word.isalpha():
                valid_words.add(word)
    return valid_words

VALID_DICTIONARY = load_dictionary()
# Filter for words with at least 7 letters made of exactly 7 unique letters (pangrams)
SEVEN_LETTER_SEEDS = sorted([w for w in VALID_DICTIONARY if len(w) >= 7 and len(set(w)) == 7])

def get_daily_puzzle():
    """Deterministically selects a 7-letter puzzle based on today's date."""
    today_str = str(date.today())
    rng = random.Random(today_str)
    
    if SEVEN_LETTER_SEEDS:
        seed_word = rng.choice(SEVEN_LETTER_SEEDS)
        letters = sorted(list(set(seed_word)))
    else:
        # Emergency fallback if dictionary has no 7-unique-letter words
        letters = ['A', 'B', 'C', 'E', 'G', 'K', 'L']
        
    center_letter = rng.choice(letters)
    allowed_set = set(letters)
    
    # Pre-filter all valid dictionary words for today's letters
    todays_valid_words = {
        w for w in VALID_DICTIONARY 
        if center_letter in w and set(w).issubset(allowed_set)
    }
    
    return {
        'date': today_str,
        'letters': letters,
        'center_letter': center_letter,
        'valid_words': todays_valid_words
    }

# --- Database Setup ---

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
            UNIQUE(user_id, puzzle_date),
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    ''')
    conn.commit()
    conn.close()

# Initialize database tables on startup
init_db()

# --- Routes ---

@app.route('/')
def index():
    username = session.get('username')
    current_score = 0
    user_found_words = []
    puzzle = get_daily_puzzle()
    
    if username:
        conn = get_db_connection()
        user_row = conn.execute('SELECT id FROM users WHERE username = ?', (username,)).fetchone()
        if user_row:
            score_row = conn.execute(
                'SELECT score, found_words FROM scores WHERE user_id = ? AND puzzle_date = ?',
                (user_row['id'], puzzle['date'])
            ).fetchone()
            if score_row:
                current_score = score_row['score']
                if score_row['found_words']:
                    user_found_words = score_row['found_words'].split(',')
        conn.close()

    return render_template(
        'index.html',
        username=username,
        score=current_score,
        found_words=user_found_words,
        letters=puzzle['letters'],
        center_letter=puzzle['center_letter'],
        puzzle_date=puzzle['date']
    )

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        identifier = request.form.get('identifier', '').strip()
        password = request.form.get('password', '')
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
            return render_template(
                'login.html',
                error="Invalid username/email or password.",
                identifier=identifier
            )

    return render_template('login.html')


@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '')
        confirm_password = request.form.get('confirm_password', '')

        if password != confirm_password:
            return render_template(
                'signup.html',
                error="Passwords do not match.",
                username=username,
                email=email
            )

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
            return render_template(
                'signup.html',
                error="Username or email already exists.",
                username=username,
                email=email
            )

    return render_template('signup.html')


@app.route('/submit_word', methods=['POST'])
def submit_word():
    data = request.get_json()
    word = data.get('word', '').strip().upper()
    puzzle = get_daily_puzzle()
    
    letters = puzzle['letters']
    center_letter = puzzle['center_letter']
    allowed_set = set(letters)

    # 1. Basic validation checks
    if len(word) < 4:
        return jsonify({'success': False, 'message': 'Word is too short (minimum 4 letters)'})
    if center_letter not in word:
        return jsonify({'success': False, 'message': f'Must include center letter ({center_letter})'})
    if not set(word).issubset(allowed_set):
        return jsonify({'success': False, 'message': 'Contains invalid letters'})
    if word not in puzzle['valid_words']:
        return jsonify({'success': False, 'message': 'Not in dictionary'})

    # 2. Calculate points (4-letter = 1 pt, 5+ = length, +7 bonus if pangram)
    is_pangram = (set(word) == allowed_set)
    points = 1 if len(word) == 4 else len(word)
    if is_pangram:
        points += 7

    # 3. Handle logged-in user persistence & duplicate prevention
    if 'username' in session:
        username = session['username']
        today = puzzle['date']
        
        conn = get_db_connection()
        user = conn.execute('SELECT id FROM users WHERE username = ?', (username,)).fetchone()
        
        if not user:
            conn.close()
            return jsonify({'success': False, 'message': 'User session invalid'})
            
        user_id = user['id']
        score_row = conn.execute(
            'SELECT id, score, found_words FROM scores WHERE user_id = ? AND puzzle_date = ?',
            (user_id, today)
        ).fetchone()
        
        if score_row:
            existing_words = score_row['found_words'].split(',') if score_row['found_words'] else []
            
            # Prevent duplicate word submission
            if word in existing_words:
                conn.close()
                return jsonify({'success': False, 'message': 'Already found!'})
                
            existing_words.append(word)
            new_score = score_row['score'] + points
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
        return jsonify({
            'success': True,
            'score': new_score,
            'points': points,
            'is_pangram': is_pangram
        })
    else:
        # Guest mode: frontend tracks found words & score in localStorage
        return jsonify({
            'success': True,
            'points': points,
            'is_pangram': is_pangram
        })

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
