-- ensure schema exists and set search_path
CREATE SCHEMA IF NOT EXISTS stg;
SET search_path TO stg;

-- Drop only tables (keep schema and enum types)
DROP TABLE IF EXISTS report_support_roles CASCADE;
DROP TABLE IF EXISTS report_line_employees CASCADE;
DROP TABLE IF EXISTS report_tasks CASCADE;
DROP TABLE IF EXISTS reports CASCADE;
DROP TABLE IF EXISTS employees CASCADE;
DROP TABLE IF EXISTS sap_catalog CASCADE;
DROP TABLE IF EXISTS sites CASCADE;

CREATE TABLE IF NOT EXISTS sites (
  id SERIAL PRIMARY KEY,
  name TEXT UNIQUE NOT NULL
);

INSERT INTO sites (name) VALUES ('Катюша') ON CONFLICT (name) DO NOTHING;
INSERT INTO sites (name) VALUES ('Другое') ON CONFLICT (name) DO NOTHING;

CREATE TABLE IF NOT EXISTS sap_catalog (
  id SERIAL PRIMARY KEY,
  sap_code TEXT UNIQUE NOT NULL,
  product_name TEXT NOT NULL,
  norm_a3_per_employee NUMERIC(5,2), -- может быть NULL если изделие не производится на A3
  norm_a4_per_employee NUMERIC(5,2)  -- может быть NULL если изделие не производится на A4
);

-- примеры (обновлены под новую структуру)
INSERT INTO sap_catalog (sap_code, product_name, norm_a3_per_employee, norm_a4_per_employee) VALUES
 ('SAP-1001', 'Изделие A', 17.5, 25)
ON CONFLICT (sap_code) DO NOTHING;
INSERT INTO sap_catalog (sap_code, product_name, norm_a3_per_employee, norm_a4_per_employee) VALUES
 ('SAP-2002', 'Изделие B', 21, 30)
ON CONFLICT (sap_code) DO NOTHING;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'prod_line') THEN
    CREATE TYPE prod_line AS ENUM ('A3','A4');
  END IF;
END $$;

CREATE TABLE IF NOT EXISTS reports (
  id SERIAL PRIMARY KEY,
  site_id INTEGER NOT NULL REFERENCES sites(id),
  report_date DATE NOT NULL,
  UNIQUE(site_id, report_date)
);

CREATE TABLE IF NOT EXISTS report_tasks (
  id SERIAL PRIMARY KEY,
  report_id INTEGER NOT NULL REFERENCES reports(id) ON DELETE CASCADE,
  line prod_line NOT NULL,
  sap_id INTEGER NOT NULL REFERENCES sap_catalog(id),
  qty_made INTEGER NOT NULL,
  count_by_norm BOOLEAN NOT NULL DEFAULT TRUE,
  discount_percent INTEGER NOT NULL DEFAULT 0 CHECK (discount_percent BETWEEN 0 AND 100)
);

CREATE TABLE IF NOT EXISTS employees (
  id INTEGER PRIMARY KEY,            -- приходят ваши id_employee
  fio TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS report_line_employees (
  id SERIAL PRIMARY KEY,
  report_id INTEGER NOT NULL REFERENCES reports(id) ON DELETE CASCADE,
  employee_id INTEGER NOT NULL REFERENCES employees(id),
  fio TEXT NOT NULL,
  work_time NUMERIC(5,2) NOT NULL,
  line prod_line NOT NULL
);

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'support_role') THEN
    CREATE TYPE support_role AS ENUM ('senior','repair');
  END IF;
END $$;

CREATE TABLE IF NOT EXISTS report_support_roles (
  id SERIAL PRIMARY KEY,
  report_id INTEGER NOT NULL REFERENCES reports(id) ON DELETE CASCADE,
  role support_role NOT NULL,
  employee_id INTEGER NOT NULL REFERENCES employees(id),
  fio TEXT NOT NULL,
  work_time NUMERIC(5,2) NOT NULL
);