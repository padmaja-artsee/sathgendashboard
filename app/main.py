from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from typing import List

from fastapi import FastAPI, File, Form, Query, Request, UploadFile
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
    Response,
)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.database import (
    create_deal,
    create_lead,
    customer_detail,
    delete_activity,
    attach_activity_to_deal,
    delete_customer,
    update_activity,
    dashboard_stats,
    get_deal_detail,
    get_lead_by_company,
    init_db,
    list_customers,
    list_active_leads,
    group_active_leads,
    list_shipping_summary,
    list_deals,
    deals_for_activity_edit,
    iso_date_input,
    list_deals_for_company,
    log_update,
    archive_deal,
    bulk_deal_action,
    delete_deal,
    mark_deal_lost,
    mark_deal_shipped,
    unarchive_deal,
    update_deal_fields,
    PRICE_UNITS,
    format_quantity_display,
    list_quantity_unit_options,
    normalize_quantity_unit,
    migrate_to_leads_deals,
    recent_activities,
    search_leads_contacts,
    summary_by_customer,
    update_lead,
    update_company_profile,
    create_contact,
    update_contact,
    delete_contact,
)
from app.exports import (
    LEADS_COLUMNS,
    export_filename,
    rollup_columns,
    rollup_sheet_name,
    to_csv_bytes,
    to_xlsx_bytes,
)
from app.deal_files import (
    add_deal_file,
    delete_deal_file,
    get_deal_file,
    list_deal_files,
)
from app.seed import load_seed

import sys as _sys
import os as _os

# Mount Finance as a sub-app at /finance (Option B single-port architecture).
# Must set env var BEFORE importing finance.app.main so FINANCE_BASE is correct.
_os.environ.setdefault("FINANCE_BASE_PATH", "/finance")

# When frozen by PyInstaller the launcher sets SATHGEN_BUNDLE_BASE = sys._MEIPASS,
# which is the directory that actually contains templates/, static/, data/.
# Fall back to Path(__file__).parent.parent for source runs.
_bundle_base = _os.environ.get("SATHGEN_BUNDLE_BASE")
BASE = Path(_bundle_base) if _bundle_base else Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=str(BASE / "templates"))
templates.env.filters["qty_display"] = format_quantity_display
templates.env.filters["iso_date"] = iso_date_input


def _money_filter(value):
    try:
        return f"{float(value):,.2f}"
    except (TypeError, ValueError):
        return value or "—"


def _num_filter(value):
    try:
        n = float(value)
        return f"{n:g}" if n == int(n) else f"{n:,.2f}"
    except (TypeError, ValueError):
        return value or "—"


templates.env.filters["money"] = _money_filter
templates.env.filters["num"] = _num_filter


def _timeline_deal_ids(timeline: dict) -> set[int]:
    ids: set[int] = set()
    for group in timeline.get("deal_groups") or []:
        if group.get("deal_id"):
            ids.add(int(group["deal_id"]))
        for act in group.get("activities") or []:
            if act.get("deal_id"):
                ids.add(int(act["deal_id"]))
    for act in timeline.get("company_level") or []:
        if act.get("deal_id"):
            ids.add(int(act["deal_id"]))
    return ids

app = FastAPI(title="Sathgen Therapeutics Dashboard")

_static_dir = BASE / "static"
if _static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")
else:
    import warnings
    warnings.warn(f"Static directory not found: {_static_dir}")

# Mount the Finance sub-app at /finance (single-port Option B).
try:
    from finance.app.main import app as _finance_app
    app.mount("/finance", _finance_app)
except Exception as _e:
    import warnings
    warnings.warn(f"Finance sub-app could not be mounted: {_e}")


