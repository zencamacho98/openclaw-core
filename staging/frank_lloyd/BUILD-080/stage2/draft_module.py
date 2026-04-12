from flask import Flask, jsonify

app = Flask(__name__)

# Sample portfolio data
portfolio_data = {
    'stocks': [
        {'ticker': 'AAPL', 'quantity': 10, 'price': 150},
        {'ticker': 'GOOGL', 'quantity': 5, 'price': 2800}
    ],
    'bonds': [
        {'ticker': 'US10Y', 'quantity': 20, 'price': 100}
    ],
    'total_value': 10000
}

@app.route('/portfolio_snapshot', methods=['GET'])
def get_portfolio_snapshot():
    return jsonify(portfolio_data)

if __name__ == '__main__':
    app.run(debug=True)
