import { useI18n } from "@/lib/i18n"
import { useState } from "react"
import {
  ArrowRight,
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
        : CircleDashed
  return (
    <Badge variant="outline" data-status={status}>
      <Icon data-icon="inline-start" />
      {t(statusLabels[status])}
    </Badge>
  )
}

export function StatementReview() {
  const { t, number, money } = useI18n()

  const [onlyReview, setOnlyReview] = useState(false)
  const [selected, setSelected] = useState<StatementLine | null>(null)
  const rows = onlyReview
    ? statement.filter((row) => row.status !== "matched")
    : statement
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
                <strong>{t(line.name)}</strong>
                <span className="cell-description">{t(line.detail)}</span>
              </TableCell>
              <TableCell className="numeric">
                {number(line.claimed)} <span className="unit">{t("m²")}</span>
              </TableCell>
              <TableCell className="numeric">
                {line.measured !== null ? (
                  <>
                    {number(line.measured)}{" "}
                    <span className="table-uncertainty">
                      ± {number(line.uncertainty ?? 0)}
                    </span>{" "}
                    <span className="unit">{t("m²")}</span>
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
                    +{number(line.claimed - line.measured)}{" "}
                    <span className="unit">{t("m²")}</span>
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
                  aria-label={`${t("Details")}: ${t(line.name)}`}
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
        <span>{t("All quantities are illustrative · KZT")}</span>
      </div>
      <Dialog
        open={selected !== null}
        onOpenChange={(open) => !open && setSelected(null)}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t(selected?.name ?? "")}</DialogTitle>
            <DialogDescription>
              {t("Statement line")} {selected?.id}{" "}
              {t("· illustrative comparison")}
            </DialogDescription>
          </DialogHeader>
          {selected && (
            <div className="review-detail">
              <StatusBadge status={selected.status} />
              <dl className="detail-list">
                <div>
                  <dt>{t("Statement area")}</dt>
                  <dd>
                    {number(selected.claimed)} {t("m²")}
                  </dd>
                </div>
                <div>
                  <dt>{t("Measured area")}</dt>
                  <dd>
                    {selected.measured === null
                      ? t("Not verified")
                      : `${number(selected.measured)} ± ${number(selected.uncertainty ?? 0)} ${t("m²")}`}
                  </dd>
                </div>
                <div>
                  <dt>{t("Rate")}</dt>
                  <dd>
                    {money(selected.rate)} {t("KZT / m²")}
                  </dd>
                </div>
                <div>
                  <dt>{t("Statement amount")}</dt>
                  <dd>
                    {money(selected.claimed * selected.rate)} {t("KZT")}
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
              <p>{t(selected.explanation)}</p>
              <div className="question-block">
                <MessageSquareText size={18} />
                <div>
                  <strong>{t("A question for your contractor")}</strong>
                  <p>{t(selected.question)}</p>
                </div>
              </div>
              <Button
                variant="outline"
                onClick={() => copyQuestion(t(selected.question))}
              >
                <Copy data-icon="inline-start" />
                {t("Copy question")}
              </Button>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </section>
  )
}
