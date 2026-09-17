export type JsonObject = Record<string, unknown>;
export interface Entity extends JsonObject {
  id: string;
  name: string;
  version?: string | number;
}
export interface Factor extends Entity {
  expression?: string;
  description?: string;
  plugin?: string;
  direction?: number;
  parameters?: JsonObject;
}
export interface Snapshot extends Entity {
  source: string;
  synthetic: boolean;
  instruments: string[];
  startDate: string;
  endDate: string;
  rowCount: number;
  hash: string;
  quality?: JsonObject;
}
export interface Job extends JsonObject {
  id: string;
  type: string;
  status: string;
  config: JsonObject;
  progress?: number;
  message?: string;
  error?: string;
  createdAt: string;
  logs?: unknown[];
  events?: unknown[];
  testViewedAt?: string | null;
  lastViewedAt?: string | null;
  testViewCount?: number;
  testViewAuditStatus?: string;
  testViewHistoryKnown?: boolean;
}
export interface Bootstrap {
  factors: Factor[];
  universes: Entity[];
  snapshots: Snapshot[];
  experiments: Entity[];
  jobs: Job[];
  operators: JsonObject[];
  defaults: JsonObject;
}
export interface Report {
  schemaVersion?: string;
  kind: string;
  status: string;
  summary: JsonObject;
  charts: Record<string, unknown>;
  tables: Record<string, unknown>;
  warnings: unknown[];
  artifacts: { name: string; path: string; mimeType?: string }[];
  provenance: JsonObject;
}
export interface Health {
  status: string;
  pythonReady?: boolean;
  workspace?: string;
}
export const EMPTY: Bootstrap = {
  factors: [],
  universes: [],
  snapshots: [],
  experiments: [],
  jobs: [],
  operators: [],
  defaults: {},
};
