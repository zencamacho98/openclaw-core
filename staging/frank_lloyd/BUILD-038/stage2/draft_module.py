import json
import sqlite3

class DatabaseHealth:
    def __init__(self, db_path):
        self.db_path = db_path

    def check_status(self):
        try:
            conn = sqlite3.connect(self.db_path)
            conn.execute('SELECT 1')
            conn.close()
            return {'status': 'success', 'message': 'Database is operational.'}
        except Exception as e:
            return {'status': 'error', 'message': str(e)}

if __name__ == '__main__':
    db_health = DatabaseHealth('path_to_your_database.db')
    print(json.dumps(db_health.check_status()))
