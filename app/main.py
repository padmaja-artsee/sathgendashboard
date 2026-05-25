import os as _os
import sys as _sys
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, File, Form, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

_os.environ.setdefault("FINANCE_BASE_PATH", "/finance")
_bundle_base = _os.environ.get("SATHGEN_BUNDLE_BASE")
BASE = Path(_bundle_base) if _bundle_base else Path(__file__).resolve().parent.parent

app = FastAPI(title="Sathgen Therapeutics BD CRM")
app.mount("/static", StaticFiles(directory=str(BASE / "static")), name="static")
app.mount("/leads-static", StaticFiles(directory=str(BASE / "static")), name="leads-static")
templates = Jinja2Templates(directory=str(BASE / "templates"))

from app.database import (
    init_db, now_iso,
    list_companies, get_company, create_company, update_company, delete_company, get_company_detail,
    list_contacts, get_contact, create_contact, update_contact, delete_contact,
    list_opportunities, get_opportunity, create_opportunity, update_opportunity, delete_opportunity,
    opportunities_by_stage, get_opportunity_detail,
    list_activities, get_activity, create_activity, update_activity, delete_activity,
    list_followups, get_followup, create_followup, complete_followup, delete_followup,
    overdue_followups, due_this_week_followups,
    list_documents, get_document, create_document, delete_document,
    list_document_shares, create_document_share,
    dashboard_stats, recent_activities, upcoming_followups,
)
from app.exports import export_to_xlsx


@app.on_event("startup")
def startup() -> None:
    import sqlite3 as _sqlite3
    import logging as _logging
    _log = _logging.getLogger("crm.startup")

    try:
        from app.database import DB_PATH as _DB_PATH
        _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        _wc = _sqlite3.connect(str(_DB_PATH), timeout=30)
        _wc.execute("PRAGMA journal_mode = WAL")
        _wc.commit()
        _wc.close()
    except Exception as exc:
        _log.error("WAL setup failed: %s", exc)

    try:
        init_db()
    except Exception as exc:
        _log.error("init_db failed: %s", exc)

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


# Mount finance sub-app LAST
try:
    from finance.app.main import app as finance_app
    app.mount("/finance", finance_app)
except Exception as _e:
    import warnings
    warnings.warn(f"Finance sub-app could not be mounted: {_e}")


def ctx(request: Request, **kwargs):
    return {"request": request, **kwargs}


def _today() -> str:
    return datetime.utcnow().date().isoformat()


# ── Dashboard ──────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    return templates.TemplateResponse("dashboard.html", ctx(
        request, page="dashboard",
        stats=dashboard_stats(),
        recent=recent_activities(10),
        upcoming=upcoming_followups(10),
        opp_by_stage=opportunities_by_stage(),
    ))


# ── Companies ──────────────────────────────────────────────────────────────────

@app.get("/companies", response_class=HTMLResponse)
async def companies_list(
    request: Request,
    search: str = Query(""),
    company_type: str = Query(""),
    status: str = Query(""),
    region: str = Query(""),
):
    return templates.TemplateResponse("companies.html", ctx(
        request, page="companies",
        companies=list_companies(search, company_type, status, region),
        search=search, company_type=company_type, status=status, region=region,
    ))


@app.get("/companies/new", response_class=HTMLResponse)
async def company_new_form(request: Request):
    return templates.TemplateResponse("company_form.html", ctx(
        request, page="companies", company=None, action="/companies/new",
    ))


@app.post("/companies/new")
async def company_new_post(
    name: str = Form(...),
    company_type: str = Form(""),
    website: str = Form(""),
    country: str = Form(""),
    region: str = Form(""),
    therapeutic_focus: str = Form(""),
    strategic_fit_score: str = Form("0"),
    status: str = Form("active"),
    owner: str = Form(""),
    notes: str = Form(""),
):
    create_company({
        'name': name, 'company_type': company_type, 'website': website,
        'country': country, 'region': region, 'therapeutic_focus': therapeutic_focus,
        'strategic_fit_score': strategic_fit_score, 'status': status,
        'owner': owner, 'notes': notes,
    })
    return RedirectResponse("/companies", status_code=303)


