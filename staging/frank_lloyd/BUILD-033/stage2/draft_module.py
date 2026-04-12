import json
import sqlite3

class HealthCheck:
    def __init__(self, db_path):
        self.db_path = db_path

    def check_health(self):
        try:
            conn = sqlite3.connect(self.db_path)
            conn.execute('SELECT 1')
            conn.close()
            return {'status': 'healthy'}, 200
        except Exception as e:
            return {'status': 'unhealthy', 'error': str(e)}, 500

if __name__ == '__main__':
    health_check = HealthCheck('path_to_database.db')
    response, status_code = health_check.check_health()
    print(json.dumps(response), status_code)
