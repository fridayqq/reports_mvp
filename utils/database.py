import os
import csv
from datetime import date
from typing import List, Dict, Any

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
import streamlit as st

# Глобальные переменные для подключения к БД
DATABASE_URL = os.getenv("DATABASE_URL")
DB_SCHEMA = os.getenv("DB_SCHEMA", "stg")

@st.cache_resource(show_spinner=False)
def get_engine() -> Engine:
    """Получение подключения к базе данных"""
    if not DATABASE_URL:
        st.error("⚠️ Не настроена переменная DATABASE_URL в файле .env")
        st.stop()
    
    # Устанавливаем search_path, чтобы работать в заданной схеме (по умолчанию stg)
    return create_engine(
        DATABASE_URL,
        pool_pre_ping=True,
        connect_args={"options": f"-csearch_path={DB_SCHEMA}"}
    )

def fetch_sites() -> Dict[str, int]:
    """Получение списка участков"""
    engine = get_engine()
    with engine.begin() as conn:
        rows = conn.execute(text("SELECT id, name FROM sites ORDER BY name"))
        return {r.name: r.id for r in rows}

@st.cache_data(show_spinner=False)
def fetch_sap_catalog() -> List[Dict[str, Any]]:
    """Получение SAP каталога"""
    engine = get_engine()
    with engine.begin() as conn:
        rows = conn.execute(text(
            "SELECT id, sap_code, product_name, norm_a3_per_employee, norm_a4_per_employee FROM sap_catalog ORDER BY sap_code"
        ))
        return [dict(row._mapping) for row in rows]

@st.cache_data(show_spinner=False)
def fetch_employees_catalog() -> List[Dict[str, Any]]:
    """Получение справочника сотрудников"""
    engine = get_engine()
    with engine.begin() as conn:
        rows = conn.execute(text("SELECT id, fio FROM employees ORDER BY fio"))
        return [dict(row._mapping) for row in rows]

def import_employees_from_csv(csv_path: str) -> int:
    """Импорт сотрудников из CSV файла"""
    engine = get_engine()
    
    if not os.path.isabs(csv_path):
        base_dir = os.path.dirname(os.path.dirname(__file__))
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

def get_report(site_id: int, d: date) -> Dict[str, Any] | None:
    """Получение существующего отчета"""
    engine = get_engine()
    with engine.begin() as conn:
        rpt = conn.execute(text(
            "SELECT id FROM reports WHERE site_id=:s AND report_date=:d"
        ), {"s": site_id, "d": d}).fetchone()
        
        if not rpt:
            return None
            
        report_id = rpt.id
        tasks = conn.execute(text(
            """
            SELECT t.id, t.line, t.sap_id, sc.sap_code, sc.product_name,
                   CASE 
                       WHEN t.line='A3' THEN ROUND(sc.norm_a3_per_employee * 0.7)::int 
                       WHEN t.line='A4' THEN sc.norm_a4_per_employee
                       ELSE 0 
                   END AS norm_per_employee,
                   t.qty_made, t.count_by_norm, t.discount_percent,
                   CASE 
                       WHEN t.line='A3' THEN ROUND(sc.norm_a3_per_employee * 0.7 * (1 - t.discount_percent/100.0))::int
                       WHEN t.line='A4' THEN ROUND(sc.norm_a4_per_employee * (1 - t.discount_percent/100.0))::int
                       ELSE 0 
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
        
        return {
            "id": report_id, 
            "tasks": list(tasks), 
            "line_emps": list(line_emps), 
            "supports": list(supports)
        }

def upsert_report(site_id: int, d: date, tasks: List[Dict], line_emps: List[Dict], supports: List[Dict]):
    """Сохранение или обновление отчета"""
    engine = get_engine()
    with engine.begin() as conn:
        rpt = conn.execute(text("""
            INSERT INTO reports(site_id, report_date) VALUES (:s,:d)
            ON CONFLICT (site_id, report_date) DO UPDATE SET report_date = EXCLUDED.report_date
            RETURNING id
        """), {"s": site_id, "d": d}).fetchone()
        
        report_id = rpt.id
        
        # Удаляем старые записи и вставляем новые
        conn.execute(text("DELETE FROM report_tasks WHERE report_id=:rid"), {"rid": report_id})
        conn.execute(text("DELETE FROM report_line_employees WHERE report_id=:rid"), {"rid": report_id})
        conn.execute(text("DELETE FROM report_support_roles WHERE report_id=:rid"), {"rid": report_id})

        # Вставляем задания
        for t in tasks:
            conn.execute(text(
                """
                INSERT INTO report_tasks(report_id, line, sap_id, qty_made, count_by_norm, discount_percent)
                VALUES (:rid, :line, :sap_id, :qty_made, :count_by_norm, :discount_percent)
                """
            ), {"rid": report_id, **t})
        
        # Вставляем линейных сотрудников
        for le in line_emps:
            # Обновляем справочник employees по мере ввода
            conn.execute(text(
                "INSERT INTO employees(id, fio) VALUES (:id,:fio) ON CONFLICT (id) DO UPDATE SET fio=EXCLUDED.fio"
            ), {"id": le['employee_id'], "fio": le['fio']})
            conn.execute(text(
                """
                INSERT INTO report_line_employees(report_id, employee_id, fio, work_time, line)
                VALUES (:rid, :employee_id, :fio, :work_time, :line)
                """
            ), {"rid": report_id, **le})
        
        # Вставляем роли поддержки
        for s in supports:
            conn.execute(text(
                "INSERT INTO employees(id, fio) VALUES (:id,:fio) ON CONFLICT (id) DO UPDATE SET fio=EXCLUDED.fio"
            ), {"id": s['employee_id'], "fio": s['fio']})
            conn.execute(text(
                """
                INSERT INTO report_support_roles(report_id, role, employee_id, fio, work_time)
                VALUES (:rid, :role, :employee_id, :fio, :work_time)
                """
            ), {"rid": report_id, **s})

def delete_report(site_id: int, d: date):
    """Удаление отчета"""
    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM reports WHERE site_id=:s AND report_date=:d"), 
                   {"s": site_id, "d": d})
