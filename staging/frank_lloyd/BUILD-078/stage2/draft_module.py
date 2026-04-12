import json
import sqlite3

class HealthCheck:
    def __init__(self, db_path):
        self.db_path = db_path

    def check_health(self):
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('SELECT 1')
            cursor.fetchone()
            return 200, json.dumps({'status': 'healthy'})
        except Exception:
            return 500, json.dumps({'status': 'unhealthy'})
        finally:
            if conn:
                conn.close()
