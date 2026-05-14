import { Injectable } from '@angular/core';
import { LoadReport } from '../models';

/** Persists load-test reports in browser localStorage (up to MAX_ENTRIES). */
@Injectable({ providedIn: 'root' })
export class LoadHistoryService {
  private readonly STORAGE_KEY = 'load_test_reports';
  private readonly MAX_ENTRIES = 15;

  /** Save (or overwrite) a report entry. Falls back to storing without buckets if quota is exceeded. */
  saveReport(report: LoadReport): void {
    const history = this.getAllReports();
    // Replace existing entry with same job_id, or prepend
    const filtered = history.filter(r => r.job_id !== report.job_id);
    filtered.unshift(report);
    const trimmed = filtered.slice(0, this.MAX_ENTRIES);

    try {
      localStorage.setItem(this.STORAGE_KEY, JSON.stringify(trimmed));
    } catch (_e) {
      // Quota exceeded — try again without per-bucket data
      try {
        const slim = trimmed.map(r => ({ ...r, buckets: [] }));
        localStorage.setItem(this.STORAGE_KEY, JSON.stringify(slim));
      } catch (_e2) {
        console.warn('[LoadHistoryService] localStorage quota exceeded — report not saved.');
      }
    }
  }

  getAllReports(): LoadReport[] {
    try {
      const raw = localStorage.getItem(this.STORAGE_KEY);
      return raw ? (JSON.parse(raw) as LoadReport[]) : [];
    } catch {
      return [];
    }
  }

  getReport(jobId: string): LoadReport | null {
    return this.getAllReports().find(r => r.job_id === jobId) ?? null;
  }

  deleteReport(jobId: string): void {
    const history = this.getAllReports().filter(r => r.job_id !== jobId);
    try {
      localStorage.setItem(this.STORAGE_KEY, JSON.stringify(history));
    } catch { /* ignore */ }
  }

  clearAll(): void {
    localStorage.removeItem(this.STORAGE_KEY);
  }
}

