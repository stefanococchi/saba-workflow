"""Handler per step DOCUMENT_PROCESSING — elaborazione automatica sui dati estratti.

Esegue operazioni configurabili sui dati accumulati dagli step precedenti:
- Confronto campi tra documenti diversi
- Calcoli (somme, differenze)
- Validazioni automatiche (formato, range, coerenza)
- Preparazione dati per step successivi

Il risultato viene salvato in step_states e mostrato allo step DOCUMENT_CHECK successivo
per la validazione umana.
"""
import logging
from app.step_handlers import register
from app.step_handlers.base import StepHandler

logger = logging.getLogger(__name__)


@register('DOCUMENT_PROCESSING')
class DocumentProcessingHandler(StepHandler):

    @property
    def is_auto_execute(self):
        return True

    def execute(self, step, practice_result, config, db_session):
        result = {'type': 'DOCUMENT_PROCESSING'}
        accumulated = self.get_accumulated_data(practice_result)

        if not accumulated:
            result['warning'] = 'Nessun dato accumulato dagli step precedenti'
            return result

        # Esegui le regole configurate nello step
        rules = config.get('rules', [])
        checks = []

        for rule in rules:
            check = self._execute_rule(rule, accumulated)
            checks.append(check)

        # Se non ci sono regole configurate, fai un riepilogo dei dati disponibili
        if not checks:
            checks.append({
                'rule': 'data_summary',
                'label': 'Dati disponibili',
                'status': 'ok',
                'value': f'{len(accumulated)} campi estratti',
                'fields': list(accumulated.keys())[:20],
            })

        result['checks'] = checks
        result['accumulated_keys'] = list(accumulated.keys())

        errors = [c for c in checks if c['status'] == 'error']
        warnings = [c for c in checks if c['status'] == 'warning']
        result['summary'] = {
            'total': len(checks),
            'ok': len([c for c in checks if c['status'] == 'ok']),
            'errors': len(errors),
            'warnings': len(warnings),
        }

        logger.info(f"Document processing: {len(checks)} checks, {len(errors)} errors, {len(warnings)} warnings")
        return result

    def _execute_rule(self, rule, data):
        """Esegue una singola regola di validazione/elaborazione."""
        rule_type = rule.get('type', '')
        label = rule.get('label', rule_type)

        try:
            if rule_type == 'compare':
                return self._rule_compare(rule, data, label)
            elif rule_type == 'required':
                return self._rule_required(rule, data, label)
            elif rule_type == 'format':
                return self._rule_format(rule, data, label)
            elif rule_type == 'calculate':
                return self._rule_calculate(rule, data, label)
            else:
                return {'rule': rule_type, 'label': label, 'status': 'warning',
                        'value': f'Tipo regola sconosciuto: {rule_type}'}
        except Exception as e:
            return {'rule': rule_type, 'label': label, 'status': 'error', 'value': str(e)}

    def _rule_compare(self, rule, data, label):
        """Confronta due campi: {type: 'compare', field_a: 'x', field_b: 'y'}"""
        field_a = rule.get('field_a', '')
        field_b = rule.get('field_b', '')
        val_a = self._find_field(data, field_a)
        val_b = self._find_field(data, field_b)

        if val_a is None:
            return {'rule': 'compare', 'label': label, 'status': 'warning',
                    'value': f'Campo "{field_a}" non trovato'}
        if val_b is None:
            return {'rule': 'compare', 'label': label, 'status': 'warning',
                    'value': f'Campo "{field_b}" non trovato'}

        match = str(val_a).strip().lower() == str(val_b).strip().lower()
        return {
            'rule': 'compare', 'label': label,
            'status': 'ok' if match else 'error',
            'value': f'{val_a}' if match else f'{val_a} ≠ {val_b}',
            'field_a': field_a, 'val_a': str(val_a),
            'field_b': field_b, 'val_b': str(val_b),
        }

    def _rule_required(self, rule, data, label):
        """Verifica che un campo esista: {type: 'required', field: 'x'}"""
        field = rule.get('field', '')
        val = self._find_field(data, field)
        present = val is not None and str(val).strip() != ''
        return {
            'rule': 'required', 'label': label,
            'status': 'ok' if present else 'error',
            'value': str(val) if present else 'Mancante',
            'field': field,
        }

    def _rule_format(self, rule, data, label):
        """Verifica formato: {type: 'format', field: 'x', pattern: 'regex'}"""
        import re
        field = rule.get('field', '')
        pattern = rule.get('pattern', '')
        val = self._find_field(data, field)
        if val is None:
            return {'rule': 'format', 'label': label, 'status': 'warning', 'value': f'Campo "{field}" non trovato'}
        match = bool(re.match(pattern, str(val)))
        return {
            'rule': 'format', 'label': label,
            'status': 'ok' if match else 'error',
            'value': str(val),
            'field': field, 'pattern': pattern,
        }

    def _rule_calculate(self, rule, data, label):
        """Calcolo semplice: {type: 'calculate', operation: 'sum', fields: ['x','y'], output: 'z'}"""
        operation = rule.get('operation', '')
        fields = rule.get('fields', [])
        values = []
        for f in fields:
            v = self._find_field(data, f)
            if v is not None:
                try:
                    values.append(float(str(v).replace(',', '.').replace('€', '').strip()))
                except ValueError:
                    pass

        if not values:
            return {'rule': 'calculate', 'label': label, 'status': 'warning', 'value': 'Nessun valore numerico trovato'}

        if operation == 'sum':
            result_val = sum(values)
        elif operation == 'diff':
            result_val = values[0] - sum(values[1:]) if len(values) > 1 else values[0]
        elif operation == 'avg':
            result_val = sum(values) / len(values)
        else:
            return {'rule': 'calculate', 'label': label, 'status': 'warning', 'value': f'Operazione sconosciuta: {operation}'}

        return {
            'rule': 'calculate', 'label': label,
            'status': 'ok',
            'value': f'{result_val:,.2f}',
            'operation': operation,
        }

    def _find_field(self, data, field_name):
        """Cerca un campo nei dati (case-insensitive, supporta nested con '.')."""
        if '.' in field_name:
            parts = field_name.split('.', 1)
            sub = self._find_field(data, parts[0])
            if isinstance(sub, dict):
                return self._find_field(sub, parts[1])
            return None

        # Cerca case-insensitive
        norm = field_name.lower().replace('_', '').replace(' ', '')
        for k, v in data.items():
            if k.lower().replace('_', '').replace(' ', '') == norm:
                return v
        return None

    def get_display_data(self, step_config, step_state):
        exec_result = step_state.get('exec_result', {})
        checks = exec_result.get('checks', [])
        summary = exec_result.get('summary', {})

        fields = []
        if summary:
            total = summary.get('total', 0)
            ok = summary.get('ok', 0)
            errors = summary.get('errors', 0)
            warnings = summary.get('warnings', 0)
            status = 'ok' if errors == 0 else 'error'
            fields.append({'label': 'Controlli', 'value': f'{ok}/{total} OK, {errors} errori, {warnings} avvisi', 'status': status})

        for check in checks:
            if check.get('rule') == 'data_summary':
                # Mostra i campi disponibili ordinati
                field_list = check.get('fields', [])
                for fname in sorted(field_list):
                    fields.append({'label': fname, 'value': '✓ presente', 'status': 'ok'})
            else:
                fields.append({
                    'label': check.get('label', check.get('rule', '')),
                    'value': check.get('value', ''),
                    'status': check.get('status', 'pending'),
                })

        if exec_result.get('warning'):
            fields.append({'label': 'Avviso', 'value': exec_result['warning'], 'status': 'warning'})

        return {
            'buttons': [
                {'label': 'Salta', 'action': 'skip', 'icon': 'bi-skip-forward', 'variant': 'outline-secondary'},
                {'label': 'Esegui e avanza', 'action': 'complete', 'icon': 'bi-play-fill', 'variant': 'primary'},
            ],
            'auto_execute': True,
            'summary_fields': fields,
        }
