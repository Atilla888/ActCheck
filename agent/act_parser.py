"""Read a photographed completion act (RU/KZ) into an ActDocument. Images only for now."""

from pathlib import Path

from agent.llm import Provider, complete_json, image_part
from schemas.act import ActDocument

SYSTEM = """You transcribe renovation completion acts, estimates and invoices from Kazakhstan
(Russian or Kazakh) into structured data. You are a careful copyist, not a calculator.

Rules:
- One entry in `lines` per numbered work or material line, in document order. Skip headers,
  signatures and stamps.
- Copy `description_raw` exactly as printed, in the original language.
- Copy quantity, unit price and amount exactly as printed. Never compute, correct or fill in a
  number. Decimal comma -> dot; drop thousands separators ("460 750,00" -> 460750.0).
  An unreadable or empty cell is null, with a note in `parser_notes`.
- unit: м2, м², кв.м, ш.м² -> "m2"; м, п.м., м.п., пог.м -> "m"; шт, дана, точка, компл -> "pcs";
  усл., работа, комплекс, "1 услуга" priced as a whole -> "lump_sum"; anything else -> "other".
  Put the printed unit text in `unit_raw`.
- work_type: wall tiling (облицовка стен плиткой, укладка плитки на стены, қабырғаға плитка) ->
  "tiling_wall"; floor tiling (укладка плитки на пол, напольная плитка) -> "tiling_floor";
  плинтус -> "skirting"; покраска -> "painting"; штукатурка, шпаклёвка -> "plastering";
  гидроизоляция -> "waterproofing"; розетки, выключатели, электроточки -> "electrical_point";
  установка унитаза, ванны, смесителя, раковины -> "plumbing_fixture"; демонтаж -> "demolition";
  materials bought for the client -> "materials"; otherwise "other". Grout, primer and similar
  auxiliary works are "other" unless the line clearly bills tiled area.
- total_stated / vat_stated: only if printed on the document (Итого, Всего, Барлығы, НДС, ҚҚС).
- language: "ru", "kk" or "mixed".
"""


def parse_act(pages: list[str | Path], provider: Provider | None = None) -> ActDocument:
    content = [{"type": "text", "text": f"Transcribe this document ({len(pages)} page(s))."}]
    content += [image_part(p) for p in pages]
    return complete_json(SYSTEM, content, ActDocument, provider=provider)
