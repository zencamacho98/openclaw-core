import json

class HealthCheck:
    def __init__(self, db_status):
        self.db_status = db_status

    def check_health(self):
        if self.db_status:
            return json.dumps({'status': 'success', 'message': 'Database is operational.'})
        else:
            return json.dumps({'status': 'error', 'message': 'Database is not operational.'})

# Example usage:
# health_check = HealthCheck(db_status=True)
# print(health_check.check_health())
