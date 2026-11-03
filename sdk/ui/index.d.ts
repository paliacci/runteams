export type PresentationMode = 'panel' | 'full';
export type PresentationTarget = {mode: 'panel'; viewId: null} | {mode: 'full'; viewId: string};
export type PresentationSnapshot = Readonly<PresentationTarget & {pending: boolean; error: string | null}>;
export const presentationVersion: '0.1.0';
/** Native display metadata; never a business authorization source. */
export interface PlatformDisplayHost {
  readonly version: '0.1.0'; readonly kind: 'platform';
  getSnapshot(): Readonly<{theme: 'light' | 'dark'; presentation?: PresentationTarget}>;
  readonly capabilities?: readonly string[];
  request?(method: string, params: Record<string, unknown>): Promise<PresentationTarget>;
  onAction?(listener: (action: {revision: string; id: string}) => void): () => void;
  subscribe(listener: () => void): () => void;
}
/** Opt in to the host theme. Omit this binding for a deliberately custom theme. */
export function connectHostTheme(host: PlatformDisplayHost, root?: HTMLElement): {dispose(): void};
export class PresentationError extends Error {readonly code: string; constructor(code: string);}
export interface PresentationAdapter {
  readonly version: '0.1.0';
  transition(target: Readonly<PresentationTarget>, options: {signal: AbortSignal}): Promise<PresentationTarget> | PresentationTarget;
}
export interface PresentationClient {
  readonly version: '0.1.0';
  getSnapshot(): PresentationSnapshot;
  subscribe(listener: (state: PresentationSnapshot) => void): () => void;
  openFull(viewId: string): Promise<PresentationSnapshot>;
  returnToPanel(): Promise<PresentationSnapshot>;
  dispose(): void;
}
export function createPresentationClient(adapter: PresentationAdapter, options?: {timeoutMs?: number}): PresentationClient;
export interface DrawerHeaderAction {
  /** Stable key within this header. Labels are rendered as plain text. */
  id: string; label: string; disabled?: boolean; onPress: (event: MouseEvent) => void;
}
export interface DrawerHeaderExtras {text?: string; actions?: DrawerHeaderAction[];}
export interface DrawerHeader {
  element: HTMLElement; collapseButton: HTMLButtonElement;
  /** Replace all extras; omitted fields are cleared. Keeps the collapse control and toolbar skeleton. */
  setExtras(extras?: DrawerHeaderExtras): void;
  /** Detach handlers and disable actions. Caller owns node removal. */
  dispose(): void;
}
export function createDrawerHeader(options: {document?: Document; onCollapse: () => void; extras?: DrawerHeaderExtras}): DrawerHeader;
export interface Section {
  element: HTMLElement; body: HTMLElement; toggle: HTMLButtonElement; openButton: HTMLButtonElement;
  readonly expanded: boolean;
  setExpanded(value: boolean): void; setSummary(value: string): void; dispose(): void;
}
export interface FullView {
  element: HTMLElement; body: HTMLElement; heading: HTMLHeadingElement; backButton: HTMLButtonElement; employeeButton: HTMLButtonElement | null; dispose(): void;
}
export interface SectionOptions {
  document?: Document; title: string; summary?: string; content: HTMLElement; expanded?: boolean;
  onOpenFull?: () => void;
}
export function createSection(options: SectionOptions): Section;
export function createFullView(options: {document?: Document; title: string; employeeName?: string; onReturn?: () => void}): FullView;
export function createModuleTemplate(options: Omit<SectionOptions, 'onOpenFull'> & {employeeName?: string; onRequestMode?: (mode: PresentationMode) => void}): {
  section: Section; full: FullView; readonly mode: PresentationMode;
  setMode(mode: PresentationMode): void; setPending(value: boolean): void; setError(message?: string): void; dispose(): void;
};

/** One controller per native host document. Display data grants no business permission. */
export interface HostControls extends Omit<PresentationClient, 'dispose'> {
  /** Plain text (256 chars) and up to 8 named actions (80-char labels). */
  setHeader(extras?: Omit<DrawerHeaderExtras, 'actions'> & {actions?: Array<Omit<DrawerHeaderAction, 'onPress'> & {onPress: () => void}>}): Promise<void>;
  dispose(): Promise<void>;
}
export function createHostControls(host: PlatformDisplayHost): HostControls;
