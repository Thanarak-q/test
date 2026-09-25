import axios, { type AxiosRequestConfig } from "axios";

export type Envelope<T> = {
  success: boolean;
  data: T | null;
  error: { code: string; message: string } | null;
  meta: { total: number; page: number; limit: number } | null;
};

export const axiosInstance = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000",
  timeout: 15_000,
});

// The API wraps every JSON response in an envelope; unwrap once here so callers
// never see it, and surface `error.message` as the thrown Error.
const unwrap = async <T>(config: AxiosRequestConfig): Promise<T> => {
  const { data } = await axiosInstance.request<Envelope<T>>(config);
  if (!data.success || data.data === null) {
    throw new Error(data.error?.message ?? "Request failed");
  }
  return data.data;
};

export const api = {
  get: <T>(url: string, config?: AxiosRequestConfig) =>
    unwrap<T>({ ...config, url, method: "GET" }),
  post: <T>(url: string, body?: unknown, config?: AxiosRequestConfig) =>
    unwrap<T>({ ...config, url, method: "POST", data: body }),
  patch: <T>(url: string, body?: unknown, config?: AxiosRequestConfig) =>
    unwrap<T>({ ...config, url, method: "PATCH", data: body }),
  delete: <T>(url: string, config?: AxiosRequestConfig) =>
    unwrap<T>({ ...config, url, method: "DELETE" }),
};
