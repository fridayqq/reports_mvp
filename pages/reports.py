import streamlit as st
from datetime import date
from typing import List, Dict, Any

from utils.database import (
    get_report, upsert_report, delete_report, 
    fetch_sap_catalog, fetch_employees_catalog
)
from models.data_models import TaskModel, LineEmployeeModel, SupportRoleModel
from utils.data_utils import (
    to_int_safe, normalize_task_row, extract_user_fields,
    ensure_row_ids, next_seq, get_available_sap_codes_for_line,
    calculate_line_statistics, calculate_product_summary
)
from components.site_selector import site_selector

# Настройка страницы
st.set_page_config(
    page_title="Отчеты - StarLine Reports GUI",
    page_icon="📋",
    layout="wide"
)

st.title("📋 Ведение отчетов")

# Отладочные элементы
col_debug1, col_debug2 = st.columns([1, 3])
with col_debug1:
    if st.button("🐛 Режим отладки"):
        st.session_state.debug_mode = not st.session_state.get('debug_mode', False)
        st.rerun()
    
    if st.session_state.get('debug_mode', False):
        st.success("✅ Отладка включена")
    else:
        st.info("ℹ️ Отладка выключена")

with col_debug2:
    if st.button("🔄 Сбросить состояние"):
        st.session_state.tasks_A3 = []
        st.session_state.tasks_A4 = []
        st.session_state.line_emps = []
        st.session_state.supports = []
        st.session_state.prefilled = False
        st.rerun()

# Выбор участка и даты
site_id, site_name = site_selector()
rep_date = st.date_input(
    "Дата отчёта", 
    value=date.today(), 
    key="date_input"
)

# Загрузка существующего отчёта
existing = get_report(site_id, rep_date)
if existing:
    st.success("✅ Найден существующий отчёт — поля заполнены из БД")
else:
    st.info("ℹ️ Отчёт пока не заполнен — можно ввести данные")

# Инициализация состояния формы
if 'tasks_A3' not in st.session_state:
    st.session_state.tasks_A3 = []
if 'tasks_A4' not in st.session_state:
    st.session_state.tasks_A4 = []
if 'line_emps' not in st.session_state:
    st.session_state.line_emps = []
if 'supports' not in st.session_state:
    st.session_state.supports = []

# Загрузка существующих данных в сессию
if existing and not st.session_state.get('prefilled'):
    st.session_state.tasks_A3 = [
        {
            "id": t.get('id'),
            "sap_code": t['sap_code'],
            "product_name": t['product_name'],
            "norm_per_employee": t['norm_per_employee'],
            "discount_percent": t.get('discount_percent', 0),
            "norm_with_discount": t.get('norm_with_discount', t['norm_per_employee']),
            "qty_made": t['qty_made'],
            "count_by_norm": t['count_by_norm'],
            "line": t['line']
        }
        for t in existing['tasks'] if t['line'] == 'A3']
    
    st.session_state.tasks_A4 = [
        {
            "id": t.get('id'),
            "sap_code": t['sap_code'],
            "product_name": t['product_name'],
            "norm_per_employee": t['norm_per_employee'],
            "discount_percent": t.get('discount_percent', 0),
            "norm_with_discount": t.get('norm_with_discount', t['norm_per_employee']),
            "qty_made": t['qty_made'],
            "count_by_norm": t['count_by_norm'],
            "line": t['line']
        }
        for t in existing['tasks'] if t['line'] == 'A4']
    
    st.session_state.line_emps = [dict(x) for x in existing['line_emps']]
    st.session_state.supports = [dict(x) for x in existing['supports']]
    st.session_state.prefilled = True

# Загрузка справочников
@st.cache_data(ttl=3600, show_spinner=False)
def load_cached_sap():
    cat = fetch_sap_catalog()
    return {
        'by_code': {x['sap_code']: x for x in cat},
        'codes': [x['sap_code'] for x in cat],
    }

