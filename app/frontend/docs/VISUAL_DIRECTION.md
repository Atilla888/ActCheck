# ActCheck visual direction

Research date: 27 October 2026. Sources below are official design-system and product publications. Recommendations are design judgments, not results of an ActCheck usability study. The app was inspected through source code; its address was not opened in Chrome.

## Styles considered

| Direction | What it offers | Fit for ActCheck |
| --- | --- | --- |
| Public-service forms | Plain language, visible tasks, restrained decoration, strong text hierarchy | Best foundation for first-time homeowners collecting evidence |
| Enterprise review workbench | Aligned rows, consistent control sizes, compact metadata, expandable details | Best foundation for comparing contractor quantities and reviewing exceptions |
| Quiet productivity application | Reduced navigation emphasis, neutral surfaces, predictable actions | Useful finishing principles; copying a software-team sidebar would add unnecessary structure |
| Construction field tool | Evidence attached to observations; capture and review treated as connected work | Useful domain model, especially on mobile; full enterprise construction navigation would exceed this prototype's needs |

GOV.UK recommends simplifying a service before introducing a task list. Its task-list pattern is meant for complex work that users may complete in different orders, not a mandatory linear sequence. For ActCheck, keep only a few clear sections and avoid a dashboard-sized checklist. [GOV.UK task list](https://design-system.service.gov.uk/components/task-list/)

Carbon provides multiple table densities and recommends consistent component sizing. This supports a statement comparison with clear aligned columns and expandable detail instead of a collection of metric cards. [Carbon data-table guidelines](https://www.carbondesignsystem.com/building-blocks/core/components/data-table/guidelines)

Linear's 2026 refresh makes supporting navigation less prominent, reduces unnecessary icon treatments, and gives primary work more visual emphasis. Its 2024 redesign also stress-tested light/dark appearance and different view types. Adopt these principles rather than its exact product navigation. [Linear 2026 refresh](https://linear.app/now/behind-the-latest-design-refresh), [Linear 2024 redesign](https://linear.app/now/how-we-redesigned-the-linear-ui)

Procore describes inspections around collecting field data, identifying issues, and generating reports. That sequence is a useful domain reference; its marketing claims do not validate ActCheck's model accuracy or usability. [Procore inspections](https://www.procore.com/quality-safety/inspections)

## Findings from the previous interface

Source inspection found three competing navigation layers: workspace sidebar, breadcrumb header, and inspection tabs. Documents appear both globally and within an inspection. The default sample overview puts four metrics, a callout, a large illustration, and a statement table together before establishing the user's next action.

Promotional sidebar copy, a hard-coded personal identity, slogan-like headings, and repeated demonstration badges add visual weight without helping someone check a contractor statement. Cards, borders, small text, and uppercase metadata give many unrelated elements similar importance. This is an information hierarchy issue as much as a palette issue.

## Recommended direction: a clear inspection record

Use one calm application header and a spacious, readable inspection record. Start at the inspection list with a single prominent **New inspection** action. Keep the synthetic example available as a clearly labeled row. Inside a record, make the workflow visible through short sections: **Evidence**, **Review**, **Report**. Preserve access to earlier sections rather than forcing a wizard. Place the next useful action beside the current section's explanation.

Show the contractor statement as the main review surface. Keep quantities aligned and make exceptions easy to find. Open reasoning, uncertainty, photo evidence, and contractor questions on demand. Show summary amounts where they help a decision, rather than leading with four large dashboard metrics. New drafts should make the missing inputs clear and should never imply a completed analysis.

Use a warm near-white canvas with a white work surface, dark charcoal text, and one restrained action color. In dark mode, use neutral charcoal surfaces with clearly separated text levels. Prefer typographic hierarchy and spacing over nested cards. Use approximately 15px body text, 28px page headings, tabular numerals, 4px corners, and generous touch targets. Keep metadata quieter but readable. Icons should clarify an action or file type rather than decorate every heading.

Keep labels literal: **Add photos and documents**, **Compare quantities**, **Prepare report**. Avoid poetic headings. Preserve Kazakh/Russian support, allow translated labels to wrap, and keep paper exports light. Explain local-only data once near the relevant upload/save action instead of repeating status badges across the entire page.

## Acceptance criteria

- A new user can identify how to start without reading the sample results.
- Each section has an obvious purpose and useful next action.
- Global and record navigation do not duplicate each other.
- No invented personal/account details or decorative KPI panels.
- Evidence, uncertainty, and unverified hidden work remain accessible.
- Narrow layouts, translated text, keyboard navigation, and both themes retain clear hierarchy.
- No screen suggests uploads have been analysed while the backend is disconnected.

Validate these decisions with a short observed task test: ask someone to start a room inspection, add evidence, find a disputed quantity in the example, and export the questions. Record where they hesitate rather than asking only whether they like the visual style.
