from datetime import datetime
from enum import Enum
from sqlalchemy import Column, Integer, String, Text, DateTime, JSON, ForeignKey, Enum as SQLEnum
from sqlalchemy.orm import relationship
from app import Base


class WorkflowStatus(str, Enum):
    """Stati possibili workflow"""
    DRAFT = 'draft'
    ACTIVE = 'active'
    PAUSED = 'paused'
    COMPLETED = 'completed'
    ARCHIVED = 'archived'


class StepType(str, Enum):
    """Tipi di step"""
    EMAIL = 'email'
    SMS = 'sms'
    WEBHOOK = 'webhook'
    WAIT_UNTIL = 'wait_until'
    GOAL_CHECK = 'goal_check'
    EXPORT_DATA = 'export_data'
    CONDITION = 'condition'


class ParticipantStatus(str, Enum):
    """Stati partecipante"""
    PENDING = 'pending'
    IN_PROGRESS = 'in_progress'
    COMPLETED = 'completed'
    BOUNCED = 'bounced'
    UNSUBSCRIBED = 'unsubscribed'


class ExecutionStatus(str, Enum):
    """Stati esecuzione step"""
    SCHEDULED = 'scheduled'
    SENT = 'sent'
    DELIVERED = 'delivered'
    OPENED = 'opened'
    CLICKED = 'clicked'
    COMPLETED = 'completed'
    FAILED = 'failed'
    SKIPPED = 'skipped'


class Workflow(Base):
    """Workflow principale"""
    __tablename__ = 'workflows'
    
    id = Column(Integer, primary_key=True)
    name = Column(String(200), nullable=False)
    description = Column(Text)
    status = Column(SQLEnum(WorkflowStatus), default=WorkflowStatus.DRAFT, nullable=False)
    
    # Configurazione JSON per dati custom
    config = Column(JSON, default={})

    # Scadenza token landing page (ore), default da config globale
    token_expiration_hours = Column(Integer, nullable=True)

    # Collegamento evento Saba Form (read-only, sync unidirezionale)
    sabaform_event_id = Column(Integer, nullable=True)
    sabaform_event_name = Column(String(300), nullable=True)

    # Metadata
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_by = Column(String(100))  # User ID o email
    
    # Relazioni
    steps = relationship('WorkflowStep', back_populates='workflow', 
                        cascade='all, delete-orphan', order_by='WorkflowStep.order')
    participants = relationship('Participant', back_populates='workflow',
                               cascade='all, delete-orphan')
    
    def __repr__(self):
        return f'<Workflow {self.id}: {self.name}>'


class WorkflowStep(Base):
    """Step del workflow"""
    __tablename__ = 'workflow_steps'
    
    id = Column(Integer, primary_key=True)
    workflow_id = Column(Integer, ForeignKey('workflows.id'), nullable=False)
    
    order = Column(Integer, nullable=False)  # Ordine esecuzione
    name = Column(String(200), nullable=False)
    type = Column(SQLEnum(StepType), default=StepType.EMAIL, nullable=False)
    
    # Template email/SMS
    template_name = Column(String(100))
    subject = Column(String(500))  # Subject email
    body_template = Column(Text)   # Template Jinja2
    
    # Timing
    delay_hours = Column(Integer, default=0)  # Delay dopo step precedente
    
    # Condizioni skip (JSON logic)
    skip_conditions = Column(JSON)
    
    # Landing page config
    landing_page_config = Column(JSON)  # Schema form se richiesto

    # Landing page builder (GrapesJS)
    landing_html = Column(Text)          # HTML generato dall'editor
    landing_css = Column(Text)           # CSS generato dall'editor
    landing_gjs_data = Column(JSON)      # Dati progetto GrapesJS (per riaprire l'editor)

    # Metadata
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relazioni
    workflow = relationship('Workflow', back_populates='steps')
    executions = relationship('Execution', back_populates='step', cascade='all, delete-orphan')
    
    def __repr__(self):
        return f'<WorkflowStep {self.id}: {self.name} (order {self.order})>'


