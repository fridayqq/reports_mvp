import streamlit as st
from utils.database import fetch_sites

def site_selector():
    """Компонент для выбора участка"""
    
    sites = fetch_sites()
    site_name = st.selectbox(
        "Участок",
        list(sites.keys()),
        index=list(sites.keys()).index('Катюша') if 'Катюша' in sites else 0,
        key="site_select",
    )
    
    return sites[site_name], site_name 