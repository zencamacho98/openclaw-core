from flask import Blueprint, jsonify
from app.portfolio import get_current_portfolio_snapshot

portfolio_snapshot_bp = Blueprint('portfolio_snapshot', __name__)

@portfolio_snapshot_bp.route('/portfolio_snapshot', methods=['GET'])
def portfolio_snapshot():
    snapshot = get_current_portfolio_snapshot()
    return jsonify(snapshot)
