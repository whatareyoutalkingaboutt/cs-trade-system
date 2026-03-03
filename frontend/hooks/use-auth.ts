import { useEffect, useState } from "react";

import { getClientToken, subscribeTokenChange } from "@/lib/auth-token";

export function useAuth() {
  const [token, setToken] = useState<string | null>(null);

  useEffect(() => {
    setToken(getClientToken());
    const onStorage = () => setToken(getClientToken());
    const unsubscribe = subscribeTokenChange(onStorage);
    window.addEventListener("storage", onStorage);
    return () => {
      unsubscribe();
      window.removeEventListener("storage", onStorage);
    };
  }, []);

  return { token, isAuthed: Boolean(token) };
}