@st.cache_data(ttl=3600, show_spinner=False)
def load_cached_emps():
    emps = fetch_employees_catalog()
    return {
        'id_to_fio': {int(e['id']): e['fio'] for e in emps},
        'ids': [int(e['id']) for e in emps],
        'full': emps,
    }

sap_cache = load_cached_sap()
sap_by_code = sap_cache['by_code']
sap_codes = sap_cache['codes']

emps_cache = load_cached_emps()
id_to_fio = emps_cache['id_to_fio']

# Функции для работы с данными
def add_task(line: str, sap_code: str, discount_percent: int, qty_made: int, count_by_norm: bool):
    """Добавление нового задания"""
    if not sap_code:
        st.error("⚠️ Выберите SAP код")
        return False
    
    item = sap_by_code.get(sap_code)
    if not item:
        st.error("⚠️ SAP код не найден в каталоге")
        return False
    
    # Безопасное приведение типов для числовых значений
    try:
        # Получаем норму и приводим к float, обрабатывая возможные decimal.Decimal
        raw_norm = item.get(f'norm_{line.lower()}_per_employee', 0)
        norm_per_emp = float(raw_norm) if raw_norm is not None else 0.0
        
        discount = float(discount_percent)
        qty = float(qty_made)
        
        # Проверяем, что норма положительная
        if norm_per_emp <= 0:
            st.error(f"⚠️ Норма для линии {line} должна быть больше 0")
            return False
        
        norm_with_discount = int(round(norm_per_emp * (1 - discount/100)))
        
    except (ValueError, TypeError) as e:
        st.error(f"⚠️ Ошибка при обработке числовых значений: {e}")
        return False
    
    new_task = {
        "id": None,  # будет установлен при сохранении в БД
        "sap_code": sap_code,
        "product_name": item['product_name'],
        "norm_per_employee": norm_per_emp,
        "discount_percent": int(discount),
        "norm_with_discount": norm_with_discount,
        "qty_made": int(qty),
        "count_by_norm": count_by_norm,
        "line": line
    }
    
    if line == 'A3':
        st.session_state.tasks_A3.append(new_task)
    else:
        st.session_state.tasks_A4.append(new_task)
    
    st.success(f"✅ Задание добавлено на линию {line}")
    return True

def remove_task(line: str, index: int):
    """Удаление задания"""
    if line == 'A3':
        if 0 <= index < len(st.session_state.tasks_A3):
            removed = st.session_state.tasks_A3.pop(index)
            st.success(f"✅ Задание '{removed['sap_code']}' удалено с линии {line}")
    else:
        if 0 <= index < len(st.session_state.tasks_A4):
            removed = st.session_state.tasks_A4.pop(index)
            st.success(f"✅ Задание '{removed['sap_code']}' удалено с линии {line}")

def add_employee(employee_id: int, work_time: float, line: str):
    """Добавление нового сотрудника"""
    if employee_id == 0:
        st.error("⚠️ Выберите сотрудника")
        return False
    
    fio = id_to_fio.get(employee_id, "")
    if not fio:
        st.error("⚠️ Сотрудник не найден")
        return False
    
    # Безопасное приведение типов для числовых значений
    try:
        work_hours = float(work_time)
        if work_hours <= 0:
            st.error("⚠️ Часы работы должны быть больше 0")
            return False
    except (ValueError, TypeError) as e:
        st.error(f"⚠️ Ошибка при обработке часов работы: {e}")
        return False
    
    # Проверяем, не добавлен ли уже этот сотрудник на эту линию
    existing_emp = next((emp for emp in st.session_state.line_emps 
                        if emp.get('employee_id') == employee_id and emp.get('line') == line), None)
    if existing_emp:
        st.error(f"⚠️ Сотрудник {fio} уже добавлен на линию {line}")
        return False
    
    new_emp = {
        "id": None,
        "employee_id": employee_id,
        "fio": fio,
        "work_time": work_hours,
        "line": line
    }
    
    st.session_state.line_emps.append(new_emp)
    st.success(f"✅ Сотрудник {fio} добавлен на линию {line}")
    return True

