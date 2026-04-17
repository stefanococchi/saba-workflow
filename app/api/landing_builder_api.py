from flask import Blueprint, request, jsonify
from app import db_session as db
from app.models import WorkflowStep, Workflow, LandingTemplate
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
            # From landing_page_config (form builder config)
            if step.landing_page_config and isinstance(step.landing_page_config, dict):
                config_fields = step.landing_page_config.get('fields', [])
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


# =============================================
# LANDING TEMPLATES
# =============================================

@landing_builder_api_bp.route('/landing-templates', methods=['GET'])
def list_landing_templates():
    """Lista template landing salvati"""
    try:
        templates = db.query(LandingTemplate).order_by(LandingTemplate.updated_at.desc()).all()
        return jsonify({
            'templates': [{
                'id': t.id,
                'name': t.name,
                'description': t.description,
                'updated_at': t.updated_at.isoformat() if t.updated_at else None,
            } for t in templates]
        }), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@landing_builder_api_bp.route('/landing-templates', methods=['POST'])
def save_landing_template():
    """Salva landing page come template riutilizzabile"""
    try:
        data = request.get_json()
        name = data.get('name', '').strip()
        if not name:
            return jsonify({'error': 'Nome template obbligatorio'}), 400

        template = LandingTemplate(
            name=name,
            description=data.get('description', ''),
            landing_html=data.get('html'),
            landing_css=data.get('css'),
            landing_gjs_data=data.get('gjs_data'),
        )
        db.add(template)
        db.commit()

        return jsonify({'id': template.id, 'name': template.name}), 201

    except Exception as e:
        db.rollback()
        return jsonify({'error': str(e)}), 500


@landing_builder_api_bp.route('/landing-templates/<int:template_id>', methods=['GET'])
def get_landing_template(template_id):
    """Carica un template landing"""
    try:
        t = db.get(LandingTemplate, template_id)
        if not t:
            return jsonify({'error': 'Template non trovato'}), 404

        return jsonify({
            'id': t.id,
            'name': t.name,
            'html': t.landing_html,
            'css': t.landing_css,
            'gjs_data': t.landing_gjs_data,
        }), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@landing_builder_api_bp.route('/landing-templates/<int:template_id>', methods=['PUT'])
def update_landing_template(template_id):
    """Aggiorna template esistente"""
    try:
        t = db.get(LandingTemplate, template_id)
        if not t:
            return jsonify({'error': 'Template non trovato'}), 404

        data = request.get_json()
        if 'name' in data:
            t.name = data['name']
        if 'description' in data:
            t.description = data['description']
        if 'html' in data:
            t.landing_html = data['html']
        if 'css' in data:
            t.landing_css = data['css']
        if 'gjs_data' in data:
            t.landing_gjs_data = data['gjs_data']

        db.commit()
        return jsonify({'id': t.id, 'name': t.name}), 200

    except Exception as e:
        db.rollback()
        return jsonify({'error': str(e)}), 500


@landing_builder_api_bp.route('/landing-templates/<int:template_id>', methods=['DELETE'])
def delete_landing_template(template_id):
    """Elimina template"""
    try:
        t = db.get(LandingTemplate, template_id)
        if not t:
            return jsonify({'error': 'Template non trovato'}), 404
        db.delete(t)
        db.commit()
        return jsonify({'message': 'Template eliminato'}), 200
    except Exception as e:
        db.rollback()
        return jsonify({'error': str(e)}), 500