@app.on_event("startup")
def startup() -> None:
    import threading as _threading
    import logging as _logging

    _log = _logging.getLogger("leads.startup")

    try:
        # Enable WAL mode before anything else so concurrent reads never block saves.
        import sqlite3 as _sqlite3
        from app.database import DB_PATH as _DB_PATH
        _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        _wc = _sqlite3.connect(str(_DB_PATH), timeout=30)
        _wc.execute("PRAGMA journal_mode = WAL")
        _wc.commit()
        _wc.close()
    except Exception as exc:
        _log.error("WAL setup failed: %s", exc)

    try:
        # init_db creates tables — must run synchronously before requests arrive.
        init_db()
    except Exception as exc:
        _log.error("init_db failed: %s", exc)

    # Finance is mounted as a sub-app; Starlette does NOT call its startup events.
    # We must initialise the Finance DB here so its tables exist before any request.
    try:
        from finance.app.database import init_db as _finance_init_db, DB_PATH as _FINANCE_DB_PATH
        import sqlite3 as _sq3
        _FINANCE_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        _fw = _sq3.connect(str(_FINANCE_DB_PATH), timeout=30)
        _fw.execute("PRAGMA journal_mode = WAL")
        _fw.commit()
        _fw.close()
        _finance_init_db()
    except Exception as exc:
        _log.error("finance init_db failed: %s", exc)

    # Seed loading can be slow (large JSON with hundreds of records).
    # Run it in a background thread so the server accepts requests immediately.
    # The 3-second delay lets the first user interaction complete before any
    # background writes begin, preventing immediate DB lock contention.
    def _seed_in_background():
        import time as _time
        _time.sleep(3)
        try:
            load_seed()
            migrate_to_leads_deals()
            import_catalogue()
            fix_legacy_product_names()
        except Exception as exc:
            _logging.getLogger("leads.startup").warning("Background seed error: %s", exc)

    _threading.Thread(target=_seed_in_background, daemon=True).start()

    try:
        upgrade_commission_invoices_schema()
        upgrade_sales_invoices_schema()
        upgrade_delivery_notes_schema()
    except Exception as exc:
        _log.error("Schema upgrade failed: %s", exc)


def _open_in_system_browser(path: str) -> None:
    """Open a local URL in the system default browser (Safari/Chrome).
    Used for Print because window.print() is blocked in Tauri's WKWebView."""
    import subprocess, sys as _s
    url = f"http://127.0.0.1:8000{path}"
    try:
        if _s.platform == "darwin":
            subprocess.Popen(["open", url])
        elif _s.platform == "win32":
            subprocess.Popen(["start", url], shell=True)
        else:
            subprocess.Popen(["xdg-open", url])
    except Exception:
        pass


@app.get("/open-print")
async def open_print_in_browser(url: str = Query(...)):
    """Called by the Print button; opens the print page in the system browser."""
    _open_in_system_browser(url)
    return Response(status_code=204)


def _export_to_downloads(content: bytes, fname: str) -> str:
    """
    Save export bytes to ~/Downloads/<fname> and open in the default app.
    Returns the full path so routes can show it in a success message.
    Used because Tauri's WKWebView does not handle Content-Disposition
    attachment downloads the way a regular browser does.
    """
    import subprocess, sys as _sys2
    downloads = Path.home() / "Downloads"
    downloads.mkdir(exist_ok=True)
    dest = downloads / fname
    # Avoid clobbering: append a counter if the file already exists.
    counter = 1
    while dest.exists():
        stem, suffix = dest.stem, dest.suffix
        dest = downloads / f"{stem}_{counter}{suffix}"
        counter += 1
    dest.write_bytes(content)
    # Open the file with the default application (Excel / Numbers on macOS).
    try:
        if _sys2.platform == "darwin":
            subprocess.Popen(["open", str(dest)])
        elif _sys2.platform == "win32":
            import os as _os2; _os2.startfile(str(dest))
        else:
            subprocess.Popen(["xdg-open", str(dest)])
    except Exception:
        pass
    return str(dest)


def ctx(request: Request, **extra):
    return {
        "request": request,
        "price_units": PRICE_UNITS,
        "quantity_units": list_quantity_unit_options(),
        **extra,
    }


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, period: str = Query("all")):
    return templates.TemplateResponse(
        "dashboard.html",
        ctx(
            request,
            page="dashboard",
            period=period,
            stats=dashboard_stats(period),
            recent=recent_activities(20, period),
            open_deals=list_deals(status="open", period="all")[:5],
        ),
    )


