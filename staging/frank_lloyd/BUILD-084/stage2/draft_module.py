from flask import Blueprint, jsonify

portfolio_snapshot_bp = Blueprint('portfolio_snapshot', __name__)

@portfolio_snapshot_bp.route('/api/portfolio_snapshot', methods=['GET'])
def get_portfolio_snapshot():
    portfolio_data = {
        'assets': [
            {'name': 'Stock A', 'value': 1000},
            {'name': 'Bond B', 'value': 500},
        ],
        'total_value': 1500
    }
    return jsonify(portfolio_data)
