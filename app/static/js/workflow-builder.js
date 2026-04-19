// Workflow Builder - Drag & Drop Logic
let workflowSteps = [];
let currentStep = 1;
let editingStepIndex = null;


// Canvas theme
var _canvasTheme = localStorage.getItem('wf_canvas_theme') || 'dark';

function setCanvasTheme(theme, btn) {
    _canvasTheme = theme;
    localStorage.setItem('wf_canvas_theme', theme);
    document.body.className = document.body.className.replace(/canvas-\S+/g, '').trim();
    document.body.classList.add('canvas-' + theme);
    document.querySelectorAll('.wf-theme-btn').forEach(function(b) { b.classList.remove('active'); });
    if (btn) btn.classList.add('active');
}

// Initialize on page load
document.addEventListener('DOMContentLoaded', function() {
    document.body.classList.add('canvas-' + _canvasTheme);
    initDragAndDrop();
});

// Initialize drag and drop
function initDragAndDrop() {
    const templates = document.querySelectorAll('.step-template');
    const canvas = document.getElementById('workflowCanvas');
    
    // Make templates draggable
    templates.forEach(template => {
        template.addEventListener('dragstart', handleDragStart);
        template.addEventListener('dragend', function() { _isDraggingFromPalette = false; });
    });
    
    // Canvas drop zone
    canvas.addEventListener('dragover', handleDragOver);
    canvas.addEventListener('drop', handleDrop);
    canvas.addEventListener('dragleave', handleDragLeave);
}

var _isDraggingFromPalette = false;

function handleDragStart(e) {
    _isDraggingFromPalette = true;
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

    // Ignore drops that landed inside a branch track (handled by branch drop)
    if (e.target.closest && e.target.closest('.wf-branch-dropzone')) return;

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
    setTimeout(function() {
        if (workflowSteps[insertAt]) editStep(insertAt);
    }, 150);
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
            true_steps: [],
            false_steps: [],
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
        human_approval: {
            approver_email: '',
            approval_message: '',
            timeout_hours: 48,
            on_timeout: 'reject',
            approved_steps: [],
            rejected_steps: [],
        },
        whatsapp: {
            template_name: 'hello_world',
            template_language: 'en_US',
            body_text: '',
            delay_hours: 0
        },
        excel_write: {
            storage: 'onedrive',
            file_path: '',
            sharepoint_site: '',
            sheet_name: 'Sheet1',
            columns: []
        },
        export_data: {
            format: 'csv',
            send_to: '',
            save_local: false
        }
    };
    return configs[type] || {};
}

// Zoom state
var _canvasZoom = 1;

function wfZoomIn() {
    _canvasZoom = Math.min(_canvasZoom + 0.1, 2);
    applyCanvasZoom();
}
function wfZoomOut() {
    _canvasZoom = Math.max(_canvasZoom - 0.1, 0.4);
    applyCanvasZoom();
}
function wfZoomReset() {
    _canvasZoom = 1;
    applyCanvasZoom();
}
function wfZoomFit() {
    var canvas = document.getElementById('workflowCanvas');
    var scroller = document.getElementById('wfCanvasScroller');
    if (!canvas || !scroller) return;
    _canvasZoom = Math.min(canvas.clientHeight / scroller.scrollHeight, 1);
    _canvasZoom = Math.max(_canvasZoom, 0.3);
    applyCanvasZoom();
}
function applyCanvasZoom() {
    var scroller = document.getElementById('wfCanvasScroller');
    var label = document.getElementById('wfZoomLabel');
    if (scroller) scroller.style.transform = 'scale(' + _canvasZoom + ')';
    if (label) label.textContent = Math.round(_canvasZoom * 100) + '%';
    updateMinimap();
}

// Minimap
function updateMinimap() {
    var vp = document.getElementById('wfMinimapViewport');
    var canvas = document.getElementById('workflowCanvas');
    if (!vp || !canvas) return;
    var scrollH = canvas.scrollHeight;
    var viewH = canvas.clientHeight;
    var scrollTop = canvas.scrollTop;
    var mcH = 130; // minimap canvas height
    var top = (scrollTop / scrollH) * mcH;
    var height = (viewH / scrollH) * mcH;
    vp.style.top = Math.max(0, top) + 'px';
    vp.style.height = Math.min(mcH, Math.max(15, height)) + 'px';
}

// Branch collapse/expand
function toggleBranch(btn) {
    var track = btn.closest('.wf-branch-track');
    if (!track) return;
    track.classList.toggle('collapsed');
    var icon = btn.querySelector('i');
    if (track.classList.contains('collapsed')) {
        icon.className = 'bi bi-chevron-down';
    } else {
        icon.className = 'bi bi-chevron-up';
    }
}

// Render guard — prevents overlapping renders
var _renderPending = null;

function renderCanvas() {
    // Cancel any pending deferred render (from SortableJS onEnd)
    if (_renderPending) { clearTimeout(_renderPending); _renderPending = null; }
    // Close any open step picker popup
    closeStepPicker();

    const canvas = document.getElementById('workflowCanvas');
    const emptyState = document.getElementById('emptyState');

    if (workflowSteps.length === 0) {
        emptyState.style.display = 'block';
        canvas.querySelector('.wf-canvas-scroller')?.remove();
        canvas.querySelector('.wf-theme-switcher')?.remove();
        canvas.querySelector('.wf-zoom-controls')?.remove();
        canvas.querySelector('.wf-minimap')?.remove();
        return;
    }

    emptyState.style.display = 'none';

    let html = '<div class="wf-canvas-scroller" id="wfCanvasScroller">';
    html += '<div class="wf-nodes" id="stepsSortContainer">';
    // Start pill
    html += '<div style="text-align:center"><span class="wf-pill start"><i class="bi bi-play-fill"></i> Start</span></div>';

    workflowSteps.forEach((step, index) => {
        // Connector before node
        html += renderConnector(index);

        // Node
        html += '<div class="step-sort-item" data-sort-index="' + index + '">';
        html += renderStep(step, index);
        html += '</div>';

        // Branch visualization for condition/approval
        if (step.type === 'condition') {
            html += renderConditionBranch(step, index);
        } else if (step.type === 'human_approval') {
            html += renderApprovalBranch(step, index);
        }
    });

    // Final connector + End pill
    html += '<div class="wf-connector"><div class="wf-connector-line"></div><div class="wf-connector-arrow">&#9660;</div></div>';
    html += '<div style="text-align:center"><span class="wf-pill end"><i class="bi bi-stop-fill"></i> End</span></div>';
    html += '<div style="height:20px"></div>';
    html += '</div>'; // .wf-nodes
    html += '</div>'; // .wf-canvas-scroller

    // Theme switcher
    html += `<div class="wf-theme-switcher">
        <div class="wf-theme-btn${_canvasTheme==='dark'?' active':''}" style="background:#1a1a1a" onclick="setCanvasTheme('dark',this)" title="Dark"></div>
        <div class="wf-theme-btn${_canvasTheme==='white'?' active':''}" style="background:#fff;border-color:#ddd" onclick="setCanvasTheme('white',this)" title="White"></div>
        <div class="wf-theme-btn${_canvasTheme==='cream'?' active':''}" style="background:#f5f0e8;border-color:#d5cfc3" onclick="setCanvasTheme('cream',this)" title="Cream"></div>
        <div class="wf-theme-btn${_canvasTheme==='warm-dark'?' active':''}" style="background:#2d2a25" onclick="setCanvasTheme('warm-dark',this)" title="Warm Dark"></div>
    </div>`;

    // Zoom controls
    html += `<div class="wf-zoom-controls">
        <button type="button" class="wf-zoom-btn" onclick="wfZoomIn()" title="Zoom In"><i class="bi bi-plus-lg"></i></button>
        <div class="wf-zoom-label" id="wfZoomLabel">${Math.round(_canvasZoom * 100)}%</div>
        <div class="wf-zoom-divider"></div>
        <button type="button" class="wf-zoom-btn" onclick="wfZoomOut()" title="Zoom Out"><i class="bi bi-dash-lg"></i></button>
        <div class="wf-zoom-divider"></div>
        <button type="button" class="wf-zoom-btn" onclick="wfZoomReset()" title="Reset"><i class="bi bi-arrows-angle-contract"></i></button>
        <div class="wf-zoom-divider"></div>
        <button type="button" class="wf-zoom-btn" onclick="wfZoomFit()" title="Fit"><i class="bi bi-fullscreen"></i></button>
    </div>`;

    // Minimap
    html += buildMinimapHtml();

    // Preserve emptyState element
    var emptyHtml = emptyState.outerHTML;
    canvas.innerHTML = html + emptyHtml;

    // Apply current zoom
    applyCanvasZoom();

    // Ctrl+scroll zoom on canvas
    canvas.onwheel = function(e) {
        if (e.ctrlKey || e.metaKey) {
            e.preventDefault();
            if (e.deltaY < 0) wfZoomIn(); else wfZoomOut();
        } else {
            setTimeout(updateMinimap, 10);
        }
    };
    canvas.onscroll = function() { updateMinimap(); };

    // Allow palette drops on the sort container too
    var sortContainer = document.getElementById('stepsSortContainer');
    if (sortContainer) {
        sortContainer.addEventListener('dragover', handleDragOver);
        sortContainer.addEventListener('drop', handleDrop);
        sortContainer.addEventListener('dragleave', handleDragLeave);
    }

    // Init SortableJS for step reordering
    initStepSortable();

    // Init drag & drop on branch tracks
    initBranchDropZones();
}