@app.post("/deals/{deal_id}/product")
async def deal_change_product(
    deal_id: int,
    product_id: int = Form(...),
    next_url: str = Form(""),
):
    update_deal_product(deal_id, product_id)
    return RedirectResponse(next_url or f"/deal/{deal_id}", status_code=303)


@app.post("/deals/{deal_id}/meta")
async def deal_update_meta(
    deal_id: int,
    notes: str = Form(""),
    po_number: str = Form(""),
    quote_ref: str = Form(""),
    quantity: str = Form(""),
    quantity_unit: str = Form("MT"),
    quantity_unit_other: str = Form(""),
    price: str = Form(""),
    price_unit: str = Form("/MT"),
    po_date: str = Form(""),
    packing: str = Form(""),
    gbl_invoice: str = Form(""),
    gbl_invoice_date: str = Form(""),
    container_number: str = Form(""),
    vessel_name: str = Form(""),
    etd_india: str = Form(""),
    transit_time: str = Form(""),
    destination: str = Form(""),
    eta: str = Form(""),
    incoterms: str = Form(""),
    payment_terms: str = Form(""),
    shipment_timing: str = Form(""),
    next_url: str = Form(""),
):
    update_deal_fields(
        deal_id,
        notes,
        po_number,
        quote_ref,
        quantity,
        quantity_unit,
        quantity_unit_other,
        price,
        price_unit,
        po_date,
        packing,
        gbl_invoice,
        gbl_invoice_date,
        container_number,
        vessel_name,
        etd_india,
        transit_time,
        destination,
        eta,
        incoterms=incoterms,
        payment_terms=payment_terms,
        shipment_timing=shipment_timing,
    )
    return RedirectResponse(next_url or f"/deal/{deal_id}", status_code=303)


@app.get("/shipping", response_class=HTMLResponse)
async def shipping_summary_page(
    request: Request,
    company: str = Query(""),
    product: str = Query(""),
    status: str = Query("all"),
    q: str = Query(""),
):
    return templates.TemplateResponse(
        "shipping.html",
        ctx(
            request,
            page="shipping",
            rows=list_shipping_summary(company, product, status, q),
            company=company,
            product=product,
            status=status,
            q=q,
        ),
    )


@app.get("/contacts", response_class=HTMLResponse)
async def contacts_page(
    request: Request,
    company: str = Query(""),
    q: str = Query(""),
):
    return templates.TemplateResponse(
        "contacts.html",
        ctx(
            request,
            page="contacts",
            contacts=search_leads_contacts(company, "", q),
            company=company,
            q=q,
        ),
    )


@app.get("/deals", response_class=HTMLResponse)
async def active_leads_page(
    request: Request,
    status: str = Query("all"),
    period: str = Query("month"),
    company: str = Query(""),
    product: str = Query(""),
    po: str = Query(""),
    q: str = Query(""),
    view: str = Query("company"),
):
    view_mode = "product" if view == "product" else "company"
    leads = list_active_leads(status, period, company, product, po, q)
    return templates.TemplateResponse(
        "deals.html",
        ctx(
            request,
            page="deals",
            leads=leads,
            lead_groups=group_active_leads(leads, view_mode),
            status=status,
            period=period,
            company=company,
            product=product,
            po=po,
            q=q,
            view=view_mode,
        ),
    )


@app.get("/api/company-deals")
async def api_company_deals(company: str = Query(...)):
    return JSONResponse(list_deals_for_company(company, active_only=False))


@app.get("/add", response_class=HTMLResponse)
async def add_page(
    request: Request,
    company: str = Query(""),
    product: str = Query(""),
    deal_id: str = Query(""),
    tab: str = Query("log"),
    return_to: str = Query(""),
):
    company_deals = (
        list_deals_for_company(company, active_only=False) if company else []
    )
    return templates.TemplateResponse(
        "add.html",
        ctx(
            request,
            page="add",
            tab=tab,
            customers=list_customers(),
            preset_company=company,
            preset_product=product,
            preset_deal_id=deal_id,
            return_to=return_to,
            company_deals=company_deals,
            lead=get_lead_by_company(company) if company else None,
        ),
    )


