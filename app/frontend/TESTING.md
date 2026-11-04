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

**Help & guidance → Test cases** offers four end-to-end cases. Each has a contractor act
(`act.jpg`), one wall photo (`wall.png`), a printable report (`report.html`: the true
measurements, the act, the correct answer and what ActCheck returned) and the same data as JSON
(`measurement.json`). Create an inspection with the tile size shown, upload the act as a statement
page and the photo as a wall photo, run the analysis and compare with the report.

| Case | Tile | True tiled area | Act bills | Correct answer | ActCheck |
| --- | --- | --- | --- | --- | --- |
| [Honest bill](public/test-data/cases/01_honest_bill/report.html) | 300 × 600 | 5.04 m² | 5.0 m² | no over-billing | same |
| [Over-billed wall tiling](public/test-data/cases/02_overbilled_wall/report.html) | 300 × 300 | 6.48 m² | 8.5 m² | over-billed (plus a grout-line arithmetic error) | same |
| [Door not deducted](public/test-data/cases/03_door_not_deducted/report.html) | 200 × 200 | 6.40 m² | 8.0 m² | over-billed | same |
| [Kazakh act, small difference](public/test-data/cases/04_kazakh_within_tolerance/report.html) | 600 × 300 | 7.20 m² | 7.4 m² | no over-billing (inside the uncertainty) | same |

The walls are rendered from exact geometry, so the true areas are exact; the acts are fictional.
Regenerate them with `uv run python scripts/make_test_cases.py --measure` from the repository root
(SAM results are cached, so a rerun costs nothing). `test-data/invalid-upload.txt` still checks
that unsupported files are rejected.

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

## Live analysis

Uploads are analysed by the backend: SAM 3.1 measures the walls and Muse Spark reads the
statement. Run it locally with a Meta API key in `.env` (`docker build -t actcheck . && docker run
--env-file .env -p 8000:8000 actcheck`, then open http://localhost:8000). The hosted version opens
the worked example but cannot currently reach the Meta Model API (see the repository README).
Without a key the interface, uploads, the worked example's fixtures, languages, themes and the
report can all still be tested.

## Developer checks

```sh
npm run test:i18n
npm run test:render
npm run lint
npm run build
```

The translation check validates both languages, matching interpolation placeholders, all literal translation calls, and fixture text coverage. The rendering check launches no browser. This redesign has not received a fresh browser/visual accessibility pass: the user requested that the app not be opened in Chrome. Use the walkthrough above for manual interaction and responsive checks; older-layout browser results do not validate this redesign.
