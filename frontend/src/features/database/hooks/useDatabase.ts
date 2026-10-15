import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { databaseApi } from "../api";

const KEY = ["database"];

/** Postgres overview: connection details, tables and views with columns, and migration state. */
export function useDatabaseOverview() {
  return useQuery({ queryKey: KEY, queryFn: databaseApi.overview, retry: false });
}

/** Applies pending migrations, then refreshes the overview. */
export function useMigrate() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: databaseApi.migrate,
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY }),
  });
}
