# Test ActCheck yourself

## Start and open

From the repository root:

```sh
cd app/frontend
npm ci
npm run dev -- --host 127.0.0.1 --port 5173
```

Open **http://127.0.0.1:5173/**. If the development server is already running, just open that address. No API key is needed for frontend testing.

## A ten-minute walkthrough

1. Start on **Your inspections**. Choose **Explore example** to try prepared data, or **New inspection** to create your own draft. Creating a draft takes you to Gather evidence; it does not open another dialog automatically.
2. Use **Gather evidence → Review quantities → Notes & report**. The example's files can be downloaded from Gather evidence. In Review quantities, use **Details** on each work item and **Items to discuss** to show the four discrepant or unverified lines. The conservative wall-tiling amount remains **99,750 KZT**.
3. Expand **Inspect the wall measurements** under the statement. Choose another wall, toggle the tile overlay, and expand the image. These are demonstration fixtures, not model results.
4. In **Notes & report**, enter `Қабырғаны тексеру. Проверить площадь.` and save. Switch interface languages: your text must remain unchanged. Select **Preview & export**, download HTML, and try **Print / save PDF**. The report uses the selected language. Paper remains light in dark mode.
5. For your draft, add a room name and **300 × 600 mm**. In Gather evidence choose **Add files**, upload the examples below, preview a file and remove it. Try the unsupported `.txt` file to check validation. **Photo tips & test files** opens the capture guide and downloads.
6. New drafts must never show measurements or reuse the example's result. Review quantities explains the unavailable analysis; Continue to notes lets you record observations without implying an analysis completed.
7. Switch between **English**, **Қазақша**, and **Русский**; toggle light/dark with the sun/moon. Reload: preferences persist, but projects, uploads, and notes clear. Export notes first.
8. Use a narrow window (390 px) and keyboard navigation. Check readable steps, visible focus, scrollable comparison table, dialogs, and the return to **All inspections**. After changing sections with a Continue button, focus should move to the active section tab.

Language and theme preferences use localStorage. If browser storage is blocked, they work for the current page but may not survive reload. Only untouched sample names/text are translated; user-entered project names, locations, notes, and file names are preserved.

## Ready-to-use test files

These links work while the local server is running:

| File | Local URL | Expected use |
| --- | --- | --- |
| Synthetic bathroom image | http://127.0.0.1:5173/images/example-bathroom.png | Accepted image upload and preview |
| RU/KZ sample work statement | http://127.0.0.1:5173/test-data/sample-statement.pdf | Accepted PDF upload and preview |
| Synthetic tile label | http://127.0.0.1:5173/test-data/tile-label.pdf | Accepted PDF; manually enter 300 × 600 mm |
| Unsupported text file | http://127.0.0.1:5173/test-data/invalid-upload.txt | Rejected with a translated file-type message |

Files are checked into `public/test-data/`; the photo is in `public/images/`. The editable PDF sources are the adjacent HTML files. All examples are synthetic and have no real customer data. The tile label does **not** establish the dimensions of the generated photo.

Other negative cases: an empty file, a corrupt file named `.png`, an image over 20 MB, a duplicate file, a thirteenth attachment, blank project name, or tile dimensions outside 10–2,000 mm. Rejections should be clear and should not fabricate analysis results. PDF validation checks the file type and PDF signature; full document parsing is not implemented.

## Where real measurement data comes from

The most useful source is your own tiled bathroom, kitchen wall, or a room belonging to someone who consents to testing. For each wall:

- Photograph the whole tiled surface with the main camera, as straight on as practical. Include its boundaries and avoid ultrawide distortion.
- Photograph the tile-box dimensions, or independently measure a tile's width and height. Keep the grout convention consistent.
- Independently measure wall width, height, and openings using a tape or laser. Record the reference tiled area before seeing a prediction.
- Include different finishes, lighting, angles, joints, and occlusions. A useful first set is 20 wall photos; the team plan later targets 6–8 rooms.
- Use an anonymized contractor statement with permission. Label manually altered quantities as `planted` rather than presenting them as actual disputes.

Store real photos and field records under ignored `data/private/rooms/<room_id>/`. Use the column layout in `validation/rooms.csv` as a template, but keep identifying notes and unapproved data private. Do not put private photos in the frontend's `public/` directory: everything there is served to visitors.

Random web photos and generated images can test the interface, but do not provide reliable metric ground truth. They cannot establish area accuracy without known tile dimensions and independent measurements.

## What cannot be tested yet

Live SAM segmentation, geometric area estimation, invoice parsing, and measurement accuracy require the backend integration. Adding Meta/Baseten keys alone does not enable those features. Until integration is implemented, the app can test uploads, review interactions, localization, themes, and report presentation only. Use the repository's `docs/MODEL_ACCESS.md` for account setup; keep all provider credentials server-side.

## Developer checks

```sh
npm run test:i18n
npm run test:render
npm run lint
npm run build
```

The translation check validates both languages, matching interpolation placeholders, all literal translation calls, and fixture text coverage. The rendering check launches no browser. This redesign has not received a fresh browser/visual accessibility pass: the user requested that the app not be opened in Chrome. Use the walkthrough above for manual interaction and responsive checks; older-layout browser results do not validate this redesign.
