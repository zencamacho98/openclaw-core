import json
import sqlite3

class HealthCheck:
    def __init__(self, db_path):
        self.db_path = db_path

    def check_database(self):
        try:
            conn = sqlite3.connect(self.db_path)
            conn.close()
            return {'status': 'success', 'message': 'Database is reachable.'}, 200
        except sqlite3.Error:
            return {'status': 'error', 'message': 'Database is not reachable.'}, 500

if __name__ == '__main__':
    health_check = HealthCheck('path_to_database.db')
    response, status_code = health_check.check_database()
    print(json.dumps(response), status_code)
