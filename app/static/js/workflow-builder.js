// Workflow Builder - Drag & Drop Logic
let workflowSteps = [];
let currentStep = 1;
let editingStepIndex = null;

// Initialize on page load
document.addEventListener('DOMContentLoaded', function() {
    initDragAndDrop();
});

// Initialize drag and drop
function initDragAndDrop() {
    const templates = document.querySelectorAll('.step-template');
    const canvas = document.getElementById('workflowCanvas');
    
    // Make templates draggable
    templates.forEach(template => {
        template.addEventListener('dragstart', handleDragStart);
    });
    
    // Canvas drop zone
    canvas.addEventListener('dragover', handleDragOver);
    canvas.addEventListener('drop', handleDrop);
    canvas.addEventListener('dragleave', handleDragLeave);
}

function handleDragStart(e) {
    e.dataTransfer.effectAllowed = 'copy';
    e.dataTransfer.setData('stepType', e.currentTarget.dataset.type);
}

function handleDragOver(e) {
    e.preventDefault();
    e.dataTransfer.dropEffect = 'copy';
    document.getElementById('workflowCanvas').classList.add('drag-over');
}

function handleDragLeave(e) {
    if (e.target.id === 'workflowCanvas') {
        e.target.classList.remove('drag-over');
    }
}

function handleDrop(e) {
    e.preventDefault();
    e.stopPropagation();
    const canvas = document.getElementById('workflowCanvas');
    canvas.classList.remove('drag-over');

    const stepType = e.dataTransfer.getData('stepType');
    if (!stepType) return;

    // Find insert position based on drop Y relative to existing step cards
    var insertIndex = workflowSteps.length;
    var container = document.getElementById('stepsSortContainer');
    if (container) {
        var items = container.querySelectorAll('.step-sort-item');
        for (var i = 0; i < items.length; i++) {
            var rect = items[i].getBoundingClientRect();
            if (e.clientY < rect.top + rect.height / 2) {
                insertIndex = i;
                break;
            }
        }
    }
    addStep(stepType, insertIndex);
}

// Add new step to workflow
function addStep(type, insertAt) {
    if (insertAt === undefined) insertAt = workflowSteps.length;

    const step = {
        id: Date.now(),
        type: type,
        order: insertAt + 1,
        name: `${capitalize(type)} Step ${workflowSteps.length + 1}`,
        config: getDefaultConfig(type)
    };

    workflowSteps.splice(insertAt, 0, step);
    // Recalculate order for all steps
    workflowSteps.forEach(function(s, i) { s.order = i + 1; });
    renderCanvas();

    // Auto-open edit modal for new step (delay to let DOM settle)
    setTimeout(function() { editStep(insertAt); }, 100);
}

// Get default configuration for step type
function getDefaultConfig(type) {
    const configs = {
        // WORKING STEPS
        email: {
            subject: '',
            body_template: '',
            delay_hours: 0,
            attachments: []
        },
        wait_until: {
            wait_type: 'date',
            target_date: '',
            target_time: '09:00',
            delay_hours: 0,
            timezone: 'UTC'
        },
        goal_check: {
            goal: 'form_submitted',
            if_met: 'complete',
            if_not_met: 'continue',
            field_name: '',
            field_value: '',
            status_value: 'completed'
        },
        
        // PLACEHOLDER STEPS
        condition: {
            field: '',
            field_source: 'sabaform_data',
            operator: 'equals',
            value: '',
            if_true: 'continue',
            if_true_step: 0,
            if_false: 'continue',
            if_false_step: 0,
        },
        survey: {
            subject: '',
            body_template: '',
            delay_hours: 0,
            question: 'Come valuti l\'evento?',
            response_type: 'choices',
            choices: ['Ottimo', 'Buono', 'Sufficiente', 'Scarso'],
            scale_max: 5,
            allow_comment: true
        },
        file_upload: {
            required_files: [],
            max_size_mb: 10,
            allowed_types: ['pdf', 'jpg', 'png']
        },
        human_approval: {
            approver_email: '',
            approval_message: '',
            timeout_hours: 48,
            on_timeout: 'reject'
        },
        export_data: {
            format: 'csv',
            send_to: '',
            save_local: false
        }
    };
    return configs[type] || {};
}

// Render workflow canvas
function renderCanvas() {
    const canvas = document.getElementById('workflowCanvas');
    const emptyState = document.getElementById('emptyState');
    
    if (workflowSteps.length === 0) {
        emptyState.style.display = 'block';
        return;
    }
    
    emptyState.style.display = 'none';
    
    let html = '<div id="stepsSortContainer">';
    workflowSteps.forEach((step, index) => {
        html += '<div class="step-sort-item" data-sort-index="' + index + '">';
        html += renderStep(step, index);
        if (index < workflowSteps.length - 1) {
            html += '<div class="step-connector"></div>';
        }
        html += '</div>';
    });
    html += '</div>';

    canvas.innerHTML = html + emptyState.outerHTML;

    // Allow palette drops on the sort container too
    var sortContainer = document.getElementById('stepsSortContainer');
    if (sortContainer) {
        sortContainer.addEventListener('dragover', handleDragOver);
        sortContainer.addEventListener('drop', handleDrop);
        sortContainer.addEventListener('dragleave', handleDragLeave);
    }

    // Init SortableJS for step reordering
    initStepSortable();
}

// Render single step
function renderStep(step, index) {
    const icons = {
        email: 'envelope',
        wait_until: 'calendar-check',
        condition: 'shuffle',
        goal_check: 'trophy',
        engagement_tracker: 'graph-up',
        survey: 'ui-checks',
        file_upload: 'file-earmark-arrow-up',
        human_approval: 'person-check',
        export_data: 'download'
    };
    
    const colors = {
        email: '#bbb',
        wait_until: '#999',
        condition: '#777',
        goal_check: '#888',
        engagement_tracker: '#aaa',
        survey: '#9a9a9a',
        file_upload: '#b0b0b0',
        human_approval: '#808080',
        export_data: '#a3a3a3'
    };

    const bgColors = {
        email: '#f7f7f7',
        wait_until: '#efefef',
        condition: '#e5e5e5',
        goal_check: '#eaeaea',
        engagement_tracker: '#f2f2f2',
        survey: '#ededed',
        file_upload: '#f4f4f4',
        human_approval: '#e8e8e8',
        export_data: '#f0f0f0'
    };
    
    const isPlaceholder = false; // Legacy, kept for template compatibility
    const placeholderBadge = isPlaceholder ? ' <span class="badge bg-warning">Placeholder</span>' : '';
    
    return `
        <div class="workflow-step${isPlaceholder ? ' step-placeholder-canvas' : ''}" 
             data-step-id="${step.id}" 
             data-step-index="${index}"
             style="border-color: ${colors[step.type]}; background: ${bgColors[step.type]}">
            <div class="step-header">
                <div class="d-flex align-items-center">
                    <div class="step-drag-handle" title="Trascina per riordinare" style="cursor:grab;padding:8px 6px;margin-right:4px;color:#aaa;font-size:18px"><i class="bi bi-grip-vertical"></i></div>
                    <div class="step-number">${index + 1}</div>
                    <div class="ms-3">
                        <h6 class="mb-0">
                            <i class="bi bi-${icons[step.type]}"></i> ${step.name}${placeholderBadge}
                        </h6>
                        <small class="text-muted">${capitalize(step.type)}</small>
                    </div>
                </div>
                <div class="step-actions">
                    <button type="button" class="btn btn-sm btn-outline-secondary" 
                            onclick="moveStepUp(${index})" title="Move Up" ${index === 0 ? 'disabled' : ''}>
                        <i class="bi bi-arrow-up"></i>
                    </button>
                    <button type="button" class="btn btn-sm btn-outline-secondary" 
                            onclick="moveStepDown(${index})" title="Move Down" ${index === workflowSteps.length - 1 ? 'disabled' : ''}>
                        <i class="bi bi-arrow-down"></i>
                    </button>
                    <button type="button" class="btn btn-sm btn-outline-primary"
                            onclick="editStep(${index})" title="Edit">
                        <i class="bi bi-pencil"></i>
                    </button>
                    ${step.type === 'email' ? `<button type="button" class="btn btn-sm btn-outline-info"
                            onclick="openLandingBuilder(${index})" title="Landing Builder">
                        <i class="bi bi-palette"></i>
                    </button>` : ''}
                    <button type="button" class="btn btn-sm btn-outline-danger"
                            onclick="deleteStep(${index})" title="Delete">
                        <i class="bi bi-trash"></i>
                    </button>
                </div>
            </div>
            <div class="step-content">
                ${renderStepSummary(step)}
            </div>
        </div>
    `;
}

// Render step summary
function renderStepSummary(step) {
    switch(step.type) {
        case 'email':
            var attCount = (step.config.attachments || []).length;
            var attInfo = attCount > 0 ? `<p class="mb-0"><i class="bi bi-paperclip"></i> ${attCount} allegat${attCount === 1 ? 'o' : 'i'}</p>` : '';
            return `
                <p class="mb-1"><strong>Subject:</strong> ${step.config.subject || '<em class="text-muted">Not set</em>'}</p>
                <p class="mb-0"><strong>Delay:</strong> ${step.config.delay_hours} hours after previous step</p>
                ${attInfo}
            `;
        case 'wait_until':
            const waitDesc = {
                'date': `Until ${step.config.target_date || 'date not set'} at ${step.config.target_time}`,
                'time': `Daily at ${step.config.target_time}`,
                'day_of_week': `Every ${step.config.target_day || 'Monday'} at ${step.config.target_time}`,
                'delay_hours': `${step.config.delay_hours || 0} ore dopo lo step precedente`
            };
            return `<p class="mb-0"><strong>Wait:</strong> ${waitDesc[step.config.wait_type] || 'Not configured'}</p>`;
        case 'goal_check':
            const goalDesc = {
                'form_submitted': 'Form submitted',
                'field_filled': `Field "${step.config.field_name || '?'}" filled`,
                'field_equals': `${step.config.field_name || '?'} = "${step.config.field_value || '?'}"`,
                'email_opened': 'Email opened',
                'status_equals': `Status = ${step.config.status_value || '?'}`
            };
            const actionDesc = step.config.if_met === 'complete' ? '→ STOP workflow' : '→ Continue';
            return `<p class="mb-0"><strong>Check:</strong> ${goalDesc[step.config.goal] || 'Not configured'} ${actionDesc}</p>`;
        case 'condition':
            var opLabels = {equals:'=', not_equals:'≠', contains:'contiene', not_empty:'non vuoto', empty:'vuoto', greater_than:'>', less_than:'<'};
            var opLabel = opLabels[step.config.operator] || step.config.operator;
            var valPart = ['not_empty','empty'].indexOf(step.config.operator) !== -1 ? '' : ' "' + (step.config.value || '?') + '"';
            function descAction(act, stepOrder) {
                if (act === 'jump') return 'vai a Step ' + (stepOrder || '?');
                if (act === 'stop') return 'ferma';
                return 'continua';
            }
            return `<p class="mb-0"><strong>Se</strong> ${step.config.field || '?'} ${opLabel}${valPart}<br><small class="text-success">✓ ${descAction(step.config.if_true, step.config.if_true_step)}</small> · <small class="text-danger">✗ ${descAction(step.config.if_false, step.config.if_false_step)}</small></p>`;
        case 'survey':
            const surveyQ = step.config.question || 'Non configurata';
            const surveyType = step.config.response_type === 'scale'
                ? `Scala 1-${step.config.scale_max || 5}`
                : (step.config.choices || []).join(' / ');
            return `
                <p class="mb-1"><strong>Subject:</strong> ${step.config.subject || '<em class="text-muted">Not set</em>'}</p>
                <p class="mb-1"><strong>Domanda:</strong> ${surveyQ}</p>
                <p class="mb-0"><strong>Risposte:</strong> ${surveyType}</p>
            `;
        case 'human_approval':
            var approvedAction = step.config.if_approved === 'jump' ? 'Jump to step ' + (step.config.if_approved_step || '?') : (step.config.if_approved === 'complete' ? 'Complete workflow' : 'Continue');
            var rejectedAction = step.config.if_rejected === 'jump' ? 'Jump to step ' + (step.config.if_rejected_step || '?') : (step.config.if_rejected === 'continue' ? 'Continue' : 'Stop workflow');
            return `
                <p class="mb-1"><strong>Approver:</strong> ${(step.config.approver_email || '').split(',').map(e => e.trim()).filter(Boolean).join(', ') || '<em class="text-muted">Not set</em>'}</p>
                <p class="mb-1"><small class="text-success">&#10003; Approved → ${approvedAction}</small> · <small class="text-danger">&#10007; Rejected → ${rejectedAction}</small></p>
                <p class="mb-0"><strong>Timeout:</strong> ${step.config.timeout_hours}h → ${step.config.on_timeout === 'approve' ? 'Auto-approve' : step.config.on_timeout === 'remind' ? 'Remind' : 'Reject'}</p>
            `;
        case 'export_data':
            const exportTo = step.config.send_to || 'No email configured';
            return `<p class="mb-0"><strong>Export:</strong> ${step.config.format.toUpperCase()} → ${exportTo}</p>`;
        default:
            return '';
    }
}

