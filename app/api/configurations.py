from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List, Dict, Any

from ..core.database import get_database
from ..core.auth import get_current_user
from ..models.configuration import Configuration
from ..models.user import User
from ..schemas.configuration import ConfigurationUpdate, ConfigurationResponse

router = APIRouter()

@router.get("/", response_model=List[ConfigurationResponse])
async def get_configurations(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_database)
):
    """Get all configurations"""
    
    result = await db.execute(select(Configuration))
    configurations = result.scalars().all()
    
    return configurations

@router.get("/{key}", response_model=ConfigurationResponse)
async def get_configuration(
    key: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_database)
):
    """Get a specific configuration by key"""
    
    result = await db.execute(
        select(Configuration).where(Configuration.key == key)
    )
    config = result.scalar_one_or_none()
    
    if not config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Configuration not found"
        )
    
    return config

@router.put("/{key}", response_model=ConfigurationResponse)
async def update_configuration(
    key: str,
    config_data: ConfigurationUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_database)
):
    """Update or create a configuration"""
    
    result = await db.execute(
        select(Configuration).where(Configuration.key == key)
    )
    config = result.scalar_one_or_none()
    
    if config:
        # Update existing
        config.value = config_data.value
        if config_data.description:
            config.description = config_data.description
    else:
        # Create new
        config = Configuration(
            key=key,
            value=config_data.value,
            description=config_data.description
        )
        db.add(config)
    
    await db.commit()
    await db.refresh(config)
    
    return config

@router.delete("/{key}")
async def delete_configuration(
    key: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_database)
):
    """Delete a configuration"""
    
    result = await db.execute(
        select(Configuration).where(Configuration.key == key)
    )
    config = result.scalar_one_or_none()
    
    if not config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Configuration not found"
        )
    
    await db.delete(config)
    await db.commit()
    
    return {"message": f"Configuration '{key}' deleted"}

@router.get("/trading/limits")
async def get_trading_limits(
    current_user: User = Depends(get_current_user)
):
    """Get current trading limits"""
    from ..core.config import settings
    
    return {
        'max_position_size': settings.MAX_POSITION_SIZE,
        'max_daily_loss': settings.MAX_DAILY_LOSS,
        'max_total_exposure': settings.MAX_TOTAL_EXPOSURE,
        'confidence_threshold': settings.CONFIDENCE_THRESHOLD,
        'kelly_fraction': settings.KELLY_FRACTION
    }

@router.post("/trading/limits")
async def update_trading_limits(
    limits: Dict[str, float],
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_database)
):
    """Update trading limits (stored as configurations)"""
    
    valid_keys = {
        'max_position_size',
        'max_daily_loss', 
        'max_total_exposure',
        'confidence_threshold',
        'kelly_fraction'
    }
    
    updated_configs = []
    
    for key, value in limits.items():
        if key not in valid_keys:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid configuration key: {key}"
            )
        
        # Validate value ranges
        if key == 'confidence_threshold' and not (0 <= value <= 1):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Confidence threshold must be between 0 and 1"
            )
        
        if key == 'kelly_fraction' and not (0 <= value <= 1):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Kelly fraction must be between 0 and 1"
            )
        
        if value < 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"{key} must be non-negative"
            )
        
        # Update or create configuration
        result = await db.execute(
            select(Configuration).where(Configuration.key == key)
        )
        config = result.scalar_one_or_none()
        
        if config:
            config.value = str(value)
        else:
            config = Configuration(
                key=key,
                value=str(value),
                description=f"Trading limit: {key}"
            )
            db.add(config)
        
        updated_configs.append(key)
    
    await db.commit()
    
    return {
        'message': 'Trading limits updated',
        'updated_configurations': updated_configs
    }
