from flask import Blueprint, jsonify

portfolio_snapshot = Blueprint('portfolio_snapshot', __name__)

@portfolio_snapshot.route('/api/portfolio', methods=['GET'])
def get_portfolio():
    portfolio_data = {
        'assets': [
            {'name': 'Asset A', 'value': 10000},
            {'name': 'Asset B', 'value': 15000}
        ],
        'total_value': 25000
    }
    return jsonify(portfolio_data)