// Edit step
function editStep(index) {
    editingStepIndex = index;
    const step = workflowSteps[index];
    const modal = new bootstrap.Modal(document.getElementById('stepEditModal'));
    const content = document.getElementById('stepEditContent');
    
    content.innerHTML = renderStepEditForm(step, index);
    // Init Summernote for email/survey body
    if (step.type === 'email' || step.type === 'survey') {
        initEmailEditor();
    }
    if (step.type === 'email') {
        initAttachmentDropZone();
    }
    // Populate landing field dropdowns for goal_check — from preceding landing steps
    if (step.type === 'goal_check') {
        populatFieldsFromPrecedingLanding('editGoalFieldName', step.config.field_name, 'goalFieldNameLoading', index);
    }
    if (step.type === 'condition') {
        onConditionSourceChange();
        // Pre-seleziona il campo dopo il caricamento
        setTimeout(function() {
            var sel = document.getElementById('editConditionField');
            var custom = document.getElementById('editConditionFieldCustom');
            if (sel && step.config.field) {
                sel.value = step.config.field;
                if (!sel.value && custom) custom.value = step.config.field;
            }
        }, 300);
    }
    
    // Destroy Summernote when modal closes
    document.getElementById('stepEditModal').addEventListener('hidden.bs.modal', function() {
        destroyEmailEditor();
    }, { once: true });

    modal.show();
}

