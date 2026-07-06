---
name: interactive-dashboard-builder
description: Provides guidelines for constructing self-contained, highly interactive HTML/CSS/JS dashboards. Focuses on data filtering, OEE and metric calculation, dynamic grid updates, state management, and clear readability.
---

# Interactive Dashboard Builder Skill

This skill governs the structure and interactivity of web-based diagnostic dashboards.

## Core Directives

1. **State Management**:
   - Maintain a single, central state object in JavaScript representing current data.
   - Render all panels, grids, and metrics reactively from this central state snapshot.

2. **Interactivity & Filtering**:
   - Provide interactive dropdowns or toggle buttons for filtering machines by production line, status, or energy intensity.
   - Keep details interactive: clicking on a machine card should display its live registers, bits, and specialized diagnostics.

3. **Data Grid & Metrics**:
   - Organize KPIs into clear, logically grouped grid sections (e.g., Performance, OEE, Energy Consumption).
   - Display absolute values alongside contextual labels (e.g., "12.4 kWh consumed / 4.2 kWh wasted").

4. **Zero-Chart Simplicity**:
   - Avoid complex, flickering, or heavy canvas charts (like live line traces) unless explicitly requested.
   - Use clean, minimal horizontal bar indicators or colored badges to represent metrics visually instead.
