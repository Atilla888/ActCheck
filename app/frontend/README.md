# ActCheck frontend

A responsive renovation inspection workspace built with React, TypeScript, Vite, Tailwind CSS, and shadcn/Radix components. Fonts and the synthetic example image are served locally.

## Language and appearance

Use the top-bar language selector for English, Қазақша, or Русский and the moon/sun button for dark/light mode. These preferences persist locally; inspection drafts and files remain session-only. Reports follow the chosen language and retain a light print layout.

See [TESTING.md](TESTING.md) for a walkthrough, downloadable synthetic files, and guidance on collecting real room data.

## Run

Use Node.js 24 and npm. From this folder:

```sh
npm ci
npm run dev -- --host 127.0.0.1 --port 5173
```

Open http://127.0.0.1:5173/. `npm run build` checks TypeScript and creates `dist/`; `npm run preview` serves the production build.

## Working interactions

- An inspection register with a separate worked example and validated draft creation.
- Three sections: Gather evidence → Review quantities → Notes & report.
- Four example wall records, selection, segmentation overlay toggle, and expanded evidence viewer.
- Statement filtering and line details, conservative discrepancy arithmetic, and copyable contractor questions.
- JPG/PNG/WebP/PDF uploads, image/PDF validation, duplicate detection, 20 MB per-file and 12-file limits, local preview, and removal.
- Per-project review notes; notes are included in the report after saving.
- Report preview, standalone HTML download, and browser print/save-to-PDF with a dedicated print layout. Unicode notes are supported by the browser's print renderer.
- Responsive navigation, accessible dialogs, keyboard controls, reduced-motion support, and empty/error states.

## How it connects to the backend

`app/server` (FastAPI) serves this interface and the API. The worked example asks `/api/sample`,
which runs the real agent on a stored SAM measurement of a synthetic wall; without the API it
falls back to the labelled fixtures in `src/features/inspection/data.ts`. A new inspection uploads
its statement pages and wall photos to `/api/inspections` and polls the job until the protocol is
ready. Projects, notes and file references live only in the browser tab; reloading clears them.
No credentials reach the frontend: the Meta API key stays on the server.

**Test cases.** Help & guidance → Test cases offers four downloadable cases (act, wall photo,
report with the true measurements, JSON) from `public/test-data/cases/`; see
[TESTING.md](TESTING.md).

## Appearance

`src/apple.css`, loaded after `src/index.css`, sets the current look: system type with tabular
figures, a grey grouped canvas with white panels, a translucent header, a segmented control for
the three steps and pill buttons. The accent is the teal of the recognised tiles in the
measurement overlay. On phones the statement table becomes one stacked row per work item.

## Verification

`npm run build`, `npm run lint`, `npm run test:i18n` and `npm run test:render` check TypeScript,
code quality, translation coverage (English, Russian, Kazakh) and real component rendering in
three languages × light and dark. The redesign was also checked in a headless browser at desktop
and phone widths, in both themes.

Research and design rationale: [UX research](docs/UX_RESEARCH.md), [visual direction](docs/VISUAL_DIRECTION.md).

Development tools: Sites local workflow skill, shadcn skill and MCP registry, image-generation skill, and Playwright MCP. Image source and exact generation prompt are in [ASSETS.md](ASSETS.md).
