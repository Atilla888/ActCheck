# ActCheck UX research and redesign rationale

Research date: 27 October 2026. This is a source-informed design audit, not a usability study with ActCheck customers. The existing React implementation was inspected directly; the application was not opened in Chrome.

## Findings from the previous interface

- The first screen is an already populated example inspection. It does not explain where a person with their own statement should begin.
- Projects, Inspections, global Documents, and inspection-level Documents overlap. Users must learn the application's structure before doing their job.
- Overview repeats the measurement screen. A large illustrative room image separates the warning from the statement rows that need attention.
- Export is a primary action before the user has reviewed any evidence. A new inspection can display report actions despite having no measurement results.
- A permanent promotional capture card, fake profile presence indicator, and ornamental status dots compete with useful status information.
- A new inspection opens another upload modal immediately after the creation modal. This makes the workflow feel like stacked dialogs rather than a clear place to work.
- The review filter only includes quantity differences, while hidden work also requires a next action. The distinction must be explicit.

These are code-based observations, not claims of measured user behavior.

## Approaches considered

| Direction | Useful qualities | ActCheck application |
| --- | --- | --- |
| Service-oriented interface | Plain headings, explicit actions, visible status, small focused tasks | Make starting and continuing an inspection obvious. Borrow the logic, not GOV.UK branding. |
| Professional review workspace | Restrained surfaces, aligned columns, compact supporting details | Use a statement-first comparison table, clear row actions, and optional evidence details. |
| Guided sequence | Separate collecting evidence, reviewing quantities, and preparing a report | Present these as navigable stages without inventing completed analysis or forcing unnecessary steps. |

The recommended blend is a simple service workflow with a document-review workspace. A different decorative card theme alone would leave the current usability problems intact.

## Research-to-design mapping

1. **Put the essential task first; disclose supporting detail on demand.** Nielsen Norman Group describes progressive disclosure as prioritizing common options while leaving secondary functionality easy to find. For ActCheck, show the next action and review rows before tile overlays, uncertainty explanations, and export options. Keep quantities and their evidence close enough to compare; do not fragment interdependent review tasks into a rigid wizard. [Progressive Disclosure](https://www.nngroup.com/articles/progressive-disclosure/)

2. **Name stages with verbs and show honest status.** GOV.UK recommends task labels that describe the activity and statuses that indicate what still needs attention. Its full task-list pattern is intended for longer transactions, so ActCheck should borrow clear stage labels without adding a large administrative checklist. Proposed stages: Add evidence, Review quantities, Prepare report. Uploading a file means “Added”, not “Verified” or “Analysed”. [Complete multiple tasks](https://design-system.service.gov.uk/patterns/complete-multiple-tasks/)

3. **Keep creation focused and explain requested information.** GOV.UK recommends clear headings, a way back, a continue action, and asking only necessary questions. Keep room name and known tile dimensions together, show why dimensions are needed, and move into an evidence workspace after creation. [Question pages](https://design-system.service.gov.uk/patterns/question-pages/)

4. **Use tables for comparison, expandable content for explanation.** Carbon's table guidance supports scanning structured data and revealing supplementary information in expanded rows or a dedicated panel. Preserve aligned claimed/measured/difference columns; make review actions visible in words; place the question for the contractor next to the relevant quantity. [Carbon data table guidance](https://www.carbondesignsystem.com/building-blocks/core/components/data-table/guidelines)

5. **Place help at the moment it is useful.** NNGroup recommends contextual help alongside the relevant task rather than asking people to remember onboarding instructions. Put “How to photograph a wall” beside photo upload and tile-size guidance beside the dimensions. Remove the permanently prominent promotional help card. [Onboarding Tutorials vs. Contextual Help](https://www.nngroup.com/articles/onboarding-tutorials/)

6. **Review before final output.** GOV.UK's check-answers pattern lets people inspect information before submitting. Adapt that principle to report preparation: summarize included files, quantities, unanswered questions, and user notes before download. Export remains available for drafts, but the draft state must be explicit. [Check answers](https://design-system.service.gov.uk/patterns/check-answers/)

## Recommended acceptance tasks

- A first-time visitor can identify how to start their own inspection and how to open the example without explanation.
- Creating an inspection leads to a stable evidence workspace with one obvious next action.
- The user can explain the difference between uploaded, analysed, needs review, and unverified.
- The user can find a billed quantity, its measured counterpart, the limitation, and a contractor question without hunting through unrelated screens.
- The user can return to their inspection list and resume the current stage.
- Kazakh and Russian labels remain readable at narrow widths, and color is never the only status cue.
- User-entered data remains unchanged when language/theme switches; the lack of persistence and live analysis remains explicit.

These are proposed usability-test tasks. Build/type checks or automated DOM checks cannot establish that users find the workflow intuitive; a short observed test with representative homeowners is the next evidence needed.
