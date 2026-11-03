import { useI18n } from "@/lib/i18n"
import { useState } from "react"
import {
  ArrowRight,
  Camera,
  Check,
  CircleDashed,
  CircleHelp,
  Copy,
  ListFilter,
  MessageSquareText,
} from "lucide-react"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import {
  statement,
  statusLabels,
  conservativeDifference,
  type StatementLine,
  type ReviewStatus,
} from "./data"

export function StatusBadge({ status }: { status: ReviewStatus }) {
  const { t } = useI18n()
  const Icon =
    status === "matched"
      ? Check
      : status === "review"
        ? CircleHelp
        : status === "incomplete"
          ? Camera
          : CircleDashed
  return (
    <Badge variant="outline" data-status={status}>
      <Icon data-icon="inline-start" />
      {t(statusLabels[status])}
    </Badge>
  )
}

export function StatementReview({
  lines = statement,
  footnote = "All quantities are illustrative · KZT",
}: {
  lines?: StatementLine[]
  footnote?: string
}) {
  const { t, number, money } = useI18n()

  const [onlyReview, setOnlyReview] = useState(false)
  const [selected, setSelected] = useState<StatementLine | null>(null)
  const rows = onlyReview
    ? lines.filter((row) => row.status !== "matched")
    : lines
  // Analysis rows arrive localized; fixture rows are catalog keys.
  const text = (row: StatementLine, value: string) =>
    row.live ? value : t(value)
  const unit = (row: StatementLine) => row.unit ?? t("m²")
  async function copyQuestion(text: string) {
    try {
      await navigator.clipboard.writeText(text)
      toast.success(t("Question copied"))
    } catch {
      toast.error(
        t("Clipboard unavailable. Select and copy the question below.")
      )
    }
  }
  return (
    <section
      className="panel statement-panel"
      aria-labelledby="statement-title"
    >
      <div className="panel-heading">
        <div>
          <h2 id="statement-title">{t("Review the work statement")}</h2>
          <span className="subtle">
            {t(
              "Compare quantities. Open an item to see the explanation and a question for your contractor."
            )}
          </span>
        </div>
        <Button
          variant={onlyReview ? "secondary" : "outline"}
          size="sm"
          onClick={() => setOnlyReview(!onlyReview)}
          aria-pressed={onlyReview}
        >
          <ListFilter data-icon="inline-start" />
          {onlyReview ? t("Show all items") : t("Items to discuss")}
        </Button>
      </div>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>{t("Work item")}</TableHead>
            <TableHead className="numeric">{t("Statement")}</TableHead>
            <TableHead className="numeric">{t("Measured")}</TableHead>
            <TableHead className="numeric">{t("Difference")}</TableHead>
            <TableHead>{t("Status")}</TableHead>
            <TableHead>{t("Details")}</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((line) => (
            <TableRow key={line.id}>
              <TableCell>
                <strong>{text(line, line.name)}</strong>
                {!line.live && (
                  <span className="cell-description">{t(line.detail)}</span>
                )}
              </TableCell>
              <TableCell className="numeric">
                {number(line.claimed)}{" "}
                <span className="unit">{unit(line)}</span>
              </TableCell>
              <TableCell className="numeric">
                {line.measured !== null ? (
                  <>
                    {number(line.measured)}{" "}
                    <span className="table-uncertainty">
                      ± {number(line.uncertainty ?? 0)}
                    </span>{" "}
                    <span className="unit">{unit(line)}</span>
                  </>
                ) : (
                  <span className="unavailable">{t("Not verified")}</span>
                )}
              </TableCell>
              <TableCell className="numeric">
                {line.measured !== null ? (
                  <span
                    className={
                      line.status === "review" ? "difference-value" : "subtle"
                    }
                  >
                    {line.claimed >= line.measured ? "+" : "−"}
                    {number(Math.abs(line.claimed - line.measured))}{" "}
                    <span className="unit">{unit(line)}</span>
                  </span>
                ) : (
                  <span className="unavailable">—</span>
                )}
              </TableCell>
              <TableCell>
                <StatusBadge status={line.status} />
              </TableCell>
              <TableCell>
                <Button
                  size="sm"
                  variant="outline"
                  aria-label={`${t("Details")}: ${text(line, line.name)}`}
                  onClick={() => setSelected(line)}
                >
                  {t("Details")}
                  <ArrowRight data-icon="inline-end" />
                </Button>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      <div className="table-footer">
        <span>
          <CircleDashed size={14} />
          {t("Hidden work requires supporting records.")}
        </span>
        <span>{t(footnote)}</span>
      </div>
      <Dialog
        open={selected !== null}
        onOpenChange={(open) => !open && setSelected(null)}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {selected ? text(selected, selected.name) : ""}
            </DialogTitle>
            <DialogDescription>
              {t("Statement line")} {selected?.id}{" "}
              {selected?.live ? "" : t("· illustrative comparison")}
            </DialogDescription>
          </DialogHeader>
          {selected && (
            <div className="review-detail">
              <StatusBadge status={selected.status} />
              <dl className="detail-list">
                <div>
                  <dt>{t("Statement quantity")}</dt>
                  <dd>
                    {number(selected.claimed)} {unit(selected)}
                  </dd>
                </div>
                <div>
                  <dt>{t("Measured")}</dt>
                  <dd>
                    {selected.measured === null
                      ? t("Not verified")
                      : selected.uncertainty === null
                        ? `${number(selected.measured)} ${unit(selected)}`
                        : `${number(selected.measured)} ± ${number(selected.uncertainty)} ${unit(selected)}`}
                  </dd>
                </div>
                {selected.upper != null && (
                  <div>
                    <dt>{t("Upper bound, hidden areas included")}</dt>
                    <dd>
                      {number(selected.upper)} {unit(selected)}
                    </dd>
                  </div>
                )}
                <div>
                  <dt>{t("Rate")}</dt>
                  <dd>
                    {money(selected.rate)} {t("KZT")} / {unit(selected)}
                  </dd>
                </div>
                <div>
                  <dt>{t("Statement amount")}</dt>
                  <dd>
                    {money(selected.amount ?? selected.claimed * selected.rate)}{" "}
                    {t("KZT")}
                  </dd>
                </div>
                {selected.status === "review" && (
                  <div>
                    <dt>{t("Amount to clarify, at least")}</dt>
                    <dd>
                      {money(conservativeDifference(selected) ?? 0)} {t("KZT")}
                    </dd>
                  </div>
                )}
              </dl>
              <p>{text(selected, selected.explanation)}</p>
              {selected.question && (
                <>
                  <div className="question-block">
                    <MessageSquareText size={18} />
                    <div>
                      <strong>{t("A question for your contractor")}</strong>
                      <p>{text(selected, selected.question)}</p>
                    </div>
                  </div>
                  <Button
                    variant="outline"
                    onClick={() =>
                      copyQuestion(text(selected, selected.question))
                    }
                  >
                    <Copy data-icon="inline-start" />
                    {t("Copy question")}
                  </Button>
                </>
              )}
            </div>
          )}
        </DialogContent>
      </Dialog>
    </section>
  )
}
