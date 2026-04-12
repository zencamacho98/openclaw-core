from flask import Blueprint, jsonify

portfolio_snapshot_bp = Blueprint('portfolio_snapshot', __name__)

@portfolio_snapshot_bp.route('/api/portfolio', methods=['GET'])
def get_portfolio_snapshot():
    portfolio = {
        'assets': [
            {'name': 'Stock A', 'value': 1000},
            {'name': 'Bond B', 'value': 500},
            {'name': 'Real Estate C', 'value': 1500}
        ],
        'total_value': 3000
    }
    return jsonify(portfolio)