def remove_employee(index: int):
    """Удаление сотрудника"""
    if 0 <= index < len(st.session_state.line_emps):
        removed = st.session_state.line_emps.pop(index)
        st.success(f"✅ Сотрудник {removed['fio']} удален")

def add_support_role(role: str, employee_id: int, work_time: float):
    """Добавление роли поддержки"""
    if employee_id == 0:
        st.error("⚠️ Выберите сотрудника")
        return False
    
    fio = id_to_fio.get(employee_id, "")
    if not fio:
        st.error("⚠️ Сотрудник не найден")
        return False
    
    # Безопасное приведение типов для числовых значений
    try:
        work_hours = float(work_time)
        if work_hours <= 0:
            st.error("⚠️ Часы работы должны быть больше 0")
            return False
    except (ValueError, TypeError) as e:
        st.error(f"⚠️ Ошибка при обработке часов работы: {e}")
        return False
    
    # Проверяем, не добавлена ли уже эта роль
    existing_role = next((s for s in st.session_state.supports 
                         if s.get('role') == role), None)
    if existing_role:
        st.error(f"⚠️ Роль {role} уже назначена")
        return False
    
    new_support = {
        "id": None,
        "role": role,
        "employee_id": employee_id,
        "fio": fio,
        "work_time": work_hours
    }
    
    st.session_state.supports.append(new_support)
    st.success(f"✅ Роль {role} назначена сотруднику {fio}")
    return True

def remove_support_role(index: int):
    """Удаление роли поддержки"""
    if 0 <= index < len(st.session_state.supports):
        removed = st.session_state.supports.pop(index)
        st.success(f"✅ Роль {removed['role']} удалена")

# Форма отчетов (только для участка Катюша)
if site_name == 'Катюша':
    st.header("➕ Добавление заданий")
    
    col_form1, col_form2 = st.columns(2)
    
    with col_form1:
        st.subheader("📋 Новое задание")
        
        # Форма добавления задания
        with st.form("add_task_form"):
            line = st.selectbox("Линия", ["A3", "A4"], key="task_line")
            
            # Фильтруем SAP коды по доступности на выбранной линии
            available_codes = get_available_sap_codes_for_line(line, sap_by_code)
            sap_code = st.selectbox("Изделие", [""] + available_codes, 
                                  format_func=lambda x: f"{x} - {sap_by_code.get(x, {}).get('product_name', '')}" if x else "Выберите изделие",
                                  key="task_sap")
            
            # Показываем информацию о выбранном изделии
            if sap_code and sap_code in sap_by_code:
                item = sap_by_code[sap_code]
                norm_key = f'norm_{line.lower()}_per_employee'
                norm_value = item.get(norm_key, 0)
                if norm_value:
                    # Безопасное приведение к float для избежания ошибок с decimal.Decimal
                    norm_value_float = float(norm_value)
                    st.info(f"📋 **{item['product_name']}**\n"
                           f"Базовая норма на {line}: **{norm_value_float:.1f}** шт/чел")
                else:
                    st.warning(f"⚠️ Изделие **{item['product_name']}** не производится на линии {line}")
            
            discount_percent = st.number_input("Скидка на норму (%)", min_value=0, max_value=100, value=0, step=1, key="task_discount")
            
            # Показываем расчет нормы со скидкой
            if sap_code and sap_code in sap_by_code and discount_percent > 0:
                item = sap_by_code[sap_code]
                norm_key = f'norm_{line.lower()}_per_employee'
                base_norm = item.get(norm_key, 0)
                if base_norm:
                    # Безопасное приведение к float для избежания ошибок с decimal.Decimal
                    base_norm_float = float(base_norm)
                    discounted_norm = base_norm_float * (1 - discount_percent/100)
                    st.success(f"🎯 Норма со скидкой: **{discounted_norm:.1f}** шт/чел")
            
            qty_made = st.number_input("Изготовлено (шт)", min_value=0, value=0, step=1, key="task_qty")
            count_by_norm = st.checkbox("СЧИТАТЬ ПО НОРМЕ", value=True, key="task_count_norm")
            
            submitted = st.form_submit_button("➕ Добавить задание")
            
            if submitted:
                add_task(line, sap_code, discount_percent, qty_made, count_by_norm)
    
    with col_form2:
        st.subheader("👥 Новый сотрудник")
        
        # Форма добавления сотрудника
        with st.form("add_employee_form"):
            emp_employee_id = st.selectbox("Сотрудник", [0] + sorted(id_to_fio.keys()), 
                                         format_func=lambda x: f"{x} - {id_to_fio.get(x, '')}" if x > 0 else "Выберите сотрудника",
                                         key="emp_employee_id")
            emp_work_time = st.number_input("Часы работы", min_value=0.0, value=8.0, step=0.5, key="emp_work_time")
            emp_line = st.selectbox("Линия", ["A3", "A4"], key="emp_line")
            
            submitted = st.form_submit_button("➕ Добавить сотрудника")
            
            if submitted:
                add_employee(emp_employee_id, emp_work_time, emp_line)
        
        st.subheader("🔧 Новая роль поддержки")
        
        # Форма добавления роли поддержки
        with st.form("add_support_form"):
            support_role = st.selectbox("Роль", ["senior", "repair"], 
                                      format_func=lambda x: "Старший" if x == "senior" else "Ремонтник",
                                      key="support_role")
            support_employee_id = st.selectbox("Сотрудник", [0] + sorted(id_to_fio.keys()), 
                                             format_func=lambda x: f"{x} - {id_to_fio.get(x, '')}" if x > 0 else "Выберите сотрудника",
                                             key="support_employee_id")
            support_work_time = st.number_input("Часы работы", min_value=0.0, value=8.0, step=0.5, key="support_work_time")
            
            submitted = st.form_submit_button("➕ Добавить роль")
            
            if submitted:
                add_support_role(support_role, support_employee_id, support_work_time)

