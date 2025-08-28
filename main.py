import os
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
import csv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
DB_SCHEMA = os.getenv("DB_SCHEMA", "stg")


def import_employees(csv_path: str) -> int:
    if not os.path.isabs(csv_path):
        base_dir = os.path.dirname(__file__)
        csv_path = os.path.join(base_dir, csv_path)
    if not os.path.exists(csv_path):
        raise FileNotFoundError(f"CSV not found: {csv_path}")

    engine = create_engine(
        DATABASE_URL,
        pool_pre_ping=True,
        connect_args={"options": f"-csearch_path={DB_SCHEMA}"},
    )

    with open(csv_path, 'r', encoding='utf-8-sig', newline='') as f:
        reader = csv.DictReader(f)
        rows = []
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


def import_norms(csv_path: str) -> int:
    if not os.path.isabs(csv_path):
        base_dir = os.path.dirname(__file__)
        csv_path = os.path.join(base_dir, csv_path)
    if not os.path.exists(csv_path):
        raise FileNotFoundError(f"CSV not found: {csv_path}")

    engine = create_engine(
        DATABASE_URL,
        pool_pre_ping=True,
        connect_args={"options": f"-csearch_path={DB_SCHEMA}"},
    )

    with open(csv_path, 'r', encoding='utf-8-sig', newline='') as f:
        reader = csv.DictReader(f)
        rows = []
        for row in reader:
            sap_code = row.get('SAP', '').strip()
            product_name = row.get('Наименование', '').strip()
            norm_a3_str = row.get('Норма А3 (чел)', '').strip()
            norm_a4_str = row.get('Норма А4 (чел)', '').strip()
            
            if not sap_code or not product_name:
                continue
                
            # парсим нормы, может быть пустая строка
            norm_a3 = None
            norm_a4 = None
            
            if norm_a3_str:
                try:
                    norm_a3 = float(norm_a3_str)
                except ValueError:
                    pass
            
            if norm_a4_str:
                try:
                    norm_a4 = float(norm_a4_str)
                except ValueError:
                    pass
            
            # проверяем что хотя бы одна норма есть
            if norm_a3 is None and norm_a4 is None:
                continue
                
            rows.append({
                "sap_code": sap_code,
                "product_name": product_name,
                "norm_a3_per_employee": norm_a3,
                "norm_a4_per_employee": norm_a4
            })

    if not rows:
        return 0

    with engine.begin() as conn:
        for r in rows:
            conn.execute(text("""
                INSERT INTO sap_catalog(sap_code, product_name, norm_a3_per_employee, norm_a4_per_employee) 
                VALUES (:sap_code, :product_name, :norm_a3_per_employee, :norm_a4_per_employee)
                ON CONFLICT (sap_code) DO UPDATE SET 
                    product_name = EXCLUDED.product_name,
                    norm_a3_per_employee = EXCLUDED.norm_a3_per_employee,
                    norm_a4_per_employee = EXCLUDED.norm_a4_per_employee
            """), r)

    return len(rows)


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Reports GUI utilities")
    sub = parser.add_subparsers(dest="cmd")

    p_imp = sub.add_parser("import-employees", help="Import employees from CSV into DB")
    p_imp.add_argument("--csv", default="w.csv")

    p_norms = sub.add_parser("import-norms", help="Import product norms from CSV into DB")
    p_norms.add_argument("--csv", default="n.csv")

    args = parser.parse_args()

    if args.cmd == "import-employees":
        count = import_employees(args.csv)
        print(f"Imported/updated employees: {count}")
    elif args.cmd == "import-norms":
        count = import_norms(args.csv)
        print(f"Imported/updated norms: {count}")
    else:
        print("Usage:")
        print("  uv run --env-file .env -- python -m reports_gui.main import-employees --csv w.csv")
        print("  uv run --env-file .env -- python -m reports_gui.main import-norms --csv n.csv")


if __name__ == "__main__":
    main()
