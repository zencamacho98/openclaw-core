from flask import Flask, jsonify

app = Flask(__name__)

portfolio_data = {
    'assets': [
        {'name': 'Stock A', 'value': 1000},
        {'name': 'Bond B', 'value': 500},
        {'name': 'Real Estate C', 'value': 2000}
    ],
    'total_value': 3500
}

@app.route('/portfolio_snapshot', methods=['GET'])
def get_portfolio_snapshot():
    return jsonify(portfolio_data)

if __name__ == '__main__':
    app.run(debug=True)
