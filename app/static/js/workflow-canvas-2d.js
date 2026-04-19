/**
 * Workflow Canvas 2D — Drawflow-based node editor
 * Works alongside workflow-builder.js, shares workflowSteps array
 */

var _drawflowEditor = null;
var _canvasMode = 'linear'; // 'linear' or '2d'
var _dfNodeMap = {}; // drawflow node id → workflowSteps index
var _dfStepMap = {}; // step.id → drawflow node id

// Step type configuration
var _stepTypeConfig = {
    email:          { icon: 'envelope',                iconBg: '#2d4a3e', iconColor: '#4ade80', outputs: 1, outputLabels: ['next'] },
    wait_until:     { icon: 'calendar-check',          iconBg: '#3d3a2a', iconColor: '#fbbf24', outputs: 1, outputLabels: ['next'] },
    condition:      { icon: 'shuffle',                 iconBg: '#2a2d4a', iconColor: '#818cf8', outputs: 2, outputLabels: ['true', 'false'] },
    goal_check:     { icon: 'trophy',                  iconBg: '#4a3a2a', iconColor: '#fb923c', outputs: 2, outputLabels: ['met', 'not met'] },
    human_approval: { icon: 'person-check',            iconBg: '#4a2a3e', iconColor: '#f472b6', outputs: 2, outputLabels: ['approved', 'rejected'] },
    survey:         { icon: 'ui-checks',               iconBg: '#2a4a4a', iconColor: '#22d3ee', outputs: 1, outputLabels: ['next'] },
    export_data:    { icon: 'download',                iconBg: '#3a2a4a', iconColor: '#a78bfa', outputs: 1, outputLabels: ['next'] },
    whatsapp:       { icon: 'whatsapp',                iconBg: '#1a3a2a', iconColor: '#25d366', outputs: 1, outputLabels: ['next'] },
    excel_write:    { icon: 'file-earmark-spreadsheet', iconBg: '#2a3a2a', iconColor: '#4ade80', outputs: 1, outputLabels: ['next'] }
};

// ========== Canvas Mode Switching ==========

function switchCanvasMode(mode) {
    _canvasMode = mode;
    document.getElementById('btnLinear').classList.toggle('active', mode === 'linear');
    document.getElementById('btn2D').classList.toggle('active', mode === '2d');
    document.getElementById('linearCanvasWrap').style.display = mode === 'linear' ? '' : 'none';
    document.getElementById('drawflowCanvasWrap').style.display = mode === '2d' ? '' : 'none';

    if (mode === '2d') {
        if (!_drawflowEditor) {
            initDrawflow();
        }
        syncStepsToDrawflow();
        _addZoomControls();
        setTimeout(_dfZoomFit, 200);
    } else {
        renderCanvas(); // re-render linear
    }
}

// ========== Drawflow Init ==========

function initDrawflow() {
    var container = document.getElementById('drawflowCanvas');
    _drawflowEditor = new Drawflow(container);
    _drawflowEditor.reroute = true;
    _drawflowEditor.reroute_fix_curvature = true;
    _drawflowEditor.force_first_input = false;

    _drawflowEditor.start();

    // Style overrides
    _applyDrawflowStyles();

    // Add SVG arrowhead marker definition globally
    if (!document.getElementById('df-arrowhead-svg')) {
        var markerSvg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
        markerSvg.id = 'df-arrowhead-svg';
        markerSvg.setAttribute('style', 'position:absolute;width:0;height:0;overflow:hidden');
        markerSvg.innerHTML = '<defs>' +
            '<marker id="df-arrowhead" markerWidth="10" markerHeight="7" refX="9" refY="3.5" orient="auto" markerUnits="strokeWidth">' +
            '<polygon points="0 0, 10 3.5, 0 7" fill="#888"/>' +
            '</marker>' +
            '<marker id="df-arrowhead-jump" markerWidth="10" markerHeight="7" refX="9" refY="3.5" orient="auto" markerUnits="strokeWidth">' +
            '<polygon points="0 0, 10 3.5, 0 7" fill="#fb923c"/>' +
            '</marker></defs>';
        document.body.appendChild(markerSvg);
    }

    // Node click = select/drag only. Edit via pencil button.

    // Event: node removed
    _drawflowEditor.on('nodeRemoved', function(nodeId) {
        var stepIndex = _dfNodeMap[nodeId];
        if (stepIndex !== undefined) {
            workflowSteps.splice(stepIndex, 1);
            workflowSteps.forEach(function(s, i) { s.order = i + 1; });
            // Rebuild maps
            _rebuildNodeMaps();
        }
    });

    // Event: connection created
    _drawflowEditor.on('connectionCreated', function(info) {
        _syncConnectionsToSteps();
    });

    // Event: connection removed
    _drawflowEditor.on('connectionRemoved', function(info) {
        _syncConnectionsToSteps();
    });

    // Event: node moved — save positions
    _drawflowEditor.on('nodeMoved', function(nodeId) {
        _saveNodePositions();
    });

    // Update zoom label on zoom change
    _drawflowEditor.on('zoom', function(zoom) {
        _updateZoomLabel();
    });

    // Setup palette drag-drop into Drawflow
    _setupPaletteDragForDrawflow();
}

