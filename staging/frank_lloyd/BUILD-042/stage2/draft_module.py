import json

class HealthCheck:
    def __init__(self, db_connection):
        self.db_connection = db_connection

    def check_status(self):
        try:
            # Simulate a database status check
            self.db_connection.execute('SELECT 1')
            return json.dumps({'status': 'success'}), 200
        except Exception:
            return json.dumps({'status': 'failure'}), 500

# Example usage:
# db_connection = some_database_connection_object
# health_check = HealthCheck(db_connection)
# response, status_code = health_check.check_status()
