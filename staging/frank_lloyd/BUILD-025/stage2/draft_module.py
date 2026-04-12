import sqlite3
from flask import Flask, jsonify

app = Flask(__name__)

def check_database_connection():
    try:
        conn = sqlite3.connect('example.db')
        conn.close()
        return True
    except:
        return False

@app.route('/health', methods=['GET'])
def health_check():
    if check_database_connection():
        return jsonify({'status': 'healthy'}), 200
    else:
        return jsonify({'status': 'unhealthy'}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
