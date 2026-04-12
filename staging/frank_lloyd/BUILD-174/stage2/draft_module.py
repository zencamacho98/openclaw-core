from flask import Blueprint, render_template

belfort_bp = Blueprint('belfort', __name__)

# Color representation for Mr. Belfort's house
HOUSE_COLOR = 'green'

@belfort_bp.route('/belfort/readiness')
def readiness():
    return render_template('belfort/readiness.html', house_color=HOUSE_COLOR)

@belfort_bp.route('/belfort/learning')
def learning():
    return render_template('belfort/learning.html', house_color=HOUSE_COLOR)

@belfort_bp.route('/belfort/diagnostics')
def diagnostics():
    return render_template('belfort/diagnostics.html', house_color=HOUSE_COLOR)

@belfort_bp.route('/belfort/memory')
def memory():
    return render_template('belfort/memory.html', house_color=HOUSE_COLOR)