// Render edit form based on step type
function renderStepEditForm(step, index) {
    const common = `
        <div class="mb-3">
            <label class="form-label">Step Name</label>
            <input type="text" class="form-control" id="editStepName" value="${step.name}">
        </div>
    `;
    
    switch(step.type) {
        case 'email':
            return common + `
                <div class="mb-3">
                    <label class="form-label">Oggetto email</label>
                    <input type="text" class="form-control" id="editEmailSubject"
                           value="${step.config.subject || ''}"
                           placeholder="es. Sei invitato a {{ workflow_name }}!">
                </div>
                <div class="mb-3">
                    <label class="form-label">Corpo email</label>
                    <div class="variable-bar">
                        <span class="variable-bar-label"><i class="bi bi-plus-circle"></i> Inserisci:</span>
                        <span class="variable-badge" onclick="insertVariable('workflow_name')" title="Il nome del workflow/evento">
                            <i class="bi bi-bookmark"></i> Nome Evento
                        </span>
                        <span class="variable-badge" onclick="insertVariable('participant.first_name')" title="Nome del partecipante">
                            <i class="bi bi-person"></i> Nome
                        </span>
                        <span class="variable-badge" onclick="insertVariable('participant.last_name')" title="Cognome del partecipante">
                            <i class="bi bi-person"></i> Cognome
                        </span>
                        <span class="variable-badge" onclick="insertVariable('participant.full_name')" title="Nome completo del partecipante">
                            <i class="bi bi-person-badge"></i> Nome Completo
                        </span>
                        <span class="variable-badge" onclick="insertVariable('participant.email')" title="Email del partecipante">
                            <i class="bi bi-envelope"></i> Email
                        </span>
                        <span class="variable-badge" onclick="insertVariable('landing_url')" title="Link alla landing page (se attiva)">
                            <i class="bi bi-link-45deg"></i> Link Landing
                        </span>
                        <span class="variable-badge" onclick="insertVariable('step_name')" title="Nome di questo step">
                            <i class="bi bi-signpost"></i> Nome Step
                        </span>
                    </div>
                    <textarea class="form-control template-editor" id="editEmailBody" rows="8"
                              placeholder="Scrivi il testo della tua email qui. Clicca i bottoni sopra per inserire i dati automatici.">${step.config.body_template || ''}</textarea>
                    <div class="form-text">Clicca sui bottoni per inserire dati dinamici. Verranno sostituiti automaticamente per ogni partecipante.</div>
                </div>
                <div class="mb-3">
                    <label class="form-label">Ritardo (ore dopo lo step precedente)</label>
                    <input type="number" class="form-control" id="editEmailDelay"
                           value="${step.config.delay_hours || 0}" min="0">
                </div>
                <div class="mb-3">
                    <label class="form-label"><i class="bi bi-paperclip"></i> Allegati</label>
                    <div id="attachmentList">${renderAttachmentList(step.config.attachments || [])}</div>
                    <div id="attachmentDropZone" class="attachment-drop-zone" onclick="document.getElementById('attachmentFileInput').click()">
                        <i class="bi bi-cloud-arrow-up" style="font-size:24px;color:#8B6914"></i>
                        <div style="margin-top:4px">Trascina file qui o <strong>clicca per caricare</strong></div>
                        <small class="text-muted">PDF, DOC, XLS, immagini, ZIP — max 3.9 MB per file</small>
                    </div>
                    <input type="file" id="attachmentFileInput" style="display:none" multiple
                           accept=".pdf,.doc,.docx,.xls,.xlsx,.csv,.txt,.png,.jpg,.jpeg,.gif,.zip"
                           onchange="handleAttachmentUpload(this.files)">
                </div>
                <div class="form-check">
                    <input class="form-check-input" type="checkbox" id="editHasLanding"
                           ${step.config.has_landing ? 'checked' : ''}>
                    <label class="form-check-label" for="editHasLanding">
                        Includi landing page per raccolta dati
                    </label>
                </div>
            `;
        case 'wait_until':
            return common + `
                <div class="mb-3">
                    <label class="form-label">Wait Type</label>
                    <select class="form-select" id="editWaitType" onchange="updateWaitUntilForm()">
                        <option value="delay_hours" ${step.config.wait_type === 'delay_hours' ? 'selected' : ''}>X ore dopo lo step precedente</option>
                        <option value="date" ${step.config.wait_type === 'date' ? 'selected' : ''}>Data e ora specifica</option>
                        <option value="time" ${step.config.wait_type === 'time' ? 'selected' : ''}>Ogni giorno a un orario</option>
                        <option value="day_of_week" ${step.config.wait_type === 'day_of_week' ? 'selected' : ''}>Giorno della settimana</option>
                    </select>
                </div>

                <div id="waitUntilDelayFields" ${step.config.wait_type !== 'delay_hours' ? 'style="display:none"' : ''}>
                    <div class="mb-3">
                        <label class="form-label">Ore di attesa</label>
                        <input type="number" class="form-control" id="editWaitDelayHours"
                               value="${step.config.delay_hours || 0}" min="0" step="1">
                        <small class="text-muted">Attendi X ore dopo il completamento dello step precedente</small>
                    </div>
                </div>

                <div id="waitUntilDateFields" ${step.config.wait_type !== 'date' ? 'style="display:none"' : ''}>
                    <div class="mb-3">
                        <label class="form-label">Data</label>
                        <input type="date" class="form-control" id="editTargetDate"
                               value="${step.config.target_date || ''}" min="${new Date().toISOString().split('T')[0]}">
                        <small class="text-muted">Attendi fino a questa data</small>
                    </div>
                </div>

                <div id="waitUntilDayFields" ${step.config.wait_type !== 'day_of_week' ? 'style="display:none"' : ''}>
                    <div class="mb-3">
                        <label class="form-label">Giorno della settimana</label>
                        <select class="form-select" id="editTargetDay">
                            <option value="monday" ${step.config.target_day === 'monday' ? 'selected' : ''}>Lunedì</option>
                            <option value="tuesday" ${step.config.target_day === 'tuesday' ? 'selected' : ''}>Martedì</option>
                            <option value="wednesday" ${step.config.target_day === 'wednesday' ? 'selected' : ''}>Mercoledì</option>
                            <option value="thursday" ${step.config.target_day === 'thursday' ? 'selected' : ''}>Giovedì</option>
                            <option value="friday" ${step.config.target_day === 'friday' ? 'selected' : ''}>Venerdì</option>
                            <option value="saturday" ${step.config.target_day === 'saturday' ? 'selected' : ''}>Sabato</option>
                            <option value="sunday" ${step.config.target_day === 'sunday' ? 'selected' : ''}>Domenica</option>
                        </select>
                    </div>
                </div>

                <div id="waitUntilTimeFields" ${step.config.wait_type === 'delay_hours' ? 'style="display:none"' : ''}>
                    <div class="mb-3">
                        <label class="form-label">Orario</label>
                        <input type="time" class="form-control" id="editTargetTime"
                               value="${step.config.target_time || '09:00'}">
                    </div>
                </div>

                <div class="alert alert-info">
                    <small><i class="bi bi-info-circle"></i>
                    <strong>Ore dopo step precedente:</strong> Attendi X ore dal completamento dello step prima<br>
                    <strong>Data e ora:</strong> Esegui in una data e ora specifica<br>
                    <strong>Ogni giorno:</strong> Esegui ogni giorno a un orario (o il giorno dopo se già passato)<br>
                    <strong>Giorno della settimana:</strong> Esegui alla prossima occorrenza del giorno scelto
                    </small>
                </div>
            `;
        case 'goal_check':
            return common + `
                <div class="mb-3">
                    <label class="form-label">Goal Type</label>
                    <select class="form-select" id="editGoalType" onchange="updateGoalCheckForm()">
                        <option value="form_submitted" ${step.config.goal === 'form_submitted' ? 'selected' : ''}>Form Submitted</option>
                        <option value="field_filled" ${step.config.goal === 'field_filled' ? 'selected' : ''}>Specific Field Filled</option>
                        <option value="field_equals" ${step.config.goal === 'field_equals' ? 'selected' : ''}>Field Equals Value</option>
                        <option value="email_opened" ${step.config.goal === 'email_opened' ? 'selected' : ''}>Email Opened</option>
                        <option value="status_equals" ${step.config.goal === 'status_equals' ? 'selected' : ''}>Status Equals</option>
                    </select>
                </div>
                
                <div id="goalFieldName" ${['field_filled', 'field_equals'].includes(step.config.goal) ? '' : 'style="display:none"'}>
                    <div class="mb-3">
                        <label class="form-label">Campo della landing page</label>
                        <select class="form-select" id="editGoalFieldName">
                            <option value="">-- Seleziona campo --</option>
                        </select>
                        <div id="goalFieldNameLoading" class="form-text text-muted">
                            <i class="bi bi-hourglass-split"></i> Caricamento campi...
                        </div>
                    </div>
                </div>
                
                <div id="goalFieldValue" ${step.config.goal === 'field_equals' ? '' : 'style="display:none"'}>
                    <div class="mb-3">
                        <label class="form-label">Expected Value</label>
                        <input type="text" class="form-control" id="editGoalFieldValue" 
                               value="${step.config.field_value || ''}" 
                               placeholder="e.g., complete, yes, approved">
                    </div>
                </div>
                
                <div id="goalStatusValue" ${step.config.goal === 'status_equals' ? '' : 'style="display:none"'}>
                    <div class="mb-3">
                        <label class="form-label">Expected Status</label>
                        <select class="form-select" id="editGoalStatusValue">
                            <option value="completed" ${step.config.status_value === 'completed' ? 'selected' : ''}>Completed</option>
                            <option value="in_progress" ${step.config.status_value === 'in_progress' ? 'selected' : ''}>In Progress</option>
                            <option value="pending" ${step.config.status_value === 'pending' ? 'selected' : ''}>Pending</option>
                        </select>
                    </div>
                </div>
                
                <hr>
                
                <div class="mb-3">
                    <label class="form-label">If Goal Met</label>
                    <select class="form-select" id="editIfMet">
                        <option value="complete" ${step.config.if_met === 'complete' ? 'selected' : ''}>Complete Workflow (stop all future steps)</option>
                        <option value="continue" ${step.config.if_met === 'continue' ? 'selected' : ''}>Continue to Next Step</option>
                    </select>
                </div>
                
                <div class="mb-3">
                    <label class="form-label">If Goal NOT Met</label>
                    <select class="form-select" id="editIfNotMet">
                        <option value="continue" ${step.config.if_not_met === 'continue' ? 'selected' : ''}>Continue to Next Step</option>
                        <option value="skip" ${step.config.if_not_met === 'skip' ? 'selected' : ''}>Skip Next Step</option>
                    </select>
                </div>
                
                <div class="alert alert-info">
                    <small><i class="bi bi-info-circle"></i> <strong>Goal Types:</strong><br>
                    • <strong>Form Submitted:</strong> Participant filled landing page form<br>
                    • <strong>Field Filled:</strong> Specific field has any value<br>
                    • <strong>Field Equals:</strong> Field matches exact value<br>
                    • <strong>Email Opened:</strong> Participant opened at least one email<br>
                    • <strong>Status Equals:</strong> Participant status matches value
                    </small>
                </div>
            `;
        case 'condition':
            return common + `
                <div class="mb-3">
                    <label class="form-label">Sorgente dati</label>
                    <select class="form-select" id="editConditionSource" onchange="onConditionSourceChange()">
                        <option value="sabaform_data" ${step.config.field_source === 'sabaform_data' ? 'selected' : ''}>Dati Saba Form (importati)</option>
                        <option value="collected_data" ${step.config.field_source === 'collected_data' ? 'selected' : ''}>Dati raccolti (landing page)</option>
                        <option value="participant" ${step.config.field_source === 'participant' ? 'selected' : ''}>Dati partecipante (nome, email, stato)</option>
                    </select>
                </div>
                <div class="mb-3">
                    <label class="form-label">Campo da verificare</label>
                    <select class="form-select" id="editConditionField">
                        <option value="">-- Seleziona campo --</option>
                    </select>
                    <div id="conditionFieldLoading" class="form-text text-muted">
                        <i class="bi bi-hourglass-split"></i> Caricamento campi...
                    </div>
                    <input type="text" class="form-control mt-2" id="editConditionFieldCustom"
                           value="${step.config.field || ''}" placeholder="Oppure scrivi il nome del campo manualmente"
                           style="font-size:13px">
                </div>
                <div class="mb-3">
                    <label class="form-label">Operatore</label>
                    <select class="form-select" id="editConditionOperator">
                        <option value="equals" ${step.config.operator === 'equals' ? 'selected' : ''}>Uguale a</option>
                        <option value="not_equals" ${step.config.operator === 'not_equals' ? 'selected' : ''}>Diverso da</option>
                        <option value="contains" ${step.config.operator === 'contains' ? 'selected' : ''}>Contiene</option>
                        <option value="not_empty" ${step.config.operator === 'not_empty' ? 'selected' : ''}>Non vuoto</option>
                        <option value="empty" ${step.config.operator === 'empty' ? 'selected' : ''}>Vuoto</option>
                        <option value="greater_than" ${step.config.operator === 'greater_than' ? 'selected' : ''}>Maggiore di</option>
                        <option value="less_than" ${step.config.operator === 'less_than' ? 'selected' : ''}>Minore di</option>
                    </select>
                </div>
                <div class="mb-3" id="conditionValueRow">
                    <label class="form-label">Valore</label>
                    <input type="text" class="form-control" id="editConditionValue"
                           value="${step.config.value || ''}" placeholder="es. FIAT, M, completed...">
                </div>
                <hr>
                <div class="row">
                    <div class="col-md-6 mb-3">
                        <label class="form-label text-success"><i class="bi bi-check-circle"></i> Se VERO</label>
                        <select class="form-select" id="editConditionIfTrue" onchange="toggleJumpStep('True')">
                            <option value="continue" ${step.config.if_true === 'continue' ? 'selected' : ''}>Continua (step successivo)</option>
                            <option value="jump" ${step.config.if_true === 'jump' ? 'selected' : ''}>Salta a step...</option>
                            <option value="stop" ${step.config.if_true === 'stop' ? 'selected' : ''}>Ferma workflow</option>
                        </select>
                        <div id="jumpTrueRow" class="mt-2" ${step.config.if_true === 'jump' ? '' : 'style="display:none"'}>
                            <select class="form-select form-select-sm" id="editConditionIfTrueStep">
                                ${buildStepOptions(step.config.if_true_step, index)}
                            </select>
                        </div>
                    </div>
                    <div class="col-md-6 mb-3">
                        <label class="form-label text-danger"><i class="bi bi-x-circle"></i> Se FALSO</label>
                        <select class="form-select" id="editConditionIfFalse" onchange="toggleJumpStep('False')">
                            <option value="continue" ${step.config.if_false === 'continue' ? 'selected' : ''}>Continua (step successivo)</option>
                            <option value="jump" ${step.config.if_false === 'jump' ? 'selected' : ''}>Salta a step...</option>
                            <option value="stop" ${step.config.if_false === 'stop' ? 'selected' : ''}>Ferma workflow</option>
                        </select>
                        <div id="jumpFalseRow" class="mt-2" ${step.config.if_false === 'jump' ? '' : 'style="display:none"'}>
                            <select class="form-select form-select-sm" id="editConditionIfFalseStep">
                                ${buildStepOptions(step.config.if_false_step, index)}
                            </select>
                        </div>
                    </div>
                </div>
                <div class="alert alert-info">
                    <small><i class="bi bi-info-circle"></i>
                    La condizione viene valutata sui dati del partecipante al momento dell'esecuzione.<br>
                    <strong>Esempio:</strong> Se campo "company" uguale a "FIAT" → continua, altrimenti → salta prossimo step.
                    </small>
                </div>
            `;
        case 'survey':
            var choicesHtml = (step.config.choices || []).map(function(c, i) {
                return `<div class="input-group input-group-sm mb-1">
                    <input type="text" class="form-control survey-choice-input" value="${c}" placeholder="Opzione ${i+1}">
                    <button class="btn btn-outline-danger" type="button" onclick="this.closest('.input-group').remove()"><i class="bi bi-x"></i></button>
                </div>`;
            }).join('');
            return common + `
                <div class="mb-3">
                    <label class="form-label">Oggetto email</label>
                    <input type="text" class="form-control" id="editSurveySubject"
                           value="${step.config.subject || ''}"
                           placeholder="es. Dicci cosa ne pensi!">
                </div>
                <div class="mb-3">
                    <label class="form-label">Corpo email</label>
                    <div class="variable-bar">
                        <span class="variable-bar-label"><i class="bi bi-plus-circle"></i> Inserisci:</span>
                        <span class="variable-badge" onclick="insertVariable('workflow_name')" title="Il nome del workflow/evento">
                            <i class="bi bi-bookmark"></i> Nome Evento
                        </span>
                        <span class="variable-badge" onclick="insertVariable('participant.first_name')" title="Nome del partecipante">
                            <i class="bi bi-person"></i> Nome
                        </span>
                        <span class="variable-badge" onclick="insertVariable('participant.last_name')" title="Cognome del partecipante">
                            <i class="bi bi-person"></i> Cognome
                        </span>
                        <span class="variable-badge" onclick="insertVariable('participant.full_name')" title="Nome completo del partecipante">
                            <i class="bi bi-person-badge"></i> Nome Completo
                        </span>
                    </div>
                    <textarea class="form-control template-editor" id="editEmailBody" rows="8"
                              placeholder="Scrivi il testo introduttivo dell'email. I bottoni del survey verranno aggiunti automaticamente in fondo.">${step.config.body_template || ''}</textarea>
                    <div class="form-text">I bottoni di risposta al survey verranno aggiunti automaticamente sotto questo testo.</div>
                </div>
                <hr>
                <h6><i class="bi bi-ui-checks"></i> Configurazione Survey</h6>
                <div class="mb-3">
                    <label class="form-label">Domanda</label>
                    <input type="text" class="form-control" id="editSurveyQuestion"
                           value="${step.config.question || ''}"
                           placeholder="es. Come valuti l'evento?">
                </div>
                <div class="mb-3">
                    <label class="form-label">Tipo di risposta</label>
                    <select class="form-select" id="editSurveyResponseType" onchange="toggleSurveyType()">
                        <option value="choices" ${step.config.response_type === 'choices' ? 'selected' : ''}>Scelta singola (bottoni)</option>
                        <option value="scale" ${step.config.response_type === 'scale' ? 'selected' : ''}>Scala numerica</option>
                    </select>
                </div>
                <div id="surveyChoicesSection" ${step.config.response_type === 'scale' ? 'style="display:none"' : ''}>
                    <label class="form-label">Opzioni</label>
                    <div id="surveyChoicesList">${choicesHtml}</div>
                    <button type="button" class="btn btn-sm btn-outline-primary mt-1" onclick="addSurveyChoice()">
                        <i class="bi bi-plus"></i> Aggiungi opzione
                    </button>
                </div>
                <div id="surveyScaleSection" ${step.config.response_type !== 'scale' ? 'style="display:none"' : ''}>
                    <div class="mb-3">
                        <label class="form-label">Scala da 1 a</label>
                        <select class="form-select" id="editSurveyScaleMax">
                            <option value="5" ${(step.config.scale_max || 5) == 5 ? 'selected' : ''}>5</option>
                            <option value="10" ${(step.config.scale_max || 5) == 10 ? 'selected' : ''}>10</option>
                        </select>
                    </div>
                </div>
                <div class="form-check mt-3">
                    <input class="form-check-input" type="checkbox" id="editSurveyAllowComment"
                           ${step.config.allow_comment ? 'checked' : ''}>
                    <label class="form-check-label" for="editSurveyAllowComment">
                        Abilita campo commento/feedback
                    </label>
                </div>
                <div class="mb-3 mt-3">
                    <label class="form-label">Ritardo (ore dopo lo step precedente)</label>
                    <input type="number" class="form-control" id="editSurveyDelay"
                           value="${step.config.delay_hours || 0}" min="0">
                </div>
            `;
        case 'human_approval':
            return common + `
                <div class="mb-3">
                    <label class="form-label">Approver Email *</label>
                    <textarea class="form-control" id="editApproverEmail" rows="2"
                              placeholder="manager@example.com, director@example.com">${step.config.approver_email || ''}</textarea>
                    <div class="form-text">Separa più email con virgola. Il primo che risponde decide per tutti.</div>
                </div>
                <div class="mb-3">
                    <label class="form-label">Message to Approver</label>
                    <textarea class="form-control" id="editApprovalMessage" rows="3"
                              placeholder="Please review and approve this participant...">${step.config.approval_message || ''}</textarea>
                    <div class="form-text">This message will be shown in the approval email. You can use {{ participant.full_name }}, {{ workflow_name }}.</div>
                </div>
                <hr>
                <div class="row">
                    <div class="col-md-6 mb-3">
                        <label class="form-label text-success"><i class="bi bi-check-circle"></i> If Approved</label>
                        <select class="form-select" id="editIfApproved" onchange="toggleApprovalJump('Approved')">
                            <option value="continue" ${(step.config.if_approved || 'continue') === 'continue' ? 'selected' : ''}>Continue to next step</option>
                            <option value="jump" ${step.config.if_approved === 'jump' ? 'selected' : ''}>Jump to step...</option>
                            <option value="complete" ${step.config.if_approved === 'complete' ? 'selected' : ''}>Complete workflow</option>
                        </select>
                        <div id="jumpApprovedRow" class="mt-2" ${step.config.if_approved === 'jump' ? '' : 'style="display:none"'}>
                            <select class="form-select form-select-sm" id="editIfApprovedStep">
                                ${buildStepOptions(step.config.if_approved_step, index)}
                            </select>
                        </div>
                    </div>
                    <div class="col-md-6 mb-3">
                        <label class="form-label text-danger"><i class="bi bi-x-circle"></i> If Rejected</label>
                        <select class="form-select" id="editIfRejected" onchange="toggleApprovalJump('Rejected')">
                            <option value="stop" ${(step.config.if_rejected || 'stop') === 'stop' ? 'selected' : ''}>Stop workflow</option>
                            <option value="continue" ${step.config.if_rejected === 'continue' ? 'selected' : ''}>Continue to next step</option>
                            <option value="jump" ${step.config.if_rejected === 'jump' ? 'selected' : ''}>Jump to step...</option>
                        </select>
                        <div id="jumpRejectedRow" class="mt-2" ${step.config.if_rejected === 'jump' ? '' : 'style="display:none"'}>
                            <select class="form-select form-select-sm" id="editIfRejectedStep">
                                ${buildStepOptions(step.config.if_rejected_step, index)}
                            </select>
                        </div>
                    </div>
                </div>
                <hr>
                <div class="mb-3">
                    <label class="form-label">Timeout (hours)</label>
                    <input type="number" class="form-control" id="editApprovalTimeout"
                           value="${step.config.timeout_hours || 48}" min="1">
                    <div class="form-text">How long to wait for approval before taking the timeout action.</div>
                </div>
                <div class="mb-3">
                    <label class="form-label">On Timeout</label>
                    <select class="form-select" id="editOnTimeout">
                        <option value="reject" ${(step.config.on_timeout || 'reject') === 'reject' ? 'selected' : ''}>Treat as Rejected</option>
                        <option value="approve" ${step.config.on_timeout === 'approve' ? 'selected' : ''}>Treat as Approved</option>
                        <option value="remind" ${step.config.on_timeout === 'remind' ? 'selected' : ''}>Send reminder email</option>
                    </select>
                </div>
                <div class="mb-3">
                    <label class="form-label">Delay (hours after previous step)</label>
                    <input type="number" class="form-control" id="editApprovalDelay"
                           value="${step.config.delay_hours || 0}" min="0">
                </div>
            `;
        case 'export_data':
            return common + `
                <div class="mb-3">
                    <label class="form-label">Export Format</label>
                    <select class="form-select" id="editExportFormat">
                        <option value="csv" ${step.config.format === 'csv' ? 'selected' : ''}>CSV</option>
                        <option value="excel" ${step.config.format === 'excel' ? 'selected' : ''}>Excel</option>
                    </select>
                </div>
                
                <div class="mb-3">
                    <label class="form-label">Send To Email</label>
                    <input type="email" class="form-control" id="editExportSendTo" 
                           value="${step.config.send_to || ''}" 
                           placeholder="admin@example.com">
                    <small class="text-muted">CSV will be sent as email attachment</small>
                </div>
                
                <div class="form-check mb-3">
                    <input class="form-check-input" type="checkbox" id="editExportSaveLocal" 
                           ${step.config.save_local ? 'checked' : ''}>
                    <label class="form-check-label" for="editExportSaveLocal">
                        Also save to server filesystem
                    </label>
                </div>
                
                <div class="alert alert-info">
                    <small><i class="bi bi-info-circle"></i> 
                    <strong>Export includes:</strong><br>
                    • All workflow participants<br>
                    • Basic info (name, email, status)<br>
                    • All collected data from forms<br>
                    • Timestamps (created, last interaction)
                    </small>
                </div>
            `;
    }
}

