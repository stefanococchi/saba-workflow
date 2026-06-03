"""Handler step verifica_report — cruscotto di validazione verifiche incrociate."""

import logging
from app.step_handlers import register
from app.step_handlers.base import StepHandler

logger = logging.getLogger(__name__)


@register('VERIFICA_REPORT')
class VerificaReportHandler(StepHandler):
    """Calcola le verifiche incrociate e presenta il cruscotto di review.

    Auto-esegue il calcolo dei check, ma NON auto-avanza:
    il notaio deve revisionare e confermare prima di procedere.
    """

    @property
    def is_auto_execute(self):
        return True

    def execute(self, step, practice_result, config, db_session):
        """Calcola le verifiche incrociate dagli step precedenti."""
        from app.api.pratiche import _build_verifiche, CHECKS_REGISTRY
        from app.models import Workflow

        result = {'type': 'VERIFICA_REPORT'}

        step_states = practice_result.step_states or {}

        # ── Raccogli dati dagli step precedenti ──
        titolo_fields = {}
        visure_list = []
        ipotecaria_list = []

        files_data = (practice_result.result_data or {}).get('files', {})
        for fhash, fdata in files_data.items():
            doc_id = (fdata.get('identification', {}).get('documentId', '') or fhash).strip()
            extraction = fdata.get('extraction', {}).get('data', {})
            if not extraction or not isinstance(extraction, dict):
                continue
            dl = doc_id.lower()
            if dl.startswith('visura') or dl.startswith('ipotecaria'):
                continue
            for k, v in extraction.items():
                kl = k.lower()
                if v and kl not in titolo_fields:
                    titolo_fields[kl] = (k, v)

        for order, ss in step_states.items():
            if ss.get('status') != 'completed':
                continue
            er = ss.get('exec_result', {})
            if er.get('type') == 'SISTER_VISURA':
                visure_list.extend(er.get('visure', []))
            elif er.get('type') == 'SISTER_IPOTECARIA':
                ipotecaria_list.extend(er.get('ispezioni', []))

        # ── Carica checks_config dal workflow ──
        checks_config = None
        if practice_result.workflow_id:
            wf = db_session.query(Workflow).get(practice_result.workflow_id)
            if wf and wf.config:
                checks_config = wf.config.get('checks_config')

        # ── Esegui verifiche ──
        verifiche = _build_verifiche(titolo_fields, visure_list, ipotecaria_list, checks_config)

        result['verifiche'] = verifiche
        result['status'] = 'REVIEW_PENDING'
        result['stats'] = {
            'total': len(verifiche),
            'ok': sum(1 for v in verifiche if v['esito'] == 'ok'),
            'errors': sum(1 for v in verifiche if v['esito'] == 'error'),
            'warnings': sum(1 for v in verifiche if v['esito'] == 'warning'),
        }

        logger.info(f"Verifica report: {result['stats']}")
        return result

    def get_display_data(self, step_config, step_state):
        exec_result = step_state.get('exec_result', {})
        verifiche = exec_result.get('verifiche', [])
        overrides = step_state.get('overrides', {})
        stats = exec_result.get('stats', {})

        fields = []

        if stats:
            status_icon = 'ok' if stats.get('errors', 0) == 0 else 'error'
            fields.append({
                'label': 'Riepilogo',
                'value': f"{stats.get('total', 0)} verifiche: {stats.get('ok', 0)} OK, "
                         f"{stats.get('warnings', 0)} warning, {stats.get('errors', 0)} errori",
                'status': status_icon,
            })

        for v in verifiche:
            check_id = v.get('check_id', '')
            override = overrides.get(check_id)
            esito = override['esito'] if override else v['esito']
            label = v['label']
            if override:
                label += ' (modificato)'

            val_parts = []
            if v.get('val_titolo') and v['val_titolo'] != '\u2014':
                val_parts.append(f"Titolo: {v['val_titolo']}")
            if v.get('val_catasto') and v['val_catasto'] != '\u2014':
                val_parts.append(f"Catasto: {v['val_catasto']}")
            value = ' | '.join(val_parts) if val_parts else '\u2014'

            fields.append({
                'label': label,
                'value': value,
                'status': esito,
                'check_id': check_id,
            })

        # Bottoni: il notaio deve confermare manualmente
        is_reviewed = step_state.get('status') == 'completed'
        buttons = [
            {'label': 'Salta', 'action': 'skip', 'icon': 'bi-skip-forward', 'variant': 'outline-secondary'},
        ]
        if not is_reviewed:
            buttons.append({
                'label': 'Conferma verifiche e avanza',
                'action': 'complete',
                'icon': 'bi-check-circle-fill',
                'variant': 'success',
            })

        return {
            'buttons': buttons,
            'auto_execute': True,
            'auto_advance': False,  # NON avanzare automaticamente
            'summary_fields': fields,
            'verifiche': verifiche,       # Dati completi per il cruscotto
            'overrides': overrides,
            'render_mode': 'verifica_report',  # Flag per UI custom
        }
