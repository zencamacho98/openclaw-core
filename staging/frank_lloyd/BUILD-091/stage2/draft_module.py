from flask import Flask, jsonify
from app.portfolio import get_current_portfolio

app = Flask(__name__)

@app.route('/portfolio_snapshot', methods=['GET'])
def portfolio_snapshot():
    snapshot = get_current_portfolio()
    return jsonify(snapshot)

if __name__ == '__main__':
    app.run(debug=True)