@app.get("/companies/{company_id}", response_class=HTMLResponse)
async def company_detail(request: Request, company_id: int):
    detail = get_company_detail(company_id)
    if not detail:
        return RedirectResponse("/companies", status_code=303)
    return templates.TemplateResponse("company_detail.html", ctx(
        request, page="companies", detail=detail, today=_today(),
    ))


@app.get("/companies/{company_id}/edit", response_class=HTMLResponse)
async def company_edit_form(request: Request, company_id: int):
    company = get_company(company_id)
    if not company:
        return RedirectResponse("/companies", status_code=303)
    return templates.TemplateResponse("company_form.html", ctx(
        request, page="companies", company=company,
        action=f"/companies/{company_id}/edit",
    ))


@app.post("/companies/{company_id}/edit")
async def company_edit_post(
    company_id: int,
    name: str = Form(...),
    company_type: str = Form(""),
    website: str = Form(""),
    country: str = Form(""),
    region: str = Form(""),
    therapeutic_focus: str = Form(""),
    strategic_fit_score: str = Form("0"),
    status: str = Form("active"),
    owner: str = Form(""),
    notes: str = Form(""),
):
    update_company(company_id, {
        'name': name, 'company_type': company_type, 'website': website,
        'country': country, 'region': region, 'therapeutic_focus': therapeutic_focus,
        'strategic_fit_score': strategic_fit_score, 'status': status,
        'owner': owner, 'notes': notes,
    })
    return RedirectResponse(f"/companies/{company_id}", status_code=303)


@app.post("/companies/{company_id}/delete")
async def company_delete(company_id: int):
    delete_company(company_id)
    return RedirectResponse("/companies", status_code=303)


# ── Contacts ───────────────────────────────────────────────────────────────────

@app.get("/contacts", response_class=HTMLResponse)
async def contacts_list(
    request: Request,
    search: str = Query(""),
    company_id: str = Query(""),
    role_type: str = Query(""),
    relationship_strength: str = Query(""),
    nda_status: str = Query(""),
):
    cid = int(company_id) if company_id.isdigit() else None
    return templates.TemplateResponse("contacts.html", ctx(
        request, page="contacts",
        contacts=list_contacts(search, cid, role_type, relationship_strength, nda_status),
        companies=list_companies(),
        search=search, company_id=company_id, role_type=role_type,
        relationship_strength=relationship_strength, nda_status=nda_status,
    ))


@app.get("/contacts/new", response_class=HTMLResponse)
async def contact_new_form(request: Request, company_id: str = Query("")):
    return templates.TemplateResponse("contact_form.html", ctx(
        request, page="contacts", contact=None,
        companies=list_companies(),
        preset_company_id=company_id,
        action="/contacts/new",
    ))


@app.post("/contacts/new")
async def contact_new_post(
    company_id: str = Form(""),
    first_name: str = Form(""),
    last_name: str = Form(""),
    title: str = Form(""),
    email: str = Form(""),
    phone: str = Form(""),
    linkedin: str = Form(""),
    role_type: str = Form(""),
    relationship_strength: str = Form("warm"),
    source: str = Form(""),
    first_contact_date: str = Form(""),
    nda_status: str = Form("none"),
    notes: str = Form(""),
):
    cid = int(company_id) if company_id.isdigit() else None
    create_contact({
        'company_id': cid, 'first_name': first_name, 'last_name': last_name,
        'title': title, 'email': email, 'phone': phone, 'linkedin': linkedin,
        'role_type': role_type, 'relationship_strength': relationship_strength,
        'source': source, 'first_contact_date': first_contact_date,
        'nda_status': nda_status, 'notes': notes,
    })
    if cid:
        return RedirectResponse(f"/companies/{cid}", status_code=303)
    return RedirectResponse("/contacts", status_code=303)


@app.get("/contacts/{contact_id}", response_class=HTMLResponse)
async def contact_detail(request: Request, contact_id: int):
    contact = get_contact(contact_id)
    if not contact:
        return RedirectResponse("/contacts", status_code=303)
    activities = list_activities(contact_id=contact_id, limit=30)
    followups = list_followups(status='open')
    followups = [f for f in followups if f.get('contact_id') == contact_id]
    return templates.TemplateResponse("contact_detail.html", ctx(
        request, page="contacts",
        contact=contact, activities=activities, followups=followups,
    ))