// Summernote WYSIWYG editor for email body
let lastFocusedIsSubject = false;

function initEmailEditor() {
    const $editor = $('#editEmailBody');
    if ($editor.length && $.fn.summernote) {
        $editor.summernote({
            height: 250,
            placeholder: 'Scrivi il testo della tua email qui...',
            dialogsInBody: true,
            disableDragAndDrop: true,
            toolbar: [
                ['style', ['style']],
                ['font', ['bold', 'italic', 'underline', 'strikethrough', 'clear']],
                ['color', ['color']],
                ['para', ['ul', 'ol', 'paragraph']],
                ['table', ['table']],
                ['insert', ['link', 'picture', 'hr']],
                ['view', ['fullscreen', 'codeview']]
            ],
            styleTags: ['p', 'h1', 'h2', 'h3', 'h4'],
            callbacks: {
                onFocus: function() { lastFocusedIsSubject = false; }
            }
        });
    }
    // Track subject focus
    const subjectField = document.getElementById('editEmailSubject');
    if (subjectField) {
        subjectField.addEventListener('focus', function() { lastFocusedIsSubject = true; });
    }
}

function destroyEmailEditor() {
    const $editor = $('#editEmailBody');
    if ($editor.length && $.fn.summernote && $editor.hasClass('note-editor') || $editor.next('.note-editor').length) {
        try { $editor.summernote('destroy'); } catch(e) {}
    }
}

function insertVariable(variable) {
    const tag = `{{ ${variable} }}`;
    if (lastFocusedIsSubject) {
        const field = document.getElementById('editEmailSubject');
        if (field) {
            const cursorPos = field.selectionStart;
            const textBefore = field.value.substring(0, cursorPos);
            const textAfter = field.value.substring(cursorPos);
            field.value = textBefore + tag + textAfter;
            field.focus();
            field.selectionStart = field.selectionEnd = cursorPos + tag.length;
        }
    } else {
        const $editor = $('#editEmailBody');
        if ($editor.length && $.fn.summernote) {
            $editor.summernote('editor.insertText', tag);
        }
    }
}

// --- Attachment helpers ---
function formatFileSize(bytes) {
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1048576) return (bytes / 1024).toFixed(1) + ' KB';
    return (bytes / 1048576).toFixed(1) + ' MB';
}

function renderAttachmentList(attachments) {
    if (!attachments || attachments.length === 0) return '';
    return attachments.map(a => `
        <div class="attachment-item d-flex align-items-center gap-2 mb-1 p-2 rounded" style="background:var(--md-sys-color-surface-variant, #f0ebe3)">
            <i class="bi bi-file-earmark"></i>
            <span class="flex-grow-1 text-truncate" style="font-size:13px">${a.filename}</span>
            <small class="text-muted">${formatFileSize(a.size)}</small>
            <button type="button" class="btn btn-sm btn-link text-danger p-0" onclick="removeAttachment(${a.id})" title="Rimuovi">
                <i class="bi bi-x-lg"></i>
            </button>
        </div>
    `).join('');
}

function handleAttachmentUpload(files) {
    if (!files || files.length === 0) return;
    var step = workflowSteps[editingStepIndex];
    if (!step.config.attachments) step.config.attachments = [];

    Array.from(files).forEach(function(file) {
        var formData = new FormData();
        formData.append('file', file);

        // Show uploading state
        var list = document.getElementById('attachmentList');
        var tempId = 'uploading_' + Date.now();
        list.insertAdjacentHTML('beforeend', `
            <div id="${tempId}" class="attachment-item d-flex align-items-center gap-2 mb-1 p-2 rounded" style="background:#fff3cd">
                <span class="spinner-border spinner-border-sm"></span>
                <span class="flex-grow-1" style="font-size:13px">${file.name}</span>
            </div>
        `);

        fetch('/admin/api/attachments', {
            method: 'POST',
            body: formData
        })
        .then(function(r) { return r.json().then(function(d) { return {ok: r.ok, data: d}; }); })
        .then(function(res) {
            var el = document.getElementById(tempId);
            if (!res.ok) {
                if (el) el.innerHTML = `<i class="bi bi-exclamation-triangle text-danger"></i> <span style="font-size:13px">${file.name}: ${res.data.error}</span>`;
                setTimeout(function() { if (el) el.remove(); }, 3000);
                return;
            }
            step.config.attachments.push(res.data);
            if (el) el.remove();
            document.getElementById('attachmentList').innerHTML = renderAttachmentList(step.config.attachments);
        })
        .catch(function(err) {
            var el = document.getElementById(tempId);
            if (el) el.innerHTML = `<i class="bi bi-exclamation-triangle text-danger"></i> <span style="font-size:13px">Errore upload</span>`;
        });
    });

    // Reset input
    document.getElementById('attachmentFileInput').value = '';
}

function removeAttachment(attachmentId) {
    var step = workflowSteps[editingStepIndex];
    if (!step || !step.config.attachments) return;

    fetch('/admin/api/attachments/' + attachmentId, { method: 'DELETE' });
    step.config.attachments = step.config.attachments.filter(function(a) { return a.id !== attachmentId; });
    document.getElementById('attachmentList').innerHTML = renderAttachmentList(step.config.attachments);
}