class Participant(Base):
    """Partecipante al workflow"""
    __tablename__ = 'participants'
    
    id = Column(Integer, primary_key=True)
    workflow_id = Column(Integer, ForeignKey('workflows.id'), nullable=False)
    
    # Dati partecipante
    email = Column(String(255), nullable=True)
    first_name = Column(String(100))
    last_name = Column(String(100))
    phone = Column(String(50))

    @property
    def full_name(self):
        parts = [self.first_name or '', self.last_name or '']
        return ' '.join(p for p in parts if p).strip() or None
    
    # Stato
    status = Column(SQLEnum(ParticipantStatus), default=ParticipantStatus.PENDING, nullable=False)
    current_step_id = Column(Integer, ForeignKey('workflow_steps.id'))
    
    # Token univoco per landing page
    token = Column(String(500), unique=True, index=True)
    
    # Dati raccolti (JSON)
    collected_data = Column(JSON, default={})

    # Dati originali importati da Saba Form (JSON)
    sabaform_data = Column(JSON, default={})

    # Metadata
    enrolled_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime)
    last_interaction = Column(DateTime)
    
    # Relazioni
    workflow = relationship('Workflow', back_populates='participants')
    current_step = relationship('WorkflowStep', foreign_keys=[current_step_id])
    executions = relationship('Execution', back_populates='participant', cascade='all, delete-orphan')
    
    def __repr__(self):
        return f'<Participant {self.id}: {self.email}>'


class Execution(Base):
    """Esecuzione di uno step per un partecipante"""
    __tablename__ = 'executions'
    
    id = Column(Integer, primary_key=True)
    participant_id = Column(Integer, ForeignKey('participants.id'), nullable=False)
    step_id = Column(Integer, ForeignKey('workflow_steps.id'), nullable=False)
    
    # Stato
    status = Column(SQLEnum(ExecutionStatus), default=ExecutionStatus.SCHEDULED, nullable=False)
    
    # Timing
    scheduled_at = Column(DateTime, nullable=False)
    sent_at = Column(DateTime)
    completed_at = Column(DateTime)
    
    # Risultato esecuzione
    result_data = Column(JSON)  # Response dati, errori, etc.
    error_message = Column(Text)
    
    # Job scheduler ID (per cancellazione)
    job_id = Column(String(100), unique=True, index=True)
    
    # Metadata
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relazioni
    participant = relationship('Participant', back_populates='executions')
    step = relationship('WorkflowStep', back_populates='executions')
    
    def __repr__(self):
        return f'<Execution {self.id}: Participant {self.participant_id} Step {self.step_id}>'


class ActivityLog(Base):
    """Log di tutte le attività del workflow"""
    __tablename__ = 'activity_log'

    id = Column(Integer, primary_key=True)
    workflow_id = Column(Integer, ForeignKey('workflows.id', ondelete='CASCADE'), nullable=False)
    participant_id = Column(Integer, ForeignKey('participants.id', ondelete='CASCADE'), nullable=True)
    step_id = Column(Integer, ForeignKey('workflow_steps.id', ondelete='CASCADE'), nullable=True)

    event_type = Column(String(50), nullable=False)
    description = Column(Text)
    details = Column(JSON)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    workflow = relationship('Workflow')
    participant = relationship('Participant')
    step = relationship('WorkflowStep')

    def __repr__(self):
        return f'<ActivityLog {self.id}: {self.event_type}>'


class LandingTemplate(Base):
    """Template landing page riutilizzabili"""
    __tablename__ = 'landing_templates'

    id = Column(Integer, primary_key=True)
    name = Column(String(200), nullable=False)
    description = Column(Text)
    landing_html = Column(Text)
    landing_css = Column(Text)
    landing_gjs_data = Column(JSON)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f'<LandingTemplate {self.id}: {self.name}>'