# Отображение данных в таблицах
st.header("📊 Текущие данные")

if site_name == 'Катюша':
    col_tables1, col_tables2 = st.columns(2)
    
    # Таблица заданий A3
    with col_tables1:
        st.subheader("📋 Задания линии A3")
        if st.session_state.tasks_A3:
            for i, task in enumerate(st.session_state.tasks_A3):
                col_task1, col_task2 = st.columns([4, 1])
                with col_task1:
                    st.write(f"**{task['sap_code']}** - {task['product_name']}")
                    norm_per_emp = float(task.get('norm_per_employee', 0))
                    norm_with_disc = int(task.get('norm_with_discount', 0))
                    discount = int(task.get('discount_percent', 0))
                    qty = int(task.get('qty_made', 0))
                    st.write(f"📊 Норма: {norm_per_emp:.1f} → {norm_with_disc} шт/чел (скидка {discount}%)")
                    st.write(f"🏭 Изготовлено: {qty} шт. | По норме: {'✅' if task['count_by_norm'] else '❌'}")
                with col_task2:
                    if st.button("🗑️", key=f"del_task_A3_{i}"):
                        remove_task('A3', i)
                        st.rerun()
                st.divider()
        else:
            st.info("ℹ️ Нет заданий на линии A3")
    
    # Таблица заданий A4
    with col_tables2:
        st.subheader("📋 Задания линии A4")
        if st.session_state.tasks_A4:
            for i, task in enumerate(st.session_state.tasks_A4):
                col_task1, col_task2 = st.columns([4, 1])
                with col_task1:
                    st.write(f"**{task['sap_code']}** - {task['product_name']}")
                    norm_per_emp = float(task.get('norm_per_employee', 0))
                    norm_with_disc = int(task.get('norm_with_discount', 0))
                    discount = int(task.get('discount_percent', 0))
                    qty = int(task.get('qty_made', 0))
                    st.write(f"📊 Норма: {norm_per_emp:.1f} → {norm_with_disc} шт/чел (скидка {discount}%)")
                    st.write(f"🏭 Изготовлено: {qty} шт. | По норме: {'✅' if task['count_by_norm'] else '❌'}")
                with col_task2:
                    if st.button("🗑️", key=f"del_task_A4_{i}"):
                        remove_task('A4', i)
                        st.rerun()
                st.divider()
        else:
            st.info("ℹ️ Нет заданий на линии A4")