// Attach drag & drop listeners to branch tracks
function initBranchDropZones() {
    var zones = document.querySelectorAll('.wf-branch-dropzone');
    zones.forEach(function(zone) {
        zone.addEventListener('dragover', function(e) {
            // Only accept drags from the palette, ignore SortableJS drags
            if (!_isDraggingFromPalette) return;
            e.preventDefault();
            e.stopPropagation();
            e.dataTransfer.dropEffect = 'copy';
            zone.classList.add('branch-drag-over');
        });
        zone.addEventListener('dragleave', function(e) {
            if (!zone.contains(e.relatedTarget)) {
                zone.classList.remove('branch-drag-over');
            }
        });
        zone.addEventListener('drop', function(e) {
            // Only accept drags from the palette
            if (!_isDraggingFromPalette) return;
            e.preventDefault();
            e.stopPropagation();
            zone.classList.remove('branch-drag-over');

            var stepType = e.dataTransfer.getData('stepType');
            if (!stepType) return;

            var parentIndex = parseInt(zone.dataset.parentIndex);
            var branchKey = zone.dataset.branchKey;

            // Find insert position based on drop Y relative to existing nodes inside the track
            var nodes = zone.querySelectorAll('.wf-node');
            var insertAt = nodes.length;
            for (var i = 0; i < nodes.length; i++) {
                var rect = nodes[i].getBoundingClientRect();
                if (e.clientY < rect.top + rect.height / 2) {
                    insertAt = i;
                    break;
                }
            }

            addStepToBranch(parentIndex, branchKey, stepType, insertAt);
        });
    });
}

// Build minimap HTML based on current steps
function buildMinimapHtml() {
    var h = '<div class="wf-minimap"><div class="wf-minimap-title">Minimap</div><div class="wf-minimap-canvas">';
    var totalItems = 0;
    workflowSteps.forEach(function(step) {
        totalItems++;
        if (step.type === 'condition') totalItems += 2;
        else if (step.type === 'human_approval') totalItems += 2;
    });
    var y = 5;
    var step_h = Math.max(4, Math.min(8, 120 / (totalItems || 1)));
    var gap = step_h + 3;
    workflowSteps.forEach(function(step) {
        h += '<div class="wf-minimap-node" style="top:' + y + 'px;left:20%;width:60%"></div>';
        y += gap;
        if (step.type === 'condition' || step.type === 'human_approval') {
            var branchKey1 = step.type === 'condition' ? 'true_steps' : 'approved_steps';
            var branchKey2 = step.type === 'condition' ? 'false_steps' : 'rejected_steps';
            var n1 = (step.config[branchKey1] || []).length;
            var n2 = (step.config[branchKey2] || []).length;
            var branchH = Math.max(n1, n2, 1) * gap + 6;
            h += '<div class="wf-minimap-branch" style="top:' + y + 'px;left:5%;width:42%;height:' + branchH + 'px"></div>';
            h += '<div class="wf-minimap-branch" style="top:' + y + 'px;left:53%;width:42%;height:' + branchH + 'px"></div>';
            // Nested nodes
            for (var i = 0; i < n1; i++) {
                h += '<div class="wf-minimap-node" style="top:' + (y + 4 + i * gap) + 'px;left:8%;width:36%"></div>';
            }
            for (var j = 0; j < n2; j++) {
                h += '<div class="wf-minimap-node" style="top:' + (y + 4 + j * gap) + 'px;left:56%;width:36%"></div>';
            }
            y += branchH + 4;
        }
    });
    h += '<div class="wf-minimap-viewport" id="wfMinimapViewport" style="top:0;left:0;width:100%;height:40%"></div>';
    h += '</div></div>';
    return h;
}

// Connector with optional add-between button (now with step picker)
function renderConnector(index) {
    return `
        <div class="wf-connector">
            <div class="wf-connector-line"></div>
            <div class="wf-add-between" title="Inserisci step" onclick="showStepPicker(${index},event)">+</div>
            <div class="wf-connector-line"></div>
            <div class="wf-connector-arrow">&#9660;</div>
        </div>`;
}

// Render branch steps inside a track
function renderBranchSteps(steps, parentIndex, branchKey, badgeClass) {
    if (!steps || steps.length === 0) {
        return '<div class="wf-branch-empty" onclick="showBranchStepPicker(' + parentIndex + ',\'' + branchKey + '\',0,event)"><i class="bi bi-plus-lg"></i> Aggiungi step</div>';
    }
    var html = '';
    steps.forEach(function(bStep, bi) {
        if (bi > 0) {
            // Connector between branch steps
            html += '<div class="wf-branch-connector">';
            html += '<div class="wf-branch-connector-line"></div>';
            html += '<div class="wf-branch-add-btn" onclick="event.stopPropagation();showBranchStepPicker(' + parentIndex + ',\'' + branchKey + '\',' + bi + ',event)">+</div>';
            html += '<div class="wf-branch-connector-line"></div>';
            html += '</div>';
        }
        var icons = {email:'envelope',wait_until:'calendar-check',condition:'shuffle',goal_check:'trophy',human_approval:'person-check',survey:'ui-checks',export_data:'download',file_upload:'file-earmark-arrow-up',engagement_tracker:'graph-up'};
        var subtitle = renderNodeSubtitle(bStep);
        var badgeLetter = branchKey === 'true_steps' || branchKey === 'approved_steps' ? 'a' : 'c';
        var badgeLabel = (parentIndex + 1) + String.fromCharCode(97 + bi); // 3a, 3b, etc. or 3c, 3d
        if (branchKey === 'false_steps' || branchKey === 'rejected_steps') {
            badgeLabel = (parentIndex + 1) + String.fromCharCode(97 + (steps.length > 0 ? steps.length : 0) + bi);
        }
        html += '<div class="wf-node" onclick="editBranchStep(' + parentIndex + ',\'' + branchKey + '\',' + bi + ')" style="margin-top:' + (bi === 0 ? '8' : '0') + 'px">';
        html += '<div class="wf-node-badge-branch ' + badgeClass + '">' + badgeLabel + '</div>';
        html += '<div class="wf-node-icon ' + bStep.type + '"><i class="bi bi-' + (icons[bStep.type] || 'gear') + '"></i></div>';
        html += '<div class="wf-node-body"><div class="wf-node-title">' + bStep.name + '</div><div class="wf-node-subtitle">' + subtitle + '</div></div>';
        html += '<div class="wf-node-actions">';
        html += '<div class="wf-node-action" onclick="event.stopPropagation();editBranchStep(' + parentIndex + ',\'' + branchKey + '\',' + bi + ')" title="Edit"><i class="bi bi-pencil"></i></div>';
        html += '<div class="wf-node-action delete" onclick="event.stopPropagation();deleteBranchStep(' + parentIndex + ',\'' + branchKey + '\',' + bi + ')" title="Delete"><i class="bi bi-trash"></i></div>';
        html += '</div></div>';
    });
    // Add button at end
    html += '<div class="wf-branch-connector">';
    html += '<div class="wf-branch-connector-line"></div>';
    html += '<div class="wf-branch-add-btn" onclick="event.stopPropagation();showBranchStepPicker(' + parentIndex + ',\'' + branchKey + '\',' + steps.length + ',event)">+</div>';
    html += '</div>';
    return html;
}

