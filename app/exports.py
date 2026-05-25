"""CSV and Excel export helpers."""
import csv
import io
from typing import Any, Optional

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment


LEADS_COLUMNS: list[tuple[str, str]] = [
    ("Company", "company"),
    ("Contact", "contact"),
    ("Email", "email"),
    ("Phone", "phone"),
    ("Website", "website"),
    ("Notes", "notes"),
    ("Last Updated", "updated_at"),
]

ROLLUP_CUSTOMER_COLUMNS = [
    ("Customer", "customer"),
    ("Activities", "activities"),
    ("Last activity", "last_activity"),
]


def rollup_columns(group: str) -> list[tuple[str, str]]:
    return ROLLUP_CUSTOMER_COLUMNS


def rollup_sheet_name(group: str) -> str:
    return "By customer"


def _cell(row: dict[str, Any], key: str) -> Any:
    val = row.get(key)
    return "" if val is None else val


def project_rows(
    rows: list[dict[str, Any]],
    columns: list[tuple[str, str]],
) -> list[dict[str, Any]]:
    return [{label: _cell(row, key) for label, key in columns} for row in rows]


def to_csv_bytes(rows: list[dict[str, Any]], columns: list[tuple[str, str]]) -> bytes:
    projected = project_rows(rows, columns)
    buf = io.StringIO()
    if not projected:
        writer = csv.writer(buf)
        writer.writerow([label for label, _ in columns])
    else:
        writer = csv.DictWriter(buf, fieldnames=[label for label, _ in columns])
        writer.writeheader()
        writer.writerows(projected)
    return buf.getvalue().encode("utf-8-sig")


def to_xlsx_bytes(
    sheets: list[tuple[str, list[dict[str, Any]], list[tuple[str, str]]]],
) -> bytes:
    wb = Workbook()
    wb.remove(wb.active)

    header_fill = PatternFill("solid", fgColor="1A5632")
    header_font = Font(bold=True, color="FFFFFF", size=10)
    alt_fill = PatternFill("solid", fgColor="F0F7F3")

    for sheet_name, rows, columns in sheets:
        projected = project_rows(rows, columns)
        ws = wb.create_sheet(title=sheet_name[:31])

        headers = [label for label, _ in columns]
        ws.append(headers)
        for cell in ws[1]:
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = Alignment(horizontal="left", vertical="center")
        ws.row_dimensions[1].height = 18

        for r_idx, row in enumerate(projected, start=2):
            ws.append([row.get(h, "") for h in headers])
            if r_idx % 2 == 0:
                for cell in ws[r_idx]:
                    cell.fill = alt_fill
            ws.row_dimensions[r_idx].height = 15

        for col in ws.columns:
            max_len = max((len(str(cell.value or "")) for cell in col), default=10)
            ws.column_dimensions[col[0].column_letter].width = min(max_len + 4, 40)

        ws.freeze_panes = "A2"

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf.read()


def export_filename(
    base: str,
    period: str,
    ext: str,
    group: Optional[str] = None,
) -> str:
    parts = [base]
    if group:
        parts.append(group)
    if period and period != "all":
        parts.append(period)
    return "-".join(parts) + f".{ext}"