# Таблица сотрудников
st.subheader("👥 Линейные сотрудники")
if st.session_state.line_emps:
    for i, emp in enumerate(st.session_state.line_emps):
        col_emp1, col_emp2 = st.columns([4, 1])
        with col_emp1:
            st.write(f"**{emp['fio']}** (ID: {emp['employee_id']})")
            work_time = float(emp.get('work_time', 0))
            st.write(f"Линия: {emp['line']} | Часы: {work_time:.1f}")
        with col_emp2:
            if st.button("🗑️", key=f"del_emp_{i}"):
                remove_employee(i)
                st.rerun()
        st.divider()
else:
    st.info("ℹ️ Нет добавленных сотрудников")

# Таблица ролей поддержки
st.subheader("🔧 Роли поддержки")
if st.session_state.supports:
    for i, support in enumerate(st.session_state.supports):
        col_support1, col_support2 = st.columns([4, 1])
        with col_support1:
            role_name = "Старший" if support['role'] == 'senior' else "Ремонтник"
            st.write(f"**{role_name}**: {support['fio']} (ID: {support['employee_id']})")
            work_time = float(support.get('work_time', 0))
            st.write(f"Часы: {work_time:.1f}")
        with col_support2:
            if st.button("🗑️", key=f"del_support_{i}"):
                remove_support_role(i)
                st.rerun()
        st.divider()
else:
    st.info("ℹ️ Нет назначенных ролей поддержки")

# Резюме
st.header("📊 Резюме смены")
show_stats = st.button("🔢 Рассчитать статистику за день", width='stretch')

