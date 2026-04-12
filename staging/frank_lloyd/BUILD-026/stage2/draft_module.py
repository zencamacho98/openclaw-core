import sqlite3
from flask import Flask, jsonify

app = Flask(__name__)

class HealthCheck:
    def __init__(self, db_path):
        self.db_path = db_path

    def check_database(self):
        try:
            conn = sqlite3.connect(self.db_path)
            conn.close()
            return True
        except Exception:
            return False

health_check = HealthCheck('database.db')

@app.route('/health', methods=['GET'])
def health():
    if health_check.check_database():
        return jsonify(status='healthy'), 200
    else:
        return jsonify(status='unhealthy'), 500

if __name__ == '__main__':
    app.run(debug=True)