@app.get("/contacts/{contact_id}/edit", response_class=HTMLResponse)
async def contact_edit_form(request: Request, contact_id: int):
    contact = get_contact(contact_id)
    if not contact:
        return RedirectResponse("/contacts", status_code=303)
    return templates.TemplateResponse("contact_form.html", ctx(
        request, page="contacts", contact=contact,
        companies=list_companies(),
        preset_company_id=str(contact.get('company_id', '')),
        action=f"/contacts/{contact_id}/edit",
    ))


@app.post("/contacts/{contact_id}/edit")
async def contact_edit_post(
    contact_id: int,
    company_id: str = Form(""),
    first_name: str = Form(""),
    last_name: str = Form(""),
    title: str = Form(""),
    email: str = Form(""),
    phone: str = Form(""),
    linkedin: str = Form(""),
    role_type: str = Form(""),
    relationship_strength: str = Form("warm"),
    source: str = Form(""),
    first_contact_date: str = Form(""),
    last_interaction_date: str = Form(""),
    nda_status: str = Form("none"),
    notes: str = Form(""),
):
    cid = int(company_id) if company_id.isdigit() else None
    update_contact(contact_id, {
        'company_id': cid, 'first_name': first_name, 'last_name': last_name,
        'title': title, 'email': email, 'phone': phone, 'linkedin': linkedin,
        'role_type': role_type, 'relationship_strength': relationship_strength,
        'source': source, 'first_contact_date': first_contact_date,
        'last_interaction_date': last_interaction_date,
        'nda_status': nda_status, 'notes': notes,
    })
    return RedirectResponse(f"/contacts/{contact_id}", status_code=303)


@app.post("/contacts/{contact_id}/delete")
async def contact_delete(contact_id: int):
    contact = get_contact(contact_id)
    cid = contact.get('company_id') if contact else None
    delete_contact(contact_id)
    if cid:
        return RedirectResponse(f"/companies/{cid}", status_code=303)
    return RedirectResponse("/contacts", status_code=303)


# ── Opportunities ──────────────────────────────────────────────────────────────

@app.get("/opportunities", response_class=HTMLResponse)
async def opportunities_list(
    request: Request,
    stage: str = Query(""),
    priority: str = Query(""),
    status: str = Query("open"),
    view: str = Query("table"),
):
    opps = list_opportunities(stage, priority, status=status)
    opp_by_stage = opportunities_by_stage() if view == "pipeline" else {}
    return templates.TemplateResponse("opportunities.html", ctx(
        request, page="opportunities",
        opportunities=opps, opp_by_stage=opp_by_stage,
        stage=stage, priority=priority, status=status, view=view,
    ))


@app.get("/opportunities/new", response_class=HTMLResponse)
async def opportunity_new_form(request: Request, company_id: str = Query("")):
    cid = int(company_id) if company_id.isdigit() else None
    companies = list_companies()
    contacts = list_contacts(company_id=cid) if cid else []
    return templates.TemplateResponse("opportunity_form.html", ctx(
        request, page="opportunities", opportunity=None,
        companies=companies, contacts=contacts,
        preset_company_id=company_id,
        action="/opportunities/new",
    ))


@app.post("/opportunities/new")
async def opportunity_new_post(
    company_id: str = Form(""),
    primary_contact_id: str = Form(""),
    name: str = Form(...),
    opportunity_type: str = Form(""),
    asset_or_program: str = Form(""),
    indication: str = Form(""),
    stage: str = Form("initial_contact"),
    priority: str = Form("medium"),
    probability: str = Form("0"),
    estimated_value: str = Form(""),
    expected_close_date: str = Form(""),
    nda_status: str = Form("none"),
    data_room_status: str = Form("none"),
    key_objections: str = Form(""),
    next_step: str = Form(""),
    next_step_due_date: str = Form(""),
    owner: str = Form(""),
    status: str = Form("open"),
    notes: str = Form(""),
):
    cid = int(company_id) if company_id.isdigit() else None
    pcid = int(primary_contact_id) if primary_contact_id.isdigit() else None
    opp_id = create_opportunity({
        'company_id': cid, 'primary_contact_id': pcid, 'name': name,
        'opportunity_type': opportunity_type, 'asset_or_program': asset_or_program,
        'indication': indication, 'stage': stage, 'priority': priority,
        'probability': probability, 'estimated_value': estimated_value,
        'expected_close_date': expected_close_date, 'nda_status': nda_status,
        'data_room_status': data_room_status, 'key_objections': key_objections,
        'next_step': next_step, 'next_step_due_date': next_step_due_date,
        'owner': owner, 'status': status, 'notes': notes,
    })
    return RedirectResponse(f"/opportunities/{opp_id}", status_code=303)


