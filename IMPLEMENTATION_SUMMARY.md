# Implementation Summary: Configurable Test Recap Threshold

## Overview
Implemented a configurable global application settings system that allows users to control when the test execution recap popup is shown. The configuration is stored in a JSON file that survives container recreation.

## What Was Implemented

### Backend (Python)

#### 1. **App Settings Loader** (`src/config/app_settings.py`)
- Loads settings from `config/app-settings.json`
- Automatically reloads every 30 seconds (hot-reload)
- Thread-safe settings management
- Validates configuration with sensible defaults
- Supports future extensibility with nested settings structure

#### 2. **API Endpoints** (`src/api/app_settings.py`)
- `GET /api/app-settings` - Retrieve current settings
- `POST /api/app-settings` - Update and save settings
- Validation and error handling
- Proper HTTP status codes and error messages

#### 3. **Integration in main.py**
- Initialized AppSettingsLoader at startup
- Added to FastAPI lifespan (startup/shutdown)
- Registered API endpoints
- Thread-safe cleanup on shutdown

#### 4. **Default Configuration** (`config/app-settings.json`)
```json
{
  "ui": {
    "test_recap_threshold": 100
  }
}
```

### Frontend (Angular)

#### 1. **AppConfigService** (`ui/src/app/core/services/app-config.service.ts`)
- Fetches settings once on app initialization
- Caches settings in BehaviorSubject for reactive updates
- Provides convenient getter methods
- Handles API errors gracefully with defaults
- Observable stream for components that need reactive updates

#### 2. **AppSettingsDialog Component** (`ui/src/app/features/settings/app-settings-dialog.component.ts`)
- Material dialog for viewing/editing settings
- Form validation (threshold must be >= 0)
- Save/Cancel actions
- User-friendly explanatory text
- Displays file location where settings are persisted
- Success/error feedback via snackbar

#### 3. **Updated TestsComponent** (`ui/src/app/features/tests/tests.component.ts`)
- Injected AppConfigService
- Modified `runSelected()` method to:
  - Fetch the threshold from settings
  - Only show recap popup if total executions > threshold
  - Execute immediately without confirmation if below threshold
  - Maintains non-blocking behavior

#### 4. **Updated LayoutComponent** (`ui/src/app/layouts/main-layout/main-layout.component.ts`)
- Added Settings button (⚙️ icon) to top-right of toolbar
- Positioned between flex-spacer and health status indicator
- Opens AppSettingsDialog on click
- Added MatDialogModule to imports

### Configuration & Documentation

#### 1. **Updated README.md**
- New "Application Settings" section
- Configuration file location and format
- Configuration options table
- Three methods to manage settings:
  - Via Web UI
  - Via JSON file
  - Via API
- Code examples for each method
- Updated API Reference table with new endpoints

## How It Works

### User Flow

1. **First Time**: User launches app
   - AppConfigService fetches settings from API (default: threshold=100)
   - Settings cached in service

2. **Running Tests**:
   - When user clicks "Run Selected" with, say, 200 total executions
   - TestsComponent checks threshold (100)
   - Since 200 > 100, recap popup is shown
   - If user had 50 executions, no popup shown (instant execution)

3. **Changing Settings**:
   - User clicks Settings button (⚙️) in toolbar
   - Dialog opens with current threshold value
   - User updates value (e.g., to 50)
   - User clicks "Save Settings"
   - AppConfigService calls API
   - API saves to `config/app-settings.json`
   - Service updates cached value
   - Dialog closes with success message

4. **Container Recreation**:
   - If `/config` is mounted as a volume (standard Docker Compose setup)
   - Settings survive container destruction/creation
   - On restart, AppSettingsLoader reads the persisted JSON file

### Configuration Persistence

- **File Location**: `/config/app-settings.json`
- **Hot-Reload**: Changes detected every 30 seconds
- **Volume Mount**: Essential for persistence across restarts
  ```yaml
  volumes:
    - ./config:/config  # This folder is where settings are stored
  ```

## Technical Details

### Thread Safety
- All access to settings in backend is protected by locks
- Frontend uses Angular's async pipe and observables
- No race conditions in multi-threaded environment

### Error Handling
- Missing config file: Uses defaults (threshold=100)
- Invalid JSON: Logs error and uses defaults
- Negative threshold: Validated and rejected with 400 error
- Backend unavailable: Frontend uses defaults (no blocking)

### Backward Compatibility
- Fully backward compatible
- No breaking changes to existing APIs
- Optional feature (works fine if file doesn't exist)

## File Structure Summary

```
src/
  config/
    ├── app_settings.py          (NEW: AppSettingsLoader class)
    └── ...existing files...
  api/
    ├── app_settings.py          (NEW: API endpoints)
    └── ...existing files...
  main.py                         (UPDATED: Initialize loader, add router)

ui/src/app/
  core/services/
    ├── app-config.service.ts    (NEW: Frontend settings service)
    └── ...existing files...
  features/
    ├── tests/
    │   └── tests.component.ts   (UPDATED: Use threshold)
    └── settings/
        └── app-settings-dialog.component.ts  (NEW: Settings UI)
  layouts/main-layout/
    └── main-layout.component.ts (UPDATED: Add settings button)

config/
  └── app-settings.json          (NEW: Default config file)
```

## Testing

All Python files have been syntax-verified:
```bash
✓ python3 -m py_compile src/config/app_settings.py
✓ python3 -m py_compile src/api/app_settings.py
✓ python3 -m py_compile src/main.py
```

## Future Enhancements

The architecture supports easy expansion:
- Add more settings under `ui` object (e.g., `ui.disable_recap`, `ui.max_history`)
- Add new top-level settings objects (e.g., `kafka`, `logging`)
- Settings are automatically hot-reloaded without code changes
- API endpoints already support any settings structure

## Usage Examples

### Change threshold to always show recap (even for 1 execution)
```json
{
  "ui": {
    "test_recap_threshold": 0
  }
}
```

### Change threshold to rarely show (only for 500+)
```json
{
  "ui": {
    "test_recap_threshold": 500
  }
}
```

### Via API
```bash
curl -X POST http://localhost:8000/api/app-settings \
  -H "Content-Type: application/json" \
  -d '{"ui": {"test_recap_threshold": 200}}'
```

---

**Implementation Date**: May 9, 2026
**Status**: ✅ Complete and ready for testing

