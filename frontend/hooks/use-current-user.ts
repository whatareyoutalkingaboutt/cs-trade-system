import { useEffect, useState } from "react";

import { apiFetch } from "@/lib/api";
import { useAuth } from "@/hooks/use-auth";

type CurrentUser = {
  id: number;
  username: string;
  email: string;
  is_active: boolean;
  is_superuser: boolean;
};

export function useCurrentUser() {
  const { token } = useAuth();
  const [user, setUser] = useState<CurrentUser | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    let active = true;
    if (!token) {
      setUser(null);
      return;
    }
    setLoading(true);
    apiFetch("/api/auth/me")
      .then((payload) => {
        if (!active) return;
        setUser(payload.data as CurrentUser);
      })
      .catch(() => {
        if (!active) return;
        setUser(null);
      })
      .finally(() => {
        if (!active) return;
        setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [token]);

  return { user, loading };
}
