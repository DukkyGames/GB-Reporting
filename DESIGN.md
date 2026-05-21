# Grimm's Bluff — Design System (Reporting)

Aligned with [grimmsbluff.events](https://www.grimmsbluff.events) and `grimms-bluff-wines/Reference/gb-styles.css`.

## Scene

Estate team reviews numbers in the office or tasting room, often on a laptop in dimmer light. **Default theme: dark** (matches the public site). **Light theme** available for bright rooms and management preference.

## Themes

| Token | Dark | Light |
|-------|------|-------|
| Page bg | `oklch(10% 0.025 30)` | `oklch(96% 0.008 75)` |
| Surface | `oklch(13% 0.022 30)` | `oklch(99% 0.005 80)` |
| Text | cream `oklch(93% 0.008 75)` | `oklch(18% 0.025 30)` |
| Accent (gold) | `oklch(65% 0.10 60)` | `oklch(52% 0.1 58)` |
| Rules | `oklch(90% 0.01 75 / 0.1)` | `oklch(30% 0.02 40 / 0.12)` |

Set via `data-theme="dark"` (default) or `data-theme="light"` on `<html>`. Persisted in `localStorage` key `gb-reporting-theme`.

## Typography

- **Display**: Cormorant Garamond (section titles, metric values, brand name)
- **UI**: Jost (nav, labels, forms, tables, buttons)
- Labels: uppercase, `letter-spacing: 0.18–0.22em` (matches site nav)

## Color strategy

**Restrained** on dark: gold accent ≤10% of chrome; cream text; layered `bg` / `bg-elevated` / `bg-muted` surfaces.

## Layout

- Sidebar nav with gold active indicator (left rule, like site filter tabs)
- Sticky toolbar for date range and unit
- 2px grid gaps between cards (site product grid rhythm)

## Charts (Plotly)

- Palette per theme in `static/charts.js`
- Dark: gold primary, muted taupe secondary, cream highlight
- Theme change reloads page so charts re-render with correct colors

## Logos

- `static/Logo.png`: light mark for **dark** theme (sidebar, login)
- `static/Logo-Black.png`: dark mark for **light** theme
- Swapped via `.brand-logo-img--for-dark-theme` / `--for-light-theme` (no CSS invert)

## KPI icons

- `static/icons/*.png` are light assets (legacy dark tiles)
- **Light theme**: `filter: brightness(0)` via `--metric-icon-filter` so icons read dark on pale cards
- **Dark theme**: no filter

## Motion

- 200ms ease-out-quart transitions on hover/focus only