// Condition branch visualization with nested steps
function renderConditionBranch(step, parentIndex) {
    var trueSteps = step.config.true_steps || [];
    var falseSteps = step.config.false_steps || [];
    var trueCount = trueSteps.length;
    var falseCount = falseSteps.length;

    return `
        <div class="wf-branch-container">
            <div class="wf-branch-split">
                <svg viewBox="0 0 750 40" preserveAspectRatio="xMidYMin meet">
                    <line x1="375" y1="0" x2="375" y2="10" stroke="var(--connector-color,#555)" stroke-width="2"/>
                    <path d="M375,10 Q375,25 190,25 L190,40" fill="none" stroke="#4ade80" stroke-width="2"/>
                    <path d="M375,10 Q375,25 560,25 L560,40" fill="none" stroke="#f87171" stroke-width="2"/>
                </svg>
            </div>
            <div class="wf-branch-arms">
                <div class="wf-branch-arm">
                    <span class="wf-branch-label yes"><i class="bi bi-check-lg"></i> True</span>
                    <div class="wf-branch-track yes-track wf-branch-dropzone" data-parent-index="${parentIndex}" data-branch-key="true_steps">
                        <div class="wf-branch-collapse" onclick="event.stopPropagation();toggleBranch(this)" title="Collapse"><i class="bi bi-chevron-up"></i></div>
                        <span class="wf-branch-collapsed-info">${trueCount} step</span>
                        ${renderBranchSteps(trueSteps, parentIndex, 'true_steps', 'yes-badge')}
                    </div>
                </div>
                <div class="wf-branch-arm">
                    <span class="wf-branch-label no"><i class="bi bi-x-lg"></i> False</span>
                    <div class="wf-branch-track no-track wf-branch-dropzone" data-parent-index="${parentIndex}" data-branch-key="false_steps">
                        <div class="wf-branch-collapse" onclick="event.stopPropagation();toggleBranch(this)" title="Collapse"><i class="bi bi-chevron-up"></i></div>
                        <span class="wf-branch-collapsed-info">${falseCount} step</span>
                        ${renderBranchSteps(falseSteps, parentIndex, 'false_steps', 'no-badge')}
                    </div>
                </div>
            </div>
            <div class="wf-branch-merge">
                <svg viewBox="0 0 750 40" preserveAspectRatio="xMidYMax meet">
                    <path d="M190,0 L190,15 Q190,30 375,30 L375,40" fill="none" stroke="var(--connector-color,#555)" stroke-width="2"/>
                    <path d="M560,0 L560,15 Q560,30 375,30 L375,40" fill="none" stroke="var(--connector-color,#555)" stroke-width="2"/>
                </svg>
            </div>
        </div>`;
}

// Approval branch visualization with nested steps
function renderApprovalBranch(step, parentIndex) {
    var approvedSteps = step.config.approved_steps || [];
    var rejectedSteps = step.config.rejected_steps || [];
    var approvedCount = approvedSteps.length;
    var rejectedCount = rejectedSteps.length;

    return `
        <div class="wf-branch-container">
            <div class="wf-branch-split">
                <svg viewBox="0 0 750 40" preserveAspectRatio="xMidYMin meet">
                    <line x1="375" y1="0" x2="375" y2="10" stroke="var(--connector-color,#555)" stroke-width="2"/>
                    <path d="M375,10 Q375,25 190,25 L190,40" fill="none" stroke="#4ade80" stroke-width="2"/>
                    <path d="M375,10 Q375,25 560,25 L560,40" fill="none" stroke="#f87171" stroke-width="2"/>
                </svg>
            </div>
            <div class="wf-branch-arms">
                <div class="wf-branch-arm">
                    <span class="wf-branch-label yes"><i class="bi bi-check-lg"></i> Approved</span>
                    <div class="wf-branch-track yes-track wf-branch-dropzone" data-parent-index="${parentIndex}" data-branch-key="approved_steps">
                        <div class="wf-branch-collapse" onclick="event.stopPropagation();toggleBranch(this)" title="Collapse"><i class="bi bi-chevron-up"></i></div>
                        <span class="wf-branch-collapsed-info">${approvedCount} step</span>
                        ${renderBranchSteps(approvedSteps, parentIndex, 'approved_steps', 'yes-badge')}
                    </div>
                </div>
                <div class="wf-branch-arm">
                    <span class="wf-branch-label no"><i class="bi bi-x-lg"></i> Rejected</span>
                    <div class="wf-branch-track no-track wf-branch-dropzone" data-parent-index="${parentIndex}" data-branch-key="rejected_steps">
                        <div class="wf-branch-collapse" onclick="event.stopPropagation();toggleBranch(this)" title="Collapse"><i class="bi bi-chevron-up"></i></div>
                        <span class="wf-branch-collapsed-info">${rejectedCount} step</span>
                        ${renderBranchSteps(rejectedSteps, parentIndex, 'rejected_steps', 'no-badge')}
                    </div>
                </div>
            </div>
            <div class="wf-branch-merge">
                <svg viewBox="0 0 750 40" preserveAspectRatio="xMidYMax meet">
                    <path d="M190,0 L190,15 Q190,30 375,30 L375,40" fill="none" stroke="var(--connector-color,#555)" stroke-width="2"/>
                    <path d="M560,0 L560,15 Q560,30 375,30 L375,40" fill="none" stroke="var(--connector-color,#555)" stroke-width="2"/>
                </svg>
            </div>
        </div>`;
}

// Step type picker — built as inline overlay, not a body-appended popup
var _stepPickerCloseHandler = null;

function _buildPickerItems(types, onSelect) {
    var picker = document.createElement('div');
    picker.className = 'wf-step-picker';
    picker.id = 'wfStepPicker';
    types.forEach(function(t) {
        var item = document.createElement('div');
        item.className = 'wf-step-picker-item';
        item.innerHTML = '<div class="wf-node-icon ' + t.cls + '"><i class="bi bi-' + t.icon + '"></i></div> ' + t.label;
        item.onmousedown = function(e) {
            e.preventDefault();
            e.stopPropagation();
        };
        item.onclick = function(e) {
            e.preventDefault();
            e.stopPropagation();
            closeStepPicker();
            onSelect(t.type);
        };
        picker.appendChild(item);
    });
    return picker;
}

function _showPickerAtElement(el, picker) {
    closeStepPicker();
    var rect = el.getBoundingClientRect();
    picker.style.left = Math.max(10, rect.left + rect.width / 2 - 140) + 'px';
    picker.style.top = (rect.bottom + 6) + 'px';
    document.body.appendChild(picker);

    // Close on click outside — use mousedown to fire before any other handler
    _stepPickerCloseHandler = function(e) {
        if (picker.contains(e.target)) return;
        closeStepPicker();
    };
    // Delay attaching so the current click doesn't immediately close it
    setTimeout(function() {
        document.addEventListener('mousedown', _stepPickerCloseHandler);
    }, 50);
}

