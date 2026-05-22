# GB-Reporting design system

Product register. Flask + Jinja + CSS (no React). High-level brand notes live in `PRODUCT.md` and `DESIGN.md`; this file is the **implementation catalog**.

## File map

| Path | Role |
|------|------|
| `static/design-system/tokens.css` | Semantic CSS custom properties (color, type, space, z-index, motion) |
| `static/styles.css` | Layout, components, utilities (`@import` tokens) |
| `templates/macros/ui.html` | Reusable Jinja macros |
| `templates/partials/empty_state.html` | Empty-state partial (include-based) |
| `static/charts.js` | Plotly palette (hex mirrors token intent; not read from CSS) |
| `static/theme.js` | `data-theme` + `localStorage` |

## Design tokens

### Color & surfaces

Defined in `tokens.css` on `:root` (dark) and `[data-theme="light"]`.

| Token | Use |
|-------|-----|
| `--bg`, `--bg-elevated`, `--bg-muted` | Page and layered surfaces |
| `--text`, `--text-muted`, `--text-dim` | Body and secondary copy |
| `--accent`, `--accent-hover`, `--accent-soft` | Primary actions, active nav, KPI labels |
| `--border`, `--border-strong` | Rules and inputs |
| `--error-*`, `--info-*`, `--warn-*` | Flash categories |
| `--row-hover`, `--row-alt` | Table stripes |

### Typography

| Token | Typical use |
|-------|-------------|
| `--serif` / `--sans` | Display vs UI |
| `--type-body` | Body copy |
| `--type-body-sm` | Section descriptions |
| `--type-ui` | Tables, inputs |
| `--type-caption` | Buttons |
| `--type-label` | Uppercase field/metric labels |
| `--type-display-sm` | Panel titles |
| `--type-display-md` | Section titles |
| `--type-metric` / `--type-metric-lead` | KPI values |
| `--tracking-label`, `--tracking-button`, `--tracking-nav` | Letter-spacing |

### Spacing

4pt scale: `--space-2xs` (2px) through `--space-4xl` (64px).

| Token | Use |
|-------|-----|
| `--gap-tile` | Mosaic gap between metric tiles and chart panels |
| `--gap-section` | Space between major page sections |

### Elevation & motion

| Token | Use |
|-------|-----|
| `--shadow` | Drawer, dropdown menus |
| `--z-sticky` … `--z-skip` | Toolbar, drawer, dropdown, skip link |
| `--duration`, `--ease-out` | Hover/focus transitions only |

### Charts (Plotly)

CSS tokens `--chart-sage` / `--chart-slate` exist for future use. Runtime colors are in `charts.js` (`GB_CHART_COLORS`). When changing brand gold, update **both** `tokens.css` accent values and `charts.js` palettes.

## Jinja macros (`macros/ui.html`)

Import at the top of a template:

```jinja
{% from 'macros/ui.html' import section_head, panel_head, metric, chart_panel, flash_messages %}
```

### `section_head(title, emphasis=None, description=None)`

Page-level section title (Cormorant `h2` + optional italic emphasis + muted description).

### `panel_head(title, description=None, heading='h3', description_class=None)`

Panel chrome. `heading='h2'` for full-width table panels; `description_class='mono'` for IDs.

### `metric(value, label, icon_url=None, lead=False, note=None)`

KPI tile. `lead=True` pairs with `.metrics-strip--snapshot` for the dashboard anchor metric.

### `chart_panel(title, chart_id, description=None)`

Panel + head + `<div class="chart-plot" id="…">`. Use inside `.grid.two-col` / `.three-col`.

### `flash_messages(messages, wrapped=True)`

Renders Flask flash list. `wrapped=False` on login (no `.flash-wrap`).

## Partials (include)

### `partials/empty_state.html`

Set `title`, `description`, optional `actions` list of `(href, label, class)` tuples before `{% include %}`.

## CSS component classes (not yet macros)

Still authored inline where extraction would be premature:

- `.filter-form`, `.toolbar-form`, `.field` / `.field-control`
- `.btn`, `.btn-primary`, `.btn-secondary`, `.ghost-btn`
- `.grid.two-col`, `.grid.three-col`, `.report-grid`
- `.table-wrap`, sortable tables
- `.theme-switch`, `.sidebar`, `.nav-link`

## Adding new UI

1. Prefer existing tokens in `tokens.css` before new raw values.
2. If a pattern appears **3+ times** with the same intent, add a macro in `macros/ui.html` and migrate callers.
3. Update this file and `DESIGN.md` when introducing new tokens or macros.

## Extraction log (2026-05-21)

- Split tokens from monolithic `styles.css`
- Added type-scale tokens and wired core typography classes
- Macros: `section_head`, `panel_head`, `metric`, `chart_panel`, `flash_messages`
- Migrated: `base`, `dashboard`, `tours`, `orders`, `inventory`, `settings`, `products_report`, `order_detail`, `login`
