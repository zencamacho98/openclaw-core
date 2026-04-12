import sqlite3

class HealthCheck:
    def __init__(self, db_path):
        self.db_path = db_path

    def check_database(self):
        try:
            conn = sqlite3.connect(self.db_path)
            conn.close()
            return {'status': 'healthy', 'message': 'Database is reachable.'}
        except Exception as e:
            return {'status': 'unhealthy', 'message': str(e)}

if __name__ == '__main__':
    health_check = HealthCheck('path_to_database.db')
    print(health_check.check_database())
