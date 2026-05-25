import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path

import os as _os

_bundle_base = _os.environ.get("SATHGEN_BUNDLE_BASE")
BASE = Path(_bundle_base) if _bundle_base else Path(__file__).resolve().parent.parent
DB_PATH = BASE / "data" / "crm.db"


def now_iso() -> str:
    return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


@contextmanager
def get_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _row(r) -> dict:
    return dict(r) if r else None


def _rows(rs) -> list:
    return [dict(r) for r in rs]


def init_db():
    with get_db() as db:
        db.executescript("""
CREATE TABLE IF NOT EXISTS companies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    company_type TEXT DEFAULT '',
    partnership_type TEXT DEFAULT '',
    website TEXT DEFAULT '',
    country TEXT DEFAULT '',
    region TEXT DEFAULT '',
    therapeutic_focus TEXT DEFAULT '',
    strategic_fit_score INTEGER DEFAULT 0,
    status TEXT DEFAULT 'active',
    owner TEXT DEFAULT '',
    notes TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS contacts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER REFERENCES companies(id),
    first_name TEXT NOT NULL DEFAULT '',
    last_name TEXT NOT NULL DEFAULT '',
    title TEXT DEFAULT '',
    email TEXT DEFAULT '',
    phone TEXT DEFAULT '',
    linkedin TEXT DEFAULT '',
    role_type TEXT DEFAULT '',
    relationship_strength TEXT DEFAULT 'warm',
    source TEXT DEFAULT '',
    first_contact_date TEXT DEFAULT '',
    last_interaction_date TEXT DEFAULT '',
    nda_status TEXT DEFAULT 'none',
    notes TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS opportunities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER REFERENCES companies(id),
    primary_contact_id INTEGER REFERENCES contacts(id),
    name TEXT NOT NULL DEFAULT '',
    opportunity_type TEXT DEFAULT '',
    asset_or_program TEXT DEFAULT '',
    indication TEXT DEFAULT '',
    stage TEXT DEFAULT 'initial_contact',
    priority TEXT DEFAULT 'medium',
    probability INTEGER DEFAULT 0,
    estimated_value TEXT DEFAULT '',
    expected_close_date TEXT DEFAULT '',
    nda_status TEXT DEFAULT 'none',
    data_room_status TEXT DEFAULT 'none',
    key_objections TEXT DEFAULT '',
    next_step TEXT DEFAULT '',
    next_step_due_date TEXT DEFAULT '',
    owner TEXT DEFAULT '',
    status TEXT DEFAULT 'open',
    notes TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS activities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER REFERENCES companies(id),
    contact_id INTEGER REFERENCES contacts(id),
    opportunity_id INTEGER REFERENCES opportunities(id),
    activity_date TEXT NOT NULL,
    activity_type TEXT DEFAULT 'email',
    subject TEXT DEFAULT '',
    summary TEXT DEFAULT '',
    documents_shared TEXT DEFAULT '',
    action_items TEXT DEFAULT '',
    follow_up_required INTEGER DEFAULT 0,
    follow_up_date TEXT DEFAULT '',
    sentiment TEXT DEFAULT 'neutral',
    owner TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS followups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER REFERENCES companies(id),
    contact_id INTEGER REFERENCES contacts(id),
    opportunity_id INTEGER REFERENCES opportunities(id),
    activity_id INTEGER REFERENCES activities(id),
    due_date TEXT NOT NULL,
    action TEXT NOT NULL DEFAULT '',
    priority TEXT DEFAULT 'medium',
    owner TEXT DEFAULT '',
    status TEXT DEFAULT 'open',
    completed_date TEXT DEFAULT '',
    notes TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_name TEXT NOT NULL DEFAULT '',
    document_type TEXT DEFAULT '',
    version TEXT DEFAULT '1.0',
    file_path TEXT DEFAULT '',
    description TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS document_shares (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id INTEGER REFERENCES documents(id),
    company_id INTEGER REFERENCES companies(id),
    contact_id INTEGER REFERENCES contacts(id),
    opportunity_id INTEGER REFERENCES opportunities(id),
    shared_date TEXT NOT NULL,
    shared_under_nda INTEGER DEFAULT 0,
    notes TEXT DEFAULT '',
    created_at TEXT NOT NULL
);
        """)
        # Migration: add partnership_type if it doesn't exist yet
        existing = {r[1] for r in db.execute("PRAGMA table_info(companies)").fetchall()}
        if 'partnership_type' not in existing:
            db.execute("ALTER TABLE companies ADD COLUMN partnership_type TEXT DEFAULT ''")


