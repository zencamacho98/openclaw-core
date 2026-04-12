import sqlite3
from flask import Flask, jsonify

app = Flask(__name__)

def check_database_connection():
    try:
        connection = sqlite3.connect('example.db')
        connection.close()
        return True
    except Exception:
        return False

@app.route('/health', methods=['GET'])
def health_check():
    if check_database_connection():
        return jsonify(status='success', message='Database is reachable'), 200
    else:
        return jsonify(status='error', message='Database is not reachable'), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
