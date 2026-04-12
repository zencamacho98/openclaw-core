from flask import Blueprint, jsonify

portfolio_snapshot_bp = Blueprint('portfolio_snapshot', __name__)

@portfolio_snapshot_bp.route('/portfolio_snapshot', methods=['GET'])
def get_portfolio_snapshot():
    current_snapshot = {
        'portfolio_value': 100000,
        'assets': [
            {'name': 'Stock A', 'value': 50000},
            {'name': 'Bond B', 'value': 30000},
            {'name': 'Real Estate C', 'value': 20000}
        ]
    }
    return jsonify(current_snapshot)