@app.get("/opportunities/{opp_id}", response_class=HTMLResponse)
async def opportunity_detail(request: Request, opp_id: int):
    detail = get_opportunity_detail(opp_id)
    if not detail:
        return RedirectResponse("/opportunities", status_code=303)
    return templates.TemplateResponse("opportunity_detail.html", ctx(
        request, page="opportunities", detail=detail,
    ))


@app.get("/opportunities/{opp_id}/edit", response_class=HTMLResponse)
async def opportunity_edit_form(request: Request, opp_id: int):
    opp = get_opportunity(opp_id)
    if not opp:
        return RedirectResponse("/opportunities", status_code=303)
    cid = opp.get('company_id')
    companies = list_companies()
    contacts = list_contacts(company_id=cid) if cid else []
    return templates.TemplateResponse("opportunity_form.html", ctx(
        request, page="opportunities", opportunity=opp,
        companies=companies, contacts=contacts,
        preset_company_id=str(cid or ''),
        action=f"/opportunities/{opp_id}/edit",
    ))


@app.post("/opportunities/{opp_id}/edit")
async def opportunity_edit_post(
    opp_id: int,
    company_id: str = Form(""),
    primary_contact_id: str = Form(""),
    name: str = Form(...),
    opportunity_type: str = Form(""),
    asset_or_program: str = Form(""),
    indication: str = Form(""),
    stage: str = Form("initial_contact"),
    priority: str = Form("medium"),
    probability: str = Form("0"),
    estimated_value: str = Form(""),
    expected_close_date: str = Form(""),
    nda_status: str = Form("none"),
    data_room_status: str = Form("none"),
    key_objections: str = Form(""),
    next_step: str = Form(""),
    next_step_due_date: str = Form(""),
    owner: str = Form(""),
    status: str = Form("open"),
    notes: str = Form(""),
):
    cid = int(company_id) if company_id.isdigit() else None
    pcid = int(primary_contact_id) if primary_contact_id.isdigit() else None
    update_opportunity(opp_id, {
        'company_id': cid, 'primary_contact_id': pcid, 'name': name,
        'opportunity_type': opportunity_type, 'asset_or_program': asset_or_program,
        'indication': indication, 'stage': stage, 'priority': priority,
        'probability': probability, 'estimated_value': estimated_value,
        'expected_close_date': expected_close_date, 'nda_status': nda_status,
        'data_room_status': data_room_status, 'key_objections': key_objections,
        'next_step': next_step, 'next_step_due_date': next_step_due_date,
        'owner': owner, 'status': status, 'notes': notes,
    })
    return RedirectResponse(f"/opportunities/{opp_id}", status_code=303)


@app.post("/opportunities/{opp_id}/delete")
async def opportunity_delete(opp_id: int):
    delete_opportunity(opp_id)
    return RedirectResponse("/opportunities", status_code=303)


@app.get("/api/contacts-for-company")
async def api_contacts_for_company(company_id: str = Query("")):
    cid = int(company_id) if company_id.isdigit() else None
    if not cid:
        return JSONResponse([])
    contacts = list_contacts(company_id=cid)
    return JSONResponse([{'id': c['id'], 'name': f"{c['first_name']} {c['last_name']}"} for c in contacts])


# ── Activities ─────────────────────────────────────────────────────────────────

