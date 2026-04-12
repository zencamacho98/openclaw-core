import sqlite3
from flask import Flask, jsonify

app = Flask(__name__)

def check_database_health():
    try:
        conn = sqlite3.connect('your_database.db')
        conn.execute('SELECT 1')
        conn.close()
        return True
    except Exception:
        return False

@app.route('/health', methods=['GET'])
def health():
    if check_database_health():
        return jsonify(status='healthy'), 200
    else:
        return jsonify(status='unhealthy'), 500

if __name__ == '__main__':
    app.run()
