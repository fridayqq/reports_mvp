import os
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

# Проверка переменных окружения
DATABASE_URL = os.getenv("DATABASE_URL")
DB_SCHEMA = os.getenv("DB_SCHEMA", "stg")

if not DATABASE_URL:
    st.error("⚠️ Не настроена переменная DATABASE_URL в файле .env")
    st.stop()

# Настройка страницы
st.set_page_config(
    page_title="StarLine Reports GUI",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Главная страница
def main():
    st.title("📊 StarLine Reports GUI")
    st.markdown("---")
    
    st.header("🎯 Назначение системы")
    st.write("""
    Система для ведения отчетов по участкам производства, включающая:
    - 📋 Ведение отчетов по линиям A3 и A4
    - 👥 Учет сотрудников и их рабочего времени
    - 📊 Расчет нормативов и статистики
    - 🔧 Управление справочниками SAP и сотрудников
    """)
    
    st.header("🚀 Быстрый старт")
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("📋 Создать отчет")
        st.write("""
        1. Выберите участок и дату
        2. Заполните задания по линиям
        3. Добавьте сотрудников
        4. Сохраните отчет
        """)
        if st.button("📋 Перейти к отчетам", width='stretch'):
            st.switch_page("pages/reports.py")
    
    with col2:
        st.subheader("⚙️ Настройки")
        st.write("""
        1. Импорт сотрудников из CSV
        2. Управление SAP каталогом
        3. Настройка справочников
        """)
        if st.button("⚙️ Перейти к настройкам", width='stretch'):
            st.switch_page("pages/catalogs.py")
    
    st.header("📈 Статистика")
    st.info("""
    **Текущие возможности:**
    - Поддержка участка "Катюша" с линиями A3 и A4
    - Расчет нормативов с учетом скидок
    - Учет рабочего времени сотрудников
    - Автоматический расчет итоговых показателей
    """)
    
    # Информация о системе
    with st.expander("ℹ️ Информация о системе"):
        st.write(f"**База данных:** {DB_SCHEMA}")
        st.write(f"**Версия:** 1.0.0")
        st.write("**Разработчик:** P2")

if __name__ == "__main__":
    main()
