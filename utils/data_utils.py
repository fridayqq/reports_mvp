import math
from typing import List, Dict, Any

def to_int_safe(value, default: int = 0) -> int:
    """Безопасное приведение к int (обрабатывает None/""/NaN)"""
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

def normalize_task_row(line: str, row: Dict[str, Any], sap_by_code: Dict) -> Dict[str, Any]:
    """Нормализация строки задания: заполняем вычисляемые поля"""
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
    
    disc = to_int_safe(normalized.get('discount_percent'), 0)
    base_norm = float(normalized.get('norm_per_employee', 0))
    normalized['norm_with_discount'] = int(round(base_norm * (1 - disc/100)))
    normalized['qty_made'] = to_int_safe(normalized.get('qty_made'), 0)
    normalized['count_by_norm'] = bool(normalized.get('count_by_norm'))
    normalized['discount_percent'] = disc
    normalized['sap_code'] = code or ""
    
    return normalized

def extract_user_fields(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Извлечение пользовательских полей из строк"""
    keys = ("sap_code","qty_made","discount_percent","count_by_norm")
    result = []
    for r in rows or []:
        result.append({k: (r.get(k) if k != 'discount_percent' else to_int_safe(r.get(k), 0)) for k in keys})
    return result

def ensure_row_ids(list_name: str, session_state: Dict):
    """Обеспечение уникальных row_id для строк"""
    seq_key = f"{list_name}_seq"
    if seq_key not in session_state:
        session_state[seq_key] = 0
    
    lst = session_state.get(list_name, [])
    for row in lst:
        if 'row_id' not in row:
            session_state[seq_key] += 1
            row['row_id'] = session_state[seq_key]

def next_seq(list_name: str, session_state: Dict) -> int:
    """Получение следующего порядкового номера"""
    seq_key = f"{list_name}_seq"
    if seq_key not in session_state:
        session_state[seq_key] = 0
    session_state[seq_key] += 1
    return session_state[seq_key]

def get_available_sap_codes_for_line(line: str, sap_by_code: Dict) -> List[str]:
    """Получение доступных SAP кодов для конкретной линии"""
    available = []
    for code, item in sap_by_code.items():
        if line == 'A3' and item.get('norm_a3_per_employee') is not None:
            available.append(code)
        elif line == 'A4' and item.get('norm_a4_per_employee') is not None:
            available.append(code)
    return available

def calculate_line_statistics(line_emps: List[Dict]) -> Dict[str, Any]:
    """Расчет статистики по линиям"""
    line_counts = {"A3": 0, "A4": 0}
    total_hours = {"A3": 0.0, "A4": 0.0}
    
    for emp in line_emps:
        line = emp.get('line', 'A3')
        if line in line_counts:
            line_counts[line] += 1
            work_time = emp.get('work_time', 0.0)
            if work_time is not None:
                total_hours[line] += float(work_time)
    
    return {
        "counts": line_counts,
        "hours": total_hours,
        "total_count": line_counts["A3"] + line_counts["A4"],
        "total_hours": total_hours["A3"] + total_hours["A4"]
    }

def calculate_product_summary(tasks_A3: List[Dict], tasks_A4: List[Dict], line_hours: Dict[str, float]) -> List[Dict]:
    """Расчет итоговых нормативов по изделиям"""
    product_summary = {}
    
    for line_name, tasks in [("A3", tasks_A3), ("A4", tasks_A4)]:
        for task in tasks:
            sap_code = task.get('sap_code', '')
            if not sap_code:
                continue
                
            product_name = task.get('product_name', '')
            norm_with_discount = task.get('norm_with_discount', 0)
            count_by_norm = task.get('count_by_norm', True)
            
            key = f"{sap_code} - {product_name}"
            if key not in product_summary:
                product_summary[key] = {"A3": 0, "A4": 0, "qty_A3": 0, "qty_A4": 0}
            
            if not count_by_norm:
                # инвертированная логика: если НЕ считать по норме, то используем формулу
                # (норма_со_скидкой / 12) * часы_сотрудников_на_линии
                if line_hours[line_name] > 0:
                    product_summary[key][line_name] += (norm_with_discount / 12) * line_hours[line_name]
            else:
                # если считаем по норме, то просто количество изготовлено
                qty_made = task.get('qty_made', 0)
                product_summary[key][line_name] += qty_made
            
            # Всегда добавляем количество изготовленного (для отображения)
            qty_made = task.get('qty_made', 0)
            if line_name == "A3":
                product_summary[key]["qty_A3"] += qty_made
            else:
                product_summary[key]["qty_A4"] += qty_made
    
    # Преобразуем в список для отображения
    summary_data = []
    for product, lines in product_summary.items():
        total_norm = lines["A3"] + lines["A4"]
        total_qty = lines["qty_A3"] + lines["qty_A4"]
        summary_data.append({
            "Изделие": product,
            "A3 (норма)": int(round(lines["A3"])),
            "A4 (норма)": int(round(lines["A4"])), 
            "Итого (норма)": int(round(total_norm)),
            "A3 (изгот.)": int(lines["qty_A3"]),
            "A4 (изгот.)": int(lines["qty_A4"]),
            "Итого (изгот.)": int(total_qty)
        })
    
    return summary_data