# ── Companies ────────────────────────────────────────────────────────────────

def list_companies(search='', company_type='', status='', region='', therapeutic_focus='') -> list:
    sql = """
        SELECT c.*,
            (SELECT COUNT(*) FROM contacts ct WHERE ct.company_id = c.id) AS contact_count,
            (SELECT COUNT(*) FROM opportunities o WHERE o.company_id = c.id AND o.status = 'open') AS opp_count
        FROM companies c
        WHERE 1=1
    """
    params = []
    if search:
        sql += " AND (c.name LIKE ? OR c.therapeutic_focus LIKE ? OR c.country LIKE ?)"
        params += [f"%{search}%", f"%{search}%", f"%{search}%"]
    if company_type:
        sql += " AND c.company_type = ?"
        params.append(company_type)
    if status:
        sql += " AND c.status = ?"
        params.append(status)
    if region:
        sql += " AND c.region LIKE ?"
        params.append(f"%{region}%")
    if therapeutic_focus:
        sql += " AND c.therapeutic_focus = ?"
        params.append(therapeutic_focus)
    sql += " ORDER BY c.name"
    with get_db() as db:
        return _rows(db.execute(sql, params).fetchall())


def get_company(company_id: int) -> dict:
    with get_db() as db:
        return _row(db.execute("SELECT * FROM companies WHERE id=?", (company_id,)).fetchone())