@app.get("/activities", response_class=HTMLResponse)
async def activities_list(
    request: Request,
    company_id: str = Query(""),
    activity_type: str = Query(""),
):
    cid = int(company_id) if company_id.isdigit() else None
    acts = list_activities(company_id=cid, limit=100)
    if activity_type:
        acts = [a for a in acts if a.get('activity_type') == activity_type]
    return templates.TemplateResponse("activities.html", ctx(
        request, page="activities",
        activities=acts,
        companies=list_companies(),
        company_id=company_id, activity_type=activity_type,
    ))


@app.get("/activities/new", response_class=HTMLResponse)
async def activity_new_form(
    request: Request,
    company_id: str = Query(""),
    contact_id: str = Query(""),
    opportunity_id: str = Query(""),
):
    cid = int(company_id) if company_id.isdigit() else None
    contacts = list_contacts(company_id=cid) if cid else list_contacts()
    return templates.TemplateResponse("activity_form.html", ctx(
        request, page="activities",
        activity=None,
        companies=list_companies(),
        contacts=contacts,
        opportunities=list_opportunities(status='open'),
        preset_company_id=company_id,
        preset_contact_id=contact_id,
        preset_opportunity_id=opportunity_id,
        today=_today(),
        action="/activities/new",
    ))


@app.post("/activities/new")
async def activity_new_post(
    company_id: str = Form(""),
    contact_id: str = Form(""),
    opportunity_id: str = Form(""),
    activity_date: str = Form(...),
    activity_type: str = Form("email"),
    subject: str = Form(""),
    summary: str = Form(""),
    documents_shared: str = Form(""),
    action_items: str = Form(""),
    follow_up_required: str = Form(""),
    follow_up_date: str = Form(""),
    follow_up_priority: str = Form("medium"),
    sentiment: str = Form("neutral"),
    owner: str = Form(""),
):
    cid = int(company_id) if company_id.isdigit() else None
    ctid = int(contact_id) if contact_id.isdigit() else None
    oid = int(opportunity_id) if opportunity_id.isdigit() else None
    act_id = create_activity({
        'company_id': cid, 'contact_id': ctid, 'opportunity_id': oid,
        'activity_date': activity_date, 'activity_type': activity_type,
        'subject': subject, 'summary': summary, 'documents_shared': documents_shared,
        'action_items': action_items, 'follow_up_required': bool(follow_up_required),
        'follow_up_date': follow_up_date, 'follow_up_priority': follow_up_priority,
        'sentiment': sentiment, 'owner': owner,
    })
    if cid:
        return RedirectResponse(f"/companies/{cid}", status_code=303)
    return RedirectResponse("/activities", status_code=303)


@app.get("/activities/{activity_id}", response_class=HTMLResponse)
async def activity_detail(request: Request, activity_id: int):
    activity = get_activity(activity_id)
    if not activity:
        return RedirectResponse("/activities", status_code=303)
    return templates.TemplateResponse("activity_detail.html", ctx(
        request, page="activities", activity=activity,
    ))


@app.post("/activities/{activity_id}/delete")
async def activity_delete(activity_id: int, next_url: str = Form("")):
    act = get_activity(activity_id)
    cid = act.get('company_id') if act else None
    delete_activity(activity_id)
    if next_url.startswith("/"):
        return RedirectResponse(next_url, status_code=303)
    if cid:
        return RedirectResponse(f"/companies/{cid}", status_code=303)
    return RedirectResponse("/activities", status_code=303)


# ── Follow-ups ─────────────────────────────────────────────────────────────────

@app.get("/followups", response_class=HTMLResponse)
async def followups_list(
    request: Request,
    status: str = Query("open"),
    priority: str = Query(""),
    owner: str = Query(""),
):
    today = _today()
    followups = list_followups(status=status, priority=priority, owner=owner)
    return templates.TemplateResponse("followups.html", ctx(
        request, page="followups",
        followups=followups, today=today,
        status=status, priority=priority, owner=owner,
    ))


@app.get("/followups/new", response_class=HTMLResponse)
async def followup_new_form(
    request: Request,
    company_id: str = Query(""),
    opportunity_id: str = Query(""),
):
    return templates.TemplateResponse("followup_form.html", ctx(
        request, page="followups",
        followup=None,
        companies=list_companies(),
        opportunities=list_opportunities(status='open'),
        contacts=list_contacts(),
        preset_company_id=company_id,
        preset_opportunity_id=opportunity_id,
        today=_today(),
        action="/followups/new",
    ))


