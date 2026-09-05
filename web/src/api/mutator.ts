import type { AxiosRequestConfig } from "axios";
import { axiosInstance, type Envelope } from "@/utils/AxiosUtil";

export const customInstance = async <T,>(config: AxiosRequestConfig): Promise<T> => {
  const { data } = await axiosInstance.request<Envelope<T>>(config);
  if (!data.success || data.data === null) {
    throw new Error(data.error?.message ?? "Request failed");
  }
  return data.data;
};