if show_stats and (st.session_state.tasks_A3 or st.session_state.tasks_A4 or st.session_state.line_emps):
    col_summary1, col_summary2 = st.columns(2)
    
    with col_summary1:
        st.subheader("Итоговые нормативы по изделиям")
        
        # Пояснение к таблице
        st.info("""
        **📊 Пояснение к таблице:**
        - **Норма** - расчетный норматив на основе времени работы сотрудников и норм производства
        - **Изгот.** - фактически изготовленное количество изделий
        - Если галочка "СЧИТАТЬ ПО НОРМЕ" снята, то норма рассчитывается по формуле
        - Если галочка установлена, то норма = количество изготовленного
        """)
        
        # Подсчитываем часы сотрудников по линиям для расчёта нормативов
        line_hours_for_calc = {"A3": 0.0, "A4": 0.0}
        for emp in st.session_state.line_emps:
            line = emp.get('line', 'A3')
            work_time = emp.get('work_time', 0.0)
            if work_time is not None and line in line_hours_for_calc:
                line_hours_for_calc[line] += float(work_time)
        
        summary_data = calculate_product_summary(
            st.session_state.tasks_A3, 
            st.session_state.tasks_A4, 
            line_hours_for_calc
        )
        
        if summary_data:
            st.dataframe(
                summary_data,
                column_config={
                    "Изделие": st.column_config.TextColumn("Изделие", width="medium"),
                    "A3 (норма)": st.column_config.NumberColumn("A3 (норма)", format="%d"),
                    "A4 (норма)": st.column_config.NumberColumn("A4 (норма)", format="%d"),
                    "Итого (норма)": st.column_config.NumberColumn("Итого (норма)", format="%d"),
                    "A3 (изгот.)": st.column_config.NumberColumn("A3 (изгот.)", format="%d"),
                    "A4 (изгот.)": st.column_config.NumberColumn("A4 (изгот.)", format="%d"),
                    "Итого (изгот.)": st.column_config.NumberColumn("Итого (изгот.)", format="%d"),
                },
                width='stretch',
                hide_index=True
            )
        else:
            st.info("ℹ️ Нет заданий для отображения")
    
    with col_summary2:
        st.subheader("Сотрудники по линиям")
        
        # Подсчёт сотрудников по линиям
        line_stats = calculate_line_statistics(st.session_state.line_emps)
        
        staff_data = [
            {"Линия": "A3", "Количество": line_stats["counts"]["A3"], "Часы": line_stats["hours"]["A3"]},
            {"Линия": "A4", "Количество": line_stats["counts"]["A4"], "Часы": line_stats["hours"]["A4"]},
            {"Линия": "Итого", "Количество": line_stats["total_count"], "Часы": line_stats["total_hours"]}
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
        
        # Дополнительная статистика
        if st.session_state.supports:
            senior = next((s for s in st.session_state.supports if s.get('role') == 'senior'), None)
            repair = next((s for s in st.session_state.supports if s.get('role') == 'repair'), None)
            
            st.write("**Поддержка:**")
            if senior and senior.get('employee_id', 0) > 0:
                st.write(f"• Старший: {senior.get('fio', '')} ({senior.get('work_time', 0):.1f}ч)")
            if repair and repair.get('employee_id', 0) > 0:
                st.write(f"• Ремонтник: {repair.get('fio', '')} ({repair.get('work_time', 0):.1f}ч)")
elif show_stats:
    st.info("ℹ️ Нет данных для расчёта статистики")

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
                    qty_made=to_int_safe(t.get('qty_made'), 0),
                    count_by_norm=bool(t.get('count_by_norm')),
                    discount_percent=to_int_safe(t.get('discount_percent'), 0),
                ))
            for t in st.session_state.tasks_A4:
                code = t.get('sap_code')
                item = sap_by_code.get(code)
                if not item:
                    continue
                tasks.append(TaskModel(
                    line='A4',
                    sap_id=item['id'],
                    qty_made=to_int_safe(t.get('qty_made'), 0),
                    count_by_norm=bool(t.get('count_by_norm')),
                    discount_percent=to_int_safe(t.get('discount_percent'), 0),
                ))
        
        # Валидация сотрудников с защитой от None значений
        line_emps = []
        for le in st.session_state.line_emps:
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
        
        # Преобразуем модели в словари для передачи в БД
        try:
            # Пробуем новый метод Pydantic v2
            tasks_dicts = [task.model_dump() for task in tasks]
            line_emps_dicts = [emp.model_dump() for emp in line_emps]
            supports_dicts = [support.model_dump() for support in supports]
        except AttributeError:
            # Fallback для старой версии Pydantic
            tasks_dicts = [task.dict() for task in tasks]
            line_emps_dicts = [emp.dict() for emp in line_emps]
            supports_dicts = [support.dict() for support in supports]
        
        # Отладочная информация
        if st.session_state.get('debug_mode', False):
            st.write(f"**Отладка сохранения:**")
            st.write(f"- Заданий: {len(tasks_dicts)}")
            st.write(f"- Сотрудников: {len(line_emps_dicts)}")
            st.write(f"- Ролей поддержки: {len(supports_dicts)}")
            st.write(f"- Пример задания: {tasks_dicts[0] if tasks_dicts else 'Нет'}")
        
        upsert_report(site_id, rep_date, tasks_dicts, line_emps_dicts, supports_dicts)
        st.success("✅ Сохранено")
        st.session_state.prefilled = False  # чтобы перечитать на след. рендере при смене даты
    except Exception as e:
        st.error(f"❌ Ошибка при сохранении: {e}")

# Показ существующих записей (для наглядности)
with st.expander("📋 Содержимое отчёта (read-only)"):
    current = get_report(site_id, rep_date)
    if not current:
        st.write("ℹ️ Нет данных")
    else:
        st.write({
            "tasks": current['tasks'],
            "line_emps": current['line_emps'],
            "supports": current['supports']
        })

# Удаление отчёта
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
                    delete_report(site_id, rep_date)
                    st.success("✅ Отчёт удалён")
                    st.session_state.confirm_delete = False
                    st.rerun()
                except Exception as e:
                    st.error(f"❌ Ошибка при удалении: {e}")
        with col_no:
            if st.button("❌ Отмена"):
                st.session_state.confirm_delete = False
                st.rerun()