function showStepPicker(insertIndex, event) {
    event.preventDefault();
    event.stopPropagation();
    var btn = event.currentTarget || event.target;

    var types = [
        { type: 'email', icon: 'envelope', label: 'Email', cls: 'email' },
        { type: 'wait_until', icon: 'calendar-check', label: 'Wait Until', cls: 'wait_until' },
        { type: 'goal_check', icon: 'trophy', label: 'Goal Check', cls: 'goal_check' },
        { type: 'condition', icon: 'shuffle', label: 'Condition', cls: 'condition' },
        { type: 'human_approval', icon: 'person-check', label: 'Approval', cls: 'human_approval' },
        { type: 'survey', icon: 'ui-checks', label: 'Survey', cls: 'survey' },
        { type: 'export_data', icon: 'download', label: 'Export', cls: 'export_data' },
    ];

    var picker = _buildPickerItems(types, function(stepType) {
        addStep(stepType, insertIndex);
    });
    _showPickerAtElement(btn, picker);
}

function showBranchStepPicker(parentIndex, branchKey, insertAt, event) {
    event.preventDefault();
    event.stopPropagation();
    var btn = event.currentTarget || event.target;

    var types = [
        { type: 'email', icon: 'envelope', label: 'Email', cls: 'email' },
        { type: 'wait_until', icon: 'calendar-check', label: 'Wait Until', cls: 'wait_until' },
        { type: 'goal_check', icon: 'trophy', label: 'Goal Check', cls: 'goal_check' },
        { type: 'survey', icon: 'ui-checks', label: 'Survey', cls: 'survey' },
        { type: 'export_data', icon: 'download', label: 'Export', cls: 'export_data' },
    ];

    var picker = _buildPickerItems(types, function(stepType) {
        addStepToBranch(parentIndex, branchKey, stepType, insertAt);
    });
    _showPickerAtElement(btn, picker);
}

function closeStepPicker() {
    if (_stepPickerCloseHandler) {
        document.removeEventListener('mousedown', _stepPickerCloseHandler);
        _stepPickerCloseHandler = null;
    }
    var existing = document.getElementById('wfStepPicker');
    if (existing) existing.remove();
}

// Add step at specific position (from "+" button between nodes)
function addStepAt(index) {
    // For the connector "+" buttons, we still do a quick add (email default)
    // But the step picker is used from the branch empty slots
    addStep('email', index);
}

// === Branch step management ===
var editingBranchContext = null; // { parentIndex, branchKey, childIndex }

function addStepToBranch(parentIndex, branchKey, type, insertAt) {
    var parent = workflowSteps[parentIndex];
    if (!parent || !parent.config[branchKey]) parent.config[branchKey] = [];
    var steps = parent.config[branchKey];

    var newStep = {
        id: Date.now(),
        type: type,
        order: insertAt + 1,
        name: capitalize(type) + ' Step',
        config: getDefaultConfig(type)
    };

    steps.splice(insertAt, 0, newStep);
    renderCanvas();

    // Auto-open edit
    setTimeout(function() {
        var p = workflowSteps[parentIndex];
        if (p && p.config[branchKey] && p.config[branchKey][insertAt]) {
            editBranchStep(parentIndex, branchKey, insertAt);
        }
    }, 150);
}

function editBranchStep(parentIndex, branchKey, childIndex) {
    var parent = workflowSteps[parentIndex];
    if (!parent) return;
    var steps = parent.config[branchKey] || [];
    var step = steps[childIndex];
    if (!step) return;

    editingBranchContext = { parentIndex: parentIndex, branchKey: branchKey, childIndex: childIndex };
    editingStepIndex = parentIndex; // fallback

    var modal = bootstrap.Modal.getOrCreateInstance(document.getElementById('stepEditModal'));
    var content = document.getElementById('stepEditContent');
    content.innerHTML = renderStepEditForm(step, childIndex);

    if (step.type === 'email' || step.type === 'survey') initEmailEditor();
    if (step.type === 'email') initAttachmentDropZone();

    document.getElementById('stepEditModal').addEventListener('hidden.bs.modal', function() {
        destroyEmailEditor();
        editingBranchContext = null;
    }, { once: true });

    modal.show();
}

function deleteBranchStep(parentIndex, branchKey, childIndex) {
    if (!confirm('Eliminare questo step?')) return;
    var parent = workflowSteps[parentIndex];
    if (!parent) return;
    var steps = parent.config[branchKey] || [];
    steps.splice(childIndex, 1);
    renderCanvas();
}

// Render single step as compact node
function renderStep(step, index) {
    const icons = {
        email: 'envelope',
        wait_until: 'calendar-check',
        condition: 'shuffle',
        goal_check: 'trophy',
        engagement_tracker: 'graph-up',
        survey: 'ui-checks',
        human_approval: 'person-check',
        export_data: 'download',
        whatsapp: 'whatsapp',
        excel_write: 'file-earmark-spreadsheet'
    };

    var subtitle = renderNodeSubtitle(step);
    var landingBtn = step.type === 'email' ? `<div class="wf-node-action" onclick="event.stopPropagation();openLandingBuilder(${index})" title="Landing Builder"><i class="bi bi-palette"></i></div>` : '';
    var upBtn = index > 0 ? `<div class="wf-node-action" onclick="event.stopPropagation();moveStepUp(${index})" title="Sposta su"><i class="bi bi-chevron-up"></i></div>` : '';
    var downBtn = index < workflowSteps.length - 1 ? `<div class="wf-node-action" onclick="event.stopPropagation();moveStepDown(${index})" title="Sposta giù"><i class="bi bi-chevron-down"></i></div>` : '';

    return `
        <div class="wf-node" data-step-id="${step.id}" data-step-index="${index}" onclick="editStep(${index})">
            <div class="wf-node-badge">${index + 1}</div>
            <div class="wf-node-icon ${step.type}"><i class="bi bi-${icons[step.type] || 'gear'}"></i></div>
            <div class="wf-node-body">
                <div class="wf-node-title">${step.name}</div>
                <div class="wf-node-subtitle">${subtitle}</div>
            </div>
            <div class="wf-node-actions">
                ${upBtn}
                ${downBtn}
                <div class="wf-node-action" onclick="event.stopPropagation();editStep(${index})" title="Edit"><i class="bi bi-pencil"></i></div>
                ${landingBtn}
                <div class="wf-node-action delete" onclick="event.stopPropagation();deleteStep(${index})" title="Delete"><i class="bi bi-trash"></i></div>
            </div>
        </div>
    `;
}

