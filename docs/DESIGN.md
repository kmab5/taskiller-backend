# Taskiller field guide design

## Direction

An explorable field guide to a working system. A dark, quiet navigation rail frames bright reading surfaces; coral marks the task's path through the backend. The opening demonstrates a Chore becoming a plan, session, and history rather than presenting a generic documentation index.

Mode: Read, with Operate conventions for searchable catalogs. The primary journey is understand → follow a task → inspect an endpoint → trace its tables → inspect exact fields.

## Visual system

- Ink #111214, paper #F7F8FA, white #FFFFFF, muted ink #646B75, borders #E5E7EB.
- Taskiller coral #FF5B3A, with ink text on filled primary actions for readable contrast.
- Semantic group colors distinguish Identity, Work, Focus, Execution, and Operations; labels always accompany color.
- Local Noto Sans body (400/600), Noto Sans Display headings (800), Noto Sans Mono code (400). Body 15–16px, prose line-height 1.65, 70ch maximum reading measure.
- Fixed 232px desktop navigation, 68px toolbar, generous main margins. Small screens use a labeled navigation drawer and stacked content.
- Thin borders separate tools and reference tables. Avoid nested panels and gratuitous decoration.

## Interactions

Search across endpoints, entities, fields, and API objects. Hash routes preserve shareable selections and work on a project Pages URL without server rewrites. Catalog filters, request/response tabs, relationship highlighting, linked type references, copy actions, and a synthetic task walkthrough expose detail progressively.

SVG relationship lines convey actual foreign keys. Selected and neighboring records remain readable; text relation lists provide an accessible equivalent. Motion conveys selection/state only, and reduced-motion users receive the same information immediately.

Every example is marked synthetic. Read/write effects, SQL columns, API properties, nullability, constraints, and source links remain distinct. No live API execution or credential storage is provided.
