# Taskiller backend field guide

The documentation website starts at [index.html](index.html). It explains the current Django backend through a guided task, an API explorer, a database relationship map, a data-object library, mechanism guides, and a glossary.

## What is covered

- All 57 documented operations: purpose, use cases, request/response shapes, headers, status codes, record reads/writes, and source links.
- All 20 Taskiller tables plus 10 Django framework tables: 261 stored fields and 35 declared foreign-key relationships. Django internals are hidden from the map by default and can be included explicitly.
- All 80 canonical API schemas, including required/nullable properties, enums, bounds, nested types, and plain-language field explanations.
- Seven synthetic task steps; 12 guides covering authentication, concurrency, timers, recommendations, analytics, worker jobs, privacy, deployment, errors, and testing; 20 glossary terms.

Examples are local illustrations, not a live API console. The site never asks for credentials or calls the Render API. It uses local fonts/assets and does not require a framework, CDN, database, backend route, or frontend build.

## Folder organization

```text
docs/
  index.html             Static GitHub Pages entry point
  .nojekyll              Publish assets directly, without Jekyll processing
  assets/                Browser code, styles, local brand assets and fonts
    data/                Generated catalog and downloadable OpenAPI snapshot
  content/               Human explanations, separate from generated metadata
  tools/                 Data generator, local preview, and browser checks
  PRODUCT.md, DESIGN.md   Audience, scope, and visual-system documentation
  *.md                   Original technical notes at their established paths
  audits/, superpowers/  Existing audit and implementation history
```

The reference reader organizes the original notes into current operations, audit/remediation, and historical domain/migration notes. Existing Markdown paths stay intact so repository links and contributor instructions continue to work. Historical notes are labeled; the current source and canonical contract remain authoritative.

## Preview locally

From the repository root:

```powershell
python docs/tools/build_data.py
python docs/tools/serve.py --port 8833
```

Open **http://127.0.0.1:8833/taskiller-backend/**. The preview deliberately uses a project-path prefix like GitHub Pages, so asset paths and deep links are exercised realistically. Use `--base-path /` for a root-path preview.

## Publish on GitHub Pages

Once the files are committed and pushed, open repository **Settings → Pages**. Choose **Deploy from a branch**, then **main** and **/docs**, and save. No change to the backend CI, Render blueprint, or Django routing is needed. See [GitHub's publishing-source instructions](https://docs.github.com/en/pages/getting-started-with-github-pages/configuring-a-publishing-source-for-your-github-pages-site).

The expected project address is `https://kmab5.github.io/taskiller-backend/` once Pages is enabled and a deployment succeeds. This repository change does not itself enable or verify that hosted deployment. Hash routes keep shared endpoint/entity selections working without server rewrites.

## Keep the guide accurate

`tools/build_data.py` reads the canonical OpenAPI JSON and parses the active model source with Python's AST. It does not import Django, read environment files, connect to a database, or execute application code. Framework-table metadata is a documented Django 5.2 snapshot; review it when changing Django's built-in schema.

When endpoints, models, or fields change, update the matching explanations in `content/`, regenerate the catalog, and run:

```powershell
python docs/tools/build_data.py --check
```

The check rejects missing operation/table/property explanations, unknown table references, and stale generated artifacts. Commit the generated catalog and OpenAPI snapshot with their source explanations. Backend release behavior is not coupled to the docs generator.

## Browser verification

`tools/check_site.mjs` uses an existing Playwright installation. Point `PLAYWRIGHT_MODULE_ROOT` at the `package.json` of a development workspace with `playwright` installed; `@axe-core/playwright` enables the accessibility checks. Then run it while the preview server is active:

```powershell
$env:PLAYWRIGHT_MODULE_ROOT = 'C:/path/to/browser-test-workspace/package.json'
node docs/tools/check_site.mjs
```

No backend dependency installation is required. Checks visit every operation, object, and table; exercise filters/search/walkthroughs, verify the Pages path prefix, inspect desktop/mobile overflow and keyboard navigation, and reject browser errors or external requests. Screenshots and reports go to the ignored `docs/qa-output/` folder.
