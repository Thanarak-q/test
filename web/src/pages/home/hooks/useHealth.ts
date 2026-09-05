import { queryKeys } from "@/consts/queryKeys";
import { getHealth } from "@/services/HealthService";
import { useQuery } from "@tanstack/react-query";

export const useHealth = () =>
  useQuery({
    queryKey: queryKeys.health.status(),
    queryFn: getHealth,
  });
