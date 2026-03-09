import { useState, useEffect, useRef } from "react";
import { invoke } from "@tauri-apps/api/core";
import { listen, UnlistenFn } from "@tauri-apps/api/event";
import { DashboardSnapshot, EMPTY_SNAPSHOT } from "../types";

export function useDashboard() {
  const [snapshot, setSnapshot] = useState<DashboardSnapshot>(EMPTY_SNAPSHOT);
  const [running, setRunning] = useState(false);
  const unlistenRef = useRef<UnlistenFn | null>(null);

  useEffect(() => {
    // Fetch the initial snapshot synchronously.
    invoke<DashboardSnapshot>("get_snapshot")
      .then(setSnapshot)
      .catch(console.error);

    // Subscribe to live updates.
    listen<DashboardSnapshot>("state-update", (event) => {
      setSnapshot(event.payload);
    }).then((fn) => {
      unlistenRef.current = fn;
    });

    return () => {
      unlistenRef.current?.();
    };
  }, []);

  const startBacktest = async () => {
    setRunning(true);
    try {
      await invoke("start_backtest");
    } catch (e) {
      console.error(e);
      setRunning(false);
    }
  };

  const stopEngine = async () => {
    await invoke("stop_engine");
    setRunning(false);
  };

  // Detect when backtest finishes (progress hits 100 %).
  useEffect(() => {
    if (running && snapshot.progress_pct >= 100) {
      setRunning(false);
    }
  }, [snapshot.progress_pct, running]);

  return { snapshot, running, startBacktest, stopEngine };
}
