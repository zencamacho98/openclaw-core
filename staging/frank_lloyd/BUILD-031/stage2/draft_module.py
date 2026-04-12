from flask import Flask, jsonify

app = Flask(__name__)

@app.route('/portfolio_snapshot', methods=['GET'])
def portfolio_snapshot():
    snapshot = {
        'portfolio': [
            {'asset': 'Stock A', 'value': 1000},
            {'asset': 'Bond B', 'value': 500},
            {'asset': 'Real Estate C', 'value': 1500}
        ],
        'total_value': 3000
    }
    return jsonify(snapshot)

if __name__ == '__main__':
    app.run(debug=True)
