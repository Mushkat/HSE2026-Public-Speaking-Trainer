import { apiClient } from "./client";

export const registerUser = async (email: string, password: string) => {
  const response = await apiClient.post("/auth/register", { email, password });
  return response.data;
};

export const loginUser = async (email: string, password: string) => {
  const data = new URLSearchParams();
  data.append("username", email);
  data.append("password", password);

  const response = await apiClient.post("/auth/login", data, {
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
  });

  return response.data as { access_token: string; token_type: string };
};
