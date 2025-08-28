from pydantic import BaseModel, field_validator, ConfigDict

class TaskModel(BaseModel):
    """Модель задания по линии"""
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
    """Модель линейного сотрудника"""
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
    """Модель роли поддержки (старший/ремонтник)"""
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