// Init drag-drop for attachment zone
function initAttachmentDropZone() {
    var zone = document.getElementById('attachmentDropZone');
    if (!zone) return;
    zone.addEventListener('dragover', function(e) { e.preventDefault(); zone.style.borderColor = '#8B6914'; zone.style.background = '#fdf6e3'; });
    zone.addEventListener('dragleave', function(e) { zone.style.borderColor = ''; zone.style.background = ''; });
    zone.addEventListener('drop', function(e) {
        e.preventDefault();
        zone.style.borderColor = '';
        zone.style.background = '';
        handleAttachmentUpload(e.dataTransfer.files);
    });
}

// Populate fields from preceding landing page steps in the canvas
function populatFieldsFromPrecedingLanding(selectId, currentValue, loadingId, currentIndex) {
    var select = document.getElementById(selectId);
    var loading = loadingId ? document.getElementById(loadingId) : null;
    if (!select) return;

    select.innerHTML = '<option value="">-- Select field --</option>';

    // Look at steps before currentIndex that have landing config
    var fields = [];
    var seen = {};
    for (var i = currentIndex - 1; i >= 0; i--) {
        var s = workflowSteps[i];
        if (!s) continue;

        // Check if step has landing page with fields (from gjs_data stored in config)
        // When loaded from DB, landing fields are available via API
        // When in-canvas (not saved), check config.has_landing
        if (s.config && s.config.has_landing) {
            // Found a landing step — try to load its fields from API if workflow is saved
            if (window._currentWorkflowId) {
                populateLandingFieldSelect(selectId, currentValue, loadingId);
                return;
            }
        }
    }

    // Fallback: try loading from API for saved workflows
    if (window._currentWorkflowId) {
        populateLandingFieldSelect(selectId, currentValue, loadingId);
        return;
    }

    // No fields found
    select.innerHTML += '<option value="" disabled>Save the workflow first, then configure landing page fields</option>';
    if (loading) {
        loading.innerHTML = '<i class="bi bi-info-circle"></i> Save the workflow and configure a landing page before this step.';
        loading.style.display = '';
    }
}

// Approval helpers
function toggleApprovalJump(which) {
    var action = document.getElementById('editIf' + which).value;
    var row = document.getElementById('jump' + which + 'Row');
    if (row) row.style.display = action === 'jump' ? 'block' : 'none';
}

// Survey helpers
function toggleSurveyType() {
    var type = document.getElementById('editSurveyResponseType').value;
    document.getElementById('surveyChoicesSection').style.display = type === 'choices' ? 'block' : 'none';
    document.getElementById('surveyScaleSection').style.display = type === 'scale' ? 'block' : 'none';
}

function addSurveyChoice() {
    var list = document.getElementById('surveyChoicesList');
    var count = list.querySelectorAll('.input-group').length + 1;
    var div = document.createElement('div');
    div.className = 'input-group input-group-sm mb-1';
    div.innerHTML = '<input type="text" class="form-control survey-choice-input" value="" placeholder="Opzione ' + count + '">' +
        '<button class="btn btn-outline-danger" type="button" onclick="this.closest(\'.input-group\').remove()"><i class="bi bi-x"></i></button>';
    list.appendChild(div);
    div.querySelector('input').focus();
}

// Update wait until form based on type
function buildStepOptions(selectedOrder, currentIndex) {
    var html = '<option value="0">-- Seleziona step --</option>';
    workflowSteps.forEach(function(s, i) {
        if (i === currentIndex) return; // Non mostrare se stesso
        var sel = (parseInt(selectedOrder) === s.order) ? ' selected' : '';
        html += '<option value="' + s.order + '"' + sel + '>Step ' + s.order + ': ' + s.name + '</option>';
    });
    return html;
}

function toggleJumpStep(which) {
    var action = document.getElementById('editConditionIf' + which).value;
    var row = document.getElementById('jump' + which + 'Row');
    if (row) row.style.display = action === 'jump' ? 'block' : 'none';
}

function onConditionSourceChange() {
    var source = document.getElementById('editConditionSource').value;
    var sel = document.getElementById('editConditionField');
    sel.innerHTML = '<option value="">-- Seleziona campo --</option>';
    var loading = document.getElementById('conditionFieldLoading');
    if (loading) loading.style.display = 'block';

    if (source === 'participant') {
        ['first_name','last_name','email','phone','status'].forEach(function(f) {
            sel.innerHTML += '<option value="' + f + '">' + f + '</option>';
        });
        if (loading) loading.style.display = 'none';
    } else if (source === 'collected_data') {
        // Carica campi landing page
        var wfId = window._currentWorkflowId;
        if (wfId) {
            fetch('/api/landing-fields/workflow/' + wfId)
            .then(function(r) { return r.json(); })
            .then(function(data) {
                (data.fields || []).forEach(function(f) {
                    sel.innerHTML += '<option value="' + f.name + '">' + (f.label || f.name) + '</option>';
                });
                if (loading) loading.style.display = 'none';
            }).catch(function() { if (loading) loading.style.display = 'none'; });
        } else {
            if (loading) loading.innerHTML = 'Salva prima il workflow';
        }
    } else {
        // sabaform_data — campi comuni
        ['company','gender','birth_date','nucleo','doc_type','doc_number','doc_expiry','volo_arrivo','volo_partenza','notes','first_name','last_name','email','phone'].forEach(function(f) {
            sel.innerHTML += '<option value="' + f + '">' + f + '</option>';
        });
        if (loading) loading.style.display = 'none';
    }
}

function updateWaitUntilForm() {
    const waitType = document.getElementById('editWaitType').value;

    document.getElementById('waitUntilDelayFields').style.display = waitType === 'delay_hours' ? 'block' : 'none';
    document.getElementById('waitUntilDateFields').style.display = waitType === 'date' ? 'block' : 'none';
    document.getElementById('waitUntilDayFields').style.display = waitType === 'day_of_week' ? 'block' : 'none';
    document.getElementById('waitUntilTimeFields').style.display = waitType === 'delay_hours' ? 'none' : 'block';
}

// Update goal check form based on type
function updateGoalCheckForm() {
    const goalType = document.getElementById('editGoalType').value;
    
    document.getElementById('goalFieldName').style.display = 
        ['field_filled', 'field_equals'].includes(goalType) ? 'block' : 'none';
    document.getElementById('goalFieldValue').style.display = 
        goalType === 'field_equals' ? 'block' : 'none';
    document.getElementById('goalStatusValue').style.display =
        goalType === 'status_equals' ? 'block' : 'none';
}

// Collect landing page fields from the workflow via dedicated API
function collectLandingFields(callback) {
    const workflowId = window._currentWorkflowId;

    if (!workflowId) {
        console.warn('No workflow ID — cannot load landing fields');
        callback([]);
        return;
    }

    fetch(`/api/landing-fields/workflow/${workflowId}`)
        .then(r => r.json())
        .then(data => {
            console.log('Landing fields for workflow', workflowId, data);
            callback(data.fields || []);
        })
        .catch(err => {
            console.warn('Error loading landing fields', err);
            callback([]);
        });
}

// Populate a <select> with landing fields
function populateLandingFieldSelect(selectId, currentValue, loadingId) {
    collectLandingFields(function(fields) {
        const select = document.getElementById(selectId);
        const loading = loadingId ? document.getElementById(loadingId) : null;
        if (!select) return;

        // Clear existing options (keep the first placeholder)
        select.innerHTML = '<option value="">-- Seleziona campo --</option>';

        if (fields.length === 0) {
            select.innerHTML += '<option value="" disabled>Nessun campo trovato</option>';
            if (loading) loading.innerHTML = '<i class="bi bi-exclamation-triangle"></i> Nessun campo landing trovato. Assicurati di aver salvato il workflow e configurato almeno una landing page con dei campi.';
            if (loading) loading.style.display = '';
        } else {
            fields.forEach(f => {
                const opt = document.createElement('option');
                opt.value = f.name;
                opt.textContent = f.label + (f.label !== f.name ? ` (${f.name})` : '');
                if (f.name === currentValue) opt.selected = true;
                select.appendChild(opt);
            });
            if (loading) loading.style.display = 'none';
        }
    });
}

// Save step edit
function saveStepEdit() {
    const step = workflowSteps[editingStepIndex];
    
    step.name = document.getElementById('editStepName').value;
    
    switch(step.type) {
        case 'email':
            step.config.subject = document.getElementById('editEmailSubject').value;
            // Read from Summernote editor
            const $body = $('#editEmailBody');
            step.config.body_template = ($body.length && $.fn.summernote) ? $body.summernote('code') : document.getElementById('editEmailBody').value;
            step.config.delay_hours = parseInt(document.getElementById('editEmailDelay').value);
            step.config.has_landing = document.getElementById('editHasLanding').checked;
            destroyEmailEditor();
            break;
        case 'delay':
            step.config.hours = parseInt(document.getElementById('editDelayHours').value);
            break;
        case 'wait_until':
            step.config.wait_type = document.getElementById('editWaitType').value;
            step.config.target_date = document.getElementById('editTargetDate')?.value || '';
            step.config.target_time = document.getElementById('editTargetTime')?.value || '09:00';
            step.config.target_day = document.getElementById('editTargetDay')?.value || '';
            step.config.delay_hours = parseInt(document.getElementById('editWaitDelayHours')?.value) || 0;
            break;
        case 'goal_check':
            step.config.goal = document.getElementById('editGoalType').value;
            step.config.if_met = document.getElementById('editIfMet').value;
            step.config.if_not_met = document.getElementById('editIfNotMet').value;
            step.config.field_name = document.getElementById('editGoalFieldName')?.value || '';
            step.config.field_value = document.getElementById('editGoalFieldValue')?.value || '';
            step.config.status_value = document.getElementById('editGoalStatusValue')?.value || 'completed';
            break;
        case 'condition':
            step.config.field_source = document.getElementById('editConditionSource').value;
            step.config.field = document.getElementById('editConditionField').value || document.getElementById('editConditionFieldCustom').value;
            step.config.operator = document.getElementById('editConditionOperator').value;
            step.config.value = document.getElementById('editConditionValue').value;
            step.config.if_true = document.getElementById('editConditionIfTrue').value;
            step.config.if_true_step = parseInt(document.getElementById('editConditionIfTrueStep')?.value) || 0;
            step.config.if_false = document.getElementById('editConditionIfFalse').value;
            step.config.if_false_step = parseInt(document.getElementById('editConditionIfFalseStep')?.value) || 0;
            break;
        case 'survey':
            step.config.subject = document.getElementById('editSurveySubject').value;
            const $surveyBody = $('#editEmailBody');
            step.config.body_template = ($surveyBody.length && $.fn.summernote) ? $surveyBody.summernote('code') : document.getElementById('editEmailBody').value;
            step.config.delay_hours = parseInt(document.getElementById('editSurveyDelay').value);
            step.config.question = document.getElementById('editSurveyQuestion').value;
            step.config.response_type = document.getElementById('editSurveyResponseType').value;
            step.config.scale_max = parseInt(document.getElementById('editSurveyScaleMax')?.value || 5);
            step.config.allow_comment = document.getElementById('editSurveyAllowComment').checked;
            // Collect choices
            var choiceInputs = document.querySelectorAll('.survey-choice-input');
            step.config.choices = [];
            choiceInputs.forEach(function(input) {
                var v = input.value.trim();
                if (v) step.config.choices.push(v);
            });
            destroyEmailEditor();
            break;
        case 'human_approval':
            step.config.approver_email = document.getElementById('editApproverEmail').value;
            step.config.approval_message = document.getElementById('editApprovalMessage').value;
            step.config.timeout_hours = parseInt(document.getElementById('editApprovalTimeout').value) || 48;
            step.config.on_timeout = document.getElementById('editOnTimeout').value;
            step.config.delay_hours = parseInt(document.getElementById('editApprovalDelay').value) || 0;
            step.config.if_approved = document.getElementById('editIfApproved').value;
            step.config.if_approved_step = parseInt(document.getElementById('editIfApprovedStep')?.value) || 0;
            step.config.if_rejected = document.getElementById('editIfRejected').value;
            step.config.if_rejected_step = parseInt(document.getElementById('editIfRejectedStep')?.value) || 0;
            break;
        case 'export_data':
            step.config.format = document.getElementById('editExportFormat').value;
            step.config.send_to = document.getElementById('editExportSendTo').value;
            step.config.save_local = document.getElementById('editExportSaveLocal').checked;
            break;
    }
    
    renderCanvas();
    bootstrap.Modal.getInstance(document.getElementById('stepEditModal')).hide();
}

