import { apiClient } from "./client";

export type LLMStatus = {
  available: boolean;
  status: "ready" | "starting" | "unavailable";
  detail: string;
};

export const fetchLLMStatus = async () => (await apiClient.get<LLMStatus>("/system/llm-status")).data;
