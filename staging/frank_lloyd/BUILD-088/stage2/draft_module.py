from flask import Blueprint, jsonify

portfolio_snapshot_bp = Blueprint('portfolio_snapshot', __name__)

@portfolio_snapshot_bp.route('/api/portfolio_snapshot', methods=['GET'])
def get_portfolio_snapshot():
    current_portfolio = {
        'assets': [
            {'name': 'Asset A', 'value': 10000},
            {'name': 'Asset B', 'value': 15000},
        ],
        'total_value': 25000
    }
    return jsonify(current_portfolio)
