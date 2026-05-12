import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable, BehaviorSubject } from 'rxjs';
import { tap } from 'rxjs/operators';

export interface UISettings {
  test_recap_threshold: number;
  verbose_tests: boolean;
  verbose_rules: boolean;
  export_format: 'json' | 'csv' | 'html';
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
              test_recap_threshold: 100,
              verbose_tests: false,
              verbose_rules: false,
              export_format: 'json',
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
   * Get verbose_tests flag
   */
  isVerboseTests(): boolean {
    return this.appSettingsSubject.value?.ui.verbose_tests ?? false;
  }

  /**
   * Get verbose_rules flag
   */
  isVerboseRules(): boolean {
    return this.appSettingsSubject.value?.ui.verbose_rules ?? false;
  }

  /**
   * Get export format (json | csv | html)
   */
  getExportFormat(): 'json' | 'csv' | 'html' {
    return this.appSettingsSubject.value?.ui.export_format ?? 'json';
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