// Generate subtitle for node
function renderNodeSubtitle(step) {
    switch(step.type) {
        case 'email':
            var parts = [];
            if (step.config.subject) parts.push(step.config.subject.substring(0, 30) + (step.config.subject.length > 30 ? '...' : ''));
            if (step.config.delay_hours) parts.push(step.config.delay_hours + 'h delay');
            var attCount = (step.config.attachments || []).length;
            if (attCount) parts.push(attCount + ' allegat' + (attCount === 1 ? 'o' : 'i'));
            if (step.config.wait_for_landing && step.config.wait_for_landing !== 'false') parts.push('⏳ ' + (step.config.landing_timeout_days || 7) + 'd');
            return parts.join(' · ') || 'Not configured';
        case 'wait_until':
            var wt = step.config.wait_type;
            if (wt === 'delay_hours') return (step.config.delay_hours || 0) + 'h delay';
            if (wt === 'date') return step.config.target_date || 'Date not set';
            if (wt === 'time') return 'Daily at ' + (step.config.target_time || '09:00');
            if (wt === 'day_of_week') return (step.config.target_day || 'Monday') + ' ' + (step.config.target_time || '09:00');
            return wt || 'Not configured';
        case 'condition':
            return (step.config.field || '?') + ' ' + (step.config.operator || '=') + ' ' + (step.config.value || '?');
        case 'human_approval':
            var emails = (step.config.approver_email || '').split(',').filter(function(e){return e.trim();});
            return emails.length + ' approver' + (emails.length !== 1 ? 's' : '') + ' · ' + (step.config.timeout_hours || 48) + 'h timeout';
        case 'survey':
            return step.config.question ? step.config.question.substring(0, 35) + (step.config.question.length > 35 ? '...' : '') : 'No question';
        case 'goal_check':
            return (step.config.goal || 'form_submitted').replace(/_/g, ' ');
        case 'export_data':
            return (step.config.format || 'CSV').toUpperCase() + (step.config.send_to ? ' → ' + step.config.send_to : '');
        case 'whatsapp':
            if (step.config.message_type === 'text') {
                return (step.config.body_text || 'No text').substring(0, 30) + (step.config.delay_hours ? ' · ' + step.config.delay_hours + 'h' : '');
            }
            return 'tpl: ' + (step.config.template_name || 'hello_world') + (step.config.delay_hours ? ' · ' + step.config.delay_hours + 'h' : '');
        case 'excel_write':
            var path = step.config.file_path || '';
            var fname = path.split('/').pop() || 'Not configured';
            return fname + ' · ' + (step.config.columns || []).length + ' col';
        default:
            return capitalize(step.type);
    }
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
    editingBranchContext = null; // Reset branch context for top-level edits
    editingStepIndex = index;
    const step = workflowSteps[index];
    if (!step) return; // Guard: step may no longer exist after re-render

    // Don't open if modal is already transitioning
    var modalEl = document.getElementById('stepEditModal');
    if (modalEl.classList.contains('show') || modalEl.classList.contains('showing')) return;

    const modal = bootstrap.Modal.getOrCreateInstance(modalEl);
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
    
    // Populate excel column field selects with correct source data
    if (step.type === 'excel_write') {
        setTimeout(function() {
            document.querySelectorAll('.excel-col-row').forEach(function(row) {
                var sourceSel = row.querySelector('.excel-col-source');
                var fieldSel = row.querySelector('.excel-col-field');
                if (sourceSel && fieldSel) {
                    _populateExcelFieldSelect(fieldSel, sourceSel.value, fieldSel.dataset.current || '');
                }
            });
        }, 100);
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

    // For branching steps, the next-step is already handled by their true/false selectors
    var _branchingTypes = ['condition', 'goal_check', 'human_approval'];
    var needsNextStep = _branchingTypes.indexOf(step.type) === -1;
    // Email with wait_for_landing is also branching
    if (step.type === 'email' && step.config && step.config.wait_for_landing) {
        needsNextStep = false;
    }
    var footer = needsNextStep ? _buildNextStepFooter(step, index) : '';

    var result = _renderStepEditFormInner(step, index, common);
    return result ? result + footer : common + footer;
}

function _renderStepEditFormInner(step, index, common) {
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
                           ${step.config.has_landing ? 'checked' : ''}
                           onchange="toggleWaitForLanding()">
                    <label class="form-check-label" for="editHasLanding">
                        Includi landing page per raccolta dati
                    </label>
                </div>
                <div id="waitForLandingFields" class="mt-2 ms-4" ${step.config.has_landing ? '' : 'style="display:none"'}>
                    <div class="form-check">
                        <input class="form-check-input" type="checkbox" id="editWaitForLanding"
                               ${step.config.wait_for_landing ? 'checked' : ''}
                               onchange="toggleWaitForLandingTimeout()">
                        <label class="form-check-label" for="editWaitForLanding">
                            Wait for form submission before proceeding
                        </label>
                    </div>
                    <div id="waitForLandingTimeout" class="mt-2" ${step.config.wait_for_landing ? '' : 'style="display:none"'}>
                        <div class="mb-3">
                            <label class="form-label">Timeout (days)</label>
                            <input type="number" class="form-control form-control-sm" id="editLandingTimeout"
                                   value="${step.config.landing_timeout_days || 7}" min="1" max="90" style="max-width:120px">
                        </div>
                        <div class="row">
                            <div class="col-md-6 mb-2">
                                <label class="form-label text-success"><i class="bi bi-check-circle"></i> If form submitted</label>
                                <select class="form-select form-select-sm" id="editLandingIfFilled" onchange="toggleLandingJump('Filled')">
                                    <option value="continue" ${(step.config.landing_if_filled || 'continue') === 'continue' ? 'selected' : ''}>Continue to next step</option>
                                    <option value="jump" ${step.config.landing_if_filled === 'jump' ? 'selected' : ''}>Jump to step...</option>
                                </select>
                                <div id="jumpFilledRow" class="mt-1" ${step.config.landing_if_filled === 'jump' ? '' : 'style="display:none"'}>
                                    <select class="form-select form-select-sm" id="editLandingIfFilledStep">
                                        ${buildStepOptions(step.config.landing_if_filled_step, index)}
                                    </select>
                                </div>
                            </div>
                            <div class="col-md-6 mb-2">
                                <label class="form-label text-danger"><i class="bi bi-clock"></i> If timeout (no response)</label>
                                <select class="form-select form-select-sm" id="editLandingIfTimeout" onchange="toggleLandingJump('Timeout')">
                                    <option value="continue" ${(step.config.landing_if_timeout || 'continue') === 'continue' ? 'selected' : ''}>Continue to next step</option>
                                    <option value="jump" ${step.config.landing_if_timeout === 'jump' ? 'selected' : ''}>Jump to step...</option>
                                    <option value="stop" ${step.config.landing_if_timeout === 'stop' ? 'selected' : ''}>Stop workflow</option>
                                </select>
                                <div id="jumpTimeoutRow" class="mt-1" ${step.config.landing_if_timeout === 'jump' ? '' : 'style="display:none"'}>
                                    <select class="form-select form-select-sm" id="editLandingIfTimeoutStep">
                                        ${buildStepOptions(step.config.landing_if_timeout_step, index)}
                                    </select>
                                </div>
                            </div>
                        </div>
                    </div>
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

                <div class="row">
                    <div class="col-md-6 mb-3">
                        <label class="form-label text-success"><i class="bi bi-check-circle"></i> If Goal Met</label>
                        <select class="form-select" id="editIfMet" onchange="toggleGoalJump('Met')">
                            <option value="continue" ${step.config.if_met === 'continue' ? 'selected' : ''}>Continue to Next Step</option>
                            <option value="jump" ${step.config.if_met === 'jump' ? 'selected' : ''}>Jump to step...</option>
                            <option value="complete" ${step.config.if_met === 'complete' ? 'selected' : ''}>Complete Workflow (stop)</option>
                        </select>
                        <div id="jumpMetRow" class="mt-2" ${step.config.if_met === 'jump' ? '' : 'style="display:none"'}>
                            <select class="form-select form-select-sm" id="editIfMetStep">
                                ${buildStepOptions(step.config.if_met_step, index)}
                            </select>
                        </div>
                    </div>
                    <div class="col-md-6 mb-3">
                        <label class="form-label text-danger"><i class="bi bi-x-circle"></i> If Goal NOT Met</label>
                        <select class="form-select" id="editIfNotMet" onchange="toggleGoalJump('NotMet')">
                            <option value="continue" ${step.config.if_not_met === 'continue' ? 'selected' : ''}>Continue to Next Step</option>
                            <option value="jump" ${step.config.if_not_met === 'jump' ? 'selected' : ''}>Jump to step...</option>
                            <option value="skip" ${step.config.if_not_met === 'skip' ? 'selected' : ''}>Skip Next Step</option>
                            <option value="complete" ${step.config.if_not_met === 'complete' ? 'selected' : ''}>Complete Workflow (stop)</option>
                        </select>
                        <div id="jumpNotMetRow" class="mt-2" ${step.config.if_not_met === 'jump' ? '' : 'style="display:none"'}>
                            <select class="form-select form-select-sm" id="editIfNotMetStep">
                                ${buildStepOptions(step.config.if_not_met_step, index)}
                            </select>
                        </div>
                    </div>
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
        case 'whatsapp':
            return common + `
                <div class="mb-3">
                    <label class="form-label">Message type</label>
                    <select class="form-select" id="editWaMessageType" onchange="toggleWaMessageType()">
                        <option value="template" ${(step.config.message_type || 'template') === 'template' ? 'selected' : ''}>Template (pre-approved by Meta)</option>
                        <option value="text" ${step.config.message_type === 'text' ? 'selected' : ''}>Free text (only within 24h window)</option>
                    </select>
                    <div class="form-text">First contact must use a template. Free text only works if the user messaged you in the last 24h.</div>
                </div>
                <div id="waTemplateFields" ${step.config.message_type === 'text' ? 'style="display:none"' : ''}>
                    <div class="mb-3">
                        <label class="form-label">Template name</label>
                        <input type="text" class="form-control" id="editWaTemplateName"
                               value="${step.config.template_name || 'hello_world'}"
                               placeholder="es. hello_world">
                        <div class="form-text">The template must be created and approved in WhatsApp Manager on Meta Business.</div>
                    </div>
                    <div class="mb-3">
                        <label class="form-label">Template language</label>
                        <input type="text" class="form-control" id="editWaTemplateLanguage"
                               value="${step.config.template_language || 'en_US'}"
                               placeholder="en_US, it, pt_BR...">
                    </div>
                </div>
                <div id="waTextFields" ${step.config.message_type !== 'text' ? 'style="display:none"' : ''}>
                    <div class="mb-3">
                        <label class="form-label">Message text</label>
                        <textarea class="form-control" id="editWaBodyText" rows="4"
                                  placeholder="Hi {{ participant.first_name }}, thanks for registering!">${step.config.body_text || ''}</textarea>
                        <div class="form-text">You can use {{ participant.first_name }}, {{ participant.last_name }}, {{ participant.email }}, {{ workflow_name }}.</div>
                    </div>
                </div>
                <div class="mb-3">
                    <label class="form-label">Delay (hours after previous step)</label>
                    <input type="number" class="form-control" id="editWaDelay"
                           value="${step.config.delay_hours || 0}" min="0">
                </div>
                <div class="alert alert-info">
                    <small><i class="bi bi-info-circle"></i>
                    <strong>How it works:</strong><br>
                    Messages are sent via Meta WhatsApp Business API to the participant's phone number.<br>
                    The participant must have a <code>phone</code> field with international prefix (e.g. +39...).<br>
                    <strong>Templates:</strong> Create them in <a href="https://business.facebook.com/wa/manage/message-templates/" target="_blank">WhatsApp Manager</a> — Meta approves them in 24-48h.<br>
                    <strong>Free text:</strong> Only works if the participant messaged your WhatsApp number in the last 24 hours.
                    </small>
                </div>
            `;
        case 'excel_write': {
            var columnsHtml = (step.config.columns || []).map(function(col, i) {
                return _buildExcelColRow(col, i);
            }).join('');
            var storage = step.config.storage || 'onedrive';
            return common + `
                <div class="mb-3">
                    <label class="form-label">Posizione file</label>
                    <select class="form-select" id="editExcelStorage" onchange="onExcelStorageChange()">
                        <option value="onedrive" ${storage === 'onedrive' ? 'selected' : ''}>OneDrive (account email)</option>
                        <option value="sharepoint" ${storage === 'sharepoint' ? 'selected' : ''}>SharePoint (sito condiviso)</option>
                    </select>
                </div>
                <div id="excelSharepointField" class="mb-3" ${storage === 'sharepoint' ? '' : 'style="display:none"'}>
                    <label class="form-label">URL sito SharePoint</label>
                    <input type="text" class="form-control" id="editExcelSharepointSite"
                           value="${step.config.sharepoint_site || ''}"
                           placeholder="es. contoso.sharepoint.com:/sites/TeamSito">
                    <div class="form-text">Il sito SharePoint dove si trova il file.</div>
                </div>
                <div class="mb-3">
                    <label class="form-label" id="excelPathLabel">${storage === 'local' ? 'Percorso file sul server' : 'Percorso file'}</label>
                    <div class="input-group">
                        <input type="text" class="form-control" id="editExcelFilePath"
                               value="${step.config.file_path || ''}"
                               placeholder="${storage === 'local' ? 'es. /data/iscrizioni.xlsx' : 'es. /Documenti/Iscrizioni.xlsx'}">
                        <button class="btn btn-outline-secondary" type="button" id="excelBrowseBtn"
                                onclick="openExcelFileBrowser()" ${storage === 'local' ? 'style="display:none"' : ''}>
                            <i class="bi bi-folder2-open"></i> Sfoglia
                        </button>
                    </div>
                    <div class="form-text" id="excelPathHint">${storage === 'local' ? 'Percorso assoluto sul filesystem del server.' : 'Percorso relativo alla root del drive.'}</div>
                </div>
                <div class="mb-3">
                    <label class="form-label">Nome foglio</label>
                    <input type="text" class="form-control" id="editExcelSheetName"
                           value="${step.config.sheet_name || 'Sheet1'}"
                           placeholder="Sheet1">
                </div>
                <hr>
                <h6><i class="bi bi-table"></i> Mappatura colonne</h6>
                <div class="form-text mb-2">Ogni riga corrisponde a una colonna Excel (A, B, C...). Scegli la sorgente e il campo.</div>
                <div id="excelColumnsList">${columnsHtml}</div>
                <button type="button" class="btn btn-sm btn-outline-primary mt-1" onclick="addExcelColumn()">
                    <i class="bi bi-plus"></i> Aggiungi colonna
                </button>
                <div class="alert alert-info mt-3">
                    <small><i class="bi bi-info-circle"></i>
                    <strong>How it works:</strong><br>
                    1. Create an Excel file on the OneDrive of the configured email account (${window._mailFromEmail || 'info@...'})<br>
                    2. Add column headers in the first row<br>
                    3. Use <strong>Browse</strong> to select the file, then map each column to a participant field<br>
                    4. Each time this step runs, a new row is appended with the participant's data<br>
                    5. Share the file with others via OneDrive — they'll see updates in real time<br><br>
                    <strong>SharePoint:</strong> Use this option for files on a shared SharePoint site instead of personal OneDrive.<br>
                    <strong>Permissions:</strong> The Azure app needs <code>Files.ReadWrite.All</code> (Application) permission in Microsoft Entra.
                    </small>
                </div>
            `;
        }
    }
}