@app.get("/deal/{deal_id}", response_class=HTMLResponse)
async def deal_page(
    request: Request,
    deal_id: int,
    error: str = Query(""),
):
    detail = get_deal_detail(deal_id)
    if not detail:
        return RedirectResponse("/deals", status_code=303)
    pid = detail["deal"].get("product_id")
    product_record = get_product(pid) if pid else None
    company = detail["deal"]["company"]
    today = datetime.utcnow().date().isoformat()
    err_msg = ""
    if error == "pdf_only":
        err_msg = "Only PDF files can be attached."
    elif error == "invalid_file":
        err_msg = "Could not attach that file."
    return templates.TemplateResponse(
        "deal.html",
        ctx(
            request,
            page="deals",
            detail=detail,
            product_record=product_record,
            deal_files=list_deal_files(deal_id),
            deal_file_error=err_msg,
            company_deals=deals_for_activity_edit(
                company,
                {deal_id, *(a.get("deal_id") for a in detail.get("activities", []))},
            ),
            today=today,
        ),
    )


@app.post("/deals/{deal_id}/upload")
async def deal_upload_pdf(
    deal_id: int,
    pdf_file: UploadFile = File(...),
    next_url: str = Form(""),
):
    if not pdf_file.filename or not pdf_file.filename.lower().endswith(".pdf"):
        dest = next_url or f"/deal/{deal_id}"
        return RedirectResponse(f"{dest}?error=pdf_only", status_code=303)
    content = await pdf_file.read()
    try:
        add_deal_file(deal_id, pdf_file.filename, content)
    except ValueError:
        dest = next_url or f"/deal/{deal_id}"
        return RedirectResponse(f"{dest}?error=invalid_file", status_code=303)
    return RedirectResponse(next_url or f"/deal/{deal_id}", status_code=303)


@app.get("/deals/files/{file_id}")
async def deal_download_pdf(file_id: int):
    info = get_deal_file(file_id)
    if not info:
        return RedirectResponse("/deals", status_code=303)
    return FileResponse(
        info["absolute_path"],
        media_type="application/pdf",
        filename=info["filename"],
    )


@app.post("/deals/files/{file_id}/delete")
async def deal_delete_pdf_route(
    file_id: int,
    next_url: str = Form(""),
):
    deal_id = delete_deal_file(file_id)
    if deal_id:
        return RedirectResponse(next_url or f"/deal/{deal_id}", status_code=303)
    return RedirectResponse("/deals", status_code=303)


@app.post("/add/contact")
async def post_contact(
    company: str = Form(...),
    contact: str = Form(""),
    email: str = Form(""),
    website: str = Form(""),
    phone: str = Form(""),
    notes: str = Form(""),
):
    create_lead(
        {
            "company": company,
            "contact": contact,
            "email": email,
            "website": website,
            "phone": phone,
            "notes": notes,
        }
    )
    return RedirectResponse(f"/contacts?company={quote(company)}", status_code=303)


@app.post("/add/deal")
async def post_deal(
    company: str = Form(...),
    product: str = Form(...),
    deal_date: str = Form(...),
    po_number: str = Form(""),
    quote_ref: str = Form(""),
    quantity: str = Form(""),
    quantity_unit: str = Form("MT"),
    quantity_unit_other: str = Form(""),
    price: str = Form(""),
    price_unit: str = Form("/MT"),
    notes: str = Form(""),
    # Shipping / tracking fields
    po_date: str = Form(""),
    packing: str = Form(""),
    gbl_invoice: str = Form(""),
    gbl_invoice_date: str = Form(""),
    container_number: str = Form(""),
    vessel_name: str = Form(""),
    etd_india: str = Form(""),
    transit_time: str = Form(""),
    destination: str = Form(""),
    eta: str = Form(""),
    incoterms: str = Form(""),
    payment_terms: str = Form(""),
    shipment_timing: str = Form(""),
):
    deal_id = create_deal(
        {
            "company": company,
            "product": product,
            "deal_date": deal_date,
            "po_number": po_number,
            "quote_ref": quote_ref,
            "quantity": quantity,
            "quantity_unit": normalize_quantity_unit(
                quantity_unit, quantity_unit_other
            ),
            "price": price,
            "price_unit": price_unit,
            "notes": notes,
        }
    )
    # Save commercial + shipping fields if any were provided
    extra = {
        "po_date": po_date, "packing": packing, "gbl_invoice": gbl_invoice,
        "gbl_invoice_date": gbl_invoice_date, "container_number": container_number,
        "vessel_name": vessel_name, "etd_india": etd_india,
        "transit_time": transit_time, "destination": destination, "eta": eta,
        "incoterms": incoterms, "payment_terms": payment_terms,
        "shipment_timing": shipment_timing,
    }
    if any(v.strip() for v in extra.values()):
        update_deal_fields(
            deal_id,
            po_number=po_number, quote_ref=quote_ref,
            quantity=quantity,
            quantity_unit=normalize_quantity_unit(quantity_unit, quantity_unit_other),
            price=price, price_unit=price_unit, notes=notes,
            **extra,
        )
    return RedirectResponse("/deals", status_code=303)


