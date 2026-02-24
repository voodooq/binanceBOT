import { create } from "zustand";

interface AuthState {
    token: string | null;
    isAuthenticated: boolean;
    isAdmin: boolean;
    setToken: (token: string, isAdmin: boolean) => void;
    logout: () => void;
}

export const useAuthStore = create<AuthState>((set) => ({
    token: localStorage.getItem("token"),
    isAuthenticated: !!localStorage.getItem("token"),
    isAdmin: localStorage.getItem("isAdmin") === "true",
    setToken: (token: string, isAdmin: boolean) => {
        localStorage.setItem("token", token);
        localStorage.setItem("isAdmin", String(isAdmin));
        set({ token, isAuthenticated: true, isAdmin });
    },
    logout: () => {
        localStorage.removeItem("token");
        localStorage.removeItem("isAdmin");
        set({ token: null, isAuthenticated: false, isAdmin: false });
    },
}));
