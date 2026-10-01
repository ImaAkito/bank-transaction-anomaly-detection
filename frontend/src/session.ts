import { createContext, useContext } from "react";
import type { Me } from "./types";

export const SessionContext = createContext<Me>({ username: "admin", role: "admin", auth_enabled: false });

export const useSession = () => useContext(SessionContext);

export const canReview = (me: Me) => me.role === "analyst" || me.role === "admin";
