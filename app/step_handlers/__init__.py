"""Registry per step handlers — mappa tipo step → handler class."""

_HANDLERS = {}


def register(step_type_name):
    """Decorator per registrare un handler: @register('EMAIL')"""
    def decorator(cls):
        _HANDLERS[step_type_name] = cls
        return cls
    return decorator


def get_handler(step_type_name):
    """Ritorna un'istanza dell'handler per il tipo step, o None."""
    cls = _HANDLERS.get(step_type_name)
    return cls() if cls else None


# Import handler modules per triggerare la registrazione
from app.step_handlers.document_check import DocumentCheckHandler  # noqa: F401,E402
from app.step_handlers.email_handler import EmailHandler  # noqa: F401,E402
from app.step_handlers.webhook_handler import WebhookHandler  # noqa: F401,E402
from app.step_handlers.whatsapp_handler import WhatsAppHandler  # noqa: F401,E402
from app.step_handlers.sister_visura import SisterVisuraHandler  # noqa: F401,E402
from app.step_handlers.document_processing import DocumentProcessingHandler  # noqa: F401,E402
