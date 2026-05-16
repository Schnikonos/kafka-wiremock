import { Pipe, PipeTransform } from '@angular/core';

/**
 * Serialises a value to a compact JSON string and truncates it to `maxLen`
 * characters (default 120), appending "…" when truncated.
 * Null / undefined is rendered as "—".
 */
@Pipe({ name: 'truncJson', standalone: true, pure: true })
export class TruncJsonPipe implements PipeTransform {
  transform(value: unknown, maxLen = 120): string {
    if (value === null || value === undefined) {
      return '—';
    }
    let s: string;
    if (typeof value === 'string') {
      s = value;
    } else {
      try {
        s = JSON.stringify(value);
      } catch {
        s = String(value);
      }
    }
    return s.length > maxLen ? s.slice(0, maxLen) + '…' : s;
  }
}

