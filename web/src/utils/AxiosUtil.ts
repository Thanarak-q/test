import axios from "axios";

// The transport wrapper every API response travels in. Not an API type: the
// OpenAPI schema describes `data`, and the mutator unwraps this before any
// generated hook sees it.
export type Envelope<T> = {
  success: boolean;
  data: T | null;
  error: { code: string; message: string } | null;
  meta: { total: number; page: number; limit: number } | null;
};

// The bare origin: API paths carry their own version (`/v1/...`), and
// `/health` is deliberately unversioned.
// TODO(session): send the main application's session once its mechanism is
// known (e.g. `withCredentials: true` for a cookie session).
export const axiosInstance = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000",
  timeout: 15_000,
});
