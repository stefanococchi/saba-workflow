from flask import Blueprint, request, jsonify
from app import db_session as db
from app.models import WorkflowStep, Workflow
import logging
import re

logger = logging.getLogger(__name__)

landing_builder_api_bp = Blueprint('landing_builder_api', __name__)


@landing_builder_api_bp.route('/landing-builder/<int:step_id>', methods=['GET'])
def get_landing_design(step_id):
    """Recupera il design salvato della landing page"""
    try:
        step = db.query(WorkflowStep).get(step_id)

        if not step:
            return jsonify({'error': 'Step non trovato'}), 404

        return jsonify({
            'html': step.landing_html,
            'css': step.landing_css,
            'gjs_data': step.landing_gjs_data,
        }), 200

    except Exception as e:
        logger.error(f"Errore get landing design: {str(e)}")
        return jsonify({'error': str(e)}), 500


@landing_builder_api_bp.route('/landing-fields/workflow/<int:workflow_id>', methods=['GET'])
def get_workflow_landing_fields(workflow_id):
    """Restituisce tutti i campi landing page di un workflow"""
    try:
        steps = db.query(WorkflowStep).filter_by(workflow_id=workflow_id).all()
        fields = []
        seen = set()

        for step in steps:
            # From gjs_data config (template builder)
            if step.landing_gjs_data and isinstance(step.landing_gjs_data, dict):
                config_fields = step.landing_gjs_data.get('fields', [])
                if isinstance(config_fields, list):
                    for f in config_fields:
                        name = f.get('name', '')
                        if name and name not in seen:
                            seen.add(name)
                            fields.append({
                                'name': name,
                                'label': f.get('label', name),
                                'type': f.get('type', 'text'),
                                'step_name': step.name
                            })

            # From HTML (Unlayer or custom) — extract input/select/textarea names
            if step.landing_html and len(fields) == 0:
                for match in re.finditer(r'<(?:input|select|textarea)[^>]+name=["\']([^"\']+)["\']', step.landing_html):
                    name = match.group(1)
                    if name and name not in seen:
                        seen.add(name)
                        fields.append({
                            'name': name,
                            'label': name.replace('_', ' ').title(),
                            'type': 'text',
                            'step_name': step.name
                        })

        return jsonify({'fields': fields}), 200

    except Exception as e:
        logger.error(f"Errore get landing fields: {str(e)}")
        return jsonify({'error': str(e)}), 500


@landing_builder_api_bp.route('/landing-builder/<int:step_id>', methods=['POST'])
def save_landing_design(step_id):
    """Salva il design della landing page (HTML, CSS, dati GrapesJS)"""
    try:
        step = db.query(WorkflowStep).get(step_id)

        if not step:
            return jsonify({'error': 'Step non trovato'}), 404

        data = request.get_json()

        step.landing_html = data.get('html')
        step.landing_css = data.get('css')
        step.landing_gjs_data = data.get('gjs_data')

        db.commit()

        logger.info(f"Landing design salvato per step {step_id}")

        return jsonify({
            'success': True,
            'message': 'Design salvato con successo'
        }), 200

    except Exception as e:
        db.rollback()
        logger.error(f"Errore save landing design: {str(e)}")
        return jsonify({'error': str(e)}), 500
