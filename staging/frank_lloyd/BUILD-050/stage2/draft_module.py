import json
import sqlite3

class HealthCheck:
    def __init__(self, db_path):
        self.db_path = db_path

    def check_database(self):
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('SELECT 1')
            conn.close()
            return {'status': 'operational'}
        except Exception:
            return {'status': 'error'}

if __name__ == '__main__':
    health_check = HealthCheck('path_to_your_database.db')
    print(json.dumps(health_check.check_database()))
