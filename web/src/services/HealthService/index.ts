import { api } from "@/utils/AxiosUtil";
import type { HealthResponse } from "./types/HealthResponse";

export const getHealth = () => api.get<HealthResponse>("/health");
