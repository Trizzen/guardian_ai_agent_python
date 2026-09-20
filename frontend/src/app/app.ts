import { CommonModule } from '@angular/common';
import { ChangeDetectorRef, Component, DestroyRef, OnInit, inject } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { HttpErrorResponse } from '@angular/common/http';
import { BehaviorSubject, combineLatest, finalize, map, tap } from 'rxjs';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';

import {
  Assignee,
  CheckInStatus,
  CodingBoard,
  CodingStory,
  CodingStoryStatus,
  DomainReport,
  PetPresenceName,
  Priority,
  Program,
  Project,
  ReportingWindow,
  SentinelSnapshot,
  Status,
  TargetSelection,
  TargetType,
  WorkItem,
} from './models';
import { SentinelApiService } from './sentinel-api.service';

interface WorkItemForm {
  id: string | null;
  title: string;
  description: string;
  target_type: TargetType;
  target_id: string;
  priority: Priority;
  status: Status;
  next_action: string;
  notes: string;
  human_check_in_status: CheckInStatus;
  execution_assignee: Assignee;
  scheduled_for: string;
  review_after: string;
}

@Component({
  selector: 'app-root',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './app.html',
  styleUrl: './app.css',
})
export class AppComponent implements OnInit {
  private readonly api = inject(SentinelApiService);
  private readonly destroyRef = inject(DestroyRef);
  private readonly changeDetector = inject(ChangeDetectorRef);
  private readonly selection = new BehaviorSubject<TargetSelection>({
    type: 'program',
    id: 'daily-command',
  });

  readonly statuses: Status[] = ['backlog', 'ready', 'active', 'waiting', 'completed'];
  readonly priorities: Priority[] = ['low', 'normal', 'high', 'critical'];
  readonly checkInStatuses: CheckInStatus[] = ['none', 'requested', 'awaiting_direction'];
  readonly assignees: Assignee[] = ['king_trizzen', 'jaza', 'star_reborn'];
  readonly reportWindows: { id: ReportingWindow; label: string }[] = [
    { id: 'today', label: 'Today' },
    { id: 'week', label: 'Week' },
    { id: 'month', label: 'Month' },
    { id: 'ytd', label: 'YTD' },
    { id: 'all', label: 'All' },
  ];

  currentSnapshot: SentinelSnapshot | null = null;
  readonly vm$ = combineLatest([
    this.api.snapshot$.pipe(tap((snapshot) => (this.currentSnapshot = snapshot))),
    this.selection,
  ]).pipe(
    map(([snapshot, selected]) => ({
      ...snapshot,
      selected,
      selectedEntity: this.findEntity(snapshot, selected),
      contextItems: snapshot.workItems.filter(
        (item) => item.target_type === selected.type && item.target_id === selected.id,
      ),
    })),
  );

  showWorkEditor = false;
  saving = false;
  petSwitching: PetPresenceName | null = null;
  formError = '';
  successMessage = '';
  workForm = this.emptyWorkForm();
  report: DomainReport | null = null;
  reportWindow: ReportingWindow = 'week';
  reportLoading = false;
  insightLoading = false;
  reportError = '';
  feedbackSent: boolean | null = null;
  private reportRequestSequence = 0;
  codingBoard: CodingBoard | null = null;
  codingLoading = false;
  codingError = '';
  selectedStory: CodingStory | null = null;
  storyLoading = false;
  startingStory = '';
  crawlingStory = '';
  uploadingStory = '';
  repositorySelections: Record<string, string> = {};
  showJiraEditor = false;
  jiraForm = { title: '', description: '' };

  captureKind: 'note' | 'check_in' = 'note';
  captureBody = '';
  captureCheckInStatus: CheckInStatus = 'requested';

  usageOpen = false;
  usageForm = {
    provider_tool: 'Codex',
    token_estimate: null as number | null,
    cost_estimate: null as number | null,
    notes: '',
  };

  ngOnInit(): void {
    this.loadReport('daily-command');
  }

