import { request } from "@/lib";

export type Dataset = { table: string; rows: number; columns: { name: string; type: string }[] };

export const datasetsApi = {
  list: () => request<Dataset[]>("/api/datasets"),
  upload: (file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return request<{ table: string; rows: number }>("/api/datasets", { method: "POST", body: fd });
  },
  remove: (table: string) => request(`/api/datasets/${encodeURIComponent(table)}`, { method: "DELETE" }),
};
