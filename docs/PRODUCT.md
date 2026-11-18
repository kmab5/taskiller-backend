# Backend field guide

Audience: curious users, frontend developers, and contributors who do not work on backends professionally. The site teaches Taskiller's actual Django API and data model, from a guided example to exact request/schema details.

This is a static, browser-only GitHub Pages site served from the main branch's docs directory. Changes stay inside docs. Examples are synthetic simulations, never requests to the hosted API. Existing Markdown paths remain stable and are organized through an indexed reference reader.

The canonical OpenAPI contract and active Django source are authoritative. A standard-library-only generator extracts every documented operation/schema and every database entity/field/relation; curated explanations add purpose and data impact. Coverage checks must fail on missing editorial entries.

Keep the existing Taskiller brand: Noto typography, ink/paper, and coral. Use progressive disclosure and interactive relationships instead of forcing readers through raw technical documents. Respect keyboard navigation, reduced motion, small screens, and private browsing.
