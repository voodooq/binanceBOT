import { create } from 'zustand';
import { persist } from 'zustand/middleware';

interface AppState {
    activeApiKeyId: number | null;
    setActiveApiKeyId: (id: number | null) => void;
}

export const useAppStore = create<AppState>()(
    persist(
        (set) => ({
            activeApiKeyId: null,
            setActiveApiKeyId: (id) => set({ activeApiKeyId: id }),
        }),
        {
            name: 'binancebot-app-storage', // name of the item in the storage (must be unique)
            partialize: (state) => ({ activeApiKeyId: state.activeApiKeyId }), // only persist activeApiKeyId
        }
    )
);
