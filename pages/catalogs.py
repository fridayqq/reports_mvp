import streamlit as st
from utils.database import fetch_sap_catalog, fetch_employees_catalog

# Настройка страницы
st.set_page_config(
    page_title="Справочники - StarLine Reports GUI",
    page_icon="⚙️",
    layout="wide"
)

st.title("⚙️ Управление справочниками")

# Вкладки для разных типов справочников
tab1, tab2, tab3 = st.tabs(["📋 SAP Каталог", "👥 Сотрудники", "🏭 Участки"])

with tab1:
    st.header("📋 SAP Каталог")
    st.info("""
    Здесь отображается текущий SAP каталог изделий с нормами производства.
    Для редактирования используйте прямые SQL запросы к базе данных.
    """)
    
    try:
        sap_catalog = fetch_sap_catalog()
        if sap_catalog:
            st.dataframe(
                sap_catalog,
                column_config={
                    "id": st.column_config.NumberColumn("ID", format="%d"),
                    "sap_code": st.column_config.TextColumn("SAP код"),
                    "product_name": st.column_config.TextColumn("Название изделия"),
                    "norm_a3_per_employee": st.column_config.NumberColumn("Норма A3", format="%.1f"),
                    "norm_a4_per_employee": st.column_config.NumberColumn("Норма A4", format="%.1f"),
                },
                width='stretch',
                hide_index=True
            )
            
            # Статистика
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("Всего изделий", len(sap_catalog))
            with col2:
                a3_count = sum(1 for item in sap_catalog if item.get('norm_a3_per_employee') is not None)
                st.metric("Доступно на A3", a3_count)
            with col3:
                a4_count = sum(1 for item in sap_catalog if item.get('norm_a4_per_employee') is not None)
                st.metric("Доступно на A4", a4_count)
        else:
            st.warning("⚠️ SAP каталог пуст")
            
    except Exception as e:
        st.error(f"❌ Ошибка при загрузке SAP каталога: {e}")

with tab2:
    st.header("👥 Справочник сотрудников")
    st.info("""
    Здесь отображается текущий справочник сотрудников.
    Для добавления новых сотрудников используйте импорт из CSV или прямые SQL запросы.
    """)
    
    try:
        employees = fetch_employees_catalog()
        if employees:
            st.dataframe(
                employees,
                column_config={
                    "id": st.column_config.NumberColumn("ID", format="%d"),
                    "fio": st.column_config.TextColumn("ФИО"),
                },
                width='stretch',
                hide_index=True
            )
            
            # Статистика
            col1, col2 = st.columns(2)
            with col1:
                st.metric("Всего сотрудников", len(employees))
            with col2:
                st.metric("Уникальных ID", len(set(emp['id'] for emp in employees)))
        else:
            st.warning("⚠️ Справочник сотрудников пуст")
            
    except Exception as e:
        st.error(f"❌ Ошибка при загрузке справочника сотрудников: {e}")

with tab3:
    st.header("🏭 Участки производства")
    st.info("""
    Здесь отображается список участков производства.
    Для добавления новых участков используйте прямые SQL запросы к базе данных.
    """)
    
    try:
        from utils.database import fetch_sites
        sites = fetch_sites()
        if sites:
            sites_data = [{"ID": id, "Название": name} for name, id in sites.items()]
            st.dataframe(
                sites_data,
                column_config={
                    "ID": st.column_config.NumberColumn("ID", format="%d"),
                    "Название": st.column_config.TextColumn("Название участка"),
                },
                width='stretch',
                hide_index=True
            )
            
            st.metric("Всего участков", len(sites))
        else:
            st.warning("⚠️ Список участков пуст")
            
    except Exception as e:
        st.error(f"❌ Ошибка при загрузке списка участков: {e}")

# Информация о структуре БД
st.header("🗄️ Структура базы данных")
with st.expander("📊 Схема базы данных"):
    st.code("""
-- Основные таблицы
reports - отчеты по участкам
├── id (PK)
├── site_id (FK -> sites.id)
├── report_date
└── created_at

report_tasks - задания по линиям
├── id (PK)
├── report_id (FK -> reports.id)
├── line (A3/A4)
├── sap_id (FK -> sap_catalog.id)
├── qty_made
├── count_by_norm
└── discount_percent

report_line_employees - линейные сотрудники
├── id (PK)
├── report_id (FK -> reports.id)
├── employee_id (FK -> employees.id)
├── fio
├── work_time
└── line (A3/A4)

report_support_roles - роли поддержки
├── id (PK)
├── report_id (FK -> reports.id)
├── role (senior/repair)
├── employee_id (FK -> employees.id)
├── fio
└── work_time

-- Справочники
sites - участки производства
├── id (PK)
└── name

sap_catalog - каталог SAP изделий
├── id (PK)
├── sap_code
├── product_name
├── norm_a3_per_employee
└── norm_a4_per_employee

employees - справочник сотрудников
├── id (PK)
└── fio
    """, language="sql")

# Рекомендации по работе
st.header("💡 Рекомендации по работе")
st.info("""
**Для добавления новых данных:**
1. **SAP каталог** - используйте SQL INSERT в таблицу `sap_catalog`
2. **Сотрудники** - используйте импорт из CSV или SQL INSERT в таблицу `employees`
3. **Участки** - используйте SQL INSERT в таблицу `sites`

**Примеры SQL запросов:**
```sql
-- Добавить новое изделие
INSERT INTO sap_catalog (sap_code, product_name, norm_a3_per_employee, norm_a4_per_employee)
VALUES ('12345', 'Новое изделие', 100, 120);

-- Добавить сотрудника
INSERT INTO employees (id, fio) VALUES (999, 'Иванов И.И.');

-- Добавить участок
INSERT INTO sites (id, name) VALUES (3, 'Новый участок');
```
""")