@app.post("/followups/new")
async def followup_new_post(
    company_id: str = Form(""),
    contact_id: str = Form(""),
    opportunity_id: str = Form(""),
    due_date: str = Form(...),
    action: str = Form(...),
    priority: str = Form("medium"),
    owner: str = Form(""),
    notes: str = Form(""),
):
    cid = int(company_id) if company_id.isdigit() else None
    ctid = int(contact_id) if contact_id.isdigit() else None
    oid = int(opportunity_id) if opportunity_id.isdigit() else None
    create_followup({
        'company_id': cid, 'contact_id': ctid, 'opportunity_id': oid,
        'due_date': due_date, 'action': action, 'priority': priority,
        'owner': owner, 'notes': notes,
    })
    return RedirectResponse("/followups", status_code=303)


@app.post("/followups/{followup_id}/complete")
async def followup_complete(followup_id: int):
    complete_followup(followup_id)
    return RedirectResponse("/followups", status_code=303)


@app.post("/followups/{followup_id}/delete")
async def followup_delete(followup_id: int):
    delete_followup(followup_id)
    return RedirectResponse("/followups", status_code=303)


# ── Documents ──────────────────────────────────────────────────────────────────

@app.get("/documents", response_class=HTMLResponse)
async def documents_list(request: Request):
    return templates.TemplateResponse("documents.html", ctx(
        request, page="documents",
        documents=list_documents(),
    ))


@app.get("/documents/new", response_class=HTMLResponse)
async def document_new_form(request: Request):
    return templates.TemplateResponse("document_form.html", ctx(
        request, page="documents", document=None, action="/documents/new",
    ))


@app.post("/documents/new")
async def document_new_post(
    document_name: str = Form(...),
    document_type: str = Form(""),
    version: str = Form("1.0"),
    description: str = Form(""),
    file: UploadFile = File(None),
):
    upload_dir = BASE / "data" / "uploads" / "documents"
    upload_dir.mkdir(parents=True, exist_ok=True)
    file_path = ""
    if file and file.filename:
        import uuid
        ext = Path(file.filename).suffix
        fname = f"{uuid.uuid4().hex}{ext}"
        dest = upload_dir / fname
        dest.write_bytes(await file.read())
        file_path = str(dest)
    doc_id = create_document({
        'document_name': document_name, 'document_type': document_type,
        'version': version, 'description': description, 'file_path': file_path,
    })
    return RedirectResponse(f"/documents/{doc_id}", status_code=303)


@app.get("/documents/{doc_id}", response_class=HTMLResponse)
async def document_detail(request: Request, doc_id: int):
    doc = get_document(doc_id)
    if not doc:
        return RedirectResponse("/documents", status_code=303)
    shares = list_document_shares(document_id=doc_id)
    return templates.TemplateResponse("document_detail.html", ctx(
        request, page="documents", document=doc, shares=shares,
    ))


@app.get("/documents/{doc_id}/file")
async def document_file(doc_id: int):
    doc = get_document(doc_id)
    if not doc or not doc.get('file_path'):
        return RedirectResponse("/documents", status_code=303)
    fpath = Path(doc['file_path'])
    if not fpath.exists():
        return Response("File not found", status_code=404)
    return FileResponse(str(fpath), filename=doc['document_name'])


@app.post("/documents/{doc_id}/delete")
async def document_delete(doc_id: int):
    delete_document(doc_id)
    return RedirectResponse("/documents", status_code=303)


@app.get("/documents/{doc_id}/share", response_class=HTMLResponse)
async def document_share_form(request: Request, doc_id: int):
    doc = get_document(doc_id)
    if not doc:
        return RedirectResponse("/documents", status_code=303)
    return templates.TemplateResponse("document_share_form.html", ctx(
        request, page="documents", document=doc,
        companies=list_companies(),
        contacts=list_contacts(),
        opportunities=list_opportunities(status='open'),
        today=_today(),
        action=f"/documents/{doc_id}/share",
    ))