@app.post("/add/log")
async def post_log(
    request: Request,
    company: str = Form(...),
    link_mode: str = Form("none"),
    deal_id: str = Form(""),
    product: str = Form(""),
    product_new: str = Form(""),
    product_none: str = Form(""),
    deal_date: str = Form(""),
    po_number: str = Form(""),
    quantity: str = Form(""),
    quantity_unit: str = Form("MT"),
    quantity_unit_other: str = Form(""),
    price: str = Form(""),
    price_unit: str = Form("/MT"),
    deal_quantity: str = Form(""),
    deal_quantity_unit: str = Form("MT"),
    deal_quantity_unit_other: str = Form(""),
    deal_price: str = Form(""),
    deal_price_unit: str = Form("/MT"),
    deal_notes: str = Form(""),
    deal_po_number: str = Form(""),
    deal_notes_append: str = Form(""),
    quote_ref: str = Form(""),
    activity_date: str = Form(...),
    channel: str = Form("Email"),
    comment: str = Form(""),
    value: str = Form(""),
    # Shipping fields — only used when link_mode == "new"
    po_date: str = Form(""),
    packing: str = Form(""),
    gbl_invoice: str = Form(""),
    gbl_invoice_date: str = Form(""),
    container_number: str = Form(""),
    vessel_name: str = Form(""),
    etd_india: str = Form(""),
    transit_time: str = Form(""),
    destination: str = Form(""),
    eta: str = Form(""),
    incoterms: str = Form(""),
    payment_terms: str = Form(""),
    shipment_timing: str = Form(""),
):
    if link_mode == "new":
        product_val = product_new or product
    elif link_mode == "none":
        product_val = product_none or product
    else:
        product_val = product
    try:
        result = log_update(
            {
                "company": company,
                "link_mode": link_mode,
                "deal_id": int(deal_id) if deal_id and link_mode == "existing" else None,
                "product": product_val,
                "deal_date": deal_date or activity_date,
                "po_number": po_number,
                "quantity": quantity or deal_quantity,
                "quantity_unit": quantity_unit or deal_quantity_unit,
                "quantity_unit_other": quantity_unit_other or deal_quantity_unit_other,
                "price": price or deal_price,
                "price_unit": price_unit if price or quantity else deal_price_unit,
                "deal_notes": deal_notes,
                "deal_po_number": deal_po_number,
                "quote_ref": quote_ref,
                "deal_quantity": deal_quantity,
                "deal_quantity_unit": deal_quantity_unit,
                "deal_quantity_unit_other": deal_quantity_unit_other,
                "deal_price": deal_price,
                "deal_price_unit": deal_price_unit,
                "deal_notes_append": deal_notes_append,
                "activity_date": activity_date,
                "channel": channel,
                "comment": comment,
                "value": value,
            }
        )
    except ValueError as e:
        return RedirectResponse(
            f"/add?tab=log&company={quote(company)}&error={quote(str(e))}",
            status_code=303,
        )
    # Save shipping + commercial fields for new or existing deals when provided
    if result.get("deal_id") and link_mode in ("new", "existing"):
        extra = {
            "po_date": po_date, "packing": packing, "gbl_invoice": gbl_invoice,
            "gbl_invoice_date": gbl_invoice_date, "container_number": container_number,
            "vessel_name": vessel_name, "etd_india": etd_india,
            "transit_time": transit_time, "destination": destination, "eta": eta,
            "incoterms": incoterms, "payment_terms": payment_terms,
            "shipment_timing": shipment_timing,
        }
        if any(v.strip() for v in extra.values()):
            update_deal_fields(result["deal_id"], **extra)
    return_to = request.query_params.get("return_to", "")
    if return_to.startswith("/"):
        return RedirectResponse(return_to, status_code=303)
    if result.get("deal_id"):
        return RedirectResponse(f"/deal/{result['deal_id']}", status_code=303)
    return RedirectResponse(f"/customer?name={quote(company)}", status_code=303)


