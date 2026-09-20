import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { BehaviorSubject, Observable, forkJoin } from 'rxjs';
import { map, shareReplay, switchMap, tap } from 'rxjs/operators';

import {
  CodingBoard,
  CodingStory,
  ContextEntry,
  Dashboard,
  DomainReport,
  PetPresence,
  PetPresenceName,
  Project,
  ReportingOverview,
  ReportingWindow,
  SentinelSnapshot,
  WorkItem,
} from './models';

interface ListResponse<T> {
  items: T[];
}

interface ItemResponse<T> {
  item: T;
}

@Injectable({ providedIn: 'root' })
export class SentinelApiService {
  private readonly http = inject(HttpClient);
  private readonly refreshRequest = new BehaviorSubject<void>(undefined);

  readonly snapshot$: Observable<SentinelSnapshot> = this.refreshRequest.pipe(
    switchMap(() =>
      forkJoin({
        dashboard: this.http.get<Dashboard>('/api/sentinel/dashboard'),
        petPresence: this.http.get<PetPresence>('/api/sentinel/pet-presence'),
        programs: this.http.get<ListResponse<SentinelSnapshot['programs'][number]>>('/api/programs'),
        projects: this.http.get<ListResponse<Project>>('/api/projects'),
        workItems: this.http.get<ListResponse<WorkItem>>('/api/work-items'),
        reporting: this.http.get<ReportingOverview>('/api/reporting/overview'),
      }),
    ),
    map(({ dashboard, petPresence, programs, projects, workItems, reporting }) =>
      ({
        dashboard,
        petPresence,
        programs: programs.items,
        projects: projects.items,
        workItems: workItems.items,
        reporting,
      }),
    ),
    shareReplay({ bufferSize: 1, refCount: true }),
  );

  refresh(): void {
    this.refreshRequest.next();
  }

  selectPet(pet: PetPresenceName): Observable<PetPresence> {
    return this.http
      .post<PetPresence>('/api/sentinel/pet-presence', { pet })
      .pipe(tap(() => this.refresh()));
  }

  createWorkItem(payload: Record<string, unknown>): Observable<ItemResponse<WorkItem>> {
    return this.http
      .post<ItemResponse<WorkItem>>('/api/work-items', payload)
      .pipe(tap(() => this.refresh()));
  }

  updateWorkItem(id: string, payload: Record<string, unknown>): Observable<ItemResponse<WorkItem>> {
    return this.http
      .patch<ItemResponse<WorkItem>>(`/api/work-items/${id}`, payload)
      .pipe(tap(() => this.refresh()));
  }

  updateProject(id: string, payload: Record<string, unknown>): Observable<ItemResponse<Project>> {
    return this.http
      .patch<ItemResponse<Project>>(`/api/projects/${id}`, payload)
      .pipe(tap(() => this.refresh()));
  }

  addNote(payload: Record<string, unknown>): Observable<ItemResponse<ContextEntry>> {
    return this.http
      .post<ItemResponse<ContextEntry>>('/api/notes', payload)
      .pipe(tap(() => this.refresh()));
  }

  addCheckIn(payload: Record<string, unknown>): Observable<ItemResponse<ContextEntry>> {
    return this.http
      .post<ItemResponse<ContextEntry>>('/api/check-ins', payload)
      .pipe(tap(() => this.refresh()));
  }

  addUsageEntry(payload: Record<string, unknown>): Observable<ItemResponse<unknown>> {
    return this.http.post<ItemResponse<unknown>>('/api/usage-entries', payload);
  }

  getDomainReport(domain: string, window: ReportingWindow): Observable<DomainReport> {
    return this.http.get<DomainReport>(`/api/reporting/domains/${domain}`, {
      params: { window },
    });
  }

  generateDomainInsight(
    domain: string,
    window: ReportingWindow,
    refresh = false,
  ): Observable<DomainReport> {
    return this.http.post<DomainReport>(`/api/reporting/domains/${domain}/insight`, {
      window,
      refresh,
    });
  }

  recordReportFeedback(payload: Record<string, unknown>): Observable<ItemResponse<unknown>> {
    return this.http.post<ItemResponse<unknown>>('/api/reporting/feedback', payload);
  }

  refreshCodingBoard(): Observable<CodingBoard> {
    return this.http.post<CodingBoard>('/api/coding/jira/refresh', {});
  }

  createCodingStory(title: string, description: string): Observable<ItemResponse<CodingStory>> {
    return this.http.post<ItemResponse<CodingStory>>('/api/coding/jira/issues', { title, description });
  }

  getCodingStory(key: string): Observable<ItemResponse<CodingStory>> {
    return this.http.get<ItemResponse<CodingStory>>(`/api/coding/jira/issues/${key}`);
  }

  beginCodingStory(
    key: string,
    surface: 'APP' | 'TERMINAL',
    localProjectId?: string,
    attachmentIds?: string[],
  ): Observable<{ item: CodingStory; handoff: Record<string, unknown> }> {
    return this.http.post<{ item: CodingStory; handoff: Record<string, unknown> }>(
      `/api/coding/jira/issues/${key}/begin`,
      { ...(localProjectId ? { local_project_id: localProjectId } : {}), surface, ...(attachmentIds ? { attachment_ids: attachmentIds } : {}) },
    );
  }

  selectCodingAttachments(key: string, attachmentIds: string[]): Observable<ItemResponse<CodingStory>> {
    return this.http.post<ItemResponse<CodingStory>>(`/api/coding/jira/issues/${key}/attachments/selection`, { attachment_ids: attachmentIds });
  }

  uploadCodingAttachment(key: string, file: File): Observable<ItemResponse<CodingStory>> {
    const body = new FormData();
    body.append('artifact', file, file.name);
    return this.http.post<ItemResponse<CodingStory>>(`/api/coding/jira/issues/${key}/attachments`, body);
  }

  runCodeCrawler(
    key: string,
    localProjectId: string,
  ): Observable<{ item: CodingStory; crawl: Record<string, unknown> }> {
    return this.http.post<{ item: CodingStory; crawl: Record<string, unknown> }>(
      `/api/coding/jira/issues/${key}/codecrawler`,
      { local_project_id: localProjectId },
    );
  }
}
