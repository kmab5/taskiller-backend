# Taskiller field guide design

## Direction

An interactive systems atlas. A midnight navigation rail and layered blue reading surfaces frame warm, oversized headings. Coral marks selected records and the task’s path through the backend. The opening uses a numbered, connected diagram to explain the conceptual journey from Project to analytics; it is distinct from the database map’s actual foreign keys.

Mode: Read, with Operate conventions for searchable catalogs. The primary journey is understand → follow a task → inspect an endpoint → trace its tables → inspect exact fields.

## Visual system

- Canvas #10151E, rail #0C1119, reading surface #1B2330, warm text #F1EEE9, muted text #AAB6C7, borders #344153.
- Taskiller coral adapted to #FF906F for dark surfaces, with dark text on filled primary actions for readable contrast.
- Semantic group colors distinguish Identity, Work, Focus, Execution, and Operations; labels always accompany color.
- Local Noto Sans body (400/600), Noto Sans Display headings (800), Noto Sans Mono code (400). Body 16px, tool prose 14–16px, technical labels 11–13px, prose line-height 1.65–1.85, 70ch maximum reading measure. Display headings scale from 43px on phones to 82px on wide screens.
- Fixed 248px desktop navigation, 78px toolbar, generous main margins. Small screens use a labeled navigation drawer and stacked content.
- Thin borders separate tools and reference tables. The home diagram uses a restrained dot grid, real SVG connectors, and a snake reading order. Flat numbered chapter links replace the former uniform feature cards. Avoid nested panels and gratuitous decoration.

## Interactions

Search across endpoints, entities, fields, and API objects. Hash routes preserve shareable selections and work on a project Pages URL without server rewrites. Catalog filters, request/response tabs, relationship highlighting, linked type references, copy actions, and a synthetic task walkthrough expose detail progressively.

SVG relationship lines convey actual foreign keys. Selected and neighboring records remain readable; text relation lists provide an accessible equivalent. Motion conveys selection/state only, and reduced-motion users receive the same information immediately.

Every example is marked synthetic. Read/write effects, SQL columns, API properties, nullability, constraints, and source links remain distinct. No live API execution or credential storage is provided.