@app.post("/deals/{deal_id}/ship")
async def ship_deal(deal_id: int, shipped_date: str = Form(""), next_url: str = Form("")):
    mark_deal_shipped(deal_id, shipped_date or None)
    return RedirectResponse(next_url or "/deals?status=open", status_code=303)


@app.post("/deals/{deal_id}/lost")
async def lost_deal(
    deal_id: int,
    closed_date: str = Form(""),
    lost_reason: str = Form(""),
    next_url: str = Form(""),
):
    mark_deal_lost(deal_id, closed_date or None, lost_reason)
    return RedirectResponse(next_url or "/deals?status=open", status_code=303)


@app.post("/deals/{deal_id}/archive")
async def archive_deal_route(deal_id: int, next_url: str = Form("")):
    archive_deal(deal_id)
    return RedirectResponse(next_url or "/deals?status=open", status_code=303)


@app.post("/deals/{deal_id}/unarchive")
async def unarchive_deal_route(deal_id: int, next_url: str = Form("")):
    unarchive_deal(deal_id)
    return RedirectResponse(next_url or "/deals?status=archived", status_code=303)


@app.post("/deals/{deal_id}/delete")
async def delete_deal_route(deal_id: int, next_url: str = Form("")):
    delete_deal(deal_id)
    return RedirectResponse(next_url or "/deals?status=open", status_code=303)


@app.post("/deals/bulk")
async def bulk_deals_route(
    action: str = Form(...),
    deal_ids: List[str] = Form(default=[]),
    lost_reason: str = Form(""),
    closed_date: str = Form(""),
    return_status: str = Form("open"),
    return_period: str = Form("all"),
):
    ids = [int(x) for x in deal_ids if x and x.isdigit()]
    if ids:
        bulk_deal_action(ids, action, lost_reason, closed_date or None)
    qs = f"status={return_status}&period={return_period}"
    return RedirectResponse(f"/deals?{qs}", status_code=303)


@app.post("/activities/{activity_id}/edit")
async def edit_activity_route(
    activity_id: int,
    activity_date: str = Form(...),
    channel: str = Form("Note"),
    comment: str = Form(""),
    link_mode: str = Form("none"),
    deal_id: str = Form(""),
    product: str = Form(""),
    product_new: str = Form(""),
    product_none: str = Form(""),
    deal_date: str = Form(""),
    next_url: str = Form(""),
):
    if link_mode == "new":
        product_val = product_new or product
    elif link_mode == "none":
        product_val = product_none or product
    else:
        product_val = product
    try:
        company = update_activity(
            activity_id,
            {
                "activity_date": activity_date,
                "channel": channel,
                "comment": comment,
                "link_mode": link_mode,
                "deal_id": deal_id if link_mode == "existing" else "",
                "product": product_val,
                "deal_date": deal_date or activity_date,
            },
        )
    except ValueError as e:
        base = next_url if next_url.startswith("/") else "/contacts"
        sep = "&" if "?" in base else "?"
        code = "pick_deal" if "Pick a deal" in str(e) else quote(str(e))
        return RedirectResponse(f"{base}{sep}error={code}", status_code=303)
    if next_url.startswith("/"):
        return RedirectResponse(next_url, status_code=303)
    if company:
        return RedirectResponse(f"/customer?name={quote(company)}", status_code=303)
    return RedirectResponse("/contacts", status_code=303)


