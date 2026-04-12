from flask import Flask, jsonify

app = Flask(__name__)

@app.route('/portfolio_snapshot', methods=['GET'])
def portfolio_snapshot():
    snapshot = {
        'assets': [
            {'name': 'Stock A', 'value': 1000},
            {'name': 'Bond B', 'value': 500}
        ],
        'total_value': 1500
    }
    return jsonify(snapshot)

if __name__ == '__main__':
    app.run(debug=True)
