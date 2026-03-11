"use client";

import { useState } from "react";
import QueryBox from "@/components/QueryBox";
import ResultCard from "@/components/ResultCard";
import { QueryResult } from "@/types";

export default function Home() {
  const [result, setResult] = useState<QueryResult | null>(null);
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [phase, setPhase] = useState<string>("");

  const handleResult = (data: QueryResult) => {
    setResult(data);
  };

  const handleLoading = (isLoading: boolean, currentPhase: string) => {
    setLoading(isLoading);
    setPhase(currentPhase);
    if (!isLoading) {
      setPhase("");
    }
  };

  const handleError = (message: string | null) => {
    setError(message);
  };

  return (
    <main className="min-h-screen bg-slate-900">
      {/* Header */}
      <header className="border-b border-slate-700 bg-slate-900/80 backdrop-blur-sm sticky top-0 z-10">
        <div className="max-w-5xl mx-auto px-4 py-4">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-lg bg-blue-600 flex items-center justify-center flex-shrink-0">
              <svg
                className="w-5 h-5 text-white"
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"
                />
              </svg>
            </div>
            <div>
              <h1 className="text-lg font-semibold text-white leading-tight">
                NVX-0228 Conflict RAG
              </h1>
              <p className="text-xs text-slate-400">
                Multi-Document Conflict Resolution System
              </p>
            </div>
          </div>
        </div>
      </header>

      <div className="max-w-5xl mx-auto px-4 py-8 space-y-6">
        {/* Hero description */}
        <div className="text-center space-y-2 pb-2">
          <h2 className="text-2xl font-bold text-white">
            Research Conflict Analysis
          </h2>
          <p className="text-slate-400 max-w-2xl mx-auto text-sm leading-relaxed">
            Query across multiple NVX-0228 research papers. The system
            automatically detects conflicting claims, classifies conflict types,
            and synthesizes a grounded answer with full reasoning trace.
          </p>
        </div>

        {/* Query Box */}
        <QueryBox
          onResult={handleResult}
          onLoading={handleLoading}
          onError={handleError}
        />

        {/* Loading State */}
        {loading && (
          <div className="flex items-center justify-center py-8">
            <div className="flex flex-col items-center gap-3">
              <div className="w-8 h-8 border-2 border-blue-500 border-t-transparent rounded-full animate-spin" />
              {phase && (
                <p
                  data-testid="loading-phase"
                  className="text-slate-400 text-sm animate-pulse"
                >
                  {phase}
                </p>
              )}
            </div>
          </div>
        )}

        {/* Error State */}
        {error && !loading && (
          <div className="bg-red-900/30 border border-red-700 rounded-lg p-4 flex items-start gap-3">
            <svg
              className="w-5 h-5 text-red-400 flex-shrink-0 mt-0.5"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
              />
            </svg>
            <div>
              <p className="text-red-300 font-medium text-sm">
                Query Failed
              </p>
              <p className="text-red-400 text-sm mt-0.5">{error}</p>
            </div>
          </div>
        )}

        {/* Result Card */}
        {result && !loading && <ResultCard result={result} />}
      </div>
    </main>
  );
}
