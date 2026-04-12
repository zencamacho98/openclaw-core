from flask import Flask, jsonify

app = Flask(__name__)

@app.route('/portfolio_snapshot', methods=['GET'])
def portfolio_snapshot():
    # Simulated portfolio data
    portfolio_data = {
        'assets': [
            {'name': 'Stock A', 'value': 10000},
            {'name': 'Bond B', 'value': 5000},
            {'name': 'Real Estate C', 'value': 20000}
        ],
        'total_value': 35000
    }
    return jsonify(portfolio_data)

if __name__ == '__main__':
    app.run(debug=True)
