import { axiosInstance, type Envelope } from "@/utils/AxiosUtil";
import axios, { type AxiosRequestConfig } from "axios";

// An API failure with the envelope's error code intact, so callers can branch
// on `code` (e.g. a revocation whose cache invalidation failed) rather than
// on message text.
export class ApiError extends Error {
  readonly code: string;
  readonly status: number;

  constructor(code: string, message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.code = code;
    this.status = status;
  }
}

export const isApiError = (error: unknown, code?: string): error is ApiError =>
  error instanceof ApiError && (code === undefined || error.code === code);

// orval's adapter: unwrap the envelope once so generated hooks return `data`,
// and turn every failure into an ApiError.
export const customInstance = async <T,>(
  config: AxiosRequestConfig,
  options?: AxiosRequestConfig,
): Promise<T> => {
  try {
    const { data } = await axiosInstance.request<Envelope<T>>({ ...config, ...options });
    if (!data.success) {
      throw new ApiError(
        data.error?.code ?? "unknown_error",
        data.error?.message ?? "Request failed",
        200,
      );
    }
    return data.data as T;
  } catch (error) {
    if (!axios.isAxiosError(error)) throw error;
    const body = error.response?.data as Partial<Envelope<unknown>> | undefined;
    throw new ApiError(
      body?.error?.code ?? "network_error",
      body?.error?.message ?? "We couldn't reach the server. Try again.",
      error.response?.status ?? 0,
    );
  }
};