// ========== Drawflow Styling ==========

function _applyDrawflowStyles() {
    var style = document.createElement('style');
    style.textContent = `
        /* Drawflow canvas */
        #drawflowCanvas .drawflow {
            background-image: radial-gradient(circle, var(--connector-color, #555) 1px, transparent 1px);
            background-size: 20px 20px;
        }

        /* Node base */
        #drawflowCanvas .drawflow-node {
            background: var(--node-bg, #2a2a2a);
            border: 1.5px solid var(--node-border, #444);
            border-radius: 12px;
            min-width: 200px;
            color: var(--canvas-text, #e0e0e0);
            padding: 0;
            cursor: pointer;
        }
        #drawflowCanvas .drawflow-node:hover {
            border-color: var(--node-hover-border, #8B6914);
            box-shadow: 0 0 0 3px rgba(139,105,20,0.15);
        }
        #drawflowCanvas .drawflow-node.selected {
            border-color: #8B6914;
            box-shadow: 0 0 0 3px rgba(139,105,20,0.3);
        }

        /* Node content */
        .df-node-content {
            display: flex;
            align-items: center;
            gap: 10px;
            padding: 10px 14px;
        }
        .df-node-icon {
            width: 34px; height: 34px; border-radius: 9px;
            display: flex; align-items: center; justify-content: center;
            font-size: 15px; flex-shrink: 0;
        }
        .df-node-body { flex: 1; min-width: 0; }
        .df-node-title {
            font-size: 12px; font-weight: 600;
            white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
        }
        .df-node-subtitle {
            font-size: 10px; color: var(--canvas-text-muted, #888); margin-top: 1px;
            white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
        }
        .df-node-badge {
            position: absolute; top: -7px; left: -7px;
            width: 20px; height: 20px; border-radius: 50%;
            background: #8B6914; color: #fff;
            font-size: 9px; font-weight: 700;
            display: flex; align-items: center; justify-content: center;
            border: 2px solid var(--canvas-bg, #1a1a1a);
            z-index: 5;
        }

        /* Output labels */
        .df-output-labels {
            display: flex;
            justify-content: space-around;
            padding: 0 8px 6px;
            gap: 4px;
        }
        .df-output-label {
            font-size: 9px;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            padding: 2px 8px;
            border-radius: 4px;
        }
        .df-output-label.true, .df-output-label.met, .df-output-label.approved, .df-output-label.filled {
            color: #4ade80; background: rgba(74,222,128,0.1);
        }
        .df-output-label.false, .df-output-label.not-met, .df-output-label.rejected, .df-output-label.timeout {
            color: #f87171; background: rgba(248,113,113,0.1);
        }
        .df-output-label.next {
            color: var(--canvas-text-muted, #888);
        }

        /* Connection lines with arrowheads */
        #drawflowCanvas .connection .main-path {
            stroke: var(--connector-color, #555);
            stroke-width: 2;
            marker-end: url(#df-arrowhead);
        }
        #drawflowCanvas .drawflow-node .input,
        #drawflowCanvas .drawflow-node .output {
            width: 10px; height: 10px;
            border: 2px solid var(--connector-color, #555);
            background: var(--node-bg, #2a2a2a);
        }
        #drawflowCanvas .drawflow-node .input:hover,
        #drawflowCanvas .drawflow-node .output:hover {
            background: #8B6914;
            border-color: #8B6914;
        }

        /* Jump connections — dashed, orange, with orange arrowhead */
        #drawflowCanvas .connection.df-jump .main-path {
            stroke: #fb923c !important;
            stroke-dasharray: 6 4;
            stroke-width: 1.5;
            marker-end: url(#df-arrowhead-jump) !important;
        }

        /* Ports — use Drawflow defaults (left input, right output) */

        /* Start/End special nodes */
        #drawflowCanvas .drawflow-node.start-node,
        #drawflowCanvas .drawflow-node.end-node {
            min-width: 80px;
            text-align: center;
            border-radius: 20px;
        }
        .df-pill {
            padding: 6px 16px;
            font-size: 11px;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 1px;
        }
        .df-pill.start { color: #4ade80; }
        .df-pill.end { color: #f87171; }

        /* Delete button — hide default, we use our own */
        #drawflowCanvas .drawflow-delete {
            display: none !important;
        }

        /* Hide default Drawflow title bar */
        #drawflowCanvas .drawflow_content_node {
            width: 100%;
        }

        /* Node action bar */
        .df-node-actions {
            display: flex;
            justify-content: flex-end;
            gap: 3px;
            padding: 0 8px 6px;
            opacity: 0;
            transition: opacity 0.15s;
        }
        #drawflowCanvas .drawflow-node:hover .df-node-actions {
            opacity: 1;
        }
        .df-node-action {
            width: 24px; height: 24px; border-radius: 6px;
            border: 1px solid var(--node-action-border, #555);
            background: var(--node-action-bg, #333);
            color: var(--canvas-text-muted, #aaa);
            display: flex; align-items: center; justify-content: center;
            font-size: 11px; cursor: pointer; transition: all 0.1s;
        }
        .df-node-action:hover {
            color: var(--canvas-text, #fff);
            border-color: var(--canvas-text-muted, #888);
        }
        .df-node-action.delete:hover {
            background: #4a2a2a; color: #f87171; border-color: #f87171;
        }

        /* Zoom controls overlay */
        .df-zoom-controls {
            position: absolute;
            top: 12px;
            left: 12px;
            display: flex;
            gap: 4px;
            background: var(--node-bg, #2a2a2a);
            border: 1px solid var(--node-border, #444);
            border-radius: 10px;
            padding: 4px;
            z-index: 10;
        }
        .df-zoom-btn {
            width: 30px; height: 30px; border-radius: 7px;
            border: none;
            background: transparent;
            color: var(--canvas-text, #e0e0e0);
            font-size: 14px;
            cursor: pointer;
            display: flex; align-items: center; justify-content: center;
            transition: background 0.1s;
        }
        .df-zoom-btn:hover {
            background: var(--node-action-bg, #333);
        }
        .df-zoom-label {
            display: flex; align-items: center;
            font-size: 11px; color: var(--canvas-text-muted, #888);
            padding: 0 4px;
            min-width: 36px; justify-content: center;
        }

        /* Theme switcher for 2D canvas */
        .df-theme-switcher {
            position: absolute;
            top: 12px;
            right: 12px;
            display: flex;
            gap: 12px;
            z-index: 10;
            background: var(--node-bg, #2a2a2a);
            border: 1px solid var(--node-border, #444);
            border-radius: 10px;
            padding: 6px 10px;
        }
        .df-theme-btn {
            width: 20px; height: 20px; border-radius: 50%;
            border: 2px solid var(--node-border, #555);
            cursor: pointer; transition: transform 0.15s;
        }
        .df-color-pick {
            display: flex;
            align-items: center;
            gap: 4px;
            cursor: pointer;
            color: var(--canvas-text-muted, #888);
            font-size: 13px;
        }
        .df-color-pick input[type="color"] {
            width: 22px; height: 22px;
            border: 2px solid var(--node-border, #555);
            border-radius: 50%;
            padding: 0;
            cursor: pointer;
            background: none;
            -webkit-appearance: none;
        }
        .df-color-pick input[type="color"]::-webkit-color-swatch-wrapper { padding: 0; }
        .df-color-pick input[type="color"]::-webkit-color-swatch { border: none; border-radius: 50%; }

        /* Diamond shape for decision nodes — perfect square rotated 45° */
        #drawflowCanvas .drawflow-node.df-decision {
            background: transparent;
            border: none;
            min-width: 140px;
            width: 140px;
            height: 140px;
        }
        .df-diamond-wrap {
            position: relative;
            width: 120px;
            height: 120px;
            margin: 10px auto 0;
        }
        .df-diamond {
            position: absolute;
            top: 0; left: 0;
            width: 120px; height: 120px;
            background: var(--node-bg, #2a2a2a);
            border: 1.5px solid var(--node-border, #444);
            transform: rotate(45deg);
            border-radius: 6px;
        }
        #drawflowCanvas .drawflow-node.df-decision:hover .df-diamond {
            border-color: var(--node-hover-border, #8B6914);
            box-shadow: 0 0 0 3px rgba(139,105,20,0.15);
        }
        #drawflowCanvas .drawflow-node.df-decision.selected .df-diamond {
            border-color: #8B6914;
            box-shadow: 0 0 0 3px rgba(139,105,20,0.3);
        }
        .df-diamond-content {
            position: absolute;
            top: 0; left: 0;
            width: 120px; height: 120px;
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            text-align: center;
            z-index: 2;
        }
        .df-diamond-content .df-node-icon {
            width: 26px; height: 26px; border-radius: 6px;
            font-size: 12px; margin-bottom: 2px;
        }
        .df-diamond-content .df-node-title {
            font-size: 9px; line-height: 1.2;
            max-width: 80px; overflow: hidden; text-overflow: ellipsis;
        }
        .df-diamond-content .df-node-subtitle {
            font-size: 7px; max-width: 70px; overflow: hidden; text-overflow: ellipsis;
        }
        /* Diamond output labels — next to ports on right side */
        .df-decision .df-output-labels {
            position: absolute;
            right: -60px;
            top: 0;
            height: 100%;
            display: flex;
            flex-direction: column;
            justify-content: space-around;
            gap: 4px;
        }
        /* Diamond actions */
        .df-decision .df-node-actions {
            position: absolute;
            bottom: -22px;
            left: 50%;
            transform: translateX(-50%);
            flex-direction: row;
        }
        /* Diamond badge */
        .df-decision .df-node-badge {
            top: 0px; left: 50%; transform: translateX(-50%);
        }

        /* Decision node — use default Drawflow port positions */
    `;
    document.head.appendChild(style);
}