// Delete step
function deleteStep(index) {
    if (!confirm('Delete this step?')) return;
    
    workflowSteps.splice(index, 1);
    // Reorder
    workflowSteps.forEach((step, i) => {
        step.order = i + 1;
    });
    renderCanvas();
}

// Move step up
function moveStepUp(index) {
    if (index === 0) return; // Already at top
    
    // Swap with previous
    const temp = workflowSteps[index - 1];
    workflowSteps[index - 1] = workflowSteps[index];
    workflowSteps[index] = temp;
    
    // Reorder all steps
    workflowSteps.forEach((step, i) => {
        step.order = i + 1;
    });
    
    // Re-render canvas
    renderCanvas();
    
    console.log('Moved step up', workflowSteps.map(s => s.order));
}

// Move step down
function moveStepDown(index) {
    if (index === workflowSteps.length - 1) return; // Already at bottom
    
    // Swap with next
    const temp = workflowSteps[index + 1];
    workflowSteps[index + 1] = workflowSteps[index];
    workflowSteps[index] = temp;
    
    // Reorder all steps
    workflowSteps.forEach((step, i) => {
        step.order = i + 1;
    });
    
    // Re-render canvas
    renderCanvas();
    
    console.log('Moved step down', workflowSteps.map(s => s.order));
}

// SortableJS-based reordering
let sortableInstance = null;

function initStepSortable() {
    const container = document.getElementById('stepsSortContainer');
    if (!container || typeof Sortable === 'undefined') return;

    // Destroy previous instance
    if (sortableInstance) {
        sortableInstance.destroy();
        sortableInstance = null;
    }

    sortableInstance = Sortable.create(container, {
        animation: 200,
        handle: '.step-drag-handle',
        draggable: '.step-sort-item',
        ghostClass: 'step-sortable-ghost',
        chosenClass: 'step-sortable-chosen',
        dragClass: 'step-sortable-drag',
        onEnd: function(evt) {
            if (evt.oldIndex === evt.newIndex) return;

            // Reorder based on new DOM order
            var item = workflowSteps.splice(evt.oldIndex, 1)[0];
            workflowSteps.splice(evt.newIndex, 0, item);

            workflowSteps.forEach(function(step, i) {
                step.order = i + 1;
            });

            renderCanvas();
        }
    });
}

// Wizard navigation
function nextStep() {
    const wizardSteps = document.querySelectorAll('.wizard-step');
    const contentSteps = document.querySelectorAll('.wizard-content');
    
    if (currentStep < 3) {
        // Validation
        if (currentStep === 1) {
            const name = document.getElementById('workflowName').value;
            if (!name) {
                alert('Please enter a workflow name');
                return;
            }
        }

        if (currentStep === 2 && workflowSteps.length === 0) {
            alert('Please add at least one step to the workflow');
            return;
        }

        // Hide current
        contentSteps[currentStep - 1].style.display = 'none';
        wizardSteps[currentStep - 1].classList.remove('active');
        wizardSteps[currentStep - 1].classList.add('completed');

        // Show next
        currentStep++;
        contentSteps[currentStep - 1].style.display = 'block';
        wizardSteps[currentStep - 1].classList.add('active');

        // Generate review if step 3
        if (currentStep === 3) {
            generateReview();
        }
    }
}

function prevStep() {
    const wizardSteps = document.querySelectorAll('.wizard-step');
    const contentSteps = document.querySelectorAll('.wizard-content');
    
    if (currentStep > 1) {
        contentSteps[currentStep - 1].style.display = 'none';
        wizardSteps[currentStep - 1].classList.remove('active');
        
        currentStep--;
        contentSteps[currentStep - 1].style.display = 'block';
        wizardSteps[currentStep - 1].classList.remove('completed');
        wizardSteps[currentStep - 1].classList.add('active');
    }
}

// Generate review
function generateReview() {
    const name = document.getElementById('workflowName').value;
    const description = document.getElementById('workflowDescription').value;
    const status = document.getElementById('workflowStatus').value;
    
    let html = `
        <h5>Workflow Details</h5>
        <dl class="row">
            <dt class="col-sm-3">Name:</dt>
            <dd class="col-sm-9">${name}</dd>
            <dt class="col-sm-3">Description:</dt>
            <dd class="col-sm-9">${description || '<em class="text-muted">None</em>'}</dd>
            <dt class="col-sm-3">Status:</dt>
            <dd class="col-sm-9"><span class="status-badge status-${status}">${status}</span></dd>
            <dt class="col-sm-3">Steps:</dt>
            <dd class="col-sm-9">${workflowSteps.length}</dd>
        </dl>
        
        <h5 class="mt-4">Workflow Steps</h5>
        <ol class="list-group list-group-numbered">
    `;
    
    workflowSteps.forEach(step => {
        html += `
            <li class="list-group-item">
                <strong><i class="bi bi-${step.type === 'email' ? 'envelope' : step.type === 'delay' ? 'clock' : 'shuffle'}"></i> ${step.name}</strong><br>
                <small class="text-muted">${renderStepSummary(step)}</small>
            </li>
        `;
    });
    
    html += '</ol>';
    
    document.getElementById('reviewContent').innerHTML = html;
}

// Save workflow
function saveWorkflow() {
    const data = {
        name: document.getElementById('workflowName').value,
        description: document.getElementById('workflowDescription').value,
        status: document.getElementById('workflowStatus').value,
        token_expiration_hours: parseInt(document.getElementById('tokenExpiration').value) || null,
        sabaform_event_id: selectedSabaformEventId || null,
        sabaform_event_name: selectedSabaformEventName || null,
        participants: importedParticipants,
        steps: workflowSteps.map(step => {
            const stepData = {
                order: step.order,
                name: step.name,
                type: step.type,
                subject: step.config.subject || '',
                body_template: step.config.body_template || '',
                delay_hours: step.config.delay_hours || 0,
                landing_page_config: step.config.has_landing ? {} : null
            };
            
            // For wait_until steps, store config in skip_conditions
            if (step.type === 'wait_until') {
                stepData.skip_conditions = {
                    wait_type: step.config.wait_type,
                    target_date: step.config.target_date,
                    target_time: step.config.target_time,
                    target_day: step.config.target_day,
                    delay_hours: step.config.delay_hours
                };
                if (step.config.wait_type === 'delay_hours') {
                    stepData.delay_hours = step.config.delay_hours;
                }
            }
            
            // For goal_check steps, store config in skip_conditions
            if (step.type === 'goal_check') {
                stepData.skip_conditions = {
                    goal: step.config.goal,
                    if_met: step.config.if_met,
                    if_not_met: step.config.if_not_met,
                    field_name: step.config.field_name,
                    field_value: step.config.field_value,
                    status_value: step.config.status_value
                };
            }
            
            // For condition steps, store config in skip_conditions
            if (step.type === 'condition') {
                stepData.skip_conditions = {
                    field_source: step.config.field_source,
                    field: step.config.field,
                    operator: step.config.operator,
                    value: step.config.value,
                    if_true: step.config.if_true,
                    if_true_step: step.config.if_true_step,
                    if_false: step.config.if_false,
                    if_false_step: step.config.if_false_step
                };
            }

            // For email steps, store has_landing and attachment IDs in skip_conditions
            if (step.type === 'email') {
                stepData.skip_conditions = {
                    has_landing: !!step.config.has_landing,
                    attachment_ids: (step.config.attachments || []).map(a => a.id)
                };
            }

            // For survey steps, store config in skip_conditions
            if (step.type === 'survey') {
                stepData.skip_conditions = {
                    question: step.config.question,
                    response_type: step.config.response_type,
                    choices: step.config.choices,
                    scale_max: step.config.scale_max,
                    allow_comment: step.config.allow_comment
                };
            }

            // For human_approval steps, store config in skip_conditions
            if (step.type === 'human_approval') {
                stepData.skip_conditions = {
                    approver_email: step.config.approver_email,
                    approval_message: step.config.approval_message,
                    timeout_hours: step.config.timeout_hours,
                    on_timeout: step.config.on_timeout,
                    if_approved: step.config.if_approved,
                    if_approved_step: step.config.if_approved_step,
                    if_rejected: step.config.if_rejected,
                    if_rejected_step: step.config.if_rejected_step
                };
            }

            // For export_data steps, store config in skip_conditions
            if (step.type === 'export_data') {
                stepData.skip_conditions = {
                    format: step.config.format,
                    send_to: step.config.send_to,
                    save_local: step.config.save_local
                };
            }
            
            return stepData;
        })
    };
    
    var isEdit = !!window._currentWorkflowId;
    var url = isEdit ? '/api/workflows/' + window._currentWorkflowId : '/api/workflows';
    var method = isEdit ? 'PUT' : 'POST';

    fetch(url, {
        method: method,
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(data)
    })
    .then(response => response.json())
    .then(result => {
        if (result.error) {
            alert('Errore: ' + result.error);
            return;
        }
        // Se è un nuovo workflow, aggiorna l'URL senza ricaricare per restare nella pagina
        if (!isEdit && result.id) {
            window._currentWorkflowId = result.id;
            history.replaceState(null, '', '/admin/workflows/' + result.id + '/edit');
        }
        // Ricarica gli step dal server per avere i nuovi ID (dopo save vengono ricreati)
        var wfId = result.id || window._currentWorkflowId;
        if (wfId) {
            fetch('/api/workflows/' + wfId)
            .then(function(r) { return r.json(); })
            .then(function(wf) {
                if (wf.steps) {
                    wf.steps.forEach(function(serverStep) {
                        var local = workflowSteps.find(function(s) { return s.order === serverStep.order; });
                        if (local) local.id = serverStep.id;
                    });
                }
            }).catch(function(){});
        }
        alert('Workflow salvato!');
    })
    .catch(error => {
        alert('Errore salvataggio: ' + error);
    });
}

