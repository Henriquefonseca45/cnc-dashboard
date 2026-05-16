import { http, API_URL } from "./http";

export const api = http;
export { API_URL };

export function getErrMsg(err) {
  return (
    err?.response?.data?.detail ||
    err?.response?.data?.msg ||
    err?.response?.data?.message ||
    err?.message ||
    "Erro desconhecido"
  );
}