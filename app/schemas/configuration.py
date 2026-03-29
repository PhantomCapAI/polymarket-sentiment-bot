from pydantic import BaseModel
from typing import Optional
from datetime import datetime

class ConfigurationUpdate(BaseModel):
    value: str
    description: Optional[str] = None

class ConfigurationResponse(BaseModel):
    id: str
    key: str
    value: str
    description: Optional[str]
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True
