"""
Application Settings API endpoints.
Provides GET/POST endpoints for managing application-wide settings.
"""
import logging
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

logger = logging.getLogger(__name__)

router = APIRouter(tags=["app-settings"])

# Global reference to app settings loader (set by main.py)
app_settings_loader: Optional['AppSettingsLoader'] = None


def set_app_settings_loader(loader: 'AppSettingsLoader') -> None:
    """Set the global app settings loader reference."""
    global app_settings_loader
    app_settings_loader = loader


class UISettingsRequest(BaseModel):
    """UI settings request model."""
    test_recap_threshold: int = 100


class AppSettingsRequest(BaseModel):
    """Application settings request model."""
    ui: UISettingsRequest = UISettingsRequest()


class AppSettingsResponse(BaseModel):
    """Application settings response model."""
    ui: UISettingsRequest


@router.get("/app-settings", response_model=AppSettingsResponse)
async def get_app_settings():
    """
    Get current application settings.

    Returns:
        AppSettingsResponse: Current application settings
    """
    if not app_settings_loader:
        raise HTTPException(status_code=503, detail="App settings loader not initialized")

    settings = app_settings_loader.get_settings()
    return AppSettingsResponse(
        ui=UISettingsRequest(
            test_recap_threshold=settings.ui.test_recap_threshold
        )
    )


@router.post("/app-settings", response_model=AppSettingsResponse)
async def update_app_settings(request: AppSettingsRequest):
    """
    Update application settings.

    Args:
        request: Updated application settings

    Returns:
        AppSettingsResponse: Updated settings
    """
    if not app_settings_loader:
        raise HTTPException(status_code=503, detail="App settings loader not initialized")

    try:
        # Validate threshold
        if request.ui.test_recap_threshold < 0:
            raise ValueError("test_recap_threshold must be >= 0")

        # Import AppSettings here to avoid circular imports
        from ..config.app_settings import AppSettings, UISettings

        # Create new settings object
        new_settings = AppSettings(
            ui=UISettings(
                test_recap_threshold=request.ui.test_recap_threshold
            )
        )

        # Update and save
        app_settings_loader.update_settings(new_settings)

        logger.info(f"App settings updated: {new_settings}")

        return AppSettingsResponse(
            ui=UISettingsRequest(
                test_recap_threshold=new_settings.ui.test_recap_threshold
            )
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error updating app settings: {e}")
        raise HTTPException(status_code=500, detail="Failed to update app settings")

