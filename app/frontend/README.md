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

## Boundaries

All measurements, statements, and overlays in the example inspection are fixtures. The room illustration is generated; its four views do not establish four independently photographed walls. No segmentation or measurement model has analysed the image. The UI, file metadata, and exported report retain this distinction.

New uploads do not generate sample results. Drafts show an explicit unanalysed state. Projects, notes, and file references are held only in memory for the browser tab; reloading clears them. Object URLs are revoked on removal and unmount. No credentials, private `.env`, or private source data are imported by the frontend. Do not add provider keys to `VITE_*` variables.

The wall-tiling amount to clarify is `(48.5 − (36.9 + 1.1)) × 9,500 = 99,750 KZT`. It concerns only that line, not total savings. Hidden work is never marked as verified. Sample uncertainty is illustrative, not a validated confidence interval.

## Backend handoff

`src/features/inspection/data.ts` contains explicitly labeled frontend view fixtures and types, not the shared Pydantic contract. The existing `schemas/` draft has not been changed. Replace fixtures with validated server responses once the team agrees on the contract; add server-side upload storage, authentication, measurement status, errors, and report generation together. Do not simply enable an analysis button against fixtures.

## Verification

For the current redesign, `npm run build`, `npm run lint`, `npm run test:i18n`, and `npm run test:render` check TypeScript, code quality, translation coverage, real component rendering in six language/theme combinations, and conservative amount arithmetic. The rendering test uses server rendering and launches no browser.

No Chrome or browser session was opened for this redesign, as requested. The previous layout had browser and automated accessibility checks; those results do not validate the redesigned layout. Responsive visual checks, keyboard navigation, and interactive flows need a fresh manual pass using [TESTING.md](TESTING.md).

Research and design rationale: [UX research](docs/UX_RESEARCH.md), [visual direction](docs/VISUAL_DIRECTION.md).

Development tools: Sites local workflow skill, shadcn skill and MCP registry, image-generation skill, and Playwright MCP. Image source and exact generation prompt are in [ASSETS.md](ASSETS.md).
