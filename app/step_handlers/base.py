"""Base class per step handlers del workflow."""
from abc import ABC, abstractmethod


class StepHandler(ABC):
    """Interfaccia standard per ogni tipo di step del workflow.

    Ogni handler implementa:
    - execute(): esegue la logica dello step
    - get_display_data(): ritorna metadata per la UI
    - is_auto_execute: se lo step si esegue automaticamente
    """

    @property
    def is_auto_execute(self):
        """Se True, lo step viene eseguito automaticamente quando diventa corrente."""
        return True

    def should_auto_execute(self, config):
        """Decide se auto-eseguire in base alla config dello step. Override per logica custom."""
        return self.is_auto_execute

    @abstractmethod
    def execute(self, step, practice_result, config, db_session):
        """Esegue lo step. NON fare db_session.commit() — lo fa il chiamante.

        Args:
            step: WorkflowStep model instance
            practice_result: PracticeResult model instance
            config: dict dalla skip_conditions dello step
            db_session: sessione SQLAlchemy (per query/flush, MAI commit)

        Returns:
            dict con risultato: {'type': 'STEP_TYPE', ...dati specifici...}
        """
        pass

    def get_display_data(self, step_config, step_state):
        """Ritorna metadata per renderizzare lo step nella UI.

        Args:
            step_config: dict config dello step (skip_conditions)
            step_state: dict dallo step_states[order] (status, exec_result, etc.)

        Returns:
            dict con:
                'buttons': lista di {label, action, icon, variant}
                'auto_execute': bool
                'summary_fields': lista di {label, value, status} per risultati
        """
        return {
            'buttons': [
                {'label': 'Salta', 'action': 'skip', 'icon': 'bi-skip-forward', 'variant': 'outline-secondary'},
                {'label': 'Esegui e avanza', 'action': 'complete', 'icon': 'bi-play-fill', 'variant': 'primary'},
            ],
            'auto_execute': self.is_auto_execute,
            'summary_fields': [],
        }

    def get_accumulated_data(self, practice_result):
        """Helper: raccoglie extracted_data da tutti gli step completati."""
        accumulated = {}
        for order_key, state in (practice_result.step_states or {}).items():
            if state.get('status') == 'completed' and state.get('extracted_data'):
                for doc_type, fields in state['extracted_data'].items():
                    if isinstance(fields, dict):
                        accumulated.update(fields)
        return accumulated
