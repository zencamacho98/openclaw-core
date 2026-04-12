import sqlite3
from flask import Flask, jsonify

app = Flask(__name__)

def check_database():
    try:
        conn = sqlite3.connect('example.db')  # Replace with actual database connection
        conn.close()
        return True
    except:
        return False

@app.route('/health', methods=['GET'])
def health_check():
    if check_database():
        return jsonify({'status': 'success'}), 200
    else:
        return jsonify({'status': 'error'}), 500

if __name__ == '__main__':
    app.run(debug=True)