@app.post("/documents/{doc_id}/share")
async def document_share_post(
    doc_id: int,
    company_id: str = Form(""),
    contact_id: str = Form(""),
    opportunity_id: str = Form(""),
    shared_date: str = Form(...),
    shared_under_nda: str = Form(""),
    notes: str = Form(""),
):
    cid = int(company_id) if company_id.isdigit() else None
    ctid = int(contact_id) if contact_id.isdigit() else None
    oid = int(opportunity_id) if opportunity_id.isdigit() else None
    create_document_share({
        'document_id': doc_id, 'company_id': cid, 'contact_id': ctid,
        'opportunity_id': oid, 'shared_date': shared_date,
        'shared_under_nda': bool(shared_under_nda), 'notes': notes,
    })
    return RedirectResponse(f"/documents/{doc_id}", status_code=303)


# ── Reports ────────────────────────────────────────────────────────────────────

@app.get("/reports", response_class=HTMLResponse)
async def reports_page(request: Request):
    opp_by_stage = opportunities_by_stage()
    stage_summary = [
        {'stage': s, 'count': len(opps)} for s, opps in opp_by_stage.items()
    ]
    return templates.TemplateResponse("reports.html", ctx(
        request, page="reports",
        stage_summary=stage_summary,
        stats=dashboard_stats(),
    ))


@app.get("/reports/export/companies.xlsx")
async def export_companies():
    rows = list_companies()
    cols = [("Name","name"),("Type","company_type"),("Website","website"),("Country","country"),
            ("Region","region"),("Therapeutic Focus","therapeutic_focus"),
            ("Fit Score","strategic_fit_score"),("Status","status"),("Owner","owner"),("Notes","notes")]
    content = export_to_xlsx("Companies", rows, cols)
    return Response(content, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": 'attachment; filename="companies.xlsx"'})


@app.get("/reports/export/contacts.xlsx")
async def export_contacts():
    rows = list_contacts()
    cols = [("First Name","first_name"),("Last Name","last_name"),("Company","company_name"),
            ("Title","title"),("Email","email"),("Phone","phone"),("LinkedIn","linkedin"),
            ("Role Type","role_type"),("Relationship","relationship_strength"),("Source","source"),
            ("First Contact","first_contact_date"),("Last Interaction","last_interaction_date"),
            ("NDA Status","nda_status"),("Notes","notes")]
    content = export_to_xlsx("Contacts", rows, cols)
    return Response(content, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": 'attachment; filename="contacts.xlsx"'})


@app.get("/reports/export/opportunities.xlsx")
async def export_opportunities():
    rows = list_opportunities(status='')
    cols = [("Name","name"),("Company","company_name"),("Type","opportunity_type"),
            ("Asset/Program","asset_or_program"),("Indication","indication"),("Stage","stage"),
            ("Priority","priority"),("Probability","probability"),("Est. Value","estimated_value"),
            ("Close Date","expected_close_date"),("NDA","nda_status"),("Data Room","data_room_status"),
            ("Next Step","next_step"),("Next Step Due","next_step_due_date"),
            ("Owner","owner"),("Status","status"),("Notes","notes")]
    content = export_to_xlsx("Opportunities", rows, cols)
    return Response(content, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": 'attachment; filename="opportunities.xlsx"'})


@app.get("/reports/export/activities.xlsx")
async def export_activities():
    rows = list_activities(limit=5000)
    cols = [("Date","activity_date"),("Type","activity_type"),("Subject","subject"),
            ("Company","company_name"),("Contact","contact_name"),("Opportunity","opportunity_name"),
            ("Summary","summary"),("Documents Shared","documents_shared"),
            ("Action Items","action_items"),("Sentiment","sentiment"),("Owner","owner")]
    content = export_to_xlsx("Activities", rows, cols)
    return Response(content, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": 'attachment; filename="activities.xlsx"'})


@app.get("/reports/export/followups.xlsx")
async def export_followups():
    rows = list_followups(status='')
    cols = [("Due Date","due_date"),("Action","action"),("Priority","priority"),
            ("Company","company_name"),("Contact","contact_name"),("Opportunity","opportunity_name"),
            ("Owner","owner"),("Status","status"),("Completed","completed_date"),("Notes","notes")]
    content = export_to_xlsx("Follow-ups", rows, cols)
    return Response(content, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": 'attachment; filename="followups.xlsx"'})