// =============================================
// SABAFORM EVENTS
// =============================================
var selectedSabaformEventId = null;
var selectedSabaformEventName = null;
var importedParticipants = [];

function loadSabaformEvents() {
    var sel = document.getElementById('sabaformEvent');
    if (!sel) return;

    sel.innerHTML = '<option value="">Caricamento...</option>';

    fetch('/api/sabaform/events')
        .then(function(r) { return r.json(); })
        .then(function(data) {
            sel.innerHTML = '<option value="">-- Nessun evento collegato --</option>';
            (data.events || []).forEach(function(ev) {
                var opt = document.createElement('option');
                opt.value = ev.id;
                opt.textContent = ev.name + (ev.client ? ' — ' + ev.client : '') +
                    ' (' + ev.participant_count + ' partecipanti)' +
                    (ev.start_date ? ' — ' + ev.start_date : '');
                opt.dataset.name = ev.name;
                sel.appendChild(opt);
            });

            // Riseleziona se c'era un valore
            if (selectedSabaformEventId) {
                sel.value = selectedSabaformEventId;
            }
        })
        .catch(function() {
            sel.innerHTML = '<option value="">Errore caricamento eventi</option>';
        });
}

function onEventSelected() {
    var sel = document.getElementById('sabaformEvent');
    selectedSabaformEventId = sel.value ? parseInt(sel.value) : null;
    var opt = sel.options[sel.selectedIndex];
    selectedSabaformEventName = opt && opt.dataset.name ? opt.dataset.name : null;

    // Mostra/nascondi bottone import
    var btn = document.getElementById('btnImportWizard');
    if (btn) btn.style.display = selectedSabaformEventId ? '' : 'none';
}

function importFromEvent() {
    if (!selectedSabaformEventId) return;

    var btn = document.getElementById('btnImportWizard');
    btn.disabled = true;
    btn.innerHTML = '<i class="bi bi-hourglass-split"></i> Caricamento...';

    fetch('/api/sabaform/events/' + selectedSabaformEventId + '/participants')
        .then(function(r) { return r.json(); })
        .then(function(data) {
            var participants = data.participants || [];
            if (participants.length === 0) {
                alert('Nessun partecipante trovato nell\'evento.');
                return;
            }

            // Aggiungi solo quelli non già importati (per nome+cognome)
            var existingKeys = importedParticipants.map(function(p) { return (p.first_name + ' ' + p.last_name).trim(); });
            var added = 0;
            participants.forEach(function(p) {
                var first = p.first_name || '';
                var last = p.last_name || '';
                var key = (first + ' ' + last).trim();
                if (!key) return;
                if (existingKeys.indexOf(key) !== -1) return;
                // Salva tutti i dati originali da Saba Form
                var sabaform_data = {};
                for (var k in p) {
                    if (p[k] !== null && p[k] !== '') sabaform_data[k] = p[k];
                }
                importedParticipants.push({
                    first_name: first,
                    last_name: last,
                    email: p.email || '',
                    phone: p.phone || '',
                    sabaform_data: sabaform_data
                });
                existingKeys.push(key);
                added++;
            });

            renderImportedParticipants();
            alert('Importati ' + added + ' partecipanti (' + (participants.length - added) + ' già presenti/vuoti).');
        })
        .catch(function(e) {
            alert('Errore: ' + e);
        })
        .finally(function() {
            btn.disabled = false;
            btn.innerHTML = '<i class="bi bi-download"></i> Importa partecipanti';
        });
}

function renderImportedParticipants() {
    var area = document.getElementById('importedParticipantsArea');
    var tbody = document.getElementById('importedParticipantsBody');
    var count = document.getElementById('importedCount');
    if (!area || !tbody) return;

    if (importedParticipants.length === 0) {
        area.style.display = 'none';
        return;
    }

    area.style.display = 'block';
    count.textContent = importedParticipants.length;
    tbody.innerHTML = '';
    importedParticipants.forEach(function(p) {
        var tr = document.createElement('tr');
        tr.innerHTML = '<td>' + escHtml(p.first_name) + '</td><td>' + escHtml(p.last_name) + '</td><td>' + escHtml(p.email) + '</td><td>' + escHtml(p.phone) + '</td>';
        tbody.appendChild(tr);
    });
}

function clearImportedParticipants() {
    if (!confirm('Svuotare la lista partecipanti importati?')) return;
    importedParticipants = [];
    renderImportedParticipants();
}

