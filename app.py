import os
import math
import csv
from datetime import date
from typing import List, Dict, Any

import streamlit as st
from pydantic import BaseModel, field_validator, ConfigDict
from sqlalchemy import (create_engine, text)
from sqlalchemy.engine import Engine
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
DB_SCHEMA = os.getenv("DB_SCHEMA", "stg")
if not DATABASE_URL:
    st.stop()  # попросит настроить .env

@st.cache_resource(show_spinner=False)
def get_engine() -> Engine:
    # Устанавливаем search_path, чтобы работать в заданной схеме (по умолчанию stg)
    return create_engine(
        DATABASE_URL,
        pool_pre_ping=True,
        connect_args={"options": f"-csearch_path={DB_SCHEMA}"}
    )

engine = get_engine()

# -----------------------------
# Модели валидации формы
# -----------------------------
class TaskModel(BaseModel):
    model_config = ConfigDict(extra='ignore')
    line: str  # 'A3' | 'A4'
    sap_id: int
    qty_made: int
    count_by_norm: bool
    discount_percent: int = 0

    @field_validator('line')
    def v_line(cls, v):
        if v not in ('A3','A4'):
            raise ValueError('line must be A3 or A4')
        return v
    @field_validator('discount_percent')
    def v_discount(cls, v):
        if v is None:
            return 0
        if not (0 <= int(v) <= 100):
            raise ValueError('discount_percent must be 0..100')
        return int(v)

class LineEmployeeModel(BaseModel):
    model_config = ConfigDict(extra='ignore')
    employee_id: int
    fio: str
    work_time: float
    line: str

    @field_validator('line')
    def v_line(cls, v):
        if v not in ('A3','A4'):
            raise ValueError('line must be A3 or A4')
        return v

class SupportRoleModel(BaseModel):
    model_config = ConfigDict(extra='ignore')
    role: str  # 'senior' | 'repair'
    employee_id: int
    fio: str
    work_time: float

    @field_validator('role')
    def v_role(cls, v):
        if v not in ('senior','repair'):
            raise ValueError('role must be senior or repair')
        return v

# -----------------------------
# Утилиты БД
# -----------------------------

def fetch_sites() -> Dict[str,int]:
    with engine.begin() as conn:
        rows = conn.execute(text("SELECT id, name FROM sites ORDER BY name"))
        return {r.name: r.id for r in rows}

@st.cache_data(show_spinner=False)
def fetch_sap_catalog() -> List[Dict[str,Any]]:
    with engine.begin() as conn:
        rows = conn.execute(text("SELECT id, sap_code, product_name, norm_a3_per_employee, norm_a4_per_employee FROM sap_catalog ORDER BY sap_code"))
        return [dict(row._mapping) for row in rows]

@st.cache_data(show_spinner=False)
def fetch_employees_catalog() -> List[Dict[str,Any]]:
    with engine.begin() as conn:
        rows = conn.execute(text("SELECT id, fio FROM employees ORDER BY fio"))
        return [dict(row._mapping) for row in rows]


def import_employees_from_csv(csv_path: str) -> int:
    if not os.path.isabs(csv_path):
        base_dir = os.path.dirname(__file__)
        csv_path = os.path.join(base_dir, csv_path)
    if not os.path.exists(csv_path):
        raise FileNotFoundError(f"CSV не найден: {csv_path}")

    with open(csv_path, 'r', encoding='utf-8-sig', newline='') as f:
        reader = csv.DictReader(f)
        rows: List[Dict[str, Any]] = []
        for row in reader:
            emp_id_raw = row.get('id_employee')
            fio_raw = row.get('fio_employee')
            if not emp_id_raw or not fio_raw:
                continue
            try:
                emp_id = int(str(emp_id_raw).strip())
            except Exception:
                continue
            fio = str(fio_raw).strip()
            if not fio:
                continue
            rows.append({"id": emp_id, "fio": fio})

    if not rows:
        return 0

    with engine.begin() as conn:
        for r in rows:
            conn.execute(text(
                "INSERT INTO employees(id, fio) VALUES (:id,:fio) ON CONFLICT (id) DO UPDATE SET fio=EXCLUDED.fio"
            ), r)
    return len(rows)