var _excelColCounter = 0;

function _buildExcelColRow(col, idx) {
    col = col || {};
    var id = _excelColCounter++;
    var source = col.source || 'participant';
    var colLetter = String.fromCharCode(65 + (idx != null ? idx : document.querySelectorAll('.excel-col-row').length));
    return '<div class="excel-col-row card card-body p-2 mb-2">' +
        '<div class="d-flex align-items-center gap-2 mb-1">' +
            '<span class="badge bg-secondary">' + colLetter + '</span>' +
            '<input type="text" class="form-control form-control-sm excel-col-header" value="' + (col.header || '') + '" placeholder="Intestazione colonna">' +
            '<button class="btn btn-sm btn-outline-danger" type="button" onclick="this.closest(\'.excel-col-row\').remove()"><i class="bi bi-x"></i></button>' +
        '</div>' +
        '<div class="d-flex gap-2">' +
            '<select class="form-select form-select-sm excel-col-source" style="max-width:40%" onchange="onExcelSourceChange(this)">' +
                '<option value="participant"' + (source === 'participant' ? ' selected' : '') + '>Partecipante</option>' +
                '<option value="collected_data"' + (source === 'collected_data' ? ' selected' : '') + '>Dati raccolti</option>' +
                '<option value="sabaform_data"' + (source === 'sabaform_data' ? ' selected' : '') + '>Dati Saba Form</option>' +
            '</select>' +
            '<select class="form-select form-select-sm excel-col-field" data-current="' + (col.field || '') + '">' +
                '<option value="">Caricamento...</option>' +
            '</select>' +
        '</div>' +
    '</div>';
}

