import json
import sqlite3

class HealthCheck:
    def __init__(self, db_path):
        self.db_path = db_path

    def check_database(self):
        try:
            conn = sqlite3.connect(self.db_path)
            conn.execute('SELECT 1')
            conn.close()
            return {'status': 'ok', 'message': 'Database is operational.'}
        except sqlite3.Error as e:
            return {'status': 'error', 'message': str(e)}

    def health_status(self):
        result = self.check_database()
        if result['status'] == 'ok':
            return json.dumps(result), 200
        else:
            return json.dumps(result), 500