  selectContext(type: TargetType, id: string): void {
    this.selection.next({ type, id });
    if (type === 'program') {
      this.loadReport(id);
      if (id === 'coding-command') {
        this.refreshCodingBoard();
      }
    } else {
      this.report = null;
      this.reportError = '';
    }
    document.querySelector('.focus-panel')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  selectReportWindow(window: ReportingWindow): void {
    this.reportWindow = window;
    if (this.selection.value.type === 'program') {
      this.loadReport(this.selection.value.id);
    }
  }

  loadReport(domain: string): void {
    const requestId = ++this.reportRequestSequence;
    this.reportLoading = true;
    this.reportError = '';
    this.feedbackSent = null;
    this.api
      .getDomainReport(domain, this.reportWindow)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (report) => {
          if (requestId !== this.reportRequestSequence) {
            return;
          }
          this.report = report;
          this.reportLoading = false;
          this.changeDetector.markForCheck();
        },
        error: (error: HttpErrorResponse) => {
          if (requestId !== this.reportRequestSequence) {
            return;
          }
          this.report = null;
          this.reportError = this.describeError(error);
          this.reportLoading = false;
          this.changeDetector.markForCheck();
        },
      });
  }

  generateInsight(refresh = false): void {
    if (this.selection.value.type !== 'program') {
      return;
    }
    this.insightLoading = true;
    this.reportError = '';
    this.api
      .generateDomainInsight(this.selection.value.id, this.reportWindow, refresh)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (report) => {
          this.report = report;
          this.insightLoading = false;
          if (report.insight_error) {
            this.reportError = report.insight_error.message;
          }
          this.changeDetector.markForCheck();
        },
        error: (error: HttpErrorResponse) => {
          this.reportError = this.describeError(error);
          this.insightLoading = false;
          this.changeDetector.markForCheck();
        },
      });
  }

  sendReportFeedback(useful: boolean): void {
    const insight = this.report?.insight;
    if (!insight || !this.report) {
      return;
    }
    this.api
      .recordReportFeedback({
        report_id: insight.report_id,
        domain: this.report.domain,
        generated_at: insight.generated_at,
        useful,
        note: '',
      })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: () => {
          this.feedbackSent = useful;
          this.flash(useful ? 'Luna insight marked useful.' : 'Adjustment signal recorded for review.');
        },
        error: (error: HttpErrorResponse) => this.flash(this.describeError(error), true),
      });
  }

  openAdd(type?: TargetType, id?: string): void {
    const selected = this.selection.value;
    this.workForm = this.emptyWorkForm(type ?? selected.type, id ?? selected.id);
    this.formError = '';
    this.showWorkEditor = true;
  }

  openAddHere(type: TargetType, id: string): void {
    if (type === 'program' && id === 'coding-command') {
      this.jiraForm = { title: '', description: '' };
      this.formError = '';
      this.showJiraEditor = true;
      return;
    }
    this.openAdd(type, id);
  }

  closeJiraEditor(): void {
    if (!this.saving) {
      this.showJiraEditor = false;
    }
  }

  saveJiraStory(): void {
    if (!this.jiraForm.title.trim() || !this.jiraForm.description.trim()) {
      this.formError = 'Title and full description are required.';
      return;
    }
    this.saving = true;
    this.formError = '';
    this.api
      .createCodingStory(this.jiraForm.title, this.jiraForm.description)
      .pipe(finalize(() => (this.saving = false)), takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: ({ item }) => {
          this.showJiraEditor = false;
          this.selectedStory = item;
          this.flash(`${item.jira_key} created in Sprint 0.`);
          this.refreshCodingBoard();
        },
        error: (error: HttpErrorResponse) => (this.formError = this.describeError(error)),
      });
  }

  refreshCodingBoard(): void {
    if (this.codingLoading) {
      return;
    }
    this.codingLoading = true;
    this.codingError = '';
    this.api
      .refreshCodingBoard()
      .pipe(finalize(() => (this.codingLoading = false)), takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (board) => {
          this.codingBoard = board;
          if (this.selectedStory) {
            this.selectedStory =
              board.stories.find((story) => story.jira_key === this.selectedStory?.jira_key) ??
              this.selectedStory;
          }
          this.changeDetector.markForCheck();
        },
        error: (error: HttpErrorResponse) => {
          this.codingBoard = null;
          this.codingError = this.describeError(error);
          this.changeDetector.markForCheck();
        },
      });
  }

  storiesFor(status: CodingStoryStatus): CodingStory[] {
    return this.codingBoard?.stories.filter((story) => story.status === status) ?? [];
  }

  selectStory(story: CodingStory): void {
    this.selectedStory = story;
    this.storyLoading = true;
    this.codingError = '';
    this.api
      .getCodingStory(story.jira_key)
      .pipe(finalize(() => (this.storyLoading = false)), takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: ({ item }) => (this.selectedStory = item),
        error: (error: HttpErrorResponse) => (this.codingError = this.describeError(error)),
      });
  }

  beginStory(story: CodingStory, surface: 'APP' | 'TERMINAL'): void {
    if (story.status === 'in_review' || story.status === 'done' || this.startingStory) {
      return;
    }
    const localProjectId = story.local_project_id || this.repositorySelections[story.jira_key];
    if (!story.local_repository_path && !localProjectId) {
      this.selectedStory = story;
      this.codingError = 'Choose a known Jaza repository before beginning this story.';
      return;
    }
    this.startingStory = story.jira_key;
    this.codingError = '';
    this.api
      .beginCodingStory(story.jira_key, surface, localProjectId || undefined, story.attachments.attachments.filter((attachment) => attachment.selected).map((attachment) => attachment.attachment_id))
      .pipe(
        finalize(() => {
          this.startingStory = '';
          this.changeDetector.markForCheck();
        }),
        takeUntilDestroyed(this.destroyRef),
      )
      .subscribe({
        next: ({ item }) => {
          this.selectedStory = item;
          if (this.codingBoard) {
            this.codingBoard = {
              ...this.codingBoard,
              stories: this.codingBoard.stories.map((current) =>
                current.jira_key === item.jira_key ? item : current,
              ),
            };
          }
          this.flash(`${item.jira_key} prepared in ${surface}; human-controlled Codex execution has not been inferred.`);
          this.changeDetector.markForCheck();
        },
        error: (error: HttpErrorResponse) => {
          this.codingError = this.describeError(error);
          this.changeDetector.markForCheck();
        },
      });
  }

  toggleAttachment(story: CodingStory, attachmentId: string, selected: boolean): void {
    const ids = story.attachments.attachments
      .filter((attachment) => attachment.selected || attachment.attachment_id === attachmentId && selected)
      .filter((attachment) => attachment.attachment_id !== attachmentId || selected)
      .map((attachment) => attachment.attachment_id);
    if (ids.length > story.attachments.limit) {
      this.codingError = `Choose at most ${story.attachments.limit} Jira attachments.`;
      return;
    }
    this.codingError = '';
    this.api.selectCodingAttachments(story.jira_key, ids).pipe(takeUntilDestroyed(this.destroyRef)).subscribe({
      next: ({ item }) => this.replaceCodingStory(item),
      error: (error: HttpErrorResponse) => (this.codingError = this.describeError(error)),
    });
  }

  uploadAttachment(story: CodingStory, event: Event): void {
    const input = event.target as HTMLInputElement;
    const file = input.files?.item(0);
    if (!file || this.uploadingStory) return;
    this.uploadingStory = story.jira_key;
    this.codingError = '';
    this.api.uploadCodingAttachment(story.jira_key, file).pipe(
      finalize(() => { this.uploadingStory = ''; input.value = ''; this.changeDetector.markForCheck(); }),
      takeUntilDestroyed(this.destroyRef),
    ).subscribe({
      next: ({ item }) => { this.replaceCodingStory(item); this.flash(`${item.jira_key} attachment uploaded to Jira; no model was invoked.`); },
      error: (error: HttpErrorResponse) => (this.codingError = this.describeError(error)),
    });
  }

  private replaceCodingStory(item: CodingStory): void {
    this.selectedStory = item;
    if (this.codingBoard) this.codingBoard = { ...this.codingBoard, stories: this.codingBoard.stories.map((current) => current.jira_key === item.jira_key ? item : current) };
    this.changeDetector.markForCheck();
  }

  runCodeCrawler(story: CodingStory): void {
    if (this.crawlingStory) {
      return;
    }
    const localProjectId = story.local_project_id || this.repositorySelections[story.jira_key];
    if (!localProjectId) {
      this.codingError = 'Choose a known Jaza repository before running CodeCrawler.';
      return;
    }
    this.crawlingStory = story.jira_key;
    this.codingError = '';
    this.api
      .runCodeCrawler(story.jira_key, localProjectId)
      .pipe(
        finalize(() => {
          this.crawlingStory = '';
          this.changeDetector.markForCheck();
        }),
        takeUntilDestroyed(this.destroyRef),
      )
      .subscribe({
        next: ({ item }) => {
          this.selectedStory = item;
          if (this.codingBoard) {
            this.codingBoard = {
              ...this.codingBoard,
              stories: this.codingBoard.stories.map((current) =>
                current.jira_key === item.jira_key ? item : current,
              ),
            };
          }
          this.flash(`${item.jira_key} CodeCrawler snapshot completed; no model was invoked.`);
          this.changeDetector.markForCheck();
        },
        error: (error: HttpErrorResponse) => {
          this.codingError = this.describeError(error);
          this.changeDetector.markForCheck();
        },
      });
  }

  async copyStoryMarkdown(story: CodingStory): Promise<void> {
    const markdown = `# ${story.jira_key} — ${story.summary}\n\n${story.markdown_description || story.description}`;
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(markdown);
      } else {
        const textarea = document.createElement('textarea');
        textarea.value = markdown;
        textarea.style.position = 'fixed';
        textarea.style.opacity = '0';
        document.body.appendChild(textarea);
        textarea.select();
        const copied = document.execCommand('copy');
        textarea.remove();
        if (!copied) {
          throw new Error('Clipboard access was denied.');
        }
      }
      this.flash(`${story.jira_key} Markdown copied; no model was invoked.`);
    } catch (error) {
      this.codingError = error instanceof Error ? error.message : 'Markdown could not be copied.';
    }
  }

  openEdit(item: WorkItem): void {
    this.workForm = {
      id: item.id,
      title: item.title,
      description: item.description,
      target_type: item.target_type,
      target_id: item.target_id,
      priority: item.priority,
      status: item.status,
      next_action: item.next_action,
      notes: item.notes,
      human_check_in_status: item.human_check_in_status,
      execution_assignee: item.execution_assignee,
      scheduled_for: this.toLocalDateTime(item.scheduled_for),
      review_after: this.toLocalDateTime(item.review_after),
    };
    this.formError = '';
    this.showWorkEditor = true;
  }

  closeWorkEditor(): void {
    if (!this.saving) {
      this.showWorkEditor = false;
    }
  }

  saveWorkItem(): void {
    if (!this.workForm.title.trim()) {
      this.formError = 'A clear title is required.';
      return;
    }
    const payload: Record<string, unknown> = {
      title: this.workForm.title,
      description: this.workForm.description,
      target_type: this.workForm.target_type,
      target_id: this.workForm.target_id,
      priority: this.workForm.priority,
      status: this.workForm.status,
      next_action: this.workForm.next_action,
      notes: this.workForm.notes,
      human_check_in_status: this.workForm.human_check_in_status,
      execution_assignee: this.workForm.execution_assignee,
      scheduled_for: this.workForm.scheduled_for || null,
      review_after: this.workForm.review_after || null,
    };
    const request = this.workForm.id
      ? this.api.updateWorkItem(this.workForm.id, payload)
      : this.api.createWorkItem(payload);

    this.saving = true;
    this.formError = '';
    request.pipe(finalize(() => (this.saving = false)), takeUntilDestroyed(this.destroyRef)).subscribe({
      next: ({ item }) => {
        this.selection.next({ type: item.target_type, id: item.target_id });
        this.showWorkEditor = false;
        this.flash(this.workForm.id ? 'Work item updated.' : 'Work item added to Jaza’s watch.');
      },
      error: (error: HttpErrorResponse) => (this.formError = this.describeError(error)),
    });
  }

  updateWorkItem(item: WorkItem, patch: Record<string, unknown>): void {
    this.api
      .updateWorkItem(item.id, patch)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: () => this.flash('Work state updated.'),
        error: (error: HttpErrorResponse) => this.flash(this.describeError(error), true),
      });
  }

  updateProject(project: Project, patch: Record<string, unknown>): void {
    this.api
      .updateProject(project.id, patch)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: () => this.flash('Project pulse updated.'),
        error: (error: HttpErrorResponse) => this.flash(this.describeError(error), true),
      });
  }

  switchPet(pet: PetPresenceName): void {
    if (this.petSwitching || this.currentSnapshot?.petPresence.selected_pet === pet) {
      return;
    }
    this.petSwitching = pet;
    this.api
      .selectPet(pet)
      .pipe(
        finalize(() => (this.petSwitching = null)),
        takeUntilDestroyed(this.destroyRef),
      )
      .subscribe({
        next: () =>
          this.flash(
            pet === 'star'
              ? 'Presence handed to Star. Current work state is unchanged.'
              : 'Jaza recalled. Star’s current work is still undisturbed.',
          ),
        error: (error: HttpErrorResponse) => this.flash(this.describeError(error), true),
      });
  }

  captureContext(): void {
    const body = this.captureBody.trim();
    if (!body) {
      this.flash('Write a note or direction first.', true);
      return;
    }
    const selected = this.selection.value;
    const payload: Record<string, unknown> = {
      target_type: selected.type,
      target_id: selected.id,
      body,
    };
    const request =
      this.captureKind === 'note'
        ? this.api.addNote(payload)
        : this.api.addCheckIn({ ...payload, check_in_status: this.captureCheckInStatus });
    request.pipe(takeUntilDestroyed(this.destroyRef)).subscribe({
      next: () => {
        this.captureBody = '';
        this.flash(this.captureKind === 'note' ? 'Note secured.' : 'Check-in placed on watch.');
      },
      error: (error: HttpErrorResponse) => this.flash(this.describeError(error), true),
    });
  }

  logUsage(): void {
    if (!this.usageForm.provider_tool.trim()) {
      this.flash('Provider or tool name is required.', true);
      return;
    }
    this.api
      .addUsageEntry({ ...this.usageForm })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: () => {
          this.usageForm = {
            provider_tool: 'Codex',
            token_estimate: null,
            cost_estimate: null,
            notes: '',
          };
          this.usageOpen = false;
          this.flash('Usage note recorded locally.');
        },
        error: (error: HttpErrorResponse) => this.flash(this.describeError(error), true),
      });
  }

  targetName(type: TargetType, id: string): string {
    if (!this.currentSnapshot) {
      return id;
    }
    return this.findEntity(this.currentSnapshot, { type, id })?.name ?? id;
  }

  contextCount(items: WorkItem[], type: TargetType, id: string): number {
    return items.filter((item) => item.target_type === type && item.target_id === id).length;
  }

  displayLabel(value: string): string {
    return value.replaceAll('_', ' ').replace(/\b\w/g, (letter) => letter.toUpperCase());
  }

  asProject(entity: Program | Project | undefined): Project | null {
    return entity && 'status' in entity ? entity : null;
  }

  private findEntity(
    snapshot: SentinelSnapshot,
    selected: TargetSelection,
  ): Program | Project | undefined {
    return selected.type === 'program'
      ? snapshot.programs.find((program) => program.id === selected.id)
      : snapshot.projects.find((project) => project.id === selected.id);
  }

  private emptyWorkForm(
    targetType: TargetType = 'program',
    targetId = 'daily-command',
  ): WorkItemForm {
    return {
      id: null,
      title: '',
      description: '',
      target_type: targetType,
      target_id: targetId,
      priority: 'normal',
      status: 'backlog',
      next_action: '',
      notes: '',
      human_check_in_status: 'none',
      execution_assignee: 'king_trizzen',
      scheduled_for: '',
      review_after: '',
    };
  }

  private toLocalDateTime(value: string | null): string {
    if (!value) {
      return '';
    }
    const date = new Date(value);
    const local = new Date(date.getTime() - date.getTimezoneOffset() * 60_000);
    return local.toISOString().slice(0, 16);
  }

  private describeError(error: HttpErrorResponse): string {
    const fields = error.error?.fields as Record<string, string> | undefined;
    if (fields) {
      return Object.entries(fields)
        .map(([field, message]) => `${this.displayLabel(field)} ${message}`)
        .join(' · ');
    }
    return error.error?.message ?? 'Jaza could not save that change. Is the local API running?';
  }

  private flash(message: string, isError = false): void {
    this.successMessage = message;
    this.formError = isError ? message : '';
    window.setTimeout(() => {
      if (this.successMessage === message) {
        this.successMessage = '';
      }
    }, 2800);
  }
}
