from flask import Flask, jsonify

app = Flask(__name__)

# Mock data representing the current portfolio snapshot
current_portfolio_snapshot = {
    'portfolio_value': 100000,
    'assets': [
        {'name': 'Stock A', 'value': 50000},
        {'name': 'Stock B', 'value': 30000},
        {'name': 'Bond C', 'value': 20000}
    ],
    'last_updated': '2026-04-11T22:00:00Z'
}

@app.route('/api/portfolio_snapshot', methods=['GET'])
def get_portfolio_snapshot():
    return jsonify(current_portfolio_snapshot)

if __name__ == '__main__':
    app.run(debug=True)