def get_report(site_id: int, d: date) -> Dict[str,Any] | None:
    with engine.begin() as conn:
        rpt = conn.execute(text("SELECT id FROM reports WHERE site_id=:s AND report_date=:d"), {"s": site_id, "d": d}).fetchone()
        if not rpt:
            return None
        report_id = rpt.id
        tasks = conn.execute(text(
            """
            SELECT t.id, t.line, t.sap_id, sc.sap_code, sc.product_name,
                   CASE WHEN t.line='A3' THEN ROUND(sc.norm_per_employee * 0.7)::int ELSE sc.norm_per_employee END AS norm_per_employee,
                   t.qty_made, t.count_by_norm, t.discount_percent,
                   CASE WHEN t.line='A3'
                        THEN ROUND(sc.norm_per_employee * 0.7 * (1 - t.discount_percent/100.0))::int
                        ELSE ROUND(sc.norm_per_employee * (1 - t.discount_percent/100.0))::int
                   END AS norm_with_discount
            FROM report_tasks t
            JOIN sap_catalog sc ON sc.id = t.sap_id
            WHERE t.report_id=:rid
            ORDER BY t.line, t.id
            """
        ), {"rid": report_id}).mappings().all()
        line_emps = conn.execute(text(
            """
            SELECT id, employee_id, fio, work_time, line
            FROM report_line_employees WHERE report_id=:rid ORDER BY id
            """
        ), {"rid": report_id}).mappings().all()
        supports = conn.execute(text(
            """
            SELECT id, role, employee_id, fio, work_time
            FROM report_support_roles WHERE report_id=:rid ORDER BY role
            """
        ), {"rid": report_id}).mappings().all()
        return {"id": report_id, "tasks": list(tasks), "line_emps": list(line_emps), "supports": list(supports)}


def upsert_report(site_id: int, d: date, tasks: List[TaskModel], line_emps: List[LineEmployeeModel], supports: List[SupportRoleModel]):
    with engine.begin() as conn:
        rpt = conn.execute(text("""
            INSERT INTO reports(site_id, report_date) VALUES (:s,:d)
            ON CONFLICT (site_id, report_date) DO UPDATE SET report_date = EXCLUDED.report_date
            RETURNING id
        """), {"s": site_id, "d": d}).fetchone()
        report_id = rpt.id
        # Удаляем старые записи и вставляем новые (просто и надёжно)
        conn.execute(text("DELETE FROM report_tasks WHERE report_id=:rid"), {"rid": report_id})
        conn.execute(text("DELETE FROM report_line_employees WHERE report_id=:rid"), {"rid": report_id})
        conn.execute(text("DELETE FROM report_support_roles WHERE report_id=:rid"), {"rid": report_id})

        for t in tasks:
            conn.execute(text(
                """
                INSERT INTO report_tasks(report_id, line, sap_id, qty_made, count_by_norm)
                VALUES (:rid, :line, :sap_id, :qty_made, :count_by_norm)
                """
            ), {"rid": report_id, **t.dict()})
        for le in line_emps:
            # Обновим справочник employees по мере ввода
            conn.execute(text(
                "INSERT INTO employees(id, fio) VALUES (:id,:fio) ON CONFLICT (id) DO UPDATE SET fio=EXCLUDED.fio"
            ), {"id": le.employee_id, "fio": le.fio})
            conn.execute(text(
                """
                INSERT INTO report_line_employees(report_id, employee_id, fio, work_time, line)
                VALUES (:rid, :employee_id, :fio, :work_time, :line)
                """
            ), {"rid": report_id, **le.dict()})
        for s in supports:
            conn.execute(text(
                "INSERT INTO employees(id, fio) VALUES (:id,:fio) ON CONFLICT (id) DO UPDATE SET fio=EXCLUDED.fio"
            ), {"id": s.employee_id, "fio": s.fio})
            conn.execute(text(
                """
                INSERT INTO report_support_roles(report_id, role, employee_id, fio, work_time)
                VALUES (:rid, :role, :employee_id, :fio, :work_time)
                """
            ), {"rid": report_id, **s.dict()})

# -----------------------------
# UI — Streamlit
# -----------------------------

st.set_page_config(page_title="Отчёты по участкам", layout="wide")
st.title("Отчёты по сотрудникам")