function _populateExcelFieldSelect(sel, source, currentValue) {
    sel.innerHTML = '<option value="">-- Seleziona campo --</option>';
    if (source === 'participant') {
        ['first_name','last_name','full_name','email','phone','status','created_at','last_interaction'].forEach(function(f) {
            sel.innerHTML += '<option value="' + f + '"' + (f === currentValue ? ' selected' : '') + '>' + f + '</option>';
        });
    } else if (source === 'collected_data') {
        var wfId = window._currentWorkflowId;
        if (wfId) {
            fetch('/api/landing-fields/workflow/' + wfId)
            .then(function(r) { return r.json(); })
            .then(function(data) {
                (data.fields || []).forEach(function(f) {
                    sel.innerHTML += '<option value="' + f.name + '"' + (f.name === currentValue ? ' selected' : '') + '>' + (f.label || f.name) + '</option>';
                });
            });
        }
    } else {
        // sabaform_data
        ['company','gender','birth_date','nucleo','doc_type','doc_number','doc_expiry','volo_arrivo','volo_partenza','notes','first_name','last_name','email','phone'].forEach(function(f) {
            sel.innerHTML += '<option value="' + f + '"' + (f === currentValue ? ' selected' : '') + '>' + f + '</option>';
        });
    }
}

// === Excel File Browser ===
var _excelBrowsePath = '';

function openExcelFileBrowser() {
    _excelBrowsePath = '';
    var modal = document.getElementById('excelBrowseModal');
    if (!modal) {
        // Create modal dynamically
        modal = document.createElement('div');
        modal.id = 'excelBrowseModal';
        modal.className = 'modal fade';
        modal.tabIndex = -1;
        modal.innerHTML = `
            <div class="modal-dialog">
                <div class="modal-content">
                    <div class="modal-header">
                        <h5 class="modal-title"><i class="bi bi-folder2-open"></i> Sfoglia file Excel</h5>
                        <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                    </div>
                    <div class="modal-body">
                        <nav aria-label="breadcrumb" id="excelBrowseBreadcrumb">
                            <ol class="breadcrumb" style="font-size:13px">
                                <li class="breadcrumb-item active">Root</li>
                            </ol>
                        </nav>
                        <div id="excelBrowseList" style="max-height:350px;overflow-y:auto">
                            <div class="text-center text-muted p-3"><i class="bi bi-hourglass-split"></i> Caricamento...</div>
                        </div>
                    </div>
                </div>
            </div>`;
        document.body.appendChild(modal);
    }
    bootstrap.Modal.getOrCreateInstance(modal).show();
    _loadExcelBrowse('');
}