// ========== Build Node HTML ==========

var _decisionTypes = ['condition', 'goal_check'];
var _branchTypes = ['condition', 'goal_check', 'human_approval'];

function _isDecision(step) {
    return _decisionTypes.indexOf(step.type) !== -1;
}

function _buildNodeHtml(step, index) {
    var cfg = _stepTypeConfig[step.type] || { icon: 'gear', iconBg: '#333', iconColor: '#888', outputs: 1, outputLabels: ['next'] };
    var subtitle = typeof renderNodeSubtitle === 'function' ? renderNodeSubtitle(step) : '';

    // Action buttons (shared)
    var landingBtn = step.type === 'email'
        ? '<div class="df-node-action" onclick="event.stopPropagation();openLandingBuilder(' + index + ')" title="Landing Builder"><i class="bi bi-palette"></i></div>'
        : '';
    var actionsHtml = '<div class="df-node-actions">' +
        '<div class="df-node-action" onclick="event.stopPropagation();editStep(' + index + ')" title="Edit"><i class="bi bi-pencil"></i></div>' +
        landingBtn +
        '<div class="df-node-action delete" onclick="event.stopPropagation();_dfDeleteStep(' + index + ')" title="Delete"><i class="bi bi-trash"></i></div>' +
        '</div>';

    // Output labels
    var outputsHtml = '';
    var outputs = _getOutputCount(step);
    if (outputs > 1) {
        outputsHtml += '<div class="df-output-labels">';
        cfg.outputLabels.forEach(function(label) {
            outputsHtml += '<span class="df-output-label ' + label.replace(/\s+/g, '-') + '">' + label + '</span>';
        });
        outputsHtml += '</div>';
    }
    if (step.type === 'email' && step.config && step.config.wait_for_landing) {
        outputsHtml += '<div class="df-output-labels">';
        outputsHtml += '<span class="df-output-label filled">filled</span>';
        outputsHtml += '<span class="df-output-label timeout">timeout</span>';
        outputsHtml += '</div>';
    }

    // Decision nodes — diamond shape
    if (_isDecision(step)) {
        var html = '<div class="df-node-badge">' + (index + 1) + '</div>';
        html += '<div class="df-diamond-wrap">';
        html += '<div class="df-diamond"></div>';
        html += '<div class="df-diamond-content">';
        html += '<div class="df-node-icon" style="background:' + cfg.iconBg + ';color:' + cfg.iconColor + '">';
        html += '<i class="bi bi-' + cfg.icon + '"></i></div>';
        html += '<div class="df-node-title">' + _escHtml(step.name) + '</div>';
        html += '<div class="df-node-subtitle">' + _escHtml(subtitle) + '</div>';
        html += '</div></div>';
        html += actionsHtml;
        html += outputsHtml;
        return html;
    }

    // Regular nodes — rectangle
    var html = '<div class="df-node-badge">' + (index + 1) + '</div>';
    html += '<div class="df-node-content">';
    html += '<div class="df-node-icon" style="background:' + cfg.iconBg + ';color:' + cfg.iconColor + '">';
    html += '<i class="bi bi-' + cfg.icon + '"></i></div>';
    html += '<div class="df-node-body">';
    html += '<div class="df-node-title">' + _escHtml(step.name) + '</div>';
    html += '<div class="df-node-subtitle">' + _escHtml(subtitle) + '</div>';
    html += '</div></div>';
    html += actionsHtml;
    html += outputsHtml;
    return html;
}

