import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

import type {
  AnalysisResponse,
  ErcFinding,
  SymbolFinding,
} from "@/lib/types";

const SESSIONS_KEY = "circuitsentinel.local_sessions.v1";

export type LocalSession = {
  id: string;
  filename: string;
  file_id: string | null;
  format: string | null;
  status: string;
  component_count: number;
  finding_count: number;
  updated_at: string;
  /** Full analysis snapshot for local reopen (local-only; not a cloud project). */
  analysis: AnalysisResponse;
};

/** Request schematic navigation for a finding/component (consumed by /schematic). */
export type PendingLocate = {
  id: number;
  findingIndex: number | null;
  reference?: string | null;
  pin?: string | null;
  x_mm?: number | null;
  y_mm?: number | null;
  label: string;
};

type WorkspaceContextValue = {
  analysis: AnalysisResponse | null;
  file: File | null;
  selectedFindingIndex: number | null;
  selectedSymbol: SymbolFinding | null;
  pendingLocate: PendingLocate | null;
  sessions: LocalSession[];
  setAnalysis: (analysis: AnalysisResponse | null, file?: File | null) => void;
  setFile: (file: File | null) => void;
  selectFinding: (index: number | null) => void;
  selectSymbol: (symbol: SymbolFinding | null) => void;
  requestLocate: (target: Omit<PendingLocate, "id">) => void;
  clearPendingLocate: () => void;
  openSession: (id: string) => boolean;
  removeSession: (id: string) => void;
  clearWorkspace: () => void;
};

const WorkspaceContext = createContext<WorkspaceContextValue | null>(null);

function loadSessions(): LocalSession[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(SESSIONS_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw) as LocalSession[];
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function persistSessions(sessions: LocalSession[]) {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(SESSIONS_KEY, JSON.stringify(sessions.slice(0, 24)));
  } catch {
    /* quota / private mode */
  }
}

function sessionFromAnalysis(analysis: AnalysisResponse): LocalSession {
  const fileId = analysis.viewer?.file_id ?? null;
  const filename = analysis.upload?.original_filename ?? "schematic";
  return {
    id: fileId ?? `local-${Date.now()}`,
    filename,
    file_id: fileId,
    format: analysis.upload?.format ?? null,
    status: analysis.status,
    component_count: analysis.confirmed?.symbols?.length ?? 0,
    finding_count: analysis.erc?.findings?.length ?? 0,
    updated_at: new Date().toISOString(),
    analysis,
  };
}

export function WorkspaceProvider({ children }: { children: ReactNode }) {
  const [analysis, setAnalysisState] = useState<AnalysisResponse | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [selectedFindingIndex, selectFinding] = useState<number | null>(null);
  const [selectedSymbol, selectSymbol] = useState<SymbolFinding | null>(null);
  const [pendingLocate, setPendingLocate] = useState<PendingLocate | null>(null);
  const [sessions, setSessions] = useState<LocalSession[]>([]);
  const locateSeq = useRef(0);

  useEffect(() => {
    setSessions(loadSessions());
  }, []);

  const setAnalysis = useCallback((next: AnalysisResponse | null, nextFile?: File | null) => {
    setAnalysisState(next);
    if (nextFile !== undefined) setFile(nextFile);
    selectFinding(null);
    selectSymbol(null);
    setPendingLocate(null);
    if (next && next.status !== "error") {
      const entry = sessionFromAnalysis(next);
      setSessions((prev) => {
        const filtered = prev.filter((s) => s.id !== entry.id && s.file_id !== entry.file_id);
        const updated = [entry, ...filtered];
        persistSessions(updated);
        return updated;
      });
    }
  }, []);

  const openSession = useCallback(
    (id: string) => {
      const found = sessions.find((s) => s.id === id);
      if (!found) return false;
      setAnalysisState(found.analysis);
      setFile(null);
      selectFinding(null);
      selectSymbol(null);
      setPendingLocate(null);
      return true;
    },
    [sessions],
  );

  const removeSession = useCallback((id: string) => {
    setSessions((prev) => {
      const updated = prev.filter((s) => s.id !== id);
      persistSessions(updated);
      return updated;
    });
  }, []);

  const clearWorkspace = useCallback(() => {
    setAnalysisState(null);
    setFile(null);
    selectFinding(null);
    selectSymbol(null);
    setPendingLocate(null);
  }, []);

  const requestLocate = useCallback((target: Omit<PendingLocate, "id">) => {
    locateSeq.current += 1;
    setPendingLocate({ ...target, id: locateSeq.current });
  }, []);

  const clearPendingLocate = useCallback(() => {
    setPendingLocate(null);
  }, []);

  const value = useMemo(
    () => ({
      analysis,
      file,
      selectedFindingIndex,
      selectedSymbol,
      pendingLocate,
      sessions,
      setAnalysis,
      setFile,
      selectFinding,
      selectSymbol,
      requestLocate,
      clearPendingLocate,
      openSession,
      removeSession,
      clearWorkspace,
    }),
    [
      analysis,
      file,
      selectedFindingIndex,
      selectedSymbol,
      pendingLocate,
      sessions,
      setAnalysis,
      requestLocate,
      clearPendingLocate,
      openSession,
      removeSession,
      clearWorkspace,
    ],
  );

  return <WorkspaceContext.Provider value={value}>{children}</WorkspaceContext.Provider>;
}

export function useWorkspace(): WorkspaceContextValue {
  const ctx = useContext(WorkspaceContext);
  if (!ctx) {
    throw new Error("useWorkspace must be used within WorkspaceProvider");
  }
  return ctx;
}

export function findingSeverityFilter(
  findings: ErcFinding[],
  filter: "all" | "error" | "warning",
): ErcFinding[] {
  if (filter === "all") return findings;
  return findings.filter((f) => f.severity.toLowerCase() === filter);
}
