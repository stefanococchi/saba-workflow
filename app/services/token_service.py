import jwt
from datetime import datetime, timedelta
from flask import current_app
import logging

logger = logging.getLogger(__name__)


class TokenService:
    """Servizio gestione JWT token"""
    
    @staticmethod
    def generate_token(participant_id, workflow_id, step_id=None, expires_hours=None):
        """
        Genera JWT token per partecipante
        
        Args:
            participant_id: ID partecipante
            workflow_id: ID workflow
            step_id: ID step (opzionale)
            expires_hours: ore di validità (default da config)
            
        Returns:
            str: JWT token
        """
        try:
            if expires_hours is None:
                expires_hours = current_app.config['JWT_EXPIRATION_HOURS']
            
            payload = {
                'participant_id': participant_id,
                'workflow_id': workflow_id,
                'iat': datetime.utcnow(),
                'exp': datetime.utcnow() + timedelta(hours=expires_hours)
            }
            
            if step_id:
                payload['step_id'] = step_id
            
            token = jwt.encode(
                payload,
                current_app.config['JWT_SECRET_KEY'],
                algorithm='HS256'
            )
            
            return token
            
        except Exception as e:
            logger.error(f"Errore generazione token: {str(e)}")
            raise
    
    @staticmethod
    def verify_token(token):
        """
        Verifica e decodifica JWT token
        
        Args:
            token: JWT token
            
        Returns:
            dict: payload decodificato o None se invalido
        """
        try:
            payload = jwt.decode(
                token,
                current_app.config['JWT_SECRET_KEY'],
                algorithms=['HS256']
            )
            return payload
            
        except jwt.ExpiredSignatureError:
            logger.warning("Token scaduto")
            return None
        except jwt.InvalidTokenError as e:
            logger.warning(f"Token invalido: {str(e)}")
            return None
    
    @staticmethod
    def generate_landing_url(participant, base_url=None):
        """
        Genera URL landing page completo
        
        Args:
            participant: istanza Participant
            base_url: URL base (default da config)
            
        Returns:
            str: URL completo
        """
        if base_url is None:
            base_url = current_app.config['LANDING_BASE_URL']
        
        return f"{base_url}/{participant.token}"
