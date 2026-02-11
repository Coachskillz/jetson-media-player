"""
Reports Routes for CMS Service.

Provides the AI-powered reporting interface where users can ask
natural language questions and get formatted reports.
"""

from flask import Blueprint, render_template, request, jsonify, Response
from flask_login import login_required
import csv
import io
import json

from cms.models import db
from cms.services.ai_reports import ask_report, get_quick_stats

reports_bp = Blueprint('reports', __name__, url_prefix='/reports')


@reports_bp.route('/')
@login_required
def reports_page():
    """Main reports page with AI query box."""
    stats = get_quick_stats()
    return render_template('reports/index.html', stats=stats)


@reports_bp.route('/ask', methods=['POST'])
@login_required
def ask_ai():
    """
    Handle AI query from the chat box.

    Expected JSON body:
    {
        "question": "How many screens are online right now?"
    }

    Returns:
        JSON with report, raw_data, sql, explanation, and error fields
    """
    data = request.json
    question = data.get('question', '').strip()

    if not question:
        return jsonify({'error': 'No question provided'}), 400

    result = ask_report(question)
    return jsonify(result)


@reports_bp.route('/export', methods=['POST'])
@login_required
def export_csv():
    """
    Export raw query results as CSV.

    Expected JSON body:
    {
        "raw_data": {
            "columns": ["col1", "col2"],
            "rows": [{"col1": "val1", "col2": "val2"}, ...]
        }
    }

    Returns:
        CSV file download
    """
    data = request.json
    raw_data = data.get('raw_data', {})
    columns = raw_data.get('columns', [])
    rows = raw_data.get('rows', [])

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(columns)
    for row in rows:
        writer.writerow([row.get(col, '') for col in columns])

    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={'Content-Disposition': 'attachment; filename=skillz_report.csv'}
    )


@reports_bp.route('/stats')
@login_required
def quick_stats():
    """Get quick statistics without AI."""
    stats = get_quick_stats()
    return jsonify(stats)
