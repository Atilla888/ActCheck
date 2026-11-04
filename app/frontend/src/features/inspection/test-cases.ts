// Downloadable end-to-end test cases (public/test-data/cases), generated with exact geometry and
// measured through SAM by scripts/make_test_cases.py. Titles are translation keys.
export type TestCase = {
  id: string
  title: string
  tile: [number, number]
}

export const testCases: TestCase[] = [
  { id: "01_honest_bill", title: "Honest bill", tile: [300, 600] },
  {
    id: "02_overbilled_wall",
    title: "Over-billed wall tiling",
    tile: [300, 300],
  },
  { id: "03_door_not_deducted", title: "Door not deducted", tile: [200, 200] },
  {
    id: "04_kazakh_within_tolerance",
    title: "Kazakh act, small difference",
    tile: [600, 300],
  },
]

export const caseFile = (id: string, file: string) =>
  `/test-data/cases/${id}/${file}`
