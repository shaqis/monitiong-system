import { cache } from "react";
import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { ApiError, getCurrentUser } from "@/lib/api";
import type { User } from "@/types";

export const getCookieHeader = cache((): string => cookies().toString());

export const getSessionUser = cache(async (): Promise<User | null> => {
  const cookieHeader = getCookieHeader();
  if (!cookieHeader) {
    return null;
  }
  try {
    return await getCurrentUser({ cookieHeader });
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) {
      return null;
    }
    throw error;
  }
});

export async function getRequiredUser(): Promise<User> {
  const user = await getSessionUser();
  if (user === null) {
    redirect("/login");
  }
  return user;
}
