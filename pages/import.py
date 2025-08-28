import streamlit as st
import os
from utils.database import import_employees_from_csv

# Настройка страницы
st.set_page_config(
    page_title="Импорт - StarLine Reports GUI",
    page_icon="📥",
    layout="wide"
)

st.title("📥 Импорт данных")

st.info("""
Эта страница позволяет импортировать данные из CSV файлов в базу данных.
В настоящее время поддерживается импорт сотрудников.
""")

# Импорт сотрудников
st.header("👥 Импорт сотрудников")

# Проверка наличия CSV файлов
csv_files = []
base_dir = os.path.dirname(os.path.dirname(__file__))
for file in os.listdir(base_dir):
    if file.endswith('.csv'):
        csv_files.append(file)

if csv_files:
    st.write("**Доступные CSV файлы:**")
    for file in csv_files:
        st.write(f"• `{file}`")
    
    # Выбор файла для импорта
    selected_file = st.selectbox(
        "Выберите CSV файл для импорта:",
        csv_files,
        help="Файл должен содержать колонки 'id_employee' и 'fio_employee'"
    )
    
    # Предварительный просмотр файла
    if selected_file:
        file_path = os.path.join(base_dir, selected_file)
        try:
            with open(file_path, 'r', encoding='utf-8-sig') as f:
                first_lines = f.readlines()[:5]  # Первые 5 строк
            
            st.subheader("📋 Предварительный просмотр файла")
            st.code(''.join(first_lines), language="text")
            
            # Информация о файле
            file_size = os.path.getsize(file_path)
            st.write(f"**Размер файла:** {file_size / 1024:.1f} KB")
            
        except Exception as e:
            st.error(f"❌ Ошибка при чтении файла: {e}")
    
    # Кнопка импорта
    if st.button("🚀 Импортировать сотрудников", type="primary"):
        if selected_file:
            try:
                with st.spinner("Импортирую сотрудников..."):
                    count = import_employees_from_csv(selected_file)
                
                if count > 0:
                    st.success(f"✅ Успешно импортировано/обновлено {count} сотрудников")
                else:
                    st.warning("⚠️ Не удалось импортировать сотрудников. Проверьте формат файла.")
                    
            except Exception as e:
                st.error(f"❌ Ошибка при импорте: {e}")
        else:
            st.warning("⚠️ Выберите файл для импорта")
else:
    st.warning("⚠️ CSV файлы не найдены в корневой папке проекта")
    st.write("""
    **Для импорта сотрудников:**
    1. Поместите CSV файл в корневую папку проекта
    2. Убедитесь, что файл содержит колонки:
       - `id_employee` - ID сотрудника (число)
       - `fio_employee` - ФИО сотрудника (текст)
    3. Используйте кодировку UTF-8
    """)

# Формат CSV файла
st.header("📋 Формат CSV файла")
st.write("""
**Пример CSV файла для импорта сотрудников:**
```csv
id_employee,fio_employee
1001,Иванов Иван Иванович
1002,Петров Петр Петрович
1003,Сидоров Сидор Сидорович
```

**Требования к файлу:**
- Разделитель: запятая (,)
- Кодировка: UTF-8
- Первая строка: заголовки колонок
- Колонка `id_employee`: числовой ID сотрудника
- Колонка `fio_employee`: ФИО сотрудника (текст)
""")

# Ручной ввод сотрудника
st.header("✏️ Ручное добавление сотрудника")
st.info("Добавьте одного сотрудника напрямую через форму")

with st.form("add_employee_form"):
    emp_id = st.number_input("ID сотрудника", min_value=1, step=1)
    emp_fio = st.text_input("ФИО сотрудника", placeholder="Иванов И.И.")
    
    submitted = st.form_submit_button("➕ Добавить сотрудника")
    
    if submitted and emp_fio.strip():
        try:
            from utils.database import get_engine
            from sqlalchemy import text
            
            engine = get_engine()
            with engine.begin() as conn:
                conn.execute(text(
                    "INSERT INTO employees(id, fio) VALUES (:id,:fio) ON CONFLICT (id) DO UPDATE SET fio=EXCLUDED.fio"
                ), {"id": emp_id, "fio": emp_fio.strip()})
            
            st.success(f"✅ Сотрудник {emp_fio} (ID: {emp_id}) добавлен/обновлен")
            
        except Exception as e:
            st.error(f"❌ Ошибка при добавлении: {e}")
    elif submitted:
        st.warning("⚠️ Введите ФИО сотрудника")

# Информация о процессе импорта
st.header("ℹ️ Информация об импорте")
st.info("""
**Как работает импорт:**
1. **Чтение файла** - система читает CSV файл с кодировкой UTF-8
2. **Валидация данных** - проверяется наличие обязательных колонок
3. **Обработка строк** - каждая строка проверяется на корректность
4. **Вставка в БД** - данные вставляются с обработкой конфликтов (ON CONFLICT)

**Обработка конфликтов:**
- Если сотрудник с таким ID уже существует, обновляется его ФИО
- Если ID новый, создается новая запись

**Логирование:**
- Успешно импортированные записи подсчитываются
- Ошибки валидации логируются в консоли
""")
