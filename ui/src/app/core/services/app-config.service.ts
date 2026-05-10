import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable, BehaviorSubject } from 'rxjs';
import { tap } from 'rxjs/operators';

export interface UISettings {
  test_recap_threshold: number;
}

export interface AppSettings {
  ui: UISettings;
}

@Injectable({
  providedIn: 'root'
})
export class AppConfigService {
  private apiUrl = '/api';
  private appSettingsSubject = new BehaviorSubject<AppSettings | null>(null);
  public appSettings$ = this.appSettingsSubject.asObservable();

  constructor(private http: HttpClient) {
    this.loadSettings();
  }

  /**
   * Load application settings from API
   */
  private loadSettings(): void {
    this.http.get<AppSettings>(`${this.apiUrl}/app-settings`)
      .pipe(
        tap(settings => {
          this.appSettingsSubject.next(settings);
        })
      )
      .subscribe({
        error: (err) => {
          console.warn('Failed to load app settings, using defaults', err);
          // Use defaults on error
          this.appSettingsSubject.next({
            ui: {
              test_recap_threshold: 100
            }
          });
        }
      });
  }

  /**
   * Get current settings synchronously (may be null if not loaded yet)
   */
  getSettings(): AppSettings | null {
    return this.appSettingsSubject.value;
  }

  /**
   * Get test recap threshold
   */
  getTestRecapThreshold(): number {
    const settings = this.appSettingsSubject.value;
    return settings?.ui.test_recap_threshold ?? 100;
  }

  /**
   * Update application settings
   */
  updateSettings(settings: AppSettings): Observable<AppSettings> {
    return this.http.post<AppSettings>(`${this.apiUrl}/app-settings`, settings)
      .pipe(
        tap(updatedSettings => {
          this.appSettingsSubject.next(updatedSettings);
        })
      );
  }
}

