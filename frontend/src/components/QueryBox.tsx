"use client";

import { useState, useRef, useEffect } from "react";
import { QueryResult } from "@/types";

interface QueryBoxProps {
  onResult: (result: QueryResult) => void;
  onLoading: (loading: boolean, phase: string) => void;
  onError: (error: string | null) => void;
}

const QUICK_QUERIES = [
  "What is the IC50 of NVX-0228?",
  "What toxicity was observed with NVX-0228?",
  "What is the mechanism of action of NVX-0228?",
  "What clinical trials have been conducted with NVX-0228?",
  "What resistance mechanisms have been identified?",
];

const LOADING_PHASES = [
  "🔍 Retrieving from papers...",
  "⚖️ Detecting conflicts...",
  "✍️ Synthesizing answer...",
];

const PHASE_TIMINGS = [0, 2000, 6000]; // ms thresholds

export default function QueryBox({ onResult, onLoading, onError }: QueryBoxProps) {
  const [query, setQuery] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const phaseIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const phaseIndexRef = useRef(0);
  const startTimeRef = useRef<number>(0);

  // Clean up interval on unmount
  useEffect(() => {
    return () => {
      if (phaseIntervalRef.current) {
        clearInterval(phaseIntervalRef.current);
      }
    };
  }, []);

  const startPhaseProgression = () => {
    phaseIndexRef.current = 0;
    startTimeRef.current = Date.now();
    onLoading(true, LOADING_PHASES[0]);

    phaseIntervalRef.current = setInterval(() => {
      const elapsed = Date.now() - startTimeRef.current;
      let newPhaseIndex = 0;
      for (let i = PHASE_TIMINGS.length - 1; i >= 0; i--) {
        if (elapsed >= PHASE_TIMINGS[i]) {
          newPhaseIndex = i;
          break;
        }
      }
      if (newPhaseIndex !== phaseIndexRef.current) {
        phaseIndexRef.current = newPhaseIndex;
        onLoading(true, LOADING_PHASES[newPhaseIndex]);
      }
    }, 500);
  };

  const stopPhaseProgression = () => {
    if (phaseIntervalRef.current) {
      clearInterval(phaseIntervalRef.current);
      phaseIntervalRef.current = null;
    }
  };

  const submitQuery = async (queryText: string) => {
    const trimmed = queryText.trim();
    if (!trimmed) return;

    setIsLoading(true);
    onError(null);
    startPhaseProgression();

    try {
      const apiUrl =
        process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
      const response = await fetch(`${apiUrl}/query`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ query: trimmed }),
      });

      if (!response.ok) {
        let errorMessage = `Server error: ${response.status}`;
        try {
          const errorData = await response.json();
          errorMessage = errorData.detail || errorData.message || errorMessage;
        } catch {
          // Use status-based message if JSON parse fails
        }
        throw new Error(errorMessage);
      }

      const data: QueryResult = await response.json();
      onResult(data);
      onError(null);
    } catch (err) {
      const message =
        err instanceof Error
          ? err.message
          : "An unexpected error occurred. Please try again.";

      if (message.includes("fetch") || message.includes("Failed to fetch") || message.includes("NetworkError")) {
        onError(
          "Unable to reach the API server. Make sure the backend is running at " +
            (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000")
        );
      } else {
        onError(message);
      }
    } finally {
      stopPhaseProgression();
      setIsLoading(false);
      onLoading(false, "");
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    await submitQuery(query);
  };

  const handleChipClick = async (chipQuery: string) => {
    setQuery(chipQuery);
    await submitQuery(chipQuery);
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
      e.preventDefault();
      submitQuery(query);
    }
  };

  const isSubmitDisabled = isLoading || !query.trim();

  return (
    <div className="bg-slate-800 border border-slate-700 rounded-xl p-5 space-y-4 shadow-lg">
      {/* Quick-select chips */}
      <div className="space-y-2">
        <p className="text-xs text-slate-500 font-medium uppercase tracking-wide">
          Quick queries
        </p>
        <div className="flex flex-wrap gap-2">
          {QUICK_QUERIES.map((q) => (
            <button
              key={q}
              data-testid="query-chip"
              onClick={() => handleChipClick(q)}
              disabled={isLoading}
              className="px-3 py-1.5 text-xs rounded-full bg-slate-700 hover:bg-slate-600 text-slate-300 hover:text-white border border-slate-600 hover:border-slate-500 transition-all disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {q}
            </button>
          ))}
        </div>
      </div>

      {/* Query form */}
      <form onSubmit={handleSubmit} className="space-y-3">
        <div className="relative">
          <textarea
            data-testid="query-input"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Ask a question about NVX-0228 research papers..."
            rows={3}
            disabled={isLoading}
            className="w-full bg-slate-900 border border-slate-600 rounded-lg px-4 py-3 text-slate-100 placeholder-slate-500 text-sm resize-none focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent disabled:opacity-60 disabled:cursor-not-allowed transition-colors"
          />
          <p className="absolute bottom-2 right-3 text-xs text-slate-600 pointer-events-none">
            ⌘↵ to send
          </p>
        </div>

        <div className="flex items-center justify-between">
          <p className="text-xs text-slate-500">
            {query.trim().length > 0
              ? `${query.trim().length} characters`
              : "Enter your research question"}
          </p>
          <button
            data-testid="submit-button"
            type="submit"
            disabled={isSubmitDisabled}
            className="flex items-center gap-2 px-5 py-2.5 bg-blue-600 hover:bg-blue-500 disabled:bg-slate-700 disabled:text-slate-500 text-white text-sm font-medium rounded-lg transition-all disabled:cursor-not-allowed focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 focus:ring-offset-slate-800"
          >
            {isLoading ? (
              <>
                <svg
                  className="w-4 h-4 animate-spin"
                  fill="none"
                  viewBox="0 0 24 24"
                >
                  <circle
                    className="opacity-25"
                    cx="12"
                    cy="12"
                    r="10"
                    stroke="currentColor"
                    strokeWidth="4"
                  />
                  <path
                    className="opacity-75"
                    fill="currentColor"
                    d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
                  />
                </svg>
                Analyzing...
              </>
            ) : (
              <>
                <svg
                  className="w-4 h-4"
                  fill="none"
                  stroke="currentColor"
                  viewBox="0 0 24 24"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={2}
                    d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"
                  />
                </svg>
                Analyze
              </>
            )}
          </button>
        </div>
      </form>
    </div>
  );
}
