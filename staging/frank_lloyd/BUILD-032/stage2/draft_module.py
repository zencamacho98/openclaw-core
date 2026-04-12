from flask import Flask, jsonify

app = Flask(__name__)

portfolio_data = {
    'stocks': [
        {'symbol': 'AAPL', 'quantity': 10, 'price': 150},
        {'symbol': 'GOOGL', 'quantity': 5, 'price': 2800}
    ],
    'bonds': [
        {'symbol': 'US10Y', 'quantity': 2, 'price': 1000}
    ],
    'total_value': 20000
}

@app.route('/portfolio_snapshot', methods=['GET'])
def get_portfolio_snapshot():
    return jsonify(portfolio_data)

if __name__ == '__main__':
    app.run(debug=True)
