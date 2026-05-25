from openpyxl import Workbook
import io


def export_to_xlsx(sheet_name: str, rows: list, columns: list) -> bytes:
    """columns = list of (header_label, row_key) tuples"""
    wb = Workbook()
    ws = wb.active
    ws.title = sheet_name
    ws.append([col[0] for col in columns])
    for row in rows:
        ws.append([row.get(col[1], '') or '' for col in columns])
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf.read()
