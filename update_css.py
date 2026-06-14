#!/usr/bin/env python3
"""Update style.css with missing styles for new features."""

import re

with open('app/static/css/style.css', 'r', encoding='utf-8') as f:
    css = f.read()

# 1. Add sorting styles after .risk-table th block
sorting_styles = """
.risk-table th.sortable {
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
"""

# Insert after .risk-table th block
th_pattern = r'(.risk-table th \{[^}]+\})'
match = re.search(th_pattern, css, re.DOTALL)
if match:
    # Check if sorting styles already exist
    if '.risk-table th.sortable' not in css:
        insert_pos = match.end()
        css = css[:insert_pos] + sorting_styles + css[insert_pos:]

# 2. Add highlight styles after .risk-table td block
highlight_styles = """
/* Highlight cells */
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
"""

td_pattern = r'(.risk-table td \{[^}]+\})'
match = re.search(td_pattern, css, re.DOTALL)
if match and '.risk-table td.highlight' not in css:
    insert_pos = match.end()
    css = css[:insert_pos] + highlight_styles + css[insert_pos:]

# 3. Add table-controls styles after .pagination section
table_controls_styles = """
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
"""

# Find pagination section and insert after it
pagination_pattern = r'(\.page-info \{[^}]+\})'
match = re.search(pagination_pattern, css, re.DOTALL)
if match and '.table-controls' not in css:
    insert_pos = match.end()
    css = css[:insert_pos] + table_controls_styles + css[insert_pos:]

# 4. Add player-row and factors-row styles (after factors-row td section)
factors_styles = """
/* Player row click */
.player-row {
    cursor: pointer;
    transition: background 0.15s ease;
}

.player-row:hover {
    background: rgba(233, 69, 96, 0.08);
}

/* Collapsible factors row */
.factors-row.collapsed {
    display: none;
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
"""

# Find factors-row td and insert after
factors_pattern = r'(\.factors-row td \{[^}]+\})'
match = re.search(factors_pattern, css, re.DOTALL)
if match and '.player-row' not in css:
    insert_pos = match.end()
    css = css[:insert_pos] + factors_styles + css[insert_pos:]

# Write back
with open('app/static/css/style.css', 'w', encoding='utf-8') as f:
    f.write(css)

print("CSS updated successfully!")
print("Added styles for: sorting, highlight cells, table controls, player row click, factors row collapse")