@app.post("/activities/{activity_id}/attach")
async def attach_activity_route(
    activity_id: int,
    deal_id: int = Form(...),
    next_url: str = Form(""),
):
    attach_activity_to_deal(activity_id, deal_id)
    return RedirectResponse(next_url or f"/deal/{deal_id}", status_code=303)


@app.post("/activities/{activity_id}/delete")
async def delete_activity_route(
    activity_id: int,
    next_url: str = Form(""),
):
    company = delete_activity(activity_id)
    if next_url.startswith("/"):
        return RedirectResponse(next_url, status_code=303)
    if company:
        return RedirectResponse(f"/customer?name={quote(company)}", status_code=303)
    return RedirectResponse("/contacts", status_code=303)


@app.get("/customer", response_class=HTMLResponse)
async def customer_page(
    request: Request,
    name: str = Query(...),
    product: str = Query(""),
    error: str = Query(""),
):
    detail = customer_detail(name, product)
    if not detail:
        return RedirectResponse("/contacts", status_code=303)
    err_msg = ""
    if error == "pick_deal":
        err_msg = "Pick a deal to attach this entry to, or switch to Company only."
    elif error:
        err_msg = error.replace("+", " ")
    return templates.TemplateResponse(
        "customer.html",
        ctx(
            request,
            page="contacts",
            detail=detail,
            product_filter=product,
            company_deals=deals_for_activity_edit(
                name, _timeline_deal_ids(detail["timeline"])
            ),
            activity_error=err_msg,
        ),
    )


@app.post("/customer/{customer_id}/delete")
async def delete_customer_route(customer_id: int):
    name = delete_customer(customer_id)
    if not name:
        return RedirectResponse("/contacts?error=company_not_found", status_code=303)
    return RedirectResponse("/contacts", status_code=303)


@app.post("/customer/{customer_id}/profile")
async def edit_company_profile_route(
    customer_id: int,
    website: str = Form(""),
    notes: str = Form(""),
    company: str = Form(""),
):
    update_company_profile(
        customer_id,
        {
            "website": website,
            "notes": notes,
        },
    )
    return RedirectResponse(f"/customer?name={quote(company)}", status_code=303)


@app.post("/customer/{customer_id}/contacts")
async def add_contact(
    customer_id: int,
    contact: str = Form(""),
    email: str = Form(""),
    phone: str = Form(""),
    is_primary: str = Form(""),
    company: str = Form(""),
):
    create_contact(
        customer_id,
        {"contact": contact, "email": email, "phone": phone},
        is_primary=bool(is_primary),
    )
    return RedirectResponse(f"/customer?name={quote(company)}", status_code=303)


@app.post("/contacts/{contact_id}/update")
async def edit_contact(
    contact_id: int,
    contact: str = Form(""),
    email: str = Form(""),
    phone: str = Form(""),
    is_primary: str = Form(""),
    company: str = Form(""),
):
    update_contact(
        contact_id,
        {
            "contact": contact,
            "email": email,
            "phone": phone,
            "is_primary": bool(is_primary),
        },
    )
    return RedirectResponse(f"/customer?name={quote(company)}", status_code=303)


@app.post("/contacts/{contact_id}/delete")
async def remove_contact(
    contact_id: int,
    company: str = Form(""),
):
    delete_contact(contact_id)
    return RedirectResponse(f"/customer?name={quote(company)}", status_code=303)


def _download_response(content: bytes, filename: str, media_type: str) -> Response:
    # In the packaged Tauri app WKWebView cannot trigger file downloads, so
    # save to ~/Downloads and open in the default app instead.
    if _os.environ.get("SATHGEN_BUNDLE_BASE") or getattr(_sys, "frozen", False):
        _export_to_downloads(content, filename)
        return Response(
            content=b"",
            status_code=204,
        )
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/summary/export.csv")
async def summary_export_csv(
    period: str = Query("month"),
    group: str = Query("product"),
    sheet: str = Query("rollup"),
):
    if sheet == "shipping":
        rows = list_shipping_summary(status="open")
        cols = SHIPPING_COLUMNS
        fname = export_filename("gbinc-shipping-summary", period, "csv")
    else:
        rows = summary_by_customer(period)
        cols = rollup_columns(group)
        fname = export_filename("gbinc-summary", period, "csv", group)
    return _download_response(
        to_csv_bytes(rows, cols),
        fname,
        "text/csv; charset=utf-8",
    )