def create_company(data: dict) -> int:
    ts = now_iso()
    with get_db() as db:
        cur = db.execute(
            """INSERT INTO companies (name, company_type, partnership_type, website, country, region,
               therapeutic_focus, strategic_fit_score, status, owner, notes, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (data.get('name', ''), data.get('company_type', ''), data.get('partnership_type', ''),
             data.get('website', ''), data.get('country', ''), data.get('region', ''),
             data.get('therapeutic_focus', ''), int(data.get('strategic_fit_score') or 0),
             data.get('status', 'active'), data.get('owner', ''), data.get('notes', ''), ts, ts),
        )
        return cur.lastrowid


def update_company(company_id: int, data: dict) -> None:
    ts = now_iso()
    with get_db() as db:
        db.execute(
            """UPDATE companies SET name=?, company_type=?, partnership_type=?, website=?, country=?, region=?,
               therapeutic_focus=?, strategic_fit_score=?, status=?, owner=?, notes=?, updated_at=?
               WHERE id=?""",
            (data.get('name', ''), data.get('company_type', ''), data.get('partnership_type', ''),
             data.get('website', ''), data.get('country', ''), data.get('region', ''),
             data.get('therapeutic_focus', ''), int(data.get('strategic_fit_score') or 0),
             data.get('status', 'active'), data.get('owner', ''), data.get('notes', ''), ts, company_id),
        )


def delete_company(company_id: int) -> None:
    with get_db() as db:
        db.execute("DELETE FROM companies WHERE id=?", (company_id,))


def get_company_detail(company_id: int) -> dict:
    company = get_company(company_id)
    if not company:
        return None
    with get_db() as db:
        contacts = _rows(db.execute(
            "SELECT * FROM contacts WHERE company_id=? ORDER BY first_name, last_name", (company_id,)
        ).fetchall())
        opportunities = _rows(db.execute(
            "SELECT * FROM opportunities WHERE company_id=? ORDER BY created_at DESC", (company_id,)
        ).fetchall())
        activities = _rows(db.execute(
            """SELECT a.*, c.first_name||' '||c.last_name AS contact_name,
               o.name AS opportunity_name
               FROM activities a
               LEFT JOIN contacts c ON c.id = a.contact_id
               LEFT JOIN opportunities o ON o.id = a.opportunity_id
               WHERE a.company_id=? ORDER BY a.activity_date DESC LIMIT 50""",
            (company_id,)
        ).fetchall())
        followups = _rows(db.execute(
            """SELECT f.*, c.first_name||' '||c.last_name AS contact_name,
               o.name AS opportunity_name
               FROM followups f
               LEFT JOIN contacts c ON c.id = f.contact_id
               LEFT JOIN opportunities o ON o.id = f.opportunity_id
               WHERE f.company_id=? ORDER BY f.due_date""",
            (company_id,)
        ).fetchall())
        doc_shares = _rows(db.execute(
            """SELECT ds.*, d.document_name, d.document_type,
               c.first_name||' '||c.last_name AS contact_name,
               o.name AS opportunity_name
               FROM document_shares ds
               JOIN documents d ON d.id = ds.document_id
               LEFT JOIN contacts c ON c.id = ds.contact_id
               LEFT JOIN opportunities o ON o.id = ds.opportunity_id
               WHERE ds.company_id=? ORDER BY ds.shared_date DESC""",
            (company_id,)
        ).fetchall())
    return {**company, 'contacts': contacts, 'opportunities': opportunities,
            'activities': activities, 'followups': followups, 'doc_shares': doc_shares}


# ── Contacts ─────────────────────────────────────────────────────────────────

def list_contacts(search='', company_id=None, role_type='', relationship_strength='', nda_status='') -> list:
    sql = """
        SELECT ct.*, co.name AS company_name
        FROM contacts ct
        LEFT JOIN companies co ON co.id = ct.company_id
        WHERE 1=1
    """
    params = []
    if search:
        sql += " AND (ct.first_name LIKE ? OR ct.last_name LIKE ? OR ct.email LIKE ? OR ct.title LIKE ?)"
        params += [f"%{search}%"] * 4
    if company_id:
        sql += " AND ct.company_id=?"
        params.append(company_id)
    if role_type:
        sql += " AND ct.role_type=?"
        params.append(role_type)
    if relationship_strength:
        sql += " AND ct.relationship_strength=?"
        params.append(relationship_strength)
    if nda_status:
        sql += " AND ct.nda_status=?"
        params.append(nda_status)
    sql += " ORDER BY ct.first_name, ct.last_name"
    with get_db() as db:
        return _rows(db.execute(sql, params).fetchall())


def get_contact(contact_id: int) -> dict:
    with get_db() as db:
        r = db.execute(
            "SELECT ct.*, co.name AS company_name FROM contacts ct LEFT JOIN companies co ON co.id=ct.company_id WHERE ct.id=?",
            (contact_id,)
        ).fetchone()
        return _row(r)


def create_contact(data: dict) -> int:
    ts = now_iso()
    with get_db() as db:
        cur = db.execute(
            """INSERT INTO contacts (company_id, first_name, last_name, title, email, phone,
               linkedin, role_type, relationship_strength, source, first_contact_date,
               last_interaction_date, nda_status, notes, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (data.get('company_id') or None, data.get('first_name', ''), data.get('last_name', ''),
             data.get('title', ''), data.get('email', ''), data.get('phone', ''),
             data.get('linkedin', ''), data.get('role_type', ''), data.get('relationship_strength', 'warm'),
             data.get('source', ''), data.get('first_contact_date', ''), data.get('last_interaction_date', ''),
             data.get('nda_status', 'none'), data.get('notes', ''), ts, ts),
        )
        return cur.lastrowid


def update_contact(contact_id: int, data: dict) -> None:
    ts = now_iso()
    with get_db() as db:
        db.execute(
            """UPDATE contacts SET company_id=?, first_name=?, last_name=?, title=?, email=?,
               phone=?, linkedin=?, role_type=?, relationship_strength=?, source=?,
               first_contact_date=?, last_interaction_date=?, nda_status=?, notes=?, updated_at=?
               WHERE id=?""",
            (data.get('company_id') or None, data.get('first_name', ''), data.get('last_name', ''),
             data.get('title', ''), data.get('email', ''), data.get('phone', ''),
             data.get('linkedin', ''), data.get('role_type', ''), data.get('relationship_strength', 'warm'),
             data.get('source', ''), data.get('first_contact_date', ''), data.get('last_interaction_date', ''),
             data.get('nda_status', 'none'), data.get('notes', ''), ts, contact_id),
        )


def delete_contact(contact_id: int) -> None:
    with get_db() as db:
        db.execute("DELETE FROM contacts WHERE id=?", (contact_id,))


# ── Opportunities ─────────────────────────────────────────────────────────────

def list_opportunities(stage='', priority='', company_id=None, status='open') -> list:
    sql = """
        SELECT o.*, co.name AS company_name,
            ct.first_name||' '||ct.last_name AS contact_name
        FROM opportunities o
        LEFT JOIN companies co ON co.id = o.company_id
        LEFT JOIN contacts ct ON ct.id = o.primary_contact_id
        WHERE 1=1
    """
    params = []
    if status:
        sql += " AND o.status=?"
        params.append(status)
    if stage:
        sql += " AND o.stage=?"
        params.append(stage)
    if priority:
        sql += " AND o.priority=?"
        params.append(priority)
    if company_id:
        sql += " AND o.company_id=?"
        params.append(company_id)
    sql += " ORDER BY CASE o.priority WHEN 'critical' THEN 0 WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END, o.created_at DESC"
    with get_db() as db:
        return _rows(db.execute(sql, params).fetchall())


def get_opportunity(opp_id: int) -> dict:
    with get_db() as db:
        r = db.execute(
            """SELECT o.*, co.name AS company_name,
               ct.first_name||' '||ct.last_name AS contact_name
               FROM opportunities o
               LEFT JOIN companies co ON co.id=o.company_id
               LEFT JOIN contacts ct ON ct.id=o.primary_contact_id
               WHERE o.id=?""",
            (opp_id,)
        ).fetchone()
        return _row(r)


def create_opportunity(data: dict) -> int:
    ts = now_iso()
    with get_db() as db:
        cur = db.execute(
            """INSERT INTO opportunities (company_id, primary_contact_id, name, opportunity_type,
               asset_or_program, indication, stage, priority, probability, estimated_value,
               expected_close_date, nda_status, data_room_status, key_objections, next_step,
               next_step_due_date, owner, status, notes, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (data.get('company_id') or None, data.get('primary_contact_id') or None,
             data.get('name', ''), data.get('opportunity_type', ''), data.get('asset_or_program', ''),
             data.get('indication', ''), data.get('stage', 'initial_contact'), data.get('priority', 'medium'),
             int(data.get('probability') or 0), data.get('estimated_value', ''),
             data.get('expected_close_date', ''), data.get('nda_status', 'none'),
             data.get('data_room_status', 'none'), data.get('key_objections', ''),
             data.get('next_step', ''), data.get('next_step_due_date', ''),
             data.get('owner', ''), data.get('status', 'open'), data.get('notes', ''), ts, ts),
        )
        return cur.lastrowid


def update_opportunity(opp_id: int, data: dict) -> None:
    ts = now_iso()
    with get_db() as db:
        db.execute(
            """UPDATE opportunities SET company_id=?, primary_contact_id=?, name=?, opportunity_type=?,
               asset_or_program=?, indication=?, stage=?, priority=?, probability=?, estimated_value=?,
               expected_close_date=?, nda_status=?, data_room_status=?, key_objections=?, next_step=?,
               next_step_due_date=?, owner=?, status=?, notes=?, updated_at=? WHERE id=?""",
            (data.get('company_id') or None, data.get('primary_contact_id') or None,
             data.get('name', ''), data.get('opportunity_type', ''), data.get('asset_or_program', ''),
             data.get('indication', ''), data.get('stage', 'initial_contact'), data.get('priority', 'medium'),
             int(data.get('probability') or 0), data.get('estimated_value', ''),
             data.get('expected_close_date', ''), data.get('nda_status', 'none'),
             data.get('data_room_status', 'none'), data.get('key_objections', ''),
             data.get('next_step', ''), data.get('next_step_due_date', ''),
             data.get('owner', ''), data.get('status', 'open'), data.get('notes', ''), ts, opp_id),
        )


def delete_opportunity(opp_id: int) -> None:
    with get_db() as db:
        db.execute("DELETE FROM opportunities WHERE id=?", (opp_id,))


def opportunities_by_stage() -> dict:
    STAGES = ['initial_contact', 'nda_negotiation', 'due_diligence', 'term_sheet', 'negotiation', 'closed_won', 'closed_lost', 'on_hold']
    with get_db() as db:
        rows = _rows(db.execute(
            """SELECT o.*, co.name AS company_name FROM opportunities o
               LEFT JOIN companies co ON co.id=o.company_id
               WHERE o.status='open' ORDER BY o.priority""",
        ).fetchall())
    result = {s: [] for s in STAGES}
    for row in rows:
        s = row.get('stage', 'initial_contact')
        if s in result:
            result[s].append(row)
    return result


def get_opportunity_detail(opp_id: int) -> dict:
    opp = get_opportunity(opp_id)
    if not opp:
        return None
    with get_db() as db:
        activities = _rows(db.execute(
            """SELECT a.*, co.name AS company_name, ct.first_name||' '||ct.last_name AS contact_name
               FROM activities a
               LEFT JOIN companies co ON co.id=a.company_id
               LEFT JOIN contacts ct ON ct.id=a.contact_id
               WHERE a.opportunity_id=? ORDER BY a.activity_date DESC""",
            (opp_id,)
        ).fetchall())
        followups = _rows(db.execute(
            """SELECT f.*, ct.first_name||' '||ct.last_name AS contact_name
               FROM followups f
               LEFT JOIN contacts ct ON ct.id=f.contact_id
               WHERE f.opportunity_id=? ORDER BY f.due_date""",
            (opp_id,)
        ).fetchall())
        doc_shares = _rows(db.execute(
            """SELECT ds.*, d.document_name, d.document_type,
               co.name AS company_name, ct.first_name||' '||ct.last_name AS contact_name
               FROM document_shares ds
               JOIN documents d ON d.id=ds.document_id
               LEFT JOIN companies co ON co.id=ds.company_id
               LEFT JOIN contacts ct ON ct.id=ds.contact_id
               WHERE ds.opportunity_id=? ORDER BY ds.shared_date DESC""",
            (opp_id,)
        ).fetchall())
    return {**opp, 'activities': activities, 'followups': followups, 'doc_shares': doc_shares}


# ── Activities ────────────────────────────────────────────────────────────────

def list_activities(company_id=None, contact_id=None, opportunity_id=None, limit=50) -> list:
    sql = """
        SELECT a.*, co.name AS company_name,
            ct.first_name||' '||ct.last_name AS contact_name,
            o.name AS opportunity_name
        FROM activities a
        LEFT JOIN companies co ON co.id=a.company_id
        LEFT JOIN contacts ct ON ct.id=a.contact_id
        LEFT JOIN opportunities o ON o.id=a.opportunity_id
        WHERE 1=1
    """
    params = []
    if company_id:
        sql += " AND a.company_id=?"
        params.append(company_id)
    if contact_id:
        sql += " AND a.contact_id=?"
        params.append(contact_id)
    if opportunity_id:
        sql += " AND a.opportunity_id=?"
        params.append(opportunity_id)
    sql += " ORDER BY a.activity_date DESC LIMIT ?"
    params.append(limit)
    with get_db() as db:
        return _rows(db.execute(sql, params).fetchall())


def get_activity(activity_id: int) -> dict:
    with get_db() as db:
        r = db.execute(
            """SELECT a.*, co.name AS company_name,
               ct.first_name||' '||ct.last_name AS contact_name,
               o.name AS opportunity_name
               FROM activities a
               LEFT JOIN companies co ON co.id=a.company_id
               LEFT JOIN contacts ct ON ct.id=a.contact_id
               LEFT JOIN opportunities o ON o.id=a.opportunity_id
               WHERE a.id=?""",
            (activity_id,)
        ).fetchone()
        return _row(r)


def create_activity(data: dict) -> int:
    ts = now_iso()
    with get_db() as db:
        cur = db.execute(
            """INSERT INTO activities (company_id, contact_id, opportunity_id, activity_date,
               activity_type, subject, summary, documents_shared, action_items,
               follow_up_required, follow_up_date, sentiment, owner, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (data.get('company_id') or None, data.get('contact_id') or None,
             data.get('opportunity_id') or None, data.get('activity_date', ''),
             data.get('activity_type', 'email'), data.get('subject', ''), data.get('summary', ''),
             data.get('documents_shared', ''), data.get('action_items', ''),
             1 if data.get('follow_up_required') else 0, data.get('follow_up_date', ''),
             data.get('sentiment', 'neutral'), data.get('owner', ''), ts, ts),
        )
        activity_id = cur.lastrowid

    if data.get('follow_up_required') and data.get('follow_up_date'):
        create_followup({
            'company_id': data.get('company_id'),
            'contact_id': data.get('contact_id'),
            'opportunity_id': data.get('opportunity_id'),
            'activity_id': activity_id,
            'due_date': data['follow_up_date'],
            'action': data.get('action_items') or f"Follow up on: {data.get('subject', '')}",
            'priority': data.get('follow_up_priority', 'medium'),
            'owner': data.get('owner', ''),
        })
    return activity_id


def update_activity(activity_id: int, data: dict) -> None:
    ts = now_iso()
    with get_db() as db:
        db.execute(
            """UPDATE activities SET company_id=?, contact_id=?, opportunity_id=?, activity_date=?,
               activity_type=?, subject=?, summary=?, documents_shared=?, action_items=?,
               follow_up_required=?, follow_up_date=?, sentiment=?, owner=?, updated_at=?
               WHERE id=?""",
            (data.get('company_id') or None, data.get('contact_id') or None,
             data.get('opportunity_id') or None, data.get('activity_date', ''),
             data.get('activity_type', 'email'), data.get('subject', ''), data.get('summary', ''),
             data.get('documents_shared', ''), data.get('action_items', ''),
             1 if data.get('follow_up_required') else 0, data.get('follow_up_date', ''),
             data.get('sentiment', 'neutral'), data.get('owner', ''), ts, activity_id),
        )


def delete_activity(activity_id: int) -> None:
    with get_db() as db:
        db.execute("DELETE FROM activities WHERE id=?", (activity_id,))


# ── Follow-ups ────────────────────────────────────────────────────────────────

def list_followups(status='open', priority='', owner='', company_id=None, opportunity_id=None) -> list:
    sql = """
        SELECT f.*, co.name AS company_name,
            ct.first_name||' '||ct.last_name AS contact_name,
            o.name AS opportunity_name
        FROM followups f
        LEFT JOIN companies co ON co.id=f.company_id
        LEFT JOIN contacts ct ON ct.id=f.contact_id
        LEFT JOIN opportunities o ON o.id=f.opportunity_id
        WHERE 1=1
    """
    params = []
    if status:
        sql += " AND f.status=?"
        params.append(status)
    if priority:
        sql += " AND f.priority=?"
        params.append(priority)
    if owner:
        sql += " AND f.owner LIKE ?"
        params.append(f"%{owner}%")
    if company_id:
        sql += " AND f.company_id=?"
        params.append(company_id)
    if opportunity_id:
        sql += " AND f.opportunity_id=?"
        params.append(opportunity_id)
    sql += " ORDER BY f.due_date"
    with get_db() as db:
        return _rows(db.execute(sql, params).fetchall())


def get_followup(followup_id: int) -> dict:
    with get_db() as db:
        r = db.execute(
            """SELECT f.*, co.name AS company_name,
               ct.first_name||' '||ct.last_name AS contact_name,
               o.name AS opportunity_name
               FROM followups f
               LEFT JOIN companies co ON co.id=f.company_id
               LEFT JOIN contacts ct ON ct.id=f.contact_id
               LEFT JOIN opportunities o ON o.id=f.opportunity_id
               WHERE f.id=?""",
            (followup_id,)
        ).fetchone()
        return _row(r)


def create_followup(data: dict) -> int:
    ts = now_iso()
    with get_db() as db:
        cur = db.execute(
            """INSERT INTO followups (company_id, contact_id, opportunity_id, activity_id,
               due_date, action, priority, owner, status, completed_date, notes, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (data.get('company_id') or None, data.get('contact_id') or None,
             data.get('opportunity_id') or None, data.get('activity_id') or None,
             data.get('due_date', ''), data.get('action', ''), data.get('priority', 'medium'),
             data.get('owner', ''), data.get('status', 'open'), data.get('completed_date', ''),
             data.get('notes', ''), ts, ts),
        )
        return cur.lastrowid


def complete_followup(followup_id: int) -> None:
    ts = now_iso()
    with get_db() as db:
        db.execute(
            "UPDATE followups SET status='completed', completed_date=?, updated_at=? WHERE id=?",
            (ts[:10], ts, followup_id),
        )


def delete_followup(followup_id: int) -> None:
    with get_db() as db:
        db.execute("DELETE FROM followups WHERE id=?", (followup_id,))


def overdue_followups() -> list:
    today = datetime.utcnow().date().isoformat()
    sql = """
        SELECT f.*, co.name AS company_name,
            ct.first_name||' '||ct.last_name AS contact_name,
            o.name AS opportunity_name
        FROM followups f
        LEFT JOIN companies co ON co.id=f.company_id
        LEFT JOIN contacts ct ON ct.id=f.contact_id
        LEFT JOIN opportunities o ON o.id=f.opportunity_id
        WHERE f.status='open' AND f.due_date < ?
        ORDER BY f.due_date
    """
    with get_db() as db:
        return _rows(db.execute(sql, (today,)).fetchall())


def due_this_week_followups() -> list:
    today = datetime.utcnow().date()
    week_end = (today + timedelta(days=7)).isoformat()
    today_str = today.isoformat()
    sql = """
        SELECT f.*, co.name AS company_name,
            ct.first_name||' '||ct.last_name AS contact_name,
            o.name AS opportunity_name
        FROM followups f
        LEFT JOIN companies co ON co.id=f.company_id
        LEFT JOIN contacts ct ON ct.id=f.contact_id
        LEFT JOIN opportunities o ON o.id=f.opportunity_id
        WHERE f.status='open' AND f.due_date >= ? AND f.due_date <= ?
        ORDER BY f.due_date
    """
    with get_db() as db:
        return _rows(db.execute(sql, (today_str, week_end)).fetchall())


# ── Documents ─────────────────────────────────────────────────────────────────

def list_documents() -> list:
    with get_db() as db:
        rows = _rows(db.execute(
            """SELECT d.*,
               (SELECT COUNT(*) FROM document_shares ds WHERE ds.document_id=d.id) AS share_count
               FROM documents d ORDER BY d.created_at DESC"""
        ).fetchall())
    return rows


def get_document(doc_id: int) -> dict:
    with get_db() as db:
        return _row(db.execute("SELECT * FROM documents WHERE id=?", (doc_id,)).fetchone())


def create_document(data: dict) -> int:
    ts = now_iso()
    with get_db() as db:
        cur = db.execute(
            """INSERT INTO documents (document_name, document_type, version, file_path, description, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?)""",
            (data.get('document_name', ''), data.get('document_type', ''), data.get('version', '1.0'),
             data.get('file_path', ''), data.get('description', ''), ts, ts),
        )
        return cur.lastrowid


def delete_document(doc_id: int) -> None:
    with get_db() as db:
        db.execute("DELETE FROM documents WHERE id=?", (doc_id,))


def list_document_shares(document_id=None, company_id=None) -> list:
    sql = """
        SELECT ds.*, d.document_name, co.name AS company_name,
            ct.first_name||' '||ct.last_name AS contact_name,
            o.name AS opportunity_name
        FROM document_shares ds
        JOIN documents d ON d.id=ds.document_id
        LEFT JOIN companies co ON co.id=ds.company_id
        LEFT JOIN contacts ct ON ct.id=ds.contact_id
        LEFT JOIN opportunities o ON o.id=ds.opportunity_id
        WHERE 1=1
    """
    params = []
    if document_id:
        sql += " AND ds.document_id=?"
        params.append(document_id)
    if company_id:
        sql += " AND ds.company_id=?"
        params.append(company_id)
    sql += " ORDER BY ds.shared_date DESC"
    with get_db() as db:
        return _rows(db.execute(sql, params).fetchall())


def create_document_share(data: dict) -> int:
    ts = now_iso()
    with get_db() as db:
        cur = db.execute(
            """INSERT INTO document_shares (document_id, company_id, contact_id, opportunity_id,
               shared_date, shared_under_nda, notes, created_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            (data.get('document_id'), data.get('company_id') or None,
             data.get('contact_id') or None, data.get('opportunity_id') or None,
             data.get('shared_date', ''), 1 if data.get('shared_under_nda') else 0,
             data.get('notes', ''), ts),
        )
        return cur.lastrowid


# ── Dashboard / Summary ───────────────────────────────────────────────────────

def dashboard_stats() -> dict:
    today = datetime.utcnow().date().isoformat()
    week_end = (datetime.utcnow().date() + timedelta(days=7)).isoformat()
    with get_db() as db:
        total_companies = db.execute("SELECT COUNT(*) FROM companies WHERE status='active'").fetchone()[0]
        total_contacts = db.execute("SELECT COUNT(*) FROM contacts").fetchone()[0]
        active_opportunities = db.execute("SELECT COUNT(*) FROM opportunities WHERE status='open'").fetchone()[0]
        followups_due_week = db.execute(
            "SELECT COUNT(*) FROM followups WHERE status='open' AND due_date >= ? AND due_date <= ?",
            (today, week_end)
        ).fetchone()[0]
        overdue = db.execute(
            "SELECT COUNT(*) FROM followups WHERE status='open' AND due_date < ?", (today,)
        ).fetchone()[0]
        nda_pending = db.execute(
            "SELECT COUNT(*) FROM opportunities WHERE nda_status IN ('sent') AND status='open'"
        ).fetchone()[0]
        data_room_shared = db.execute(
            "SELECT COUNT(*) FROM opportunities WHERE data_room_status='shared' AND status='open'"
        ).fetchone()[0]
    return {
        'total_companies': total_companies,
        'total_contacts': total_contacts,
        'active_opportunities': active_opportunities,
        'followups_due_week': followups_due_week,
        'overdue_followups': overdue,
        'nda_pending': nda_pending,
        'data_room_shared': data_room_shared,
    }


def recent_activities(limit=10) -> list:
    with get_db() as db:
        return _rows(db.execute(
            """SELECT a.*, co.name AS company_name,
               ct.first_name||' '||ct.last_name AS contact_name,
               o.name AS opportunity_name
               FROM activities a
               LEFT JOIN companies co ON co.id=a.company_id
               LEFT JOIN contacts ct ON ct.id=a.contact_id
               LEFT JOIN opportunities o ON o.id=a.opportunity_id
               ORDER BY a.activity_date DESC, a.created_at DESC LIMIT ?""",
            (limit,)
        ).fetchall())


def upcoming_followups(limit=10) -> list:
    today = datetime.utcnow().date().isoformat()
    with get_db() as db:
        return _rows(db.execute(
            """SELECT f.*, co.name AS company_name,
               ct.first_name||' '||ct.last_name AS contact_name,
               o.name AS opportunity_name
               FROM followups f
               LEFT JOIN companies co ON co.id=f.company_id
               LEFT JOIN contacts ct ON ct.id=f.contact_id
               LEFT JOIN opportunities o ON o.id=f.opportunity_id
               WHERE f.status='open' AND f.due_date >= ?
               ORDER BY f.due_date LIMIT ?""",
            (today, limit)
        ).fetchall())
