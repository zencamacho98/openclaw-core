import sqlite3

class HealthCheck:
    def __init__(self, db_path):
        self.db_path = db_path

    def check_health(self):
        try:
            conn = sqlite3.connect(self.db_path)
            conn.execute('SELECT 1')
            conn.close()
            return {'status': 'success', 'message': 'Database is reachable.'}
        except sqlite3.Error:
            return {'status': 'failure', 'message': 'Database is not reachable.'}
