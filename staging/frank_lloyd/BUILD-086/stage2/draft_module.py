import json

class Database:
    def is_operational(self):
        # Simulate a database check
        return True

class HealthCheck:
    def __init__(self, database):
        self.database = database

    def check(self):
        if self.database.is_operational():
            return json.dumps({'status': 'success', 'message': 'Database is operational.'})
        else:
            return json.dumps({'status': 'error', 'message': 'Database is not operational.'})

# Example usage
if __name__ == '__main__':
    db = Database()
    health_check = HealthCheck(db)
    print(health_check.check())
