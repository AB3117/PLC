---
name: taste-frontend
description: Establishes a premium, minimalist frontend design system. Restricts generic templates, neon glows, or oversaturated indicators. Enforces typographic hierarchy, spacious spacing, and clean industrial layouts.
---

# Taste Frontend Skill

This skill governs the aesthetic quality, colors, spacing, and visual design of web frontends, aiming for a professional, premium "anti-generic" look.

## Core Directives

1. **Color Constraints**:
   - Use a **Minimalist Light Mode** palette: light grays and off-whites for panels (`#f8fafc`, `#f1f5f9`), slate-charcoal for text (`#0f172a`, `#334155`).
   - Muted, low-saturation colors for status indicators:
     - **Active/Working**: Muted Sage Green (`#10b981` or `#34d399`)
     - **Stopped/E-Stop**: Muted Rose (`#ef4444` or `#f87171`)
     - **Idle/Standby**: Muted Ochre/Amber (`#f59e0b` or `#fbbf24`)
   - Avoid pure blacks (`#000`), harsh neon glows, or high-contrast box shadows.

2. **Typography**:
   - Use clean, premium fonts like *Outfit* or *Inter* (fallbacks: sans-serif).
   - Maintain clear vertical rhythm: section headers should be prominent, subtext should be small and muted (`#64748b`).

3. **Crisp Layout**:
   - Enforce grid structures with thin borders (`1px solid #e2e8f0`) rather than heavy background panel shadows.
   - Use generous padding (`16px` to `24px`) and margins to let the layout breathe.

4. **Micro-Animations**:
   - Use subtle transitions (`transition: all 0.2s ease`) for hover and active states of interactive elements.
