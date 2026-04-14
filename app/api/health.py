from flask import Blueprint, jsonify
from app import db_session as db
from sqlalchemy import text
import logging

logger = logging.getLogger(__name__)

health_bp = Blueprint('health', __name__)


@health_bp.route('/api/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    try:
        # Test DB connection
        db.execute(text('SELECT 1'))
        
        return jsonify({
            'status': 'ok',
            'database': 'connected'
        }), 200
        
    except Exception as e:
        logger.error(f"Health check failed: {str(e)}")
        return jsonify({
            'status': 'error',
            'database': 'disconnected',
            'error': str(e)
        }), 503
