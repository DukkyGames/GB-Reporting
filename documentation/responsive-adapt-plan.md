# Responsive adapt plan (Impeccable `adapt`)

## Source context

- Desktop-first reporting shell: fixed sidebar, sticky date toolbar, dense tables and Plotly charts.
- Primary use: laptop in office or tasting room (see `DESIGN.md` scene).

## Target contexts

| Context | Adaptation |
|---------|------------|
| Phone (≤720px) | Drawer nav; full-width filters; single-column KPIs; 44px touch targets |
| Narrow tablet (≤860px) | Same drawer; two-column date fields where space allows |
| Tablet / small laptop (861–1024px) | Sidebar stays; multi-column report grids collapse to one column |
| Coarse pointer | Larger controls via `(hover: none) and (pointer: coarse)` |

## Implementation

- [x] Off-canvas sidebar + backdrop (`static/nav-mobile.js`, `templates/base.html`)
- [x] Toolbar grid layout on small screens (`static/styles.css`)
- [x] Collapse `report-grid`, `two-col`, `three-col` at 1024px
- [x] Safe-area padding for notched devices
- [x] Document breakpoints in `DESIGN.md` and `documentation/context.md`

## Verify

- [ ] Resize browser: 320px, 390px, 768px, 1024px, 1440px
- [ ] Open/close nav drawer; follow a nav link; Escape closes drawer
- [ ] Orders/Inventory filter forms usable without horizontal page scroll
- [ ] Plotly charts reflow inside panels (existing `min-width: 0` on chart containers)
- [ ] Real device spot-check (iOS Safari, Android Chrome) when available

## Follow-up

- Run `impeccable polish` for final visual pass after device testing.