function escHtml(s) {
    return String(s || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

// Auto-load events on page load
document.addEventListener('DOMContentLoaded', function() {
    loadSabaformEvents();
});

// Utility
function capitalize(str) {
    return str.charAt(0).toUpperCase() + str.slice(1);
}

// =============================================
// OPEN LANDING BUILDER
// =============================================
function openLandingBuilder(index) {
    var step = workflowSteps[index];
    if (!step) return;

    // Step già salvato nel DB (id numerico dal server)
    var workflowId = window._currentWorkflowId;
    if (workflowId && step.id && typeof step.id === 'number' && step.id < 1000000000) {
        window.open('/admin/workflows/' + workflowId + '/steps/' + step.id + '/landing-builder', '_blank');
    } else {
        alert('Salva prima il workflow, poi potrai configurare la landing page di questo step.');
    }
}

// =============================================
// LANDING PAGE CONFIG (Step 3 del wizard)
// =============================================
var lpFields = [];
var lpCurrentTemplate = 'modern';
var lpCurrentStepId = null;
var lpPreviewTimer = null;

var LP_PRESETS = {
    modern:    { bg1:'#8B6914', bg2:'#5C6134', cardBg:'#ffffff', titleColor:'#1a1a2e', textColor:'#666666', btn1:'#8B6914', btn2:'#5C6134', btnText:'#ffffff', labelColor:'#333333', inputBorder:'#e1e8ed' },
    corporate: { bg1:'#1a1a2e', bg2:'#16213e', cardBg:'#1a1a3e', titleColor:'#ffffff', textColor:'#8888aa', btn1:'#8B6914', btn2:'#8B6914', btnText:'#ffffff', labelColor:'#cccccc', inputBorder:'#2a2a5a' },
    minimal:   { bg1:'#f8f9fa', bg2:'#f8f9fa', cardBg:'#ffffff', titleColor:'#111111', textColor:'#888888', btn1:'#111111', btn2:'#111111', btnText:'#ffffff', labelColor:'#333333', inputBorder:'#dddddd' },
    warm:      { bg1:'#f093fb', bg2:'#f5576c', cardBg:'#ffffff', titleColor:'#1a1a2e', textColor:'#666666', btn1:'#f093fb', btn2:'#f5576c', btnText:'#ffffff', labelColor:'#333333', inputBorder:'#f0e0f0' },
    nature:    { bg1:'#11998e', bg2:'#38ef7d', cardBg:'#ffffff', titleColor:'#064e3b', textColor:'#6b7280', btn1:'#11998e', btn2:'#38ef7d', btnText:'#ffffff', labelColor:'#374151', inputBorder:'#d1fae5' },
    ocean:     { bg1:'#2193b0', bg2:'#6dd5ed', cardBg:'#ffffff', titleColor:'#0c4a6e', textColor:'#64748b', btn1:'#2193b0', btn2:'#6dd5ed', btnText:'#ffffff', labelColor:'#334155', inputBorder:'#bae6fd' }
};

function populateLandingStepSelect() {
    var sel = document.getElementById('landingStepSelect');
    if (!sel) return;
    sel.innerHTML = '<option value="">-- Seleziona uno step --</option>';
    workflowSteps.forEach(function(step, i) {
        var opt = document.createElement('option');
        opt.value = step.id;
        opt.textContent = 'Step ' + (i + 1) + ': ' + step.name + ' (' + step.type + ')';
        sel.appendChild(opt);
    });
}

function loadLandingForStep() {
    var sel = document.getElementById('landingStepSelect');
    var stepId = sel.value;
    var area = document.getElementById('landingConfigArea');

    if (!stepId) {
        area.style.display = 'none';
        return;
    }

    lpCurrentStepId = stepId;
    area.style.display = 'block';

    // Prova a caricare config salvata
    fetch('/api/landing-builder/' + stepId)
        .then(function(r) { return r.json(); })
        .then(function(data) {
            if (data.gjs_data && data.gjs_data.template) {
                loadLpFromConfig(data.gjs_data);
            } else {
                // Default
                var step = workflowSteps.find(function(s) { return String(s.id) === String(stepId); });
                document.getElementById('lpTitle').value = step ? step.name : '';
                document.getElementById('lpSubtitle').value = 'Compila il form per partecipare.';
                document.getElementById('lpBtnText').value = 'Invia';
                document.getElementById('lpSuccessMsg').value = 'Grazie! Dati salvati con successo.';
                document.getElementById('lpLogo').value = '';
                document.getElementById('lpBgImage').value = '';
                lpFields = [
                    { label: 'Nome completo', name: 'nome', type: 'text', required: true },
                    { label: 'Email', name: 'email', type: 'email', required: true }
                ];
                selectLpTemplate('modern');
                renderLpFields();
                updateLpPreview();
            }
        })
        .catch(function() {
            selectLpTemplate('modern');
            lpFields = [
                { label: 'Nome completo', name: 'nome', type: 'text', required: true },
                { label: 'Email', name: 'email', type: 'email', required: true }
            ];
            renderLpFields();
            updateLpPreview();
        });
}

function loadLpFromConfig(cfg) {
    selectLpTemplate(cfg.template || 'modern');
    document.getElementById('lpTitle').value = cfg.title || '';
    document.getElementById('lpSubtitle').value = cfg.subtitle || '';
    document.getElementById('lpBtnText').value = cfg.button_text || 'Invia';
    document.getElementById('lpSuccessMsg').value = cfg.success_message || '';
    document.getElementById('lpLogo').value = cfg.logo_url || '';
    document.getElementById('lpBgImage').value = (cfg.style && cfg.style.bg_image) || '';
    lpFields = (cfg.fields || []).map(function(f) {
        return { label: f.label, name: f.name, type: f.type, required: !!f.required, placeholder: f.placeholder || '', options: f.options || '' };
    });
    renderLpFields();
    updateLpPreview();
}

function selectLpTemplate(name) {
    lpCurrentTemplate = name;
    document.querySelectorAll('.lp-tpl-card').forEach(function(c) {
        c.classList.toggle('selected', c.dataset.tpl === name);
    });
    updateLpPreview();
}

function addLpField() {
    lpFields.push({ label: '', name: '', type: 'text', required: false, placeholder: '', options: '' });
    renderLpFields();
}

function removeLpField(i) {
    lpFields.splice(i, 1);
    renderLpFields();
    updateLpPreview();
}

function renderLpFields() {
    var tbody = document.getElementById('lpFieldsBody');
    if (!tbody) return;
    tbody.innerHTML = '';
    lpFields.forEach(function(f, i) {
        var isChoice = (f.type === 'select' || f.type === 'radio' || f.type === 'checkbox');
        var tr = document.createElement('tr');
        tr.innerHTML =
            '<td><i class="bi bi-grip-vertical" style="cursor:grab;color:#aaa"></i></td>' +
            '<td><input type="text" class="form-control form-control-sm" value="' + escHtml(f.label) + '" onchange="lpFields[' + i + '].label=this.value;updateLpPreview()"></td>' +
            '<td><input type="text" class="form-control form-control-sm" style="font-family:monospace" value="' + escHtml(f.name) + '" onchange="lpFields[' + i + '].name=this.value"></td>' +
            '<td><select class="form-select form-select-sm" onchange="lpFields[' + i + '].type=this.value;renderLpFields();updateLpPreview()">' +
                '<option value="text"' + (f.type==='text'?' selected':'') + '>Testo</option>' +
                '<option value="email"' + (f.type==='email'?' selected':'') + '>Email</option>' +
                '<option value="tel"' + (f.type==='tel'?' selected':'') + '>Telefono</option>' +
                '<option value="number"' + (f.type==='number'?' selected':'') + '>Numero</option>' +
                '<option value="date"' + (f.type==='date'?' selected':'') + '>Data</option>' +
                '<option value="textarea"' + (f.type==='textarea'?' selected':'') + '>Area testo</option>' +
                '<option value="select"' + (f.type==='select'?' selected':'') + '>Menu</option>' +
                '<option value="radio"' + (f.type==='radio'?' selected':'') + '>Radio</option>' +
                '<option value="checkbox"' + (f.type==='checkbox'?' selected':'') + '>Checkbox</option>' +
                '<option value="file"' + (f.type==='file'?' selected':'') + '>File upload</option>' +
            '</select></td>' +
            '<td class="text-center"><input type="checkbox" class="form-check-input"' + (f.required ? ' checked' : '') + ' onchange="lpFields[' + i + '].required=this.checked;updateLpPreview()"></td>' +
            '<td><button type="button" class="btn btn-sm text-danger p-0" onclick="removeLpField(' + i + ')"><i class="bi bi-trash"></i></button></td>';
        tbody.appendChild(tr);
    });

    if (typeof Sortable !== 'undefined') {
        Sortable.create(tbody, {
            handle: '.bi-grip-vertical',
            animation: 150,
            onEnd: function(evt) {
                var item = lpFields.splice(evt.oldIndex, 1)[0];
                lpFields.splice(evt.newIndex, 0, item);
                renderLpFields();
                updateLpPreview();
            }
        });
    }
}

function escHtml(s) { return String(s || '').replace(/"/g, '&quot;').replace(/</g, '&lt;'); }

function updateLpPreview() {
    clearTimeout(lpPreviewTimer);
    lpPreviewTimer = setTimeout(function() {
        var iframe = document.getElementById('lpPreviewFrame');
        if (iframe) iframe.srcdoc = generateLpHtml();
    }, 200);
}

function generateLpHtml() {
    var p = LP_PRESETS[lpCurrentTemplate] || LP_PRESETS.modern;
    var title = document.getElementById('lpTitle').value || 'Titolo';
    var subtitle = document.getElementById('lpSubtitle').value || '';
    var btnText = document.getElementById('lpBtnText').value || 'Invia';
    var successMsg = document.getElementById('lpSuccessMsg').value || 'Grazie!';
    var logo = document.getElementById('lpLogo').value;
    var bgImage = document.getElementById('lpBgImage').value;
    var font = 'Inter';
    var br = '10px';

    var inputBg = p.cardBg === '#ffffff' ? '#fff' : 'rgba(255,255,255,0.1)';

    var fieldsHtml = '';
    lpFields.forEach(function(f) {
        if (!f.label && !f.name) return;
        fieldsHtml += '<div style="margin-bottom:20px">';
        fieldsHtml += '<label style="display:block;margin-bottom:6px;font-weight:600;color:' + p.labelColor + ';font-size:14px">' + escHtml(f.label) + (f.required ? ' <span style="color:#ef4444">*</span>' : '') + '</label>';
        var is = 'width:100%;padding:14px 16px;border:2px solid ' + p.inputBorder + ';border-radius:' + br + ';font-size:15px;box-sizing:border-box;outline:none;font-family:inherit;background:' + inputBg + ';color:' + p.titleColor;
        if (f.type === 'file') {
            fieldsHtml += '<input type="file" name="' + escHtml(f.name) + '" accept=".pdf,.jpg,.jpeg,.png,.doc,.docx,.xls,.xlsx" style="' + is + '"' + (f.required ? ' required' : '') + '>';
            fieldsHtml += '<small style="color:' + p.textColor + ';opacity:0.6;font-size:12px;margin-top:4px;display:block">Max 20 MB — PDF, JPG, PNG, DOC, XLS</small>';
        } else if (f.type === 'textarea') {
            fieldsHtml += '<textarea name="' + escHtml(f.name) + '" rows="3" style="' + is + ';resize:vertical"></textarea>';
        } else if (f.type === 'select') {
            fieldsHtml += '<select name="' + escHtml(f.name) + '" style="' + is + '"><option value="">Seleziona...</option>';
            (f.options || '').split(',').forEach(function(o) { o = o.trim(); if (o) fieldsHtml += '<option value="' + escHtml(o) + '">' + escHtml(o) + '</option>'; });
            fieldsHtml += '</select>';
        } else if (f.type === 'radio' || f.type === 'checkbox') {
            (f.options || '').split(',').forEach(function(o) { o = o.trim(); if (o) fieldsHtml += '<label style="display:flex;align-items:center;gap:8px;margin-bottom:8px;font-weight:400;color:' + p.textColor + ';font-size:14px;cursor:pointer"><input type="' + f.type + '" name="' + escHtml(f.name) + '" value="' + escHtml(o) + '"> ' + escHtml(o) + '</label>'; });
        } else {
            fieldsHtml += '<input type="' + f.type + '" name="' + escHtml(f.name) + '" style="' + is + '">';
        }
        fieldsHtml += '</div>';
    });

    var bgStyle = bgImage
        ? 'background-image:url(\'' + escHtml(bgImage) + '\');background-size:cover;background-position:center;'
        : 'background:linear-gradient(135deg,' + p.bg1 + ',' + p.bg2 + ');';

    var overlayHtml = bgImage ? '<div style="position:absolute;inset:0;background:linear-gradient(135deg,' + p.bg1 + ',' + p.bg2 + ');opacity:0.5"></div>' : '';
    var logoHtml = logo ? '<img src="' + escHtml(logo) + '" alt="Logo" style="max-height:48px;margin-bottom:16px">' : '';

    return '<!DOCTYPE html><html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"><link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap" rel="stylesheet"><style>*{margin:0;padding:0;box-sizing:border-box}</style></head><body>' +
        '<div style="min-height:100vh;display:flex;align-items:center;justify-content:center;' + bgStyle + 'padding:40px 20px;font-family:\'' + font + '\',sans-serif;position:relative">' +
        overlayHtml +
        '<div style="background:' + p.cardBg + ';border-radius:16px;box-shadow:0 25px 60px rgba(0,0,0,0.3);max-width:520px;width:100%;padding:48px;position:relative;z-index:1">' +
        '<div style="text-align:center;margin-bottom:32px">' + logoHtml +
        '<h1 style="color:' + p.titleColor + ';font-size:28px;font-weight:800;margin:0 0 8px">' + escHtml(title) + '</h1>' +
        (subtitle ? '<p style="color:' + p.textColor + ';font-size:16px;margin:0;line-height:1.5">' + escHtml(subtitle) + '</p>' : '') +
        '</div><form class="saba-landing-form">' + fieldsHtml +
        '<button type="submit" style="width:100%;padding:16px;background:linear-gradient(135deg,' + p.btn1 + ',' + p.btn2 + ');color:' + p.btnText + ';border:none;border-radius:' + br + ';font-size:16px;font-weight:700;cursor:pointer;font-family:inherit">' + escHtml(btnText) + '</button>' +
        '</form>' +
        '<div class="saba-success-msg" style="display:none;background:#ecfdf5;border:1px solid #a7f3d0;padding:16px;border-radius:' + br + ';margin-top:20px;text-align:center;color:#065f46;font-weight:600">' + escHtml(successMsg) + '</div>' +
        '<p style="text-align:center;color:' + p.textColor + ';opacity:0.5;font-size:12px;margin-top:24px">Powered by Saba Workflow</p>' +
        '</div></div></body></html>';
}

function saveLpConfig() {
    if (!lpCurrentStepId) { alert('Seleziona uno step'); return; }

    var p = LP_PRESETS[lpCurrentTemplate] || LP_PRESETS.modern;
    var config = {
        template: lpCurrentTemplate,
        title: document.getElementById('lpTitle').value,
        subtitle: document.getElementById('lpSubtitle').value,
        button_text: document.getElementById('lpBtnText').value,
        success_message: document.getElementById('lpSuccessMsg').value,
        logo_url: document.getElementById('lpLogo').value,
        footer: 'Powered by Saba Workflow',
        style: {
            bg_color_1: p.bg1, bg_color_2: p.bg2, card_bg: p.cardBg,
            title_color: p.titleColor, text_color: p.textColor,
            btn_color_1: p.btn1, btn_color_2: p.btn2, btn_text_color: p.btnText,
            label_color: p.labelColor, input_border: p.inputBorder,
            bg_image: document.getElementById('lpBgImage').value,
            font: 'Inter', title_size: '28px', border_radius: '10px',
            card_radius: '16px', card_shadow: '0 25px 60px rgba(0,0,0,0.3)', card_width: '520px'
        },
        fields: lpFields
    };

    var html = generateLpHtml();
    // Inietta script submit
    var submitScript = '<scr' + 'ipt>(function(){function readFileAsBase64(file){return new Promise(function(resolve,reject){var reader=new FileReader();reader.onload=function(){resolve(reader.result)};reader.onerror=reject;reader.readAsDataURL(file)});}var forms=document.querySelectorAll(".saba-landing-form");forms.forEach(function(f){f.addEventListener("submit",function(e){e.preventDefault();var btn=f.querySelector("[type=submit]");if(btn){btn.disabled=true;btn.textContent="Invio...";}var fd=new FormData(f);var d={};var filePromises=[];fd.forEach(function(v,k){if(v instanceof File&&v.size>0){if(v.size>20*1024*1024){alert("File troppo grande (max 20 MB)");btn.disabled=false;btn.textContent=btn.dataset.origText||"Invia";return;}filePromises.push(readFileAsBase64(v).then(function(b64){d[k]={filename:v.name,mime:v.type,size:v.size,data:b64};}));}else if(!(v instanceof File)){d[k]=v;}});Promise.all(filePromises).then(function(){return fetch(window.location.pathname,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(d)});}).then(function(r){if(r.ok){var s=document.querySelector(".saba-success-msg");if(s)s.style.display="block";f.style.display="none";}else{alert("Errore nel salvataggio");if(btn){btn.disabled=false;btn.textContent="Invia";}}}).catch(function(){alert("Errore");if(btn){btn.disabled=false;btn.textContent="Invia";}});});});})();</scr' + 'ipt>';
    html = html.replace('</body>', submitScript + '</body>');

    fetch('/api/landing-builder/' + lpCurrentStepId, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ html: html, css: '', gjs_data: config })
    })
    .then(function(r) {
        if (r.ok) alert('Landing page salvata!');
        else alert('Errore nel salvataggio');
    })
    .catch(function() { alert('Errore di connessione'); });
}
