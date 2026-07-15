import { Component, input, output, signal, effect } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';

/* ----- helper utilities ----- */

function deepClone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}

type JsonPrimitive = string | number | boolean | null;
type JsonValue = JsonPrimitive | JsonValue[] | { [key: string]: JsonValue };
type JsonObject = { [key: string]: JsonValue };

function isObject(value: unknown): value is JsonObject {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

function isArray(value: unknown): value is unknown[] {
  return Array.isArray(value);
}

function orderedKeys(obj: JsonObject): string[] {
  return Object.keys(obj);
}

function isEmptyString(value: unknown): boolean {
  return typeof value === 'string' && value.trim() === '';
}

/* ----- path helpers for nested mutations ----- */

type PathSegment = string | number;

function parsePath(path: string): PathSegment[] {
  if (!path) return [];
  const segments: PathSegment[] = [];
  const regex = /([^\[\].]+)|\[(\d+)\]/g;
  let match: RegExpExecArray | null;
  while ((match = regex.exec(path)) !== null) {
    if (match[1] !== undefined) {
      segments.push(match[1]);
    } else if (match[2] !== undefined) {
      segments.push(parseInt(match[2], 10));
    }
  }
  return segments;
}

function getByPath(obj: Record<string, unknown>, path: string): unknown {
  const segs = parsePath(path);
  let current: unknown = obj;
  for (const seg of segs) {
    if (current == null || typeof current !== 'object') return undefined;
    current = (current as Record<string, unknown>)[seg];
  }
  return current;
}

function setByPath(obj: Record<string, unknown>, path: string, value: unknown): void {
  const segs = parsePath(path);
  if (segs.length === 0) return;
  let current: Record<string, unknown> = obj;
  for (let i = 0; i < segs.length - 1; i++) {
    const seg = segs[i];
    const nextSeg = segs[i + 1];
    if (current[seg] == null || typeof current[seg] !== 'object') {
      current[seg] = typeof nextSeg === 'number' ? [] : {};
    }
    current = current[seg] as Record<string, unknown>;
  }
  current[segs[segs.length - 1]] = value;
}

/* ----- Component ----- */

@Component({
  selector: 'app-structured-json-editor',
  standalone: true,
  imports: [CommonModule, FormsModule],
  template: `
    <div class="sje-root">
      <ng-container
        *ngTemplateOutlet="
          nodeTpl;
          context: { node: model(), path: '', depth: 0 }
        "
      />
    </div>

    <ng-template #nodeTpl let-node="node" let-path="path" let-depth="depth">

      <!-- ========== OBJECT ========== -->
      <ng-container *ngIf="isObject(node); else notObject">
        <!-- opening brace -->
        <span class="sje-brace">{{ '{' }}</span>

        <ng-container *ngIf="orderedKeys(node).length > 0; else emptyObj">
          <br />
          <ng-container *ngFor="let key of orderedKeys(node); let last = last">
            <span class="sje-indent" [style.paddingLeft.px]="(depth + 1) * 20"></span
            ><span class="sje-key">"{{ key }}"</span
            ><span class="sje-colon">: </span
            ><ng-container
              *ngTemplateOutlet="
                nodeTpl;
                context: {
                  node: node[key],
                  path: joinPath(path, key),
                  depth: depth + 1
                }
              " /><span *ngIf="!last" class="sje-comma">,</span><br *ngIf="isSimpleValue(node[key])" />
            <br *ngIf="!isSimpleValue(node[key])" />
          </ng-container>
          <span [style.paddingLeft.px]="depth * 20"></span>
        </ng-container>
        <ng-template #emptyObj></ng-template>

        <!-- closing brace -->
        <span class="sje-brace">{{ '}' }}</span>
      </ng-container>

      <!-- ========== ARRAY ========== -->
      <ng-template #notObject>
        <ng-container *ngIf="isArray(node); else notArray">
          <span class="sje-bracket">{{ '[' }}</span>

          <ng-container *ngIf="$any(node).length > 0; else emptyArr">
            <br />
            <ng-container *ngFor="let item of $any(node); let idx = index; let last = last">
              <span class="sje-indent" [style.paddingLeft.px]="(depth + 1) * 20"></span
              ><ng-container
                *ngTemplateOutlet="
                  nodeTpl;
                  context: {
                    node: item,
                    path: joinArrayPath(path, idx),
                    depth: depth + 1
                  }
                " /><span *ngIf="!last" class="sje-comma">,</span
              ><button
                class="sje-remove-btn"
                title="Remove item"
                (click)="removeFromArray(path, idx)"
              >−</button
              ><br />
            </ng-container>
            <span [style.paddingLeft.px]="depth * 20"></span>
          </ng-container>
          <ng-template #emptyArr></ng-template>

          <span class="sje-bracket">{{ ']' }}</span
          ><button
            class="sje-add-btn"
            title="Add item"
            (click)="addToArray(path)"
          >+ Add</button>
        </ng-container>
      </ng-template>

      <!-- ========== STRING ========== -->
      <ng-template #notArray>
        <ng-container *ngIf="isString(node); else notString">
          <span class="sje-quote">"</span
          ><input
            class="sje-value-input sje-string-input"
            [value]="node"
            (blur)="onStringBlur(path, $any($event.target).value)"
            (keydown.enter)="blurTarget($event)"
            spellcheck="false"
          /><span class="sje-quote">"</span>
        </ng-container>
      </ng-template>

      <!-- ========== NUMBER ========== -->
      <ng-template #notString>
        <ng-container *ngIf="isNumber(node); else notNumber">
          <input
            class="sje-value-input sje-number-input"
            type="number"
            [value]="node"
            (blur)="onNumberBlur(path, $any($event.target).value)"
            (keydown.enter)="blurTarget($event)"
            step="any"
          />
        </ng-container>
      </ng-template>

      <!-- ========== BOOLEAN ========== -->
      <ng-template #notNumber>
        <ng-container *ngIf="isBool(node); else notBool">
          <select
            class="sje-value-input sje-bool-select"
            [value]="node ? 'true' : 'false'"
            (change)="onBoolChange(path, $any($event.target).value)"
          >
            <option value="true">true</option>
            <option value="false">false</option>
          </select>
        </ng-container>
      </ng-template>

      <!-- ========== NULL ========== -->
      <ng-template #notBool>
        <span class="sje-null">null</span>
      </ng-template>

    </ng-template>
  `,
  styles: [`
    :host {
      display: block;
      width: 100%;
      font-family: 'Roboto Mono', 'Cascadia Code', 'Fira Code', monospace;
      font-size: 13px;
      line-height: 1.7;
      color: #d4d4d8;
    }

    .sje-root {
      margin: 0;
      padding: 12px 16px;
      background: rgba(15, 23, 42, 0.72);
      border: 1px solid rgba(148, 163, 184, 0.18);
      border-radius: 6px;
      overflow-wrap: break-word;
      word-break: break-word;
      white-space: pre-wrap;
      max-height: 520px;
      overflow-y: auto;
    }

    /* ---- structural tokens – read-only ---- */
    .sje-brace,
    .sje-bracket {
      color: #facc15;
      font-weight: 700;
    }

    .sje-key {
      color: #67e8f9;
    }

    .sje-colon {
      color: #94a3b8;
    }

    .sje-comma {
      color: #94a3b8;
    }

    .sje-quote {
      color: #f8fafc;
      user-select: none;
    }

    .sje-null {
      color: #64748b;
      font-style: italic;
    }

    .sje-indent {
      display: inline;
    }

    /* ---- editable value inputs ---- */
    .sje-value-input {
      font-family: inherit;
      font-size: inherit;
      line-height: inherit;
      background: rgba(30, 41, 59, 0.85);
      border: 1px solid rgba(103, 232, 249, 0.25);
      border-radius: 3px;
      outline: none;
      color: #a5f3fc;
      padding: 0 4px;
      margin: 0;
      vertical-align: baseline;
      transition: border-color 0.15s ease, box-shadow 0.15s ease;
    }

    .sje-value-input:focus {
      border-color: #67e8f9;
      box-shadow: 0 0 0 2px rgba(103, 232, 249, 0.2);
      background: rgba(15, 23, 42, 0.95);
    }

    .sje-string-input {
      min-width: 80px;
      width: auto;
    }

    .sje-number-input {
      width: 90px;
      text-align: right;
      -moz-appearance: textfield;
    }

    .sje-number-input::-webkit-inner-spin-button,
    .sje-number-input::-webkit-outer-spin-button {
      -webkit-appearance: none;
      margin: 0;
    }

    .sje-bool-select {
      width: auto;
      min-width: 52px;
      cursor: pointer;
      color: #facc15;
    }

    /* ---- array inline controls ---- */
    .sje-remove-btn {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 18px;
      height: 18px;
      margin-left: 6px;
      padding: 0;
      border: 1px solid rgba(239, 68, 68, 0.35);
      border-radius: 3px;
      background: rgba(239, 68, 68, 0.08);
      color: rgba(248, 113, 113, 0.7);
      font-family: inherit;
      font-size: 13px;
      font-weight: 700;
      line-height: 1;
      cursor: pointer;
      vertical-align: middle;
      transition: background 0.15s ease, color 0.15s ease;
    }

    .sje-remove-btn:hover {
      background: rgba(239, 68, 68, 0.2);
      color: #f87171;
    }

    .sje-add-btn {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      height: 20px;
      margin-left: 8px;
      padding: 0 7px;
      border: 1px solid rgba(250, 204, 21, 0.35);
      border-radius: 4px;
      background: rgba(250, 204, 21, 0.08);
      color: rgba(250, 204, 21, 0.75);
      font-family: inherit;
      font-size: 11px;
      font-weight: 700;
      line-height: 1;
      cursor: pointer;
      vertical-align: middle;
      transition: background 0.15s ease, color 0.15s ease;
    }

    .sje-add-btn:hover {
      background: rgba(250, 204, 21, 0.2);
      color: #facc15;
    }
  `]
})
export class StructuredJsonEditorComponent {
  readonly value = input<unknown>(null);
  readonly valueChange = output<unknown>();

  readonly model = signal<unknown>(null);

  constructor() {
    effect(() => {
      this.model.set(deepClone(this.value()));
    });
  }

  /* ---- template helpers ---- */
  readonly isObject = isObject;
  readonly isArray = isArray;

  isString(value: unknown): value is string {
    return typeof value === 'string';
  }

  isNumber(value: unknown): value is number {
    return typeof value === 'number';
  }

  isBool(value: unknown): value is boolean {
    return typeof value === 'boolean';
  }

  isSimpleValue(value: unknown): boolean {
    if (value === null || value === undefined) return true;
    const t = typeof value;
    return t === 'string' || t === 'number' || t === 'boolean';
  }

  orderedKeys = orderedKeys;

  joinPath(parent: string, key: string): string {
    return parent ? `${parent}.${key}` : key;
  }

  joinArrayPath(parent: string, idx: number): string {
    return `${parent}[${idx}]`;
  }

  /* ---- value mutations ---- */

  blurTarget(event: Event): void {
    (event.target as HTMLElement).blur();
  }

  onNumberBlur(path: string, raw: string): void {
    const num = parseFloat(raw);
    const value = isNaN(num) ? 0 : num;
    const cloned = deepClone(this.model());
    setByPath(cloned as Record<string, unknown>, path, value);
    this.model.set(cloned);
    this.valueChange.emit(cloned);
  }

  onBoolChange(path: string, raw: string): void {
    const value = raw === 'true';
    const cloned = deepClone(this.model());
    setByPath(cloned as Record<string, unknown>, path, value);
    this.model.set(cloned);
    this.valueChange.emit(cloned);
  }

  /**
   * When a string input inside an ARRAY is blurred while empty,
   * remove that item from the array (natural "select & delete" behaviour).
   * Otherwise emit the change.
   */
  onStringBlur(path: string, raw: string): void {
    if (isEmptyString(raw) && this.isArrayElement(path)) {
      const parentPath = this.arrayParentPath(path);
      const idx = this.arrayIndex(path);
      const cloned = deepClone(this.model());
      const arr = getByPath(cloned as Record<string, unknown>, parentPath) as unknown[];
      if (Array.isArray(arr) && idx >= 0 && idx < arr.length) {
        arr.splice(idx, 1);
        this.model.set(cloned);
        this.valueChange.emit(cloned);
        return;
      }
    }
    // Normal path – finalise the string value
    const cloned = deepClone(this.model());
    setByPath(cloned as Record<string, unknown>, path, raw);
    this.model.set(cloned);
    this.valueChange.emit(cloned);
  }

  /* ---- array mutations ---- */

  addToArray(path: string): void {
    const cloned = deepClone(this.model());
    const arr = getByPath(cloned as Record<string, unknown>, path) as unknown[];
    if (!Array.isArray(arr)) return;

    let defaultItem: unknown = '';
    if (arr.length > 0) {
      const first = arr[0];
      if (typeof first === 'string') defaultItem = '';
      else if (typeof first === 'number') defaultItem = 0;
      else if (typeof first === 'boolean') defaultItem = false;
      else if (Array.isArray(first)) defaultItem = [];
      else if (isObject(first)) defaultItem = {};
    }
    arr.push(defaultItem);
    this.model.set(cloned);
    this.valueChange.emit(cloned);
  }

  removeFromArray(path: string, index: number): void {
    const cloned = deepClone(this.model());
    const arr = getByPath(cloned as Record<string, unknown>, path) as unknown[];
    if (!Array.isArray(arr) || index < 0 || index >= arr.length) return;
    arr.splice(index, 1);
    this.model.set(cloned);
    this.valueChange.emit(cloned);
  }

  /* ---- array element deletion helpers ---- */

  private isArrayElement(path: string): boolean {
    return /\[\d+\]$/.test(path);
  }

  private arrayParentPath(path: string): string {
    return path.replace(/\[\d+\]$/, '');
  }

  private arrayIndex(path: string): number {
    const match = path.match(/\[(\d+)\]$/);
    return match ? parseInt(match[1], 10) : -1;
  }
}