@app.get("/summary/export.xlsx")
async def summary_export_xlsx(
    period: str = Query("month"),
    group: str = Query("product"),
    sheet: str = Query("all"),
):
    rollup_rows = summary_by_customer(period)
    shipping_rows = list_shipping_summary(status="open")
    if sheet == "rollup":
        sheets = [(rollup_sheet_name(group), rollup_rows, rollup_columns(group))]
        fname = export_filename("gbinc-summary", period, "xlsx", group)
    elif sheet == "shipping":
        sheets = [("Shipping", shipping_rows, SHIPPING_COLUMNS)]
        fname = export_filename("gbinc-shipping-summary", period, "xlsx")
    else:
        sheets = [
            (rollup_sheet_name(group), rollup_rows, rollup_columns(group)),
            ("Shipping", shipping_rows, SHIPPING_COLUMNS),
        ]
        fname = export_filename("gbinc-summary-all", period, "xlsx", group)
    return _download_response(
        to_xlsx_bytes(sheets),
        fname,
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@app.get("/shipping/export.csv")
async def shipping_export_csv(
    company: str = Query(""),
    product: str = Query(""),
    status: str = Query("all"),
    q: str = Query(""),
):
    rows = list_shipping_summary(company, product, status, q)
    fname = export_filename("gbinc-shipping", status if status != "all" else "", "csv")
    return _download_response(
        to_csv_bytes(rows, SHIPPING_COLUMNS),
        fname,
        "text/csv; charset=utf-8",
    )


@app.get("/shipping/export.xlsx")
async def shipping_export_xlsx(
    company: str = Query(""),
    product: str = Query(""),
    status: str = Query("all"),
    q: str = Query(""),
):
    rows = list_shipping_summary(company, product, status, q)
    fname = export_filename("gbinc-shipping", status if status != "all" else "", "xlsx")
    return _download_response(
        to_xlsx_bytes([("Shipping", rows, SHIPPING_COLUMNS)]),
        fname,
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )



DEALS_COLUMNS: list[tuple[str, str]] = [
    ("Deal Date", "deal_date"),
    ("Company", "company"),
    ("Product", "product"),
    ("Quantity", "quantity"),
    ("Unit", "quantity_unit"),
    ("Price", "price"),
    ("Price Unit", "price_unit"),
    ("Value", "value"),
    ("Status", "status"),
    ("PO Number", "po_number"),
    ("Quote Ref", "quote_ref"),
    ("Notes", "notes"),
]


@app.get("/contacts/export.xlsx")
async def contacts_export_xlsx(
    company: str = Query(""),
    q: str = Query(""),
):
    rows = search_leads_contacts(company, "", q)
    fname = export_filename("sathgen-contacts", "", "xlsx")
    return _download_response(
        to_xlsx_bytes([("Contacts", rows, LEADS_COLUMNS)]),
        fname,
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@app.get("/deals/export.xlsx")
async def deals_export_xlsx(
    status: str = Query("open"),
    period: str = Query("all"),
    company: str = Query(""),
    product: str = Query(""),
    q: str = Query(""),
):
    rows = list_active_leads(status, period, company, product, "", q)
    fname = export_filename("gbinc-active-leads", status, "xlsx")
    return _download_response(
        to_xlsx_bytes([("Active Leads", rows, DEALS_COLUMNS)]),
        fname,
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@app.get("/summary", response_class=HTMLResponse)
async def summary(
    request: Request,
    period: str = Query("month"),
    group: str = Query("product"),
):
    rows = summary_by_customer(period)
    shipping_rows = list_shipping_summary(status="open")[:40]
    return templates.TemplateResponse(
        "summary.html",
        ctx(
            request,
            page="summary",
            shipping_rows=shipping_rows,
            period=period,
            group=group,
            rows=rows,
            stats=dashboard_stats(period),
        ),
    )


