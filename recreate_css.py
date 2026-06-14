#!/usr/bin/env python3
"""Recreate style.css with all styles including new features."""

css_content = """body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    background: #0f0f23;
    color: #e0e0e0;
    margin: 0;
    padding: 0;
    line-height: 1.6;
}

/* Navigation Bar */
.navbar {
    background: #1a1a3e;
    border-bottom: 2px solid #e94560;
    padding: 0 24px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    position: sticky;
    top: 0;
    z-index: 100;
}

.nav-brand {
    color: #e94560;
    font-size: 20px;
    font-weight: bold;
    padding: 14px 0;
}

.nav-links {
    display: flex;
    gap: 8px;
}

.nav-links a {
    color: #a0a0c0;
    text-decoration: none;
    padding: 14px 18px;
    border-radius: 4px 4px 0 0;
    transition: all 0.2s;
    border-bottom: 3px solid transparent;
}

.nav-links a:hover {
    color: #e94560;
    background: rgba(233, 69, 96, 0.1);
}

.nav-links a.active {
    color: #e94560;
    border-bottom-color: #e94560;
}

/* Container */
.container {
    max-width: 1200px;
    margin: 0 auto;
    padding: 24px;
}

/* Headings */
h1, h2, h3 {
    color: #e94560;
}

h1 { font-size: 28px; margin-bottom: 16px; }
h2 { font-size: 22px; margin-bottom: 12px; }
h3 { font-size: 18px; margin-bottom: 8px; }

/* Upload Form */
.upload-form {
    background: #16213e;
    padding: 24px;
    border-radius: 8px;
    margin-bottom: 24px;
    border: 1px solid #0f3460;
}

/* Buttons */
button, .match-btn, .page-btn {
    background: #e94560;
    color: white;
    border: none;
    padding: 12px 24px;
    border-radius: 4px;
    cursor: pointer;
    font-size: 16px;
    text-decoration: none;
    display: inline-block;
    transition: background 0.2s;
}

button:hover, .match-btn:hover, .page-btn:hover {
    background: #c73e54;
}

button:disabled {
    background: #555;
    cursor: not-allowed;
}

.btn-save {
    background: #2ecc71;
}

.btn-save:hover {
    background: #27ae60;
}

/* Progress Bar */
.progress-container {
    margin: 16px 0;
}

.progress-bar {
    position: relative;
    height: 32px;
    background: #1a1a3e;
    border-radius: 6px;
    overflow: hidden;
    border: 1px solid #0f3460;
}

.progress-fill {
    height: 100%;
    background: #e94560;
    transition: width 0.5s ease;
    border-radius: 6px;
}

.progress-text {
    position: absolute;
    top: 0;
    left: 12px;
    line-height: 32px;
    font-size: 14px;
    font-weight: bold;
    color: white;
    text-shadow: 0 1px 2px rgba(0,0,0,0.7);
}

/* Summary Cards */
.summary-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
    gap: 16px;
    margin-bottom: 24px;
}

.summary-card {
    background: #1a1a3e;
    padding: 16px;
    border-radius: 8px;
    text-align: center;
    border: 1px solid #0f3460;
}

.summary-value {
    display: block;
    font-size: 28px;
    font-weight: bold;
    color: #e94560;
}

.summary-label {
    display: block;
    font-size: 13px;
    color: #a0a0c0;
    margin-top: 4px;
}

.flagged-card .summary-value { color: #f39c12; }
.danger-card .summary-value { color: #e74c3c; }

/* Match Info */
.match-info {
    background: #16213e;
    padding: 20px;
    border-radius: 8px;
    margin-bottom: 24px;
    border: 1px solid #0f3460;
}

.match-info h2 { margin-top: 0; }

.match-narrative {
    color: #a0a0c0;
    font-style: italic;
    margin-top: 12px;
    padding-top: 12px;
    border-top: 1px solid #0f3460;
}

/* Legend */
.legend {
    display: flex;
    gap: 20px;
    margin-bottom: 16px;
    flex-wrap: wrap;
}

.legend-item {
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: 14px;
    color: #a0a0c0;
}

.legend-color {
    width: 16px;
    height: 16px;
    border-radius: 4px;
    display: inline-block;
}

/* Risk Table - High Contrast */
.risk-table {
    width: 100%;
    border-collapse: separate;
    border-spacing: 0;
    margin-top: 16px;
    background: #16213e;
    border-radius: 8px;
    overflow: hidden;
}

.risk-table thead {
    background: #1a1a3e;
}

.risk-table th {
    padding: 14px 12px;
    text-align: left;
    color: #e94560;
    font-weight: 600;
    border-bottom: 2px solid #e94560;
    font-size: 14px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    cursor: pointer;
    user-select: none;
}

.risk-table th.sortable:hover {
    background: rgba(233, 69, 96, 0.1);
}

.risk-table th.sorted-asc::after {
    content: " ↑";
    font-size: 10px;
}

.risk-table th.sorted-desc::after {
    content: " ↓";
    font-size: 10px;
}

.risk-table td {
    padding: 12px;
    text-align: left;
    border-bottom: 1px solid #0f3460;
    color: #e0e0e0;
}

.risk-table td.highlight {
    background: rgba(231, 76, 60, 0.25);
    font-weight: 600;
    position: relative;
}

.risk-table td.highlight::before {
    content: "";
    position: absolute;
    left: 0;
    top: 0;
    bottom: 0;
    width: 3px;
    background: #e74c3c;
}

.risk-table tbody tr:hover {
    background: rgba(233, 69, 96, 0.05);
}

.risk-table tbody tr.flagged {
    background: rgba(231, 76, 60, 0.15);
    border-left: 4px solid #e74c3c;
}

.risk-table tbody tr.flagged td:first-child {
    border-left: 4px solid #e74c3c;
}

/* Risk Bar */
.risk-bar {
    position: relative;
    height: 24px;
    background: #1a1a3e;
    border-radius: 6px;
    overflow: hidden;
    border: 1px solid #333;
}

.risk-fill {
    height: 100%;
    transition: width 0.5s ease;
}

.risk-bar span {
    position: absolute;
    top: 0;
    left: 8px;
    line-height: 24px;
    font-size: 13px;
    font-weight: bold;
    color: white;
    text-shadow: 0 1px 2px rgba(0,0,0,0.7);
}

/* Table Controls */
.table-controls {
    display: flex;
    gap: 8px;
    margin-bottom: 12px;
    flex-wrap: wrap;
}

.sort-label {
    color: #a0a0c0;
    font-size: 14px;
    display: flex;
    align-items: center;
}

.sort-btn {
    background: #1a1a3e;
    color: #e0e0e0;
    border: 1px solid #0f3460;
    padding: 6px 12px;
    border-radius: 4px;
    cursor: pointer;
    font-size: 13px;
    transition: all 0.2s;
}

.sort-btn:hover {
    background: #16213e;
    border-color: #e94560;
}

.sort-btn.active {
    background: #e94560;
    color: white;
    border-color: #e94560;
}

/* Explanations */
.explanations {
    margin-top: 30px;
    padding-top: 20px;
    border-top: 1px solid #0f3460;
}

.explanation-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
    gap: 16px;
    margin-top: 16px;
}

.exp-card {
    background: #16213e;
    padding: 16px;
    border-radius: 8px;
    border: 1px solid #0f3460;
    font-size: 14px;
    line-height: 1.6;
}

.exp-card strong {
    color: #e94560;
}

/* Dataset Browser */
.dataset-tabs {
    display: flex;
    gap: 8px;
    margin-bottom: 20px;
}

.dataset-tabs a {
    padding: 10px 20px;
    background: #16213e;
    color: #a0a0c0;
    text-decoration: none;
    border-radius: 6px;
    border: 1px solid #0f3460;
}

.dataset-tabs a:hover, .dataset-tabs a.active {
    background: #e94560;
    color: white;
    border-color: #e94560;
}

.match-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
    gap: 16px;
    margin-bottom: 24px;
}

.match-card {
    background: #16213e;
    border-radius: 8px;
    padding: 16px;
    border: 2px solid #0f3460;
    display: flex;
    flex-direction: column;
}

.match-card.cheat {
    border-color: rgba(231, 76, 60, 0.5);
}

.match-card.clean {
    border-color: rgba(46, 204, 113, 0.3);
}

.match-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 12px;
}

.match-badge {
    font-size: 13px;
    font-weight: 600;
}

.match-id {
    color: #a0a0c0;
    font-size: 13px;
}

.match-body {
    flex: 1;
    margin-bottom: 12px;
}

.match-body p {
    margin: 4px 0;
    font-size: 14px;
    color: #a0a0c0;
}

.cached-badge {
    display: inline-block;
    background: #f39c12;
    color: #000;
    font-size: 11px;
    padding: 2px 8px;
    border-radius: 4px;
    margin-top: 8px;
}

/* Pagination */
.pagination {
    display: flex;
    justify-content: center;
    align-items: center;
    gap: 16px;
    margin-top: 24px;
}

.page-info {
    color: #a0a0c0;
}

/* Settings */
.settings-grid {
    display: grid;
    grid-template-columns: 1fr;
    gap: 24px;
}

.settings-section {
    background: #16213e;
    padding: 24px;
    border-radius: 8px;
    border: 1px solid #0f3460;
}

.settings-section h2 {
    margin-top: 0;
    color: #ff6b8a;
}

.stat-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
    gap: 16px;
}

.stat-card {
    background: #1a1a3e;
    padding: 16px;
    border-radius: 8px;
    text-align: center;
}

.stat-value {
    display: block;
    font-size: 28px;
    font-weight: bold;
    color: #e94560;
}

.stat-label {
    display: block;
    font-size: 13px;
    color: #a0a0c0;
    margin-top: 4px;
}

.settings-table {
    width: 100%;
    border-collapse: collapse;
}

.settings-table td {
    padding: 12px;
    border-bottom: 1px solid #0f3460;
}

.settings-table td:first-child {
    color: #a0a0c0;
    width: 40%;
}

/* Feature Importance */
.feature-importance {
    margin-top: 16px;
}

.fi-row {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 8px 0;
}

.fi-name {
    width: 200px;
    font-size: 14px;
    color: #e0e0e0;
}

.fi-bar-container {
    flex: 1;
    height: 20px;
    background: #1a1a3e;
    border-radius: 4px;
    overflow: hidden;
}

.fi-bar {
    height: 100%;
    background: #e94560;
    border-radius: 4px;
}

.fi-value {
    width: 60px;
    text-align: right;
    font-size: 13px;
    color: #a0a0c0;
}

/* Forms */
.form-group {
    margin-bottom: 20px;
}

.form-group label {
    display: block;
    margin-bottom: 8px;
    color: #e0e0e0;
    font-weight: 500;
}

.form-group input[type="number"], .form-group input[type="text"] {
    width: 200px;
    padding: 10px 14px;
    background: #1a1a3e;
    border: 1px solid #0f3460;
    border-radius: 6px;
    color: #e0e0e0;
    font-size: 15px;
}

.form-group input:disabled {
    background: #2a2a4e;
    color: #777;
    cursor: not-allowed;
}

.form-group small {
    display: block;
    margin-top: 6px;
    color: #777;
    font-size: 13px;
}

.locked-badge {
    display: inline-block;
    background: #f39c12;
    color: #000;
    font-size: 11px;
    padding: 2px 8px;
    border-radius: 4px;
    margin-left: 8px;
}

.hint {
    color: #777;
    font-size: 14px;
    margin-top: 12px;
}

/* Status colors */
.status-done { color: #2ecc71; font-weight: bold; }
.status-error { color: #e74c3c; font-weight: bold; }
.status-pending { color: #f39c12; }
.status-processing { color: #3498db; }

/* Warning */
.warning {
    background: rgba(231, 76, 60, 0.2);
    border: 1px solid #e74c3c;
    padding: 16px;
    border-radius: 8px;
    color: #e74c3c;
}

/* Polling Progress */
.polling-progress {
    width: 100%;
    max-width: 500px;
    height: 24px;
    background: #1a1a3e;
    border-radius: 12px;
    overflow: hidden;
    margin: 20px auto;
    border: 1px solid #0f3460;
}

.polling-bar {
    height: 100%;
    width: 0%;
    background: #e94560;
    border-radius: 12px;
    transition: width 1.2s ease-out;
}

#pollingStatus {
    text-align: center;
    color: #a0a0c0;
    font-size: 14px;
    margin-top: 8px;
}

/* Match Events Log */
.match-events {
    background: #16213e;
    padding: 20px;
    border-radius: 8px;
    margin-top: 40px;
    margin-bottom: 24px;
    border: 1px solid #0f3460;
}

.match-events h2 {
    margin-top: 0;
}

.events-log {
    background: #1a1a3e;
    border-radius: 6px;
    padding: 12px;
}

.event-item {
    display: flex;
    gap: 12px;
    padding: 8px 0;
    border-bottom: 1px solid #0f3460;
    font-size: 14px;
}

.event-item:last-child {
    border-bottom: none;
}

.event-time {
    color: #a0a0c0;
    font-family: monospace;
    min-width: 60px;
    flex-shrink: 0;
    font-size: 13px;
}

.event-separator {
    height: 1px;
    background: linear-gradient(to right, transparent, #e94560, transparent);
    margin: 2px 0;
    border-radius: 1px;
}

.event-desc {
    color: #e0e0e0;
}

.event-item.kill {
    border-left: 3px solid #e74c3c;
    padding-left: 8px;
}

.event-item.headshot {
    border-left: 3px solid #f39c12;
    padding-left: 8px;
}

.event-item.round {
    border-left: 3px solid #3498db;
    padding-left: 8px;
}

/* Player Factors */
.factors-row {
    background: rgba(233, 69, 96, 0.05);
}

.factors-row.collapsed {
    display: none;
}

.factors-row td {
    padding: 8px 12px;
    border-bottom: 1px solid #0f3460;
}

.player-row {
    cursor: pointer;
    transition: background 0.15s ease;
}

.player-row:hover {
    background: rgba(233, 69, 96, 0.08);
}

.player-factors {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    align-items: center;
    font-size: 13px;
}

.factor-tag {
    background: #1a1a3e;
    border: 1px solid #e94560;
    color: #e0e0e0;
    padding: 4px 10px;
    border-radius: 4px;
    font-size: 12px;
    cursor: help;
}

/* SHAP contributions */
.shap-section {
    margin-bottom: 8px;
}

.shap-group {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    align-items: center;
    margin-bottom: 6px;
}

.shap-label {
    font-size: 12px;
    font-weight: 600;
    margin-right: 4px;
    white-space: nowrap;
}

.shap-label.shap-pos {
    color: #e74c3c;
}

.shap-label.shap-neg {
    color: #2ecc71;
}

.factor-tag.factor-pos {
    border-color: #e74c3c;
    color: #ff9f9f;
}

.factor-tag.factor-neg {
    border-color: #2ecc71;
    color: #7ee8a8;
}

/* Footer */
.footer {
    text-align: center;
    padding: 20px;
    color: #555;
    font-size: 13px;
    border-top: 1px solid #1a1a3e;
    margin-top: 40px;
}

a { color: #e94560; }
a:hover { color: #ff6b8a; }

/* File info */
#fileInfo { margin-top: 10px; color: #a0a0c0; }

/* Spinner */
#spinner { animation: spin 1s linear infinite; display: inline-block; }
@keyframes spin { 0% { transform: rotate(0deg); } 100% { transform: rotate(360deg); } }
"""

with open('app/static/css/style.css', 'w', encoding='utf-8') as f:
    f.write(css_content)

print('CSS file recreated successfully!')
print('File length:', len(css_content))
