from flask import Blueprint, jsonify
from app.portfolio import get_current_portfolio

portfolio_snapshot_bp = Blueprint('portfolio_snapshot', __name__)

@portfolio_snapshot_bp.route('/portfolio_snapshot', methods=['GET'])
def portfolio_snapshot():
    portfolio_data = get_current_portfolio()
    return jsonify(portfolio_data)
