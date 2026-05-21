import { http, API_URL } from "./http";

export const api = http;
export { API_URL };

export function getErrMsg(err) {
  const detail = err?.response?.data?.detail;
  if (detail && typeof detail === "object") {
    return detail.message || detail.msg || detail.detail || JSON.stringify(detail);
  }

  return (
    detail ||
    err?.response?.data?.msg ||
    err?.response?.data?.message ||
    err?.message ||
    "Erro desconhecido"
  );
}
