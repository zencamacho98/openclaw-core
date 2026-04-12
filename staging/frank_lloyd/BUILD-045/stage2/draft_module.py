from flask import Blueprint, jsonify

portfolio_snapshot_bp = Blueprint('portfolio_snapshot', __name__)

@portfolio_snapshot_bp.route('/api/portfolio_snapshot', methods=['GET'])
def get_portfolio_snapshot():
    portfolio = {
        'assets': [
            {'name': 'Stock A', 'value': 10000},
            {'name': 'Bond B', 'value': 5000}
        ],
        'total_value': 15000
    }
    return jsonify(portfolio)