# Хэндлер для сброса формы при смене участка/даты
def _reset_form_state():
    st.session_state.tasks_A3 = []
    st.session_state.tasks_A4 = []
    st.session_state.line_emps = []
    st.session_state.supports = []
    st.session_state.prefilled = False
    # счётчики для row_id (пер-лист)
    st.session_state.tasks_A3_seq = 0
    st.session_state.tasks_A4_seq = 0
    st.session_state.line_emps_seq = 0

# Безопасное приведение к int (обрабатывает None/""/NaN)
def _to_int_safe(value, default: int = 0) -> int:
    try:
        if value is None:
            return default
        if isinstance(value, float) and math.isnan(value):
            return default
        if isinstance(value, str) and value.strip() == "":
            return default
        return int(value)
    except Exception:
        return default

# Нормализация строки задания: заполняем вычисляемые поля
def _normalize_task_row(line: str, row: Dict[str, Any]) -> Dict[str, Any]:
    normalized = dict(row)
    code = normalized.get('sap_code')
    item = sap_by_code.get(code)
    if item:
        normalized['product_name'] = item['product_name']
        # выбираем норму в зависимости от линии
        if line == 'A3':
            base_norm = item.get('norm_a3_per_employee')
        else:  # A4
            base_norm = item.get('norm_a4_per_employee')
        
        if base_norm is not None:
            normalized['norm_per_employee'] = float(base_norm)
        else:
            normalized['norm_per_employee'] = 0
            normalized['product_name'] = f"{normalized['product_name']} (не производится на {line})"
    else:
        normalized['product_name'] = ""
        normalized['norm_per_employee'] = 0
    
    disc = _to_int_safe(normalized.get('discount_percent'), 0)
    base_norm = float(normalized.get('norm_per_employee', 0))
    normalized['norm_with_discount'] = int(round(base_norm * (1 - disc/100)))
    normalized['qty_made'] = _to_int_safe(normalized.get('qty_made'), 0)
    normalized['count_by_norm'] = bool(normalized.get('count_by_norm'))
    normalized['discount_percent'] = disc
    normalized['sap_code'] = code or ""
    return normalized

