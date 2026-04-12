from flask import Flask, jsonify

app = Flask(__name__)

portfolio_snapshot = {
    'assets': [
        {'name': 'Stock A', 'value': 1000},
        {'name': 'Bond B', 'value': 500}
    ],
    'total_value': 1500
}

@app.route('/portfolio_snapshot', methods=['GET'])
def get_portfolio_snapshot():
    return jsonify(portfolio_snapshot), 200

if __name__ == '__main__':
    app.run(debug=True)