function _getOutputCount(step) {
    var cfg = _stepTypeConfig[step.type] || {};
    var count = cfg.outputs || 1;
    // Email with wait_for_landing has 2 outputs
    if (step.type === 'email' && step.config && step.config.wait_for_landing) {
        count = 2;
    }
    return count;
}

function _escHtml(str) {
    if (!str) return '';
    return String(str).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

// ========== Delete Step from 2D Canvas ==========

function _dfDeleteStep(index) {
    if (!confirm('Delete this step?')) return;
    var step = workflowSteps[index];
    if (!step) return;
    var nodeId = _dfStepMap[step.id];

    workflowSteps.splice(index, 1);
    workflowSteps.forEach(function(s, i) { s.order = i + 1; });

    // Re-sync entire canvas (simpler than partial update)
    syncStepsToDrawflow();
}

// ========== Zoom Controls ==========

function _addZoomControls() {
    var wrap = document.getElementById('drawflowCanvasWrap');
    if (!wrap) return;

    // Remove existing controls
    var existing = wrap.querySelector('.df-zoom-controls');
    if (existing) existing.remove();
    var existingTheme = wrap.querySelector('.df-theme-switcher');
    if (existingTheme) existingTheme.remove();

    // Zoom controls
    var zc = document.createElement('div');
    zc.className = 'df-zoom-controls';
    zc.innerHTML = '' +
        '<button type="button" class="df-zoom-btn" onclick="_dfZoomIn()" title="Zoom In"><i class="bi bi-plus-lg"></i></button>' +
        '<div class="df-zoom-label" id="dfZoomLabel">' + Math.round((_drawflowEditor ? _drawflowEditor.zoom : 1) * 100) + '%</div>' +
        '<button type="button" class="df-zoom-btn" onclick="_dfZoomOut()" title="Zoom Out"><i class="bi bi-dash-lg"></i></button>' +
        '<button type="button" class="df-zoom-btn" onclick="_dfZoomReset()" title="Reset"><i class="bi bi-arrows-angle-contract"></i></button>' +
        '<button type="button" class="df-zoom-btn" onclick="_dfZoomFit()" title="Fit All"><i class="bi bi-fullscreen"></i></button>' +
        '<div style="width:1px;height:20px;background:var(--node-border,#444);margin:0 2px"></div>' +
        '<button type="button" class="df-zoom-btn" onclick="_dfAutoLayout()" title="Auto Layout"><i class="bi bi-grid-3x3-gap"></i></button>';
    wrap.style.position = 'relative';
    wrap.appendChild(zc);

    // Color pickers for canvas and palette
    var ts = document.createElement('div');
    ts.className = 'df-theme-switcher';
    var savedCanvasBg = localStorage.getItem('df_canvas_bg') || '';
    var savedPaletteBg = localStorage.getItem('df_palette_bg') || '';
    ts.innerHTML = '' +
        '<label class="df-color-pick" title="Canvas background">' +
            '<i class="bi bi-palette"></i>' +
            '<input type="color" value="' + (savedCanvasBg || '#1a1a1a') + '" onchange="_dfSetCanvasColor(this.value)">' +
        '</label>' +
        '<label class="df-color-pick" title="Step palette background">' +
            '<i class="bi bi-list-ul"></i>' +
            '<input type="color" value="' + (savedPaletteBg || '#222222') + '" onchange="_dfSetPaletteColor(this.value)">' +
        '</label>';
    wrap.appendChild(ts);

    // Apply saved colors
    if (savedCanvasBg) _dfSetCanvasColor(savedCanvasBg);
    if (savedPaletteBg) _dfSetPaletteColor(savedPaletteBg);
}

function _dfSetCanvasColor(color) {
    var canvas = document.getElementById('drawflowCanvas');
    if (canvas) canvas.style.background = color;
    // Also update dot grid color based on brightness
    var r = parseInt(color.slice(1,3),16), g = parseInt(color.slice(3,5),16), b = parseInt(color.slice(5,7),16);
    var bright = (r*299 + g*587 + b*114) / 1000;
    var dotColor = bright > 128 ? 'rgba(0,0,0,0.15)' : 'rgba(255,255,255,0.08)';
    var drawflow = canvas.querySelector('.drawflow');
    if (drawflow) {
        drawflow.style.backgroundImage = 'radial-gradient(circle, ' + dotColor + ' 1px, transparent 1px)';
        drawflow.style.backgroundSize = '20px 20px';
    }
    localStorage.setItem('df_canvas_bg', color);
}

function _dfSetPaletteColor(color) {
    var palette = document.querySelector('.step-palette');
    if (palette) palette.style.background = color;
    localStorage.setItem('df_palette_bg', color);
}

function _updateZoomLabel() {
    var label = document.getElementById('dfZoomLabel');
    if (label && _drawflowEditor) {
        label.textContent = Math.round(_drawflowEditor.zoom * 100) + '%';
    }
}

function _dfZoomIn() {
    if (!_drawflowEditor) return;
    _drawflowEditor.zoom_in();
    _updateZoomLabel();
}

function _dfZoomOut() {
    if (!_drawflowEditor) return;
    _drawflowEditor.zoom_out();
    _updateZoomLabel();
}

function _dfZoomReset() {
    if (!_drawflowEditor) return;
    _drawflowEditor.zoom_reset();
    _updateZoomLabel();
}

function _dfZoomFit() {
    if (!_drawflowEditor) return;

    var data = _drawflowEditor.export();
    var nodes = data.drawflow.Home.data;
    var keys = Object.keys(nodes);
    if (keys.length === 0) return;

    // Find bounding box of all nodes
    var minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
    keys.forEach(function(k) {
        var n = nodes[k];
        minX = Math.min(minX, n.pos_x);
        minY = Math.min(minY, n.pos_y);
        maxX = Math.max(maxX, n.pos_x + 240); // approximate node width
        maxY = Math.max(maxY, n.pos_y + 120);  // approximate node height
    });

    var canvasEl = document.getElementById('drawflowCanvas');
    var cw = canvasEl.offsetWidth;
    var ch = canvasEl.offsetHeight;

    var graphW = maxX - minX;
    var graphH = maxY - minY;
    if (graphW < 1) graphW = 1;
    if (graphH < 1) graphH = 1;

    // Calculate zoom to fit with padding
    var pad = 80;
    var zoom = Math.min((cw - pad) / graphW, (ch - pad) / graphH);
    zoom = Math.max(0.15, Math.min(zoom, 1.0));

    // Calculate translate to center the graph
    var translateX = (cw / 2) - ((minX + maxX) / 2) * zoom;
    var translateY = (ch / 2) - ((minY + maxY) / 2) * zoom;

    // Apply to Drawflow
    _drawflowEditor.zoom = zoom;
    _drawflowEditor.canvas_x = translateX;
    _drawflowEditor.canvas_y = translateY;

    var precanvas = canvasEl.querySelector('.drawflow');
    if (precanvas) {
        precanvas.style.transform = 'translate(' + translateX + 'px, ' + translateY + 'px) scale(' + zoom + ')';
    }
    _updateZoomLabel();
}

// ========== Auto Layout ==========

function _dfAutoLayout() {
    if (!_drawflowEditor || workflowSteps.length === 0) return;

    // Clear saved positions so sync uses fresh centered layout
    workflowSteps.forEach(function(step) {
        delete step._dfPos;
    });

    // Re-sync with default centered layout
    syncStepsToDrawflow();
    _addZoomControls();

    // Fit view
    setTimeout(_dfZoomFit, 150);
}

// ========== Sync Steps ↔ Drawflow ==========

function syncStepsToDrawflow() {
    if (!_drawflowEditor) return;

    _drawflowEditor.clear();
    _dfNodeMap = {};
    _dfStepMap = {};

    if (workflowSteps.length === 0) return;

    // Layout constants — horizontal left-to-right
    var spacingX = 280;
    var centerY = 200;  // vertical center for main flow
    var x = 40;

    // Create START node
    var startId = _drawflowEditor.addNode('start', 0, 1, x, centerY - 20, 'start-node', {},
        '<div class="df-pill start"><i class="bi bi-play-fill"></i> START</div>');
    x += 160;

    var prevNodeId = startId;
    var prevOutput = 1;

    // Create step nodes
    workflowSteps.forEach(function(step, index) {
        var outputs = _getOutputCount(step);
        var savedPos = step._dfPos;
        var isDec = _isDecision(step);
        var posX = savedPos ? savedPos.x : x;
        var posY = savedPos ? savedPos.y : centerY - (isDec ? 70 : 30);

        var nodeClass = isDec ? 'df-decision' : '';
        var nodeId = _drawflowEditor.addNode(
            'step_' + step.type,
            1, outputs,
            posX, posY,
            nodeClass,
            { stepIndex: index },
            _buildNodeHtml(step, index)
        );

        _dfNodeMap[nodeId] = index;
        _dfStepMap[step.id] = nodeId;

        // Auto-connect from previous (only if previous output isn't a jump)
        if (prevNodeId !== null && prevOutput > 0) {
            try {
                _drawflowEditor.addConnection(prevNodeId, nodeId, 'output_' + prevOutput, 'input_1');
            } catch(e) {}
        }

        // Determine which output continues the linear chain
        // Default: output_1 goes to next step linearly
        prevNodeId = nodeId;
        prevOutput = 1;

        // Jump connections for branching nodes
        if (outputs > 1) {
            var jumpOutputs = _addJumpConnections(step, nodeId, index);
            // If output_1 has a jump, the linear chain continues from output_2 (or stops)
            if (jumpOutputs.indexOf(1) !== -1 && jumpOutputs.indexOf(2) === -1) {
                prevOutput = 2; // linear chain uses the non-jump output
            } else if (jumpOutputs.indexOf(1) !== -1 && jumpOutputs.indexOf(2) !== -1) {
                prevOutput = 0; // both outputs are jumps, no linear chain
            }
        }

        x += isDec ? spacingX + 40 : spacingX;
    });

    // Create END node
    var endId = _drawflowEditor.addNode('end', 1, 0, x, centerY - 20, 'end-node', {},
        '<div class="df-pill end"><i class="bi bi-stop-fill"></i> END</div>');

    if (prevNodeId && prevOutput > 0) {
        try {
            _drawflowEditor.addConnection(prevNodeId, endId, 'output_' + prevOutput, 'input_1');
        } catch(e) {}
    }

    // Mark jump connections with df-jump class after all are rendered
    setTimeout(_markJumpConnections, 50);
}

function _markJumpConnections() {
    var conns = document.querySelectorAll('#drawflowCanvas svg.connection');
    conns.forEach(function(conn) {
        // Drawflow connection classes contain output_X info
        var cls = conn.getAttribute('class') || '';
        if (cls.indexOf('output_2') !== -1) {
            conn.classList.add('df-jump');
        }
        // Also check backward connections
        var nodeOutMatch = cls.match(/node_out_node-(\d+)/);
        var nodeInMatch = cls.match(/node_in_node-(\d+)/);
        if (nodeOutMatch && nodeInMatch) {
            var outNode = document.getElementById('node-' + nodeOutMatch[1]);
            var inNode = document.getElementById('node-' + nodeInMatch[1]);
            if (outNode && inNode) {
                var outX = parseFloat(outNode.style.left) || 0;
                var inX = parseFloat(inNode.style.left) || 0;
                if (inX < outX - 50) {
                    conn.classList.add('df-jump');
                }
            }
        }
    });
}

function _addJumpConnections(step, nodeId, index) {
    // For condition: output_1 = true, output_2 = false
    // For goal_check: output_1 = met, output_2 = not met
    // For human_approval: output_1 = approved, output_2 = rejected
    // For email with wait_for_landing: output_1 = filled, output_2 = timeout

    var jumpConfigs = [];

    if (step.type === 'condition') {
        if (step.config.if_true === 'jump' && step.config.if_true_step) {
            jumpConfigs.push({ output: 1, targetOrder: step.config.if_true_step });
        }
        if (step.config.if_false === 'jump' && step.config.if_false_step) {
            jumpConfigs.push({ output: 2, targetOrder: step.config.if_false_step });
        }
    } else if (step.type === 'goal_check') {
        if (step.config.if_met === 'jump' && step.config.if_met_step) {
            jumpConfigs.push({ output: 1, targetOrder: step.config.if_met_step });
        }
        if (step.config.if_not_met === 'jump' && step.config.if_not_met_step) {
            jumpConfigs.push({ output: 2, targetOrder: step.config.if_not_met_step });
        }
    } else if (step.type === 'human_approval') {
        if (step.config.if_approved === 'jump' && step.config.if_approved_step) {
            jumpConfigs.push({ output: 1, targetOrder: step.config.if_approved_step });
        }
        if (step.config.if_rejected === 'jump' && step.config.if_rejected_step) {
            jumpConfigs.push({ output: 2, targetOrder: step.config.if_rejected_step });
        }
    } else if (step.type === 'email' && step.config.wait_for_landing) {
        if (step.config.landing_if_filled === 'jump' && step.config.landing_if_filled_step) {
            jumpConfigs.push({ output: 1, targetOrder: step.config.landing_if_filled_step });
        }
        if (step.config.landing_if_timeout === 'jump' && step.config.landing_if_timeout_step) {
            jumpConfigs.push({ output: 2, targetOrder: step.config.landing_if_timeout_step });
        }
    }

    var jumpedOutputs = [];
    jumpConfigs.forEach(function(jc) {
        jumpedOutputs.push(jc.output);
        // Find target step by order
        var targetStep = workflowSteps.find(function(s) { return s.order === jc.targetOrder; });
        if (targetStep && _dfStepMap[targetStep.id]) {
            try {
                _drawflowEditor.addConnection(nodeId, _dfStepMap[targetStep.id], 'output_' + jc.output, 'input_1');
            } catch(e) {}
        }
    });
    return jumpedOutputs;
}

// ========== Sync Connections → Steps ==========

function _syncConnectionsToSteps() {
    // Read connections from Drawflow and update step configs
    // This is called when user manually creates/removes connections
    // For now we keep it simple — manual connections don't change step config
    // The step config is the source of truth, connections are visual
}

// ========== Node Position Persistence ==========

function _saveNodePositions() {
    if (!_drawflowEditor) return;
    var data = _drawflowEditor.export();
    var nodes = data.drawflow.Home.data;
    Object.keys(nodes).forEach(function(nodeId) {
        var node = nodes[nodeId];
        var stepIndex = _dfNodeMap[nodeId];
        if (stepIndex !== undefined && workflowSteps[stepIndex]) {
            workflowSteps[stepIndex]._dfPos = { x: node.pos_x, y: node.pos_y };
        }
    });
}

function _rebuildNodeMaps() {
    _dfNodeMap = {};
    _dfStepMap = {};
    if (!_drawflowEditor) return;
    var data = _drawflowEditor.export();
    var nodes = data.drawflow.Home.data;
    Object.keys(nodes).forEach(function(nodeId) {
        var node = nodes[nodeId];
        if (node.data && node.data.stepIndex !== undefined) {
            _dfNodeMap[nodeId] = node.data.stepIndex;
            if (workflowSteps[node.data.stepIndex]) {
                _dfStepMap[workflowSteps[node.data.stepIndex].id] = parseInt(nodeId);
            }
        }
    });
}

// ========== Palette Drag → Drawflow ==========

function _setupPaletteDragForDrawflow() {
    document.querySelectorAll('.step-template').forEach(function(tpl) {
        tpl.addEventListener('dragend', function(e) {
            if (_canvasMode !== '2d' || !_drawflowEditor) return;

            var canvasEl = document.getElementById('drawflowCanvas');
            var rect = canvasEl.getBoundingClientRect();

            // Check if dropped inside canvas
            if (e.clientX >= rect.left && e.clientX <= rect.right &&
                e.clientY >= rect.top && e.clientY <= rect.bottom) {

                var type = tpl.dataset.type;
                if (!type) return;

                // Calculate position in Drawflow coordinates
                var zoom = _drawflowEditor.zoom;
                var x = (e.clientX - rect.left) / zoom + _drawflowEditor.canvas_x * -1 / zoom;
                var y = (e.clientY - rect.top) / zoom + _drawflowEditor.canvas_y * -1 / zoom;

                // Create step in workflowSteps array
                var step = {
                    id: Date.now(),
                    type: type,
                    order: workflowSteps.length + 1,
                    name: capitalize(type) + ' Step ' + (workflowSteps.length + 1),
                    config: getDefaultConfig(type),
                    _dfPos: { x: x, y: y }
                };
                workflowSteps.push(step);

                // Add node to Drawflow
                var outputs = _getOutputCount(step);
                var nodeClass = _isDecision(step) ? 'df-decision' : (type === 'human_approval' ? 'df-branch' : '');
                var nodeId = _drawflowEditor.addNode(
                    'step_' + type, 1, outputs, x, y, nodeClass,
                    { stepIndex: workflowSteps.length - 1 },
                    _buildNodeHtml(step, workflowSteps.length - 1)
                );
                _dfNodeMap[nodeId] = workflowSteps.length - 1;
                _dfStepMap[step.id] = nodeId;

                // Open edit modal
                setTimeout(function() {
                    editStep(workflowSteps.length - 1);
                }, 200);
            }
        });
    });
}

// ========== Refresh Node Content ==========

function refreshDrawflowNode(stepIndex) {
    if (!_drawflowEditor || _canvasMode !== '2d') return;
    var step = workflowSteps[stepIndex];
    if (!step) return;
    var nodeId = _dfStepMap[step.id];
    if (!nodeId) return;

    var el = document.querySelector('#node-' + nodeId + ' .drawflow_content_node');
    if (el) {
        el.innerHTML = _buildNodeHtml(step, stepIndex);
    }
}

// Hook into saveStepEdit to refresh 2D canvas
document.addEventListener('DOMContentLoaded', function() {
    if (typeof saveStepEdit === 'function' && !saveStepEdit._hooked2d) {
        var _orig = saveStepEdit;
        saveStepEdit = function() {
            // Capture output count before edit
            var prevOutputs = 0;
            var idx = editingBranchContext ? editingBranchContext.parentIndex : editingStepIndex;
            if (idx !== null && workflowSteps[idx]) {
                prevOutputs = _getOutputCount(workflowSteps[idx]);
            }

            _orig.apply(this, arguments);

            // After save, refresh the 2D canvas
            if (_canvasMode === '2d' && idx !== null && workflowSteps[idx]) {
                var newOutputs = _getOutputCount(workflowSteps[idx]);
                if (newOutputs !== prevOutputs) {
                    // Output count changed — full re-sync needed
                    _saveNodePositions();
                    syncStepsToDrawflow();
                    _addZoomControls();
                } else {
                    refreshDrawflowNode(idx);
                }
            }
        };
        saveStepEdit._hooked2d = true;
    }
});
