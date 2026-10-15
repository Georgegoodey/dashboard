import { jsonInit, request } from "@/lib";

export type Column = { name: string; type: string; nullable: boolean };
export type Relation = {
  name: string;
  kind: "table" | "view" | "materialized view";
  /** Exact for tables; null for views, which are not counted. */
  rows: number | null;
  size: string | null;
  columns: Column[];
};
export type Migrations = { applied: { version: string }[]; pending: string[] };
export type DatabaseOverview = {
  name: string;
  role: string;
  server_version: string;
  size: string;
  relations: Relation[];
  migrations: Migrations;
};

export const databaseApi = {
  overview: () => request<DatabaseOverview>("/api/database"),
  migrate: () => request<{ applied: string[] }>("/api/database/migrate", jsonInit("POST")),
};