def _extract_user_fields(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    keys = ("sap_code","qty_made","discount_percent","count_by_norm")
    result = []
    for r in rows or []:
        result.append({k: (r.get(k) if k != 'discount_percent' else _to_int_safe(r.get(k), 0)) for k in keys})
    return result

def _ensure_row_ids(list_name: str):
    seq_key = f"{list_name}_seq"
    if seq_key not in st.session_state:
        st.session_state[seq_key] = 0
    lst = st.session_state.get(list_name, [])
    for row in lst:
        if 'row_id' not in row:
            st.session_state[seq_key] += 1
            row['row_id'] = st.session_state[seq_key]

def _next_seq(list_name: str) -> int:
    seq_key = f"{list_name}_seq"
    if seq_key not in st.session_state:
        st.session_state[seq_key] = 0
    st.session_state[seq_key] += 1
    return st.session_state[seq_key]

sites = fetch_sites()
site_name = st.selectbox(
    "Участок",
    list(sites.keys()),
    index=list(sites.keys()).index('Катюша') if 'Катюша' in sites else 0,
    key="site_select",
    on_change=_reset_form_state,
)
site_id = sites[site_name]

rep_date = st.date_input("Дата отчёта", value=date.today(), key="date_input", on_change=_reset_form_state)

# Загрузка существующего отчёта
existing = get_report(site_id, rep_date)
if existing:
    st.success("Найден существующий отчёт — поля заполнены из БД")
else:
    st.info("Отчёт пока не заполнен — можно ввести данные")

# Состояние формы для динамических списков
if 'tasks_A3' not in st.session_state:
    st.session_state.tasks_A3 = []
if 'tasks_A4' not in st.session_state:
    st.session_state.tasks_A4 = []
if 'line_emps' not in st.session_state:
    st.session_state.line_emps = []
if 'supports' not in st.session_state:
    st.session_state.supports = []

# Если есть существующие — загрузим в сессию один раз
if existing and not st.session_state.get('prefilled'):
    st.session_state.tasks_A3 = [
        {
            "sap_code": t['sap_code'],
            "product_name": t['product_name'],
            "norm_per_employee": t['norm_per_employee'],
            "discount_percent": t.get('discount_percent', 0),
            "norm_with_discount": t.get('norm_with_discount', t['norm_per_employee']),
            "qty_made": t['qty_made'],
            "count_by_norm": t['count_by_norm'],
        }
        for t in existing['tasks'] if t['line'] == 'A3']
    st.session_state.tasks_A4 = [
        {
            "sap_code": t['sap_code'],
            "product_name": t['product_name'],
            "norm_per_employee": t['norm_per_employee'],
            "discount_percent": t.get('discount_percent', 0),
            "norm_with_discount": t.get('norm_with_discount', t['norm_per_employee']),
            "qty_made": t['qty_made'],
            "count_by_norm": t['count_by_norm'],
        }
        for t in existing['tasks'] if t['line'] == 'A4']
    st.session_state.line_emps = [dict(x) for x in existing['line_emps']]
    st.session_state.supports = [dict(x) for x in existing['supports']]
    st.session_state.prefilled = True

@st.cache_data(ttl=3600, show_spinner=False)
def _load_cached_sap():
    cat = fetch_sap_catalog()
    return {
        'by_code': {x['sap_code']: x for x in cat},
        'codes': [x['sap_code'] for x in cat],
    }

@st.cache_data(ttl=3600, show_spinner=False)
def _load_cached_emps():
    emps = fetch_employees_catalog()
    return {
        'id_to_fio': {int(e['id']): e['fio'] for e in emps},
        'ids': [int(e['id']) for e in emps],
        'full': emps,
    }

sap_cache = _load_cached_sap()
sap_by_code = sap_cache['by_code']
sap_codes = sap_cache['codes']

# фильтруем SAP коды по доступности на выбранных линиях
def _get_available_sap_codes_for_line(line: str) -> List[str]:
    available = []
    for code, item in sap_by_code.items():
        if line == 'A3' and item.get('norm_a3_per_employee') is not None:
            available.append(code)
        elif line == 'A4' and item.get('norm_a4_per_employee') is not None:
            available.append(code)
    return available

if site_name == 'Катюша':
    st.header("Задания по линиям")
    colA3, colA4 = st.columns(2)

    # --- Линия A3 ---
    with colA3:
        st.subheader("Линия A3")
        st.markdown('<div style="background-color:#e8f4ff; padding:6px; border-radius:6px;">', unsafe_allow_html=True)
        if not sap_codes:
            st.warning("Каталог SAP пуст. Сначала заполните `sap_catalog` в БД.")
        if st.button("+ Добавить", key="add_row_A3", disabled=(not sap_codes) or (len(st.session_state.tasks_A3) >= 10)):
            _ensure_row_ids('tasks_A3')
            st.session_state.tasks_A3.append({
                "row_id": _next_seq('tasks_A3'),
                "sap_code": "",
                "product_name": "",
                "norm_per_employee": 0,
                "discount_percent": 0,
                "qty_made": 0,
                "count_by_norm": True,
            })
        # готовим отображаемые строки, не трогая session_state до редактирования
        _ensure_row_ids('tasks_A3')
        available_a3_codes = _get_available_sap_codes_for_line('A3')
        display_A3 = [_normalize_task_row('A3', r) for r in _extract_user_fields(st.session_state.tasks_A3)]
        edited_A3 = st.data_editor(
            display_A3,
            column_config={
                "sap_code": st.column_config.SelectboxColumn(
                    "SAP",
                    options=[""] + available_a3_codes,
                    required=False,
                ),
                "product_name": st.column_config.TextColumn("Название изделия", disabled=True),
                "norm_per_employee": st.column_config.NumberColumn("Норма на сотрудника", disabled=True),
                "discount_percent": st.column_config.NumberColumn("Скидка на норму (%)", min_value=0, max_value=100, step=1),
                "norm_with_discount": st.column_config.NumberColumn("Норма со скидкой", disabled=True),
                "qty_made": st.column_config.NumberColumn("Изготовлено (шт)", min_value=0, step=1),
                "count_by_norm": st.column_config.CheckboxColumn("СЧИТАТЬ ПО НОРМЕ"),
            },
            column_order=["sap_code","product_name","norm_per_employee","discount_percent","norm_with_discount","qty_made","count_by_norm"],
            hide_index=False,
            num_rows="dynamic",
            width='stretch',
            key="editor_A3",
        )
        # пересчёт после редактирования + обнаружение изменений
        enriched_A3 = [_normalize_task_row('A3', r) for r in edited_A3]
        if len(enriched_A3) > 10:
            st.error("Максимум 10 заданий на линию. Лишние строки будут отброшены.")
            enriched_A3 = enriched_A3[:10]
        
        # проверяем, изменились ли SAP коды (триггер для обновления)
        old_saps = [r.get('sap_code', '') for r in st.session_state.tasks_A3]
        new_saps = [r.get('sap_code', '') for r in enriched_A3]
        if old_saps != new_saps and 'rerun_guard_A3' not in st.session_state:
            st.session_state.tasks_A3 = enriched_A3
            st.session_state.rerun_guard_A3 = True
            st.rerun()
        elif 'rerun_guard_A3' in st.session_state:
            del st.session_state.rerun_guard_A3
        
        st.session_state.tasks_A3 = enriched_A3
        st.markdown('</div>', unsafe_allow_html=True)

    # --- Линия A4 ---
    with colA4:
        st.subheader("Линия A4")
        st.markdown('<div style="background-color:#fff8db; padding:6px; border-radius:6px;">', unsafe_allow_html=True)
        if not sap_codes:
            st.warning("Каталог SAP пуст. Сначала заполните `sap_catalog` в БД.")
        if st.button("+ Добавить", key="add_row_A4", disabled=(not sap_codes) or (len(st.session_state.tasks_A4) >= 10)):
            _ensure_row_ids('tasks_A4')
            st.session_state.tasks_A4.append({
                "row_id": _next_seq('tasks_A4'),
                "sap_code": "",
                "product_name": "",
                "norm_per_employee": 0,
                "discount_percent": 0,
                "qty_made": 0,
                "count_by_norm": True,
            })
        _ensure_row_ids('tasks_A4')
        available_a4_codes = _get_available_sap_codes_for_line('A4')
        display_A4 = [_normalize_task_row('A4', r) for r in _extract_user_fields(st.session_state.tasks_A4)]
        edited_A4 = st.data_editor(
            display_A4,
            column_config={
                "sap_code": st.column_config.SelectboxColumn(
                    "SAP",
                    options=[""] + available_a4_codes,
                    required=False,
                ),
                "product_name": st.column_config.TextColumn("Название изделия", disabled=True),
                "norm_per_employee": st.column_config.NumberColumn("Норма на сотрудника", disabled=True),
                "discount_percent": st.column_config.NumberColumn("Скидка на норму (%)", min_value=0, max_value=100, step=1),
                "norm_with_discount": st.column_config.NumberColumn("Норма со скидкой", disabled=True),
                "qty_made": st.column_config.NumberColumn("Изготовлено (шт)", min_value=0, step=1),
                "count_by_norm": st.column_config.CheckboxColumn("СЧИТАТЬ ПО НОРМЕ"),
            },
            column_order=["sap_code","product_name","norm_per_employee","discount_percent","norm_with_discount","qty_made","count_by_norm"],
            hide_index=False,
            num_rows="dynamic",
            width='stretch',
            key="editor_A4",
        )
        enriched_A4 = [_normalize_task_row('A4', r) for r in edited_A4]
        if len(enriched_A4) > 10:
            st.error("Максимум 10 заданий на линию. Лишние строки будут отброшены.")
            enriched_A4 = enriched_A4[:10]
        
        # проверяем, изменились ли SAP коды (триггер для обновления)
        old_saps = [r.get('sap_code', '') for r in st.session_state.tasks_A4]
        new_saps = [r.get('sap_code', '') for r in enriched_A4]
        if old_saps != new_saps and 'rerun_guard_A4' not in st.session_state:
            st.session_state.tasks_A4 = enriched_A4
            st.session_state.rerun_guard_A4 = True
            st.rerun()
        elif 'rerun_guard_A4' in st.session_state:
            del st.session_state.rerun_guard_A4
        
        st.session_state.tasks_A4 = enriched_A4
        st.markdown('</div>', unsafe_allow_html=True)

# Линейные сотрудники
st.header("Линейные сотрудники (по линиям)")
if st.button("+ Добавить сотрудника", key="add_row_emp"):
    _ensure_row_ids('line_emps')
    st.session_state.line_emps.append({
        "row_id": _next_seq('line_emps'),
        "employee_id": 0,
        "fio": "",
        "work_time": 8.0,
        "line": "A3",
    })
emps_cache = _load_cached_emps()
id_to_fio = emps_cache['id_to_fio']
# автозаполнение ФИО по выбранному ID
for r in st.session_state.line_emps:
    emp_id = r.get('employee_id')
    if isinstance(emp_id, str) and emp_id.isdigit():
        emp_id = int(emp_id)
        r['employee_id'] = emp_id
    r['fio'] = id_to_fio.get(r.get('employee_id') or 0, r.get('fio', ""))

display_emps = [dict(r) for r in st.session_state.line_emps]
# отразим актуальные ФИО для отображения прямо сейчас
for r in display_emps:
    emp_id = r.get('employee_id')
    if isinstance(emp_id, str) and emp_id.isdigit():
        emp_id = int(emp_id)
        r['employee_id'] = emp_id
    r['fio'] = id_to_fio.get(emp_id or 0, r.get('fio', ""))

edited_emps = st.data_editor(
    display_emps,
    column_config={
        "employee_id": st.column_config.SelectboxColumn("ID сотрудника", options=sorted(id_to_fio.keys())),
        "fio": st.column_config.TextColumn("ФИО", disabled=True),
        "work_time": st.column_config.NumberColumn("Часы", min_value=0.0, step=0.5),
        "line": st.column_config.SelectboxColumn("Линия", options=['A3','A4']),
    },
    column_order=["employee_id","fio","work_time","line"],
    hide_index=False,
    num_rows="dynamic",
    use_container_width=True,
    key="editor_emps",
)

# после редактирования снова проставим ФИО по ID
for r in edited_emps:
    emp_id = r.get('employee_id')
    if isinstance(emp_id, str) and emp_id.isdigit():
        emp_id = int(emp_id)
        r['employee_id'] = emp_id
    r['fio'] = id_to_fio.get(emp_id or 0, r.get('fio', ""))

# проверяем, изменились ли ID сотрудников (триггер для обновления)
old_ids = [r.get('employee_id', 0) for r in st.session_state.line_emps]
new_ids = [r.get('employee_id', 0) for r in edited_emps]
if old_ids != new_ids and 'rerun_guard_emps' not in st.session_state:
    st.session_state.line_emps = edited_emps
    st.session_state.rerun_guard_emps = True
    st.rerun()
elif 'rerun_guard_emps' in st.session_state:
    del st.session_state.rerun_guard_emps

st.session_state.line_emps = edited_emps

# Старший и Ремонтник
st.header("Старший и Ремонтник")
if not any(r.get('role')=='senior' for r in st.session_state.supports):
    st.session_state.supports.append({"role":"senior","employee_id":0,"fio":"","work_time":8.0})
if not any(r.get('role')=='repair' for r in st.session_state.supports):
    st.session_state.supports.append({"role":"repair","employee_id":0,"fio":"","work_time":8.0})

# подтягиваем ФИО перед отображением
display_supports = [dict(r) for r in st.session_state.supports]
for r in display_supports:
    emp_id = r.get('employee_id')
    if isinstance(emp_id, str) and emp_id.isdigit():
        emp_id = int(emp_id)
        r['employee_id'] = emp_id
    r['fio'] = id_to_fio.get(emp_id or 0, r.get('fio', ""))

edited_supports = st.data_editor(
    display_supports,
    column_config={
        "role": st.column_config.TextColumn("Роль", disabled=True),
        "employee_id": st.column_config.SelectboxColumn("ID", options=sorted(id_to_fio.keys())),
        "fio": st.column_config.TextColumn("ФИО", disabled=True),
        "work_time": st.column_config.NumberColumn("Часы", min_value=0.0, step=0.5),
    },
    num_rows="fixed",
    use_container_width=True,
    key="editor_supports",
)

# после редактирования снова проставим ФИО по ID
for r in edited_supports:
    emp_id = r.get('employee_id')
    if isinstance(emp_id, str) and emp_id.isdigit():
        emp_id = int(emp_id)
        r['employee_id'] = emp_id
    r['fio'] = id_to_fio.get(emp_id or 0, r.get('fio', ""))

# проверяем изменения для rerun
old_support_ids = [r.get('employee_id', 0) for r in st.session_state.supports]
new_support_ids = [r.get('employee_id', 0) for r in edited_supports]
if old_support_ids != new_support_ids and 'rerun_guard_supports' not in st.session_state:
    st.session_state.supports = edited_supports
    st.session_state.rerun_guard_supports = True
    st.rerun()
elif 'rerun_guard_supports' in st.session_state:
    del st.session_state.rerun_guard_supports

st.session_state.supports = edited_supports

# Резюме
st.header("📊 Резюме смены")
show_stats = st.button("🔢 Рассчитать статистику за день", width='stretch')

if show_stats and (st.session_state.tasks_A3 or st.session_state.tasks_A4 or st.session_state.line_emps):
    col_summary1, col_summary2 = st.columns(2)
    
    with col_summary1:
        st.subheader("Итоговые нормативы по изделиям")
        
        # сначала подсчитаем часы сотрудников по линиям для расчёта нормативов
        line_hours_for_calc = {"A3": 0.0, "A4": 0.0}
        for emp in st.session_state.line_emps:
            line = emp.get('line', 'A3')
            work_time = emp.get('work_time', 0.0)
            if work_time is not None and line in line_hours_for_calc:
                line_hours_for_calc[line] += float(work_time)
        
        # собираем данные по изделиям и линиям
        product_summary = {}
        for line_name, tasks in [("A3", st.session_state.tasks_A3), ("A4", st.session_state.tasks_A4)]:
            for task in tasks:
                sap_code = task.get('sap_code', '')
                if not sap_code:
                    continue
                product_name = task.get('product_name', '')
                norm_with_discount = task.get('norm_with_discount', 0)
                count_by_norm = task.get('count_by_norm', True)
                
                key = f"{sap_code} - {product_name}"
                if key not in product_summary:
                    product_summary[key] = {"A3": 0, "A4": 0}
                
                if not count_by_norm:
                    # инвертированная логика: если НЕ считать по норме, то используем формулу
                    # (норма_со_скидкой / 12) * часы_сотрудников_на_линии
                    if line_hours_for_calc[line_name] > 0:
                        product_summary[key][line_name] += (norm_with_discount / 12) * line_hours_for_calc[line_name]
                else:
                    # если считаем по норме, то просто количество изготовлено
                    qty_made = task.get('qty_made', 0)
                    product_summary[key][line_name] += qty_made
        
        if product_summary:
            summary_data = []
            for product, lines in product_summary.items():
                total = lines["A3"] + lines["A4"]
                summary_data.append({
                    "Изделие": product,
                    "A3": int(round(lines["A3"])),
                    "A4": int(round(lines["A4"])), 
                    "Итого": int(round(total))
                })
            
            st.dataframe(
                summary_data,
                column_config={
                    "Изделие": st.column_config.TextColumn("Изделие", width="medium"),
                    "A3": st.column_config.NumberColumn("A3", format="%d"),
                    "A4": st.column_config.NumberColumn("A4", format="%d"),
                    "Итого": st.column_config.NumberColumn("Итого", format="%d"),
                },
                width='stretch',
                hide_index=True
            )
        else:
            st.info("Нет заданий для отображения")
    
    with col_summary2:
        st.subheader("Сотрудники по линиям")
        
        # подсчёт сотрудников по линиям
        line_counts = {"A3": 0, "A4": 0}
        total_hours = {"A3": 0.0, "A4": 0.0}
        
        for emp in st.session_state.line_emps:
            line = emp.get('line', 'A3')
            if line in line_counts:
                line_counts[line] += 1
                work_time = emp.get('work_time', 0.0)
                if work_time is not None:
                    total_hours[line] += float(work_time)
        
        staff_data = [
            {"Линия": "A3", "Количество": line_counts["A3"], "Часы": total_hours["A3"]},
            {"Линия": "A4", "Количество": line_counts["A4"], "Часы": total_hours["A4"]},
            {"Линия": "Итого", "Количество": line_counts["A3"] + line_counts["A4"], "Часы": total_hours["A3"] + total_hours["A4"]}
        ]
        
        st.dataframe(
            staff_data,
            column_config={
                "Линия": st.column_config.TextColumn("Линия"),
                "Количество": st.column_config.NumberColumn("Сотрудников", format="%d"),
                "Часы": st.column_config.NumberColumn("Часов", format="%.1f"),
            },
            width='stretch',
            hide_index=True
        )
        
        # дополнительная статистика
        if st.session_state.supports:
            senior = next((s for s in st.session_state.supports if s.get('role') == 'senior'), None)
            repair = next((s for s in st.session_state.supports if s.get('role') == 'repair'), None)
            
            st.write("**Поддержка:**")
            if senior and senior.get('employee_id', 0) > 0:
                st.write(f"• Старший: {senior.get('fio', '')} ({senior.get('work_time', 0):.1f}ч)")
            if repair and repair.get('employee_id', 0) > 0:
                st.write(f"• Ремонтник: {repair.get('fio', '')} ({repair.get('work_time', 0):.1f}ч)")
elif show_stats:
    st.info("Нет данных для расчёта статистики")

# Кнопка сохранить
if st.button("💾 Сохранить отчёт", width='stretch'):
    try:
        tasks = []
        if site_name == 'Катюша':
            for t in st.session_state.tasks_A3:
                code = t.get('sap_code')
                item = sap_by_code.get(code)
                if not item:
                    continue
                tasks.append(TaskModel(
                    line='A3',
                    sap_id=item['id'],
                    qty_made=_to_int_safe(t.get('qty_made'), 0),
                    count_by_norm=bool(t.get('count_by_norm')),
                    discount_percent=_to_int_safe(t.get('discount_percent'), 0),
                ))
            for t in st.session_state.tasks_A4:
                code = t.get('sap_code')
                item = sap_by_code.get(code)
                if not item:
                    continue
                tasks.append(TaskModel(
                    line='A4',
                    sap_id=item['id'],
                    qty_made=_to_int_safe(t.get('qty_made'), 0),
                    count_by_norm=bool(t.get('count_by_norm')),
                    discount_percent=_to_int_safe(t.get('discount_percent'), 0),
                ))
        # Валидация сотрудников с защитой от None значений
        line_emps = []
        for le in st.session_state.line_emps:
            # защита от None в обязательных полях
            clean_le = dict(le)
            clean_le['employee_id'] = clean_le.get('employee_id') or 0
            clean_le['fio'] = clean_le.get('fio') or ""
            clean_le['work_time'] = clean_le.get('work_time') or 0.0
            clean_le['line'] = clean_le.get('line') or "A3"
            line_emps.append(LineEmployeeModel(**clean_le))
        
        supports = []
        for s in st.session_state.supports:
            clean_s = dict(s)
            clean_s['role'] = clean_s.get('role') or "senior"
            clean_s['employee_id'] = clean_s.get('employee_id') or 0
            clean_s['fio'] = clean_s.get('fio') or ""
            clean_s['work_time'] = clean_s.get('work_time') or 0.0
            supports.append(SupportRoleModel(**clean_s))
        upsert_report(site_id, rep_date, tasks, line_emps, supports)
        st.success("Сохранено ✅")
        st.session_state.prefilled = False  # чтобы перечитать на след. рендере при смене даты
    except Exception as e:
        st.error(f"Ошибка при сохранении: {e}")

# Показ существующих записей (для наглядности)
with st.expander("Содержимое отчёта (read-only)"):
    current = get_report(site_id, rep_date)
    if not current:
        st.write("Нет данных")
    else:
        st.write({
            "tasks": current['tasks'],
            "line_emps": current['line_emps'],
            "supports": current['supports']
        })

# Удаление отчёта (в самом низу)
if existing:
    st.divider()
    if st.button("🗑️ Удалить отчёт", type="secondary"):
        st.session_state.confirm_delete = True

    # Подтверждение удаления
    if st.session_state.get('confirm_delete', False):
        st.warning("⚠️ Вы уверены, что хотите удалить отчёт?")
        col_yes, col_no = st.columns(2)
        with col_yes:
            if st.button("✅ Да, удалить", type="primary"):
                try:
                    with engine.begin() as conn:
                        conn.execute(text("DELETE FROM reports WHERE site_id=:s AND report_date=:d"), 
                                   {"s": site_id, "d": rep_date})
                    st.success("Отчёт удалён")
                    st.session_state.confirm_delete = False
                    _reset_form_state()
                    st.rerun()
                except Exception as e:
                    st.error(f"Ошибка при удалении: {e}")
        with col_no:
            if st.button("❌ Отмена"):
                st.session_state.confirm_delete = False
                st.rerun()
