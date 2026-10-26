import assert from "node:assert/strict"
import { createServer } from "vite"
import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"

// Server rendering exercises the real component tree without launching a browser.
// Preferences read these two browser APIs lazily; effects do not run during SSR.
const preferences = new Map()
globalThis.localStorage = { getItem: (key) => preferences.get(key) ?? null }
globalThis.window = { matchMedia: () => ({ matches: false }) }

const server = await createServer({
  server: { middlewareMode: true, hmr: false, ws: false },
  appType: "custom",
})
try {
  const { default: App } = await server.ssrLoadModule("/src/App.tsx")
  const { PreferencesProvider, translate } = await server.ssrLoadModule(
    "/src/lib/i18n/index.tsx"
  )
  const { StatementReview } = await server.ssrLoadModule(
    "/src/features/inspection/review.tsx"
  )
  const { statement, conservativeDifference } = await server.ssrLoadModule(
    "/src/features/inspection/data.ts"
  )
  const render = (Component) =>
    renderToStaticMarkup(
      createElement(PreferencesProvider, null, createElement(Component))
    )
  const escape = (text) =>
    text
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#x27;")
  for (const locale of ["en", "ru", "kk"]) {
    preferences.set("actcheck.locale", locale)
    for (const theme of ["light", "dark"]) {
      preferences.set("actcheck.theme", theme)
      const home = render(App)
      const review = render(StatementReview)
      assert.ok(
        home.includes(escape(translate(locale, "Your inspections"))),
        `${locale}/${theme}: inspection register must render`
      )
      assert.ok(
        home.includes(escape(translate(locale, "New inspection"))),
        `${locale}/${theme}: own-inspection entry must exist`
      )
      assert.ok(
        home.includes(escape(translate(locale, "Explore example"))),
        `${locale}/${theme}: sample entry must exist`
      )
      assert.equal(
        (home.match(/<h1[ >]/g) ?? []).length,
        1,
        "Home needs one primary heading"
      )
      assert.ok(
        home.includes('id="main-content"'),
        "Skip link destination must exist"
      )
      assert.ok(
        home.includes('id="language-select"'),
        "Language selector must render"
      )
      assert.ok(
        !home.includes('role="dialog"'),
        "Initial screen must not trap users in a dialog"
      )
      assert.equal(
        (review.match(/data-slot="table-row"/g) ?? []).length,
        6,
        "Review must show all five statement items"
      )
      assert.ok(
        review.includes(escape(translate(locale, "Not verified"))),
        "Hidden work must never appear as a measured zero"
      )
      for (const row of statement) {
        assert.ok(
          review.includes(escape(translate(locale, row.name))),
          `${locale}: missing work item ${row.id}`
        )
      }
    }
  }
  assert.equal(
    conservativeDifference(statement[0]),
    99750,
    "Use upper area bound for conservative wall amount"
  )
  assert.equal(
    conservativeDifference(statement[1]),
    0,
    "Within-range line must not produce a dispute amount"
  )
  assert.equal(
    conservativeDifference(statement[3]),
    null,
    "Concealed work has no calculated discrepancy"
  )
  console.log(
    "PASS: register and five-item review render in 3 languages × 2 themes; conservative amounts and unknown measurements verified."
  )
} finally {
  await server.close()
  delete globalThis.localStorage
  delete globalThis.window
}
