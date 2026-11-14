import { cache } from "react";
import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { ApiError, getCurrentUser } from "@/lib/api";
import type { User } from "@/types";

export const getCookieHeader = cache((): string => cookies().toString());

export const getOptionalUser = cache(async (): Promise<User | null> => {
  const cookieHeader = getCookieHeader();
  if (!cookieHeader) {
    return null;
  }
  try {
    return await getCurrentUser({ cookieHeader });
  } catch {
    return null;
  }
});

export const getRequiredUser = cache(async (): Promise<User> => {
  const cookieHeader = getCookieHeader();
  if (!cookieHeader) {
    redirect("/login");
  }
  try {
    return await getCurrentUser({ cookieHeader });
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) {
      redirect("/login");
    }
    throw error;
  }
});
