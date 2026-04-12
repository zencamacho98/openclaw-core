import json

class HealthCheck:
    def __init__(self, db_status):
        self.db_status = db_status

    def check_health(self):
        if self.db_status:
            return json.dumps({'status': 'healthy'}), 200
        else:
            return json.dumps({'status': 'unhealthy'}), 503

# Example usage:
# health_check = HealthCheck(db_status=True)
# response = health_check.check_health()
# print(response)