function _loadExcelBrowse(path) {
    _excelBrowsePath = path;
    var list = document.getElementById('excelBrowseList');
    list.innerHTML = '<div class="text-center text-muted p-3"><i class="bi bi-hourglass-split"></i> Caricamento...</div>';

    var storage = document.getElementById('editExcelStorage').value;
    var site = document.getElementById('editExcelSharepointSite')?.value || '';
    var url = '/admin/api/onedrive/browse?storage=' + storage + '&path=' + encodeURIComponent(path);
    if (site) url += '&site=' + encodeURIComponent(site);

    // Update breadcrumb
    var parts = path ? path.split('/').filter(Boolean) : [];
    var bc = '<li class="breadcrumb-item"><a href="#" onclick="_loadExcelBrowse(\'\');return false">Root</a></li>';
    var cumPath = '';
    parts.forEach(function(p, i) {
        cumPath += '/' + p;
        if (i === parts.length - 1) {
            bc += '<li class="breadcrumb-item active">' + p + '</li>';
        } else {
            var cp = cumPath;
            bc += '<li class="breadcrumb-item"><a href="#" onclick="_loadExcelBrowse(\'' + cp + '\');return false">' + p + '</a></li>';
        }
    });
    document.querySelector('#excelBrowseBreadcrumb .breadcrumb').innerHTML = bc;

    fetch(url)
    .then(function(r) { return r.json(); })
    .then(function(data) {
        if (data.error) {
            list.innerHTML = '<div class="alert alert-danger">' + data.error + '</div>';
            return;
        }
        if (!data.items || data.items.length === 0) {
            list.innerHTML = '<div class="text-muted text-center p-3">Nessun file Excel trovato in questa cartella</div>';
            return;
        }
        var html = '<div class="list-group list-group-flush">';
        data.items.forEach(function(item) {
            var itemPath = (path ? path + '/' : '') + item.name;
            if (item.type === 'folder') {
                html += '<a href="#" class="list-group-item list-group-item-action d-flex align-items-center" onclick="_loadExcelBrowse(\'' + itemPath.replace(/'/g, "\\'") + '\');return false">' +
                    '<i class="bi bi-folder-fill text-warning me-2"></i> ' + item.name + '</a>';
            } else {
                var size = item.size ? ' <small class="text-muted">(' + (item.size / 1024).toFixed(0) + ' KB)</small>' : '';
                html += '<a href="#" class="list-group-item list-group-item-action d-flex align-items-center" onclick="_selectExcelFile(\'' + itemPath.replace(/'/g, "\\'") + '\');return false">' +
                    '<i class="bi bi-file-earmark-spreadsheet text-success me-2"></i> ' + item.name + size + '</a>';
            }
        });
        html += '</div>';
        list.innerHTML = html;
    })
    .catch(function(e) {
        list.innerHTML = '<div class="alert alert-danger">Errore: ' + e.message + '</div>';
    });
}

function _selectExcelFile(path) {
    document.getElementById('editExcelFilePath').value = '/' + path.replace(/^\//, '');
    bootstrap.Modal.getInstance(document.getElementById('excelBrowseModal')).hide();
}

function onExcelSourceChange(sourceSelect) {
    var row = sourceSelect.closest('.excel-col-row');
    var fieldSel = row.querySelector('.excel-col-field');
    _populateExcelFieldSelect(fieldSel, sourceSelect.value, '');
}

function toggleWaitForLanding() {
    var hasLanding = document.getElementById('editHasLanding').checked;
    document.getElementById('waitForLandingFields').style.display = hasLanding ? '' : 'none';
    if (!hasLanding) {
        document.getElementById('editWaitForLanding').checked = false;
        document.getElementById('waitForLandingTimeout').style.display = 'none';
    }
}

function toggleWaitForLandingTimeout() {
    var wait = document.getElementById('editWaitForLanding').checked;
    document.getElementById('waitForLandingTimeout').style.display = wait ? '' : 'none';
}

function toggleLandingJump(which) {
    var sel = document.getElementById('editLandingIf' + which);
    var row = document.getElementById('jump' + which + 'Row');
    row.style.display = sel.value === 'jump' ? '' : 'none';
}

function toggleGoalJump(which) {
    var sel = document.getElementById('editIf' + which);
    var row = document.getElementById('jump' + which + 'Row');
    row.style.display = sel.value === 'jump' ? '' : 'none';
}

function toggleWaMessageType() {
    var type = document.getElementById('editWaMessageType').value;
    document.getElementById('waTemplateFields').style.display = type === 'template' ? '' : 'none';
    document.getElementById('waTextFields').style.display = type === 'text' ? '' : 'none';
}

function onExcelStorageChange() {
    var storage = document.getElementById('editExcelStorage').value;
    var spField = document.getElementById('excelSharepointField');
    var pathLabel = document.getElementById('excelPathLabel');
    var pathInput = document.getElementById('editExcelFilePath');
    var pathHint = document.getElementById('excelPathHint');
    var browseBtn = document.getElementById('excelBrowseBtn');

    spField.style.display = storage === 'sharepoint' ? '' : 'none';
    if (storage === 'sharepoint') {
        pathLabel.textContent = 'Percorso file nel sito';
        pathInput.placeholder = 'es. /Documenti condivisi/Iscrizioni.xlsx';
        pathHint.textContent = 'Percorso relativo alla root del drive SharePoint.';
    } else {
        pathLabel.textContent = 'Percorso file';
        pathInput.placeholder = 'es. /Documenti/Iscrizioni.xlsx';
        pathHint.textContent = 'Percorso relativo alla root di OneDrive.';
    }
}

function addExcelColumn() {
    var idx = document.querySelectorAll('.excel-col-row').length;
    var row = _buildExcelColRow(null, idx);
    document.getElementById('excelColumnsList').insertAdjacentHTML('beforeend', row);
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
function buildStepOptions(selectedOrder, currentIndex, includeEnd) {
    var html = '<option value="0">-- Seleziona step --</option>';
    workflowSteps.forEach(function(s, i) {
        if (i === currentIndex) return;
        var sel = (parseInt(selectedOrder) === s.order) ? ' selected' : '';
        html += '<option value="' + s.order + '"' + sel + '>Step ' + s.order + ': ' + s.name + '</option>';
    });
    if (includeEnd !== false) {
        var endSel = selectedOrder === 'end' ? ' selected' : '';
        html += '<option value="end"' + endSel + '>END</option>';
    }
    return html;
}

function _buildNextStepFooter(step, index) {
    var nextStep = step.config.next_step || 'auto';
    return `
        <hr>
        <div class="mb-3">
            <label class="form-label"><i class="bi bi-arrow-right-circle"></i> Next Step</label>
            <select class="form-select" id="editNextStep">
                <option value="auto" ${nextStep === 'auto' ? 'selected' : ''}>Next in sequence (Step ${index + 2})</option>
                ${workflowSteps.map(function(s, i) {
                    if (i === index) return '';
                    return '<option value="' + s.order + '"' + (parseInt(nextStep) === s.order ? ' selected' : '') + '>Step ' + s.order + ': ' + s.name + '</option>';
                }).join('')}
                <option value="end" ${nextStep === 'end' ? 'selected' : ''}>END (stop workflow)</option>
            </select>
        </div>
    `;
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
    var step;
    if (editingBranchContext) {
        var parent = workflowSteps[editingBranchContext.parentIndex];
        var branchSteps = parent.config[editingBranchContext.branchKey] || [];
        step = branchSteps[editingBranchContext.childIndex];
    } else {
        step = workflowSteps[editingStepIndex];
    }
    
    step.name = document.getElementById('editStepName').value;
    
    switch(step.type) {
        case 'email':
            step.config.subject = document.getElementById('editEmailSubject').value;
            // Read from Summernote editor
            const $body = $('#editEmailBody');
            step.config.body_template = ($body.length && $.fn.summernote) ? $body.summernote('code') : document.getElementById('editEmailBody').value;
            step.config.delay_hours = parseInt(document.getElementById('editEmailDelay').value);
            step.config.has_landing = document.getElementById('editHasLanding').checked;
            step.config.wait_for_landing = document.getElementById('editWaitForLanding')?.checked || false;
            step.config.landing_timeout_days = parseInt(document.getElementById('editLandingTimeout')?.value) || 7;
            step.config.landing_if_filled = document.getElementById('editLandingIfFilled')?.value || 'continue';
            step.config.landing_if_filled_step = parseInt(document.getElementById('editLandingIfFilledStep')?.value) || 0;
            step.config.landing_if_timeout = document.getElementById('editLandingIfTimeout')?.value || 'continue';
            step.config.landing_if_timeout_step = parseInt(document.getElementById('editLandingIfTimeoutStep')?.value) || 0;
            if (!step.config.has_landing) {
                step.config.wait_for_landing = false;
            }
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
            step.config.if_met_step = parseInt(document.getElementById('editIfMetStep')?.value) || 0;
            step.config.if_not_met = document.getElementById('editIfNotMet').value;
            step.config.if_not_met_step = parseInt(document.getElementById('editIfNotMetStep')?.value) || 0;
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
        case 'whatsapp':
            step.config.message_type = document.getElementById('editWaMessageType').value;
            step.config.template_name = document.getElementById('editWaTemplateName')?.value || '';
            step.config.template_language = document.getElementById('editWaTemplateLanguage')?.value || 'en_US';
            step.config.body_text = document.getElementById('editWaBodyText')?.value || '';
            step.config.delay_hours = parseInt(document.getElementById('editWaDelay').value) || 0;
            break;
        case 'excel_write':
            step.config.storage = document.getElementById('editExcelStorage').value;
            step.config.file_path = document.getElementById('editExcelFilePath').value;
            step.config.sharepoint_site = document.getElementById('editExcelSharepointSite')?.value || '';
            step.config.sheet_name = document.getElementById('editExcelSheetName').value || 'Sheet1';
            step.config.columns = [];
            document.querySelectorAll('.excel-col-row').forEach(function(row) {
                var header = row.querySelector('.excel-col-header').value.trim();
                var source = row.querySelector('.excel-col-source').value;
                var field = row.querySelector('.excel-col-field').value;
                if (header || field) {
                    step.config.columns.push({header: header, source: source, field: field});
                }
            });
            break;
    }

    // Save next_step for all step types
    var nextStepEl = document.getElementById('editNextStep');
    if (nextStepEl) {
        step.config.next_step = nextStepEl.value;
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

// SortableJS no longer used for step reordering (replaced by up/down buttons).
// The complex DOM structure (branch containers, connectors, SVGs between step-sort-items)
// causes SortableJS to miscalculate drop positions. Up/down buttons are more reliable.
function initStepSortable() {
    // No-op — kept for compatibility
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
                    if_met_step: step.config.if_met_step || 0,
                    if_not_met: step.config.if_not_met,
                    if_not_met_step: step.config.if_not_met_step || 0,
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
                    if_false_step: step.config.if_false_step,
                    true_steps: (step.config.true_steps || []).map(function(bs) {
                        return { type: bs.type, name: bs.name, config: bs.config };
                    }),
                    false_steps: (step.config.false_steps || []).map(function(bs) {
                        return { type: bs.type, name: bs.name, config: bs.config };
                    })
                };
            }

            // For email steps, store has_landing and attachment IDs in skip_conditions
            if (step.type === 'email') {
                stepData.skip_conditions = {
                    has_landing: !!step.config.has_landing,
                    attachment_ids: (step.config.attachments || []).map(a => a.id),
                    wait_for_landing: !!step.config.wait_for_landing,
                    landing_timeout_days: step.config.landing_timeout_days || 7,
                    landing_if_filled: step.config.landing_if_filled || 'continue',
                    landing_if_filled_step: step.config.landing_if_filled_step || 0,
                    landing_if_timeout: step.config.landing_if_timeout || 'continue',
                    landing_if_timeout_step: step.config.landing_if_timeout_step || 0
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
                    if_rejected_step: step.config.if_rejected_step,
                    approved_steps: (step.config.approved_steps || []).map(function(bs) {
                        return { type: bs.type, name: bs.name, config: bs.config };
                    }),
                    rejected_steps: (step.config.rejected_steps || []).map(function(bs) {
                        return { type: bs.type, name: bs.name, config: bs.config };
                    })
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
            
            // For whatsapp steps
            if (step.type === 'whatsapp') {
                stepData.skip_conditions = {
                    message_type: step.config.message_type || 'template',
                    template_name: step.config.template_name || 'hello_world',
                    template_language: step.config.template_language || 'en_US',
                    body_text: step.config.body_text || ''
                };
            }

            // For excel_write steps
            if (step.type === 'excel_write') {
                stepData.skip_conditions = {
                    storage: step.config.storage || 'onedrive',
                    file_path: step.config.file_path || '',
                    sharepoint_site: step.config.sharepoint_site || '',
                    sheet_name: step.config.sheet_name || 'Sheet1',
                    columns: step.config.columns || []
                };
            }

            // Save next_step for all step types
            if (step.config.next_step && step.config.next_step !== 'auto') {
                stepData.skip_conditions = stepData.skip_conditions || {};
                stepData.skip_conditions.next_step = step.config.next_step;
            }

            // Save 2D canvas position if available
            if (step._dfPos) {
                stepData.skip_conditions = stepData.skip_conditions || {};
                stepData.skip_conditions._dfPos = step._dfPos;
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
        if (typeof _onWorkflowSaved === 'function') _onWorkflowSaved();
    })
    .catch(error => {
        console.error('Save error:', error);
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